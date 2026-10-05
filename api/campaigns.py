import os
import re
import csv
import math
import falcon
import requests
import traceback
import hashlib
import random
import json
import zipfile
import email.utils
import shortuuid
from abc import abstractmethod
from typing import Any, List, Tuple, Dict, Set, cast, Iterable
from fnmatch import fnmatch
from datetime import datetime, timedelta
from io import BytesIO

from .shared import config as config_module_side_effects  # noqa: F401
from .shared.db import open_db, json_iter, json_obj, JsonObj, DB
from .shared.crud import (
    CRUDCollection,
    CRUDSingle,
    get_orig,
    check_noadmin,
    patch_schema,
)
from .shared.utils import (
    run_task,
    run_tasks,
    generate_html,
    gather_init,
    gather_check,
    gather_complete,
    MPDictWriter,
    is_true,
    get_webroot,
    fix_tag,
    djb2,
    MPDictReader,
    MTA_TIMEOUT,
    remove_newlines,
    device_names,
    os_names,
    browser_names,
    gen_screenshot,
    set_onboarding,
    fix_sink_url,
)
from .shared.segments import (
    segment_get_params,
    get_segment_rows,
    segment_eval_parts,
    segment_get_segments,
    segment_get_campaignids,
    get_segment_sentrows,
    supp_rows,
    Cache,
)
from .shared.tasks import tasks, HIGH_PRIORITY, LOW_PRIORITY
from .shared.send import (
    mailgun_send,
    ses_send,
    sparkpost_send,
    easylink_send,
    smtprelay_send,
    send_backend_mail,
    sink_get_settings,
    sink_get_ips,
    fix_headers,
    update_sink_camp,
    check_send_limit,
    check_test_limit,
    client_domain,
    get_frontend_params,
    load_domain_throttles,
    validate_sender_domains,
)
from .shared.s3 import (
    s3_write_stream,
    s3_write,
    s3_list,
    s3_copy,
    s3_read,
    s3_read_stream,
)
from .shared.log import get_logger

log = get_logger()


def validate_campaign_sender(db: DB, camp: JsonObj) -> None:
    validate_sender_domains(
        db, camp["cid"], camp.get("fromemail"), camp.get("returnpath")
    )


class _CSVWriter:
    @abstractmethod
    def writerow(self, row: Iterable[str]) -> None:
        pass


@tasks.task(priority=LOW_PRIORITY)
def write_campaign_lists(
    segment: JsonObj,
    hashval: int,
    listfactors: List[str],
    hashlimit: int,
    suppfactors: List[str],
    campaignids: List[str],
    supptagslist: List[str],
    gatherid: str,
    domaingroups: List[JsonObj],
    domainstartpct: int,
    domainendpct: int,
    sinkobjs: List[JsonObj],
    policy: JsonObj,
    campid: str,
    maingatherid: str,
    randomize: bool = False,
    newestfirst: bool = False,
) -> None:
    with open_db() as db:
        try:
            logsize = 0
            countbydomain: Dict[str, Dict[str, int]] = {}

            databucket = os.environ["s3_databucket"]

            policydomains = policy.get("domains", "*").split()

            supptags: Set[str] = set(supptagslist)

            segments: Dict[str, JsonObj | None] = {}
            segment_get_segments(db, segment["parts"], segments)

            sentrows = get_segment_sentrows(
                db, segment["cid"], campaignids, hashval, hashlimit
            )

            rows = get_segment_rows(db, segment["cid"], hashval, listfactors, hashlimit)

            cache = Cache()

            r2 = []
            segcounts: Dict[str, int] = {}
            numrows = len(rows)
            for row in rows:
                if segment_eval_parts(
                    segment["parts"],
                    segment["operator"],
                    row,
                    segcounts,
                    numrows,
                    segments,
                    sentrows,
                    segment,
                    hashlimit,
                    cache,
                ):
                    r2.append(row)
            rows = r2

            def most_recent(row: JsonObj) -> int:
                maxts = 0
                for prop in ("!!open-logs", "!!click-logs"):
                    vals = row.get(prop, None)
                    if vals:
                        for dt, _ in vals:
                            if dt > maxts:
                                maxts = dt
                return maxts

            def newest_data(row: JsonObj) -> int:
                return cast(int, row.get("!!added", 0))

            if not randomize and not newestfirst:
                rows.sort(key=most_recent, reverse=True)
            elif newestfirst:
                rows.sort(key=newest_data, reverse=True)
            else:
                random.shuffle(rows)

            allprops = set()

            def fix_row(r: JsonObj) -> JsonObj:
                fixedrow = {}
                for prop in r.keys():
                    if not prop.startswith("!"):
                        allprops.add(prop)
                        fixedrow[prop] = r.get(prop, ("",))[0]
                    elif prop == "!!tags":
                        fixedrow[prop] = set()
                        for v in r.get(prop, ("",)):
                            if v:
                                for tag in v.split(","):
                                    fixedrow[prop].add(tag)
                return fixedrow

            rows = [fix_row(row) for row in rows]

            def eval_dg(dg: JsonObj | None, email: str) -> bool:
                if dg is None:
                    return True
                d = email.split("@")[1]
                for domain in dg["domainsplit"]:
                    if fnmatch(d, domain):
                        return True
                return False

            def filter_result(r: JsonObj) -> bool:
                email = r["Email"]

                found = -1
                for i in range(len(domaingroups)):
                    if eval_dg(domaingroups[i], email):
                        found = i
                        break
                if found != len(domaingroups) - 1:
                    return False

                pct = djb2(email) % 100
                return pct >= domainstartpct and pct < domainendpct

            rows = [row for row in rows if filter_result(row)]

            if len(rows):
                supprows = supp_rows(
                    db, segment["cid"], hashval, hashlimit, suppfactors
                )

                def eval_suppress(r: JsonObj) -> bool:
                    if is_true(r.get("Unsubscribed", "")):
                        return False
                    if is_true(r.get("Complained", "")):
                        return False
                    if is_true(r.get("Bounced", "")):
                        return False

                    if "!!tags" in r and (r["!!tags"] & supptags):
                        return False
                    if len(supprows):
                        md5 = hashlib.md5(r["Email"].encode("utf-8")).hexdigest()
                        if md5 in supprows:
                            return False
                    return True

                rows = [row for row in rows if eval_suppress(row)]

            if len(rows):

                def filter_policy(r: JsonObj) -> bool:
                    for domain in policydomains:
                        if fnmatch(r["Email"].split("@")[1], domain):
                            return True
                    return False

                rows = [row for row in rows if filter_policy(row)]

            for row in rows:
                row.pop("!!tags", None)

            sendid = shortuuid.uuid()
            countbydomain[sendid] = {}

            if len(rows):
                pct = 0
                cnt = 0
                for obj in sinkobjs:
                    pct += obj["pct"]

                    outfile = BytesIO()
                    writer = MPDictWriter(outfile, list(allprops))
                    writer.writeheader()

                    listcnt = 0

                    while (
                        cnt < len(rows)
                        and ((float(cnt) / float(len(rows))) * 100) < pct
                    ):
                        writer.writerow(rows[cnt])
                        em = rows[cnt]["Email"]
                        domain = em.split("@")[1]
                        if domain not in countbydomain[sendid]:
                            countbydomain[sendid][domain] = 1
                        else:
                            countbydomain[sendid][domain] = (
                                countbydomain[sendid][domain] + 1
                            )
                        cnt += 1
                        listcnt += 1
                        logsize += len(em) + 1

                    listfile = "lists/%s-%s/%s-%s-%s-%08d.blk" % (
                        campid,
                        gatherid,
                        obj["id"],
                        sendid,
                        listcnt,
                        hashval,
                    )
                    outfile.seek(0, 0)

                    s3_write_stream(databucket, listfile, outfile)

                    if pct >= 100:
                        break

            for countdict in countbydomain.values():
                for domain, dcnt in countdict.items():
                    db.execute(
                        """insert into campaign_domains (campaign_id, domain, count) values (%s, %s, %s)
                                on conflict (campaign_id, domain) do update set
                                count = campaign_domains.count + excluded.count""",
                        campid,
                        domain,
                        dcnt,
                    )

            res = gather_complete(
                db, gatherid, {"logdatasize": logsize, "countbydomain": countbydomain}
            )
            if res is not None:
                countsbydomain = {}
                for r in res:
                    for sendid, cdict in r["countbydomain"].items():
                        countsbydomain[sendid] = cdict

                camp = db.campaigns.get(campid)

                if camp is None:
                    return

                mainres = gather_complete(
                    db,
                    maingatherid,
                    {
                        "countsbydomain": countsbydomain,
                        "logdatasize": sum(r["logdatasize"] for r in res),
                        "taskid": gatherid,
                        "sinkobjs": sinkobjs,
                        "settingsid": policy["id"],
                    },
                )
                if mainres is not None:
                    if db.single(
                        "select (data->>'canceled')::boolean from campaigns where id = %s",
                        campid,
                    ):
                        return

                    c = 0
                    countsbydomain = {}
                    alldomains = set()
                    for r in mainres:
                        for sendid, cdict in r["countsbydomain"].items():
                            countsbydomain[sendid] = cdict
                            alldomains.update(iter(cdict.keys()))
                            c += sum(cdict.values())
                    p = {
                        "count": c,
                        "logdatasize": sum(r["logdatasize"] for r in mainres),
                        "domaincount": len(alldomains),
                    }
                    db.campaigns.patch(campid, p)

                    demo = False
                    imagebucket = os.environ["s3_imagebucket"]
                    company = db.companies.get(camp["cid"])
                    if company is not None:
                        parentcompany = db.companies.get(company["cid"])
                        if parentcompany is not None:
                            demo = parentcompany.get("demo", False)
                            imagebucket = parentcompany.get(
                                "s3_imagebucket", imagebucket
                            )

                    html, linkurls = generate_html(
                        db, camp, campid, imagebucket, camp.get("disableopens", False)
                    )

                    if demo:
                        allsinkobjs = []
                        for mr in mainres:
                            allsinkobjs.append((mr["sinkobjs"], mr["settingsid"]))
                        fake_hour_stats(db, campid, camp["cid"], allsinkobjs)
                    else:
                        bodyutf8 = html.encode("utf-8")
                        bodykey = "templates/camp/%s/%s-%s.html" % (
                            camp["cid"],
                            campid,
                            hashlib.md5(bodyutf8).hexdigest(),
                        )
                        s3_write(databucket, bodykey, bodyutf8)

                        for mr in mainres:
                            sinkobjs = mr["sinkobjs"]
                            taskid = mr["taskid"]
                            settingsid = mr["settingsid"]

                            fromemail = camp.get("returnpath") or camp["fromemail"]

                            fromdomain = ""
                            if "@" in fromemail:
                                fromdomain = fromemail.split("@")[-1].strip().lower()
                            frm = email.utils.formataddr(
                                (
                                    remove_newlines(camp["fromname"]),
                                    remove_newlines(
                                        camp.get("fromemail") or camp["returnpath"]
                                    ),
                                )
                            )

                            if camp.get("replyto", ""):
                                replyto = remove_newlines(camp["replyto"])
                            else:
                                replyto = remove_newlines(
                                    camp.get("fromemail") or camp["returnpath"]
                                )

                            subject = remove_newlines(camp["subject"])

                            listkeys: Dict[str, List[Tuple[str, int, str]]] = {}

                            for key in s3_list(
                                databucket, "lists/%s-%s/" % (campid, taskid)
                            ):
                                sinkid, sendid, cntstr = key.key.split("/")[-1].split(
                                    "-"
                                )[:3]

                                if sinkid not in listkeys:
                                    listkeys[sinkid] = []

                                listkeys[sinkid].append((sendid, int(cntstr), key.key))

                            for obj in sinkobjs:
                                if obj["id"] not in listkeys:
                                    continue

                                db.execute(
                                    """update campaigns set data = data ||
                                                    jsonb_build_object('sinkstatus', (data->>'sinkstatus')::jsonb || jsonb_build_object(%s, %s),
                                                                        'linkclicks', to_jsonb(%s::int[]),
                                                                        'linkurls', to_jsonb(%s::text[]))
                                            where id = %s""",
                                    obj["id"],
                                    False,
                                    [0] * len(linkurls),
                                    linkurls,
                                    campid,
                                )

                                with db.transaction():
                                    for sendid, _, listkey in listkeys[obj["id"]]:
                                        for todomain, cnt in countsbydomain.get(
                                            sendid, {}
                                        ).items():
                                            db.execute(
                                                """insert into campqueue (cid, campid, sendid, domain, count, remaining, data)
                                                        values (%s, %s, %s, %s, %s, %s, %s)""",
                                                camp["cid"],
                                                campid,
                                                sendid,
                                                todomain,
                                                cnt,
                                                cnt,
                                                {
                                                    "policytype": obj.get("policytype"),
                                                    "sinkid": obj["id"],
                                                    "sendid": sendid,
                                                    "from": frm,
                                                    "returnpath": fromemail,
                                                    "fromdomain": fromdomain,
                                                    "replyto": replyto,
                                                    "subject": subject,
                                                    "template": bodykey,
                                                    "listkey": listkey,
                                                    "settingsid": settingsid,
                                                },
                                            )

                    p = {"sinks_pushed": True}
                    if not c:
                        p["finished_at"] = datetime.utcnow().isoformat() + "Z"
                    db.campaigns.patch(campid, p)

                    if demo and c:
                        fake_stats(db, campid, c, len(linkurls))
        except Exception as e:
            log.exception("error")
            db.campaigns.patch(
                campid,
                {"finished_at": datetime.utcnow().isoformat() + "Z", "error": str(e)},
            )


def fake_rates(
    campid: str,
) -> Tuple[random.Random, float, float, float, float, float, float, float, float]:
    r = random.Random()
    r.seed(djb2(campid))

    hardrate = r.uniform(0.0, 0.02)
    softrate = r.uniform(0.0, 0.02)
    openrate = r.uniform(0.21, 0.50)
    clickrate = r.uniform(0.01, 0.11)
    complainrate = r.uniform(0.0, 0.0001)
    unsubrate = r.uniform(0.0, 0.001)
    errrate = r.uniform(0.001, 0.005)
    deferrate = r.uniform(0.001, 0.005)

    return (
        r,
        hardrate,
        softrate,
        openrate,
        clickrate,
        complainrate,
        unsubrate,
        errrate,
        deferrate,
    )


def fake_hour_stats(
    db: DB, campid: str, campcid: str, allsinkobjs: List[Tuple[List[JsonObj], str]]
) -> None:
    domaincounts = {}
    for domain, count in db.execute(
        "select domain, count from campaign_domains where campaign_id = %s", campid
    ):
        domaincounts[domain] = count

    (
        r,
        hardrate,
        softrate,
        openrate,
        clickrate,
        complainrate,
        unsubrate,
        errrate,
        deferrate,
    ) = fake_rates(campid)

    uniqsinks = {}
    for sinkobjs, settingsid in allsinkobjs:
        for sink in sinkobjs:
            uniqsinks[sink["id"]] = (sink, settingsid)

    pieces = 0
    for sink, _ in list(uniqsinks.values()):
        for ip in sink["ipdata"]:
            for hour in range(16):
                pieces += 1

    def chop(count: int, remain: int) -> Tuple[int, int]:
        c = int(count / pieces)
        c += int(r.uniform(0.0, 0.15) * c)
        remain -= c
        if remain < 0:
            remain = 0
            c = 0
        return c, remain

    for domain, count in domaincounts.items():
        hardtotal = int(hardrate * count)
        sendtotal = int((1 - hardrate - softrate) * count)
        softtotal = int(softrate * count)
        openedtotal = int(openrate * count)
        clickedtotal = int(clickrate * openrate * count)
        complainedtotal = int(complainrate * count)
        unsubtotal = int(unsubrate * count)
        errtotal = int(errrate * count)
        defertotal = int(deferrate * count)

        hardremain = hardtotal
        sendremain = sendtotal
        softremain = softtotal
        openedremain = openedtotal
        clickedremain = clickedtotal
        complainedremain = complainedtotal
        unsubremain = unsubtotal
        errremain = errtotal
        deferremain = defertotal
        for sink, settingsid in list(uniqsinks.values()):
            for ip in [d["ip"] for d in sink["ipdata"]]:
                ts = datetime.utcnow()
                for hour in range(16):
                    hard, hardremain = chop(hardtotal, hardremain)
                    send, sendremain = chop(sendtotal, sendremain)
                    soft, softremain = chop(softtotal, softremain)
                    opened, openedremain = chop(openedtotal, openedremain)
                    clicked, clickedremain = chop(clickedtotal, clickedremain)
                    complained, complainedremain = chop(
                        complainedtotal, complainedremain
                    )
                    unsub, unsubremain = chop(unsubtotal, unsubremain)
                    err, errremain = chop(errtotal, errremain)
                    defer, deferremain = chop(defertotal, deferremain)
                    if (
                        hard > 0
                        or send > 0
                        or soft > 0
                        or opened > 0
                        or clicked > 0
                        or complained > 0
                        or unsub > 0
                        or err > 0
                        or defer > 0
                    ):
                        db.execute(
                            """insert into hourstats (id, cid, campcid, ts, sinkid, domaingroupid, ip, settingsid, campid,
                                      complaint, open, click, unsub, send, soft, hard, err, defercnt)
                                      values (%s, %s, %s, date_trunc('hour', %s), %s, %s, %s, %s, %s,
                                      %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            shortuuid.uuid(),
                            sink["cid"],
                            campcid,
                            ts,
                            sink["id"],
                            domain,
                            ip,
                            settingsid,
                            campid,
                            complained,
                            opened,
                            clicked,
                            unsub,
                            send,
                            soft,
                            hard,
                            err,
                            defer,
                        )

                        db.execute(
                            """insert into statmsgs (id, cid, ts, sinkid, domaingroupid, ip, settingsid, campid,
                                                            message, msgtype, count)
                                      values (%s, %s, date_trunc('hour', %s), %s, %s, %s, %s, %s, %s, %s, %s)""",
                            shortuuid.uuid(),
                            sink["cid"],
                            ts,
                            sink["id"],
                            domain,
                            ip,
                            settingsid,
                            campid,
                            "TCP error/connection dropped",
                            "err",
                            err,
                        )
                        db.execute(
                            """insert into statmsgs (id, cid, ts, sinkid, domaingroupid, ip, settingsid, campid,
                                                            message, msgtype, count)
                                      values (%s, %s, date_trunc('hour', %s), %s, %s, %s, %s, %s, %s, %s, %s)""",
                            shortuuid.uuid(),
                            sink["cid"],
                            ts,
                            sink["id"],
                            domain,
                            ip,
                            settingsid,
                            campid,
                            "421 Please try again later",
                            "defer",
                            defer,
                        )
                        db.execute(
                            """insert into statmsgs (id, cid, ts, sinkid, domaingroupid, ip, settingsid, campid,
                                                            message, msgtype, count)
                                      values (%s, %s, date_trunc('hour', %s), %s, %s, %s, %s, %s, %s, %s, %s)""",
                            shortuuid.uuid(),
                            sink["cid"],
                            ts,
                            sink["id"],
                            domain,
                            ip,
                            settingsid,
                            campid,
                            "521 Error processing mail",
                            "soft",
                            soft,
                        )
                        db.execute(
                            """insert into statmsgs (id, cid, ts, sinkid, domaingroupid, ip, settingsid, campid,
                                                            message, msgtype, count)
                                      values (%s, %s, date_trunc('hour', %s), %s, %s, %s, %s, %s, %s, %s, %s)""",
                            shortuuid.uuid(),
                            sink["cid"],
                            ts,
                            sink["id"],
                            domain,
                            ip,
                            settingsid,
                            campid,
                            "504 User mailbox not found",
                            "hard",
                            hard,
                        )

                        db.execute(
                            """insert into statlogs2 (id, cid, ip, ts, err, hard, send, soft, count, lastts, sinkid,
                                                             deferlen, defermsg, settingsid, domaingroupid)
                                      values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            shortuuid.uuid(),
                            sink["cid"],
                            ip,
                            (ts + timedelta(minutes=5)).isoformat() + "Z",
                            0,
                            0,
                            0,
                            0,
                            0,
                            ts.isoformat() + "Z",
                            sink["id"],
                            300,
                            "421 Please try again later",
                            settingsid,
                            domain,
                        )
                        db.execute(
                            """insert into statlogs2 (id, cid, ip, ts, err, hard, send, soft, count, lastts, sinkid,
                                                             deferlen, defermsg, settingsid, domaingroupid)
                                      values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            shortuuid.uuid(),
                            sink["cid"],
                            ip,
                            (ts + timedelta(hours=1)).isoformat() + "Z",
                            err,
                            hard,
                            send,
                            soft,
                            hard + send + soft,
                            (ts + timedelta(minutes=5)).isoformat() + "Z",
                            sink["id"],
                            0,
                            "",
                            settingsid,
                            domain,
                        )

                    ts += timedelta(hours=1)


def fake_linkclicks(r: random.Random, numlinks: int, clicked: int) -> List[int]:
    ret = []
    for i in range(numlinks):
        n = float(clicked) / numlinks
        ret.append(int(n + (n * r.uniform(0.0, 0.10))))
    return ret


def fake_stats(db: DB, campid: str, count: int, numlinks: int) -> None:
    r, hardrate, softrate, openrate, clickrate, complainrate, unsubrate, _, _ = (
        fake_rates(campid)
    )

    clicked = int(clickrate * openrate * count)

    db.campaigns.patch(
        campid,
        {
            "finished_at": datetime.utcnow().isoformat() + "Z",
            "hard": int(hardrate * count),
            "send": int((1 - hardrate - softrate) * count),
            "soft": int(softrate * count),
            "opened": int(openrate * count),
            "opened_all": int((openrate + 0.01) * count),
            "clicked": clicked,
            "clicked_all": int(((clickrate + 0.01) * openrate) * count),
            "delivered": count,
            "complained": int(complainrate * count),
            "unsubscribed": int(unsubrate * count),
            "linkclicks": fake_linkclicks(r, numlinks, clicked),
        },
    )


@tasks.task(priority=HIGH_PRIORITY)
def campaign_calculate_segment(
    segment: JsonObj,
    suppsegment: JsonObj | None,
    hashval: int,
    listfactors: List[str],
    hashlimit: int,
    suppfactors: List[str],
    campaignids: List[str],
    supptagslist: List[str],
    gatherid: str,
) -> None:
    with open_db() as db:
        try:
            segments: Dict[str, JsonObj | None] = {}
            segment_get_segments(db, segment["parts"], segments)

            suppsegments: Dict[str, JsonObj | None] = {}
            if suppsegment is not None:
                segment_get_segments(db, suppsegment["parts"], suppsegments)

            sentrows = get_segment_sentrows(
                db, segment["cid"], campaignids, hashval, hashlimit
            )

            rows = get_segment_rows(db, segment["cid"], hashval, listfactors, hashlimit)

            unavailable = 0
            tagsupped = 0

            supptags: Set[str] = set(supptagslist)

            cache = Cache()

            segrows = set()
            numrows = len(rows)
            suppsegcounts: Dict[str, int] = {}
            segcounts: Dict[str, int] = {}
            for row in rows:
                suppsegmentpassed = True
                if suppsegment is not None:
                    if not segment_eval_parts(
                        suppsegment["parts"],
                        suppsegment["operator"],
                        row,
                        suppsegcounts,
                        numrows,
                        suppsegments,
                        sentrows,
                        suppsegment,
                        hashlimit,
                        cache,
                    ):
                        suppsegmentpassed = False

                if segment_eval_parts(
                    segment["parts"],
                    segment["operator"],
                    row,
                    segcounts,
                    numrows,
                    segments,
                    sentrows,
                    segment,
                    hashlimit,
                    cache,
                ):
                    if (
                        is_true(row.get("Unsubscribed", ("",))[0])
                        or is_true(row.get("Complained", ("",))[0])
                        or is_true(row.get("Bounced", ("",))[0])
                    ):
                        unavailable += 1
                    elif (
                        "!!tags" in row
                        and (row["!!tags"] & supptags)
                        or not suppsegmentpassed
                    ):
                        tagsupped += 1
                    else:
                        segrows.add(
                            hashlib.md5(row["Email"][0].encode("utf-8")).hexdigest()
                        )

            supprows = supp_rows(db, segment["cid"], hashval, hashlimit, suppfactors)

            diff = segrows - supprows

            gather_complete(
                db,
                gatherid,
                {
                    "suppressed": (len(segrows) - len(diff)) + tagsupped,
                    "remaining": len(diff),
                    "unavailable": unavailable,
                    "count": len(segrows) + tagsupped + unavailable,
                },
                False,
            )
        except Exception as e:
            log.exception("error")
            gather_complete(db, gatherid, {"error": str(e)}, False)


@tasks.task(priority=HIGH_PRIORITY)
def get_camp_screenshot(id: str) -> None:
    try:
        with open_db() as db:
            gen_screenshot(db, id, "campaigns")
    except:
        log.exception("error")


@tasks.task(priority=LOW_PRIORITY)
def campaign_start(campid: str) -> None:
    with open_db() as db:
        try:
            camp = json_obj(
                db.row(
                    "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
                    campid,
                )
            )

            if camp is None or camp.get("started"):
                return
            validate_campaign_sender(db, camp)
            db.campaigns.patch(campid, {"started": True})

            if not camp.get("type") or camp["type"] == "beefree":
                run_task(get_camp_screenshot, campid)

            company = db.companies.get(camp["cid"])
            if company is None:
                return
            availroutes = company["routes"]

            if camp.get("route", ""):
                if camp["route"] not in availroutes:
                    raise Exception("Postal route no longer available")
            elif len(availroutes) == 1:
                camp["route"] = availroutes[0]
            else:
                raise Exception("No postal route selected and multiple are available")

            route = db.routes.get(camp["route"])
            if route is None or "published" not in route:
                raise Exception("Missing postal route")

            for l in camp["lists"]:
                if db.lists.get(l) is None:
                    raise Exception("List not found")
            for l in camp["segments"]:
                if db.segments.get(l) is None:
                    raise Exception("Segment not found")
            for l in camp["supplists"]:
                if db.supplists.get(l) is None:
                    raise Exception("Suppression list not found")
            for l in camp["suppsegs"]:
                if db.segments.get(l) is None:
                    raise Exception("Exclude segment not found")

            taskgroups = []

            domaingroups: List[JsonObj | None] = []
            for rule in route["published"]["rules"]:
                if not rule["domaingroup"]:
                    domaingroups.append(None)
                else:
                    dg = db.domaingroups.get(rule["domaingroup"])
                    if dg is None:
                        continue
                    dg["domainsplit"] = dg["domains"].split()
                    domaingroups.append(dg)

                if len(rule["splits"]) == 1:
                    rule["splits"][0]["pct"] = 100
                else:
                    totalpct = sum(split["pct"] for split in rule["splits"])
                    if totalpct > 0:
                        for split in rule["splits"]:
                            split["pct"] = int(
                                math.ceil((split["pct"] / totalpct) * 100)
                            )

                sinkobjs: List[JsonObj | None]
                startpct = 0
                for split in rule["splits"]:
                    if not split["policy"]:
                        continue
                    policy = db.policies.get(split["policy"])
                    if policy is None:
                        mg = db.mailgun.get(split["policy"])
                        if mg is None:
                            ses = db.ses.get(split["policy"])
                            if ses is None:
                                sparkpost = db.sparkpost.get(split["policy"])
                                if sparkpost is None:
                                    el = db.easylink.get(split["policy"])
                                    if el is None:
                                        smtp = db.smtprelays.get(split["policy"])
                                        if smtp is None:
                                            continue
                                        else:
                                            smtp["pct"] = 100
                                            policy = smtp
                                            sinkobjs = [smtp]
                                    else:
                                        el["pct"] = 100
                                        policy = el
                                        sinkobjs = [el]
                                else:
                                    sparkpost["pct"] = 100
                                    policy = sparkpost
                                    sinkobjs = [sparkpost]
                            else:
                                ses["pct"] = 100
                                policy = ses
                                sinkobjs = [ses]
                        else:
                            mg["pct"] = 100
                            policy = mg
                            sinkobjs = [mg]
                    else:
                        policy = policy["published"]
                        if policy is None:
                            continue
                        policy["id"] = split["policy"]
                        if len(policy["sinks"]) == 1:
                            policy["sinks"][0]["pct"] = 100
                        sinkobjs = [
                            db.sinks.get(sink["sink"]) for sink in policy["sinks"]
                        ]
                        for sink, obj in zip(policy["sinks"], sinkobjs):
                            if obj is not None:
                                obj["pct"] = sink["pct"]
                        sinkobjs = [s for s in sinkobjs if s is not None]
                        if len(sinkobjs) == 0:
                            continue

                    taskgroups.append(
                        {
                            "domaingroups": list(domaingroups),
                            "startpct": startpct,
                            "endpct": startpct + split["pct"],
                            "sinks": sinkobjs,
                            "policy": policy,
                        }
                    )
                    startpct += split["pct"]

            if not len(taskgroups):
                raise Exception("No valid domain routes found")

            fakesegment = fake_segment(camp)

            supplists = []
            for sl in camp["supplists"]:
                supplist = db.supplists.get(sl)
                if supplist is None:
                    raise Exception("Suppression list not found")
                if "count" not in supplist or not isinstance(supplist["count"], int):
                    raise Exception(
                        "Suppression list data is not fully imported, try again soon"
                    )
                supplists.append(supplist)

            for taglist in (
                camp.get("openaddtags", ()),
                camp.get("clickaddtags", ()),
                camp.get("sendaddtags", ()),
            ):
                for tag in taglist:
                    t = fix_tag(tag)
                    if t:
                        db.execute(
                            """insert into alltags (cid, tag, added, count) values (%s, %s, now(), 0)
                                    on conflict (cid, tag) do nothing""",
                            camp["cid"],
                            t,
                        )
            segments: Dict[str, JsonObj | None] = {}
            segment_get_segments(db, fakesegment["parts"], segments)

            campaignids = segment_get_campaignids(fakesegment, list(segments.values()))

            hashlimit, listfactors = segment_get_params(
                db, camp["cid"], fakesegment, approvedonly=True
            )

            suppfactors = [
                supplist["id"] for supplist in supplists if supplist is not None
            ]

            maingatherid = gather_init(db, "campaign_start", len(taskgroups))

            taskparams = []
            for taskobj in taskgroups:
                gatherid = gather_init(db, "write_campaign_lists", hashlimit)
                for i in range(hashlimit):
                    taskparams.append(
                        (
                            write_campaign_lists,
                            fakesegment,
                            i,
                            listfactors,
                            hashlimit,
                            suppfactors,
                            campaignids,
                            camp.get("supptags", []),
                            gatherid,
                            taskobj["domaingroups"],
                            taskobj["startpct"],
                            taskobj["endpct"],
                            taskobj["sinks"],
                            taskobj["policy"],
                            campid,
                            maingatherid,
                            camp.get("randomize", False),
                            camp.get("newestfirst", False),
                        )
                    )
            run_tasks(taskparams)

            set_onboarding(db, camp["cid"], "broadcast", "complete")
        except Exception as e:
            log.exception("error")
            db.campaigns.patch(
                campid,
                {"finished_at": datetime.utcnow().isoformat() + "Z", "error": str(e)},
            )


class CampaignStart(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        camp = json_obj(
            db.row(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s and cid = %s",
                id,
                db.get_cid(),
            )
        )

        if camp is None:
            raise falcon.HTTPForbidden()

        validate_campaign_sender(db, camp)

        campcid = camp["cid"]

        db.set_cid(None)

        company = db.companies.get(campcid)

        if company is None:
            raise Exception(
                "No postal route configured for you to send mail with. Please contact your administrator."
            )

        ok = db.single(
            """update campaigns set data = data || %s where id = %s and (data->>'sent_at' is null or data->>'sent_at' = '') returning true""",
            {
                "sent_at": datetime.utcnow().isoformat() + "Z",
                "count": "counting",
                "sinkstatus": {},
            },
            id,
        )
        if ok:
            run_task(campaign_start, id)

        req.context["result"] = {"result": "ok"}


class CampaignCancel(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        camp = db.campaigns.get(id)

        if camp is None:
            raise falcon.HTTPForbidden()

        db.set_cid(None)

        if not camp.get("sent_at"):
            raise falcon.HTTPBadRequest(
                title="Not started", description="Campaign was not started"
            )

        db.campaigns.patch(id, {"canceled": True})

        db.execute(
            "delete from campqueue where cid = %s and campid = %s", camp["cid"], id
        )

        for sinkid in camp["sinkstatus"].keys():
            sink = db.sinks.get(sinkid)
            if sink is None:
                continue

            url = fix_sink_url(sink["url"])
            try:
                r = requests.post(
                    url + "/cancel",
                    json={
                        "id": id,
                        "accesskey": sink["accesskey"],
                    },
                    timeout=MTA_TIMEOUT,
                )
                r.raise_for_status()
            except Exception as e:
                raise falcon.HTTPBadRequest(
                    title="Server error",
                    description="Error contacting server: %s" % str(e),
                )

        db.campaigns.patch(
            id,
            {"error": "Canceled", "finished_at": datetime.utcnow().isoformat() + "Z"},
        )


@tasks.task(priority=HIGH_PRIORITY)
def export_campaign(
    campid: str, cid: str, exportid: str, path: str, totransfer: bool
) -> None:
    with open_db() as db:
        try:
            cnt = 0

            files = {
                "delivered": "/tmp/delivered-%s.csv" % exportid,
                "opened": "/tmp/opened-%s.csv" % exportid,
                "clicked": "/tmp/clicked-%s.csv" % exportid,
                "unsubscribed": "/tmp/unsubscribed-%s.csv" % exportid,
                "complained": "/tmp/complained-%s.csv" % exportid,
                "bounced": "/tmp/bounced-%s.csv" % exportid,
                "softbounced": "/tmp/softbounced-%s.csv" % exportid,
            }
            fps = {}
            writers: Dict[str, _CSVWriter | "csv.DictWriter[str]"] = {}

            cmdtokey = {
                "open": "opened",
                "click": "clicked",
                "unsub": "unsubscribed",
                "complaint": "complained",
                "bounce": "bounced",
                "soft": "softbounced",
            }

            for (contact_email,) in db.execute(
                f"""select c.email
                                    from contacts."contacts_{cid}" c
                                    join contacts."contact_send_logs_{cid}" s on s.contact_id = c.contact_id
                                    where s.campid = %s""",
                campid,
            ):
                key = "delivered"
                if key not in fps:
                    fps[key] = open(files[key], "w")
                    dw = csv.DictWriter(fps[key], ["Email"])
                    writers[key] = dw
                    dw.writeheader()
                dw = cast("csv.DictWriter[str]", writers[key])
                dw.writerow({"Email": contact_email})
                cnt += 1

            for contact_email, cmd, ts, code in db.execute(
                "select email, cmd, ts, code from camplogs where campid = %s", campid
            ):
                key = cmdtokey[cmd]
                if key not in fps:
                    fps[key] = open(files[key], "w")
                    w = cast(_CSVWriter, csv.writer(fps[key]))
                    writers[key] = w
                    if cmd in ("bounce", "soft"):
                        w.writerow(("Email", "Date", "Msg"))
                    else:
                        w.writerow(("Email", "Date"))
                if cmd in ("bounce", "soft"):
                    w = cast(_CSVWriter, writers[key])
                    w.writerow((contact_email, ts.isoformat() + "Z", code))
                else:
                    w = cast(_CSVWriter, writers[key])
                    w.writerow((contact_email, ts.isoformat() + "Z"))

            zipname = "/tmp/%s.zip" % exportid
            outzip = zipfile.ZipFile(zipname, "w", zipfile.ZIP_DEFLATED)
            for key, fp in fps.items():
                fp.close()
                outzip.write(files[key], "%s.csv" % key)
            outzip.close()

            size = os.path.getsize(zipname)
            outfp = open(zipname, "rb")
            if totransfer:
                s3_write_stream(os.environ["s3_transferbucket"], path, outfp)
            else:
                s3_write_stream(os.environ["s3_databucket"], path, outfp)

            outfp.close()

            if totransfer:
                db.exports.patch(
                    exportid, {"complete": True, "count": cnt, "size": size}
                )
            else:
                db.campaigns.patch(
                    campid,
                    {"archive_count": cnt, "archive_size": size, "archive_key": path},
                )
        except Exception as e:
            log.exception("error")
            if totransfer:
                db.exports.patch(exportid, {"error": str(e)})


class CampaignUpdate(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        db = req.context["db"]

        doc.pop("when", None)
        doc.pop("scheduled_for", None)
        doc.pop("route", None)
        doc.pop("tags", None)
        doc.pop("lists", None)
        doc.pop("segments", None)
        doc.pop("supplists", None)
        doc.pop("suppsegs", None)
        doc.pop("supptags", None)

        uniq = "name"
        if uniq in doc:
            old = db.campaigns.find_one({uniq: doc[uniq]})
            if old is not None and old["id"] != id:
                orig, i = get_orig(doc[uniq])
                while True:
                    doc[uniq] = "%s (%s)" % (orig, i)
                    old = db.campaigns.find_one({uniq: doc[uniq]})
                    if old is None:
                        break
                    i += 1

        p = {}
        for k, v in doc.items():
            if k in (
                "name",
                "subject",
                "fromname",
                "returnpath",
                "fromemail",
                "replyto",
                "parts",
                "bodyStyle",
                "rawText",
                "preheader",
                "openaddtags",
                "openremtags",
                "clickaddtags",
                "clickremtags",
                "sendaddtags",
                "sendremtags",
                "funnel",
                "disableopens",
                "randomize",
                "newestfirst",
            ):
                p[k] = v

        oldcamp = db.campaigns.get(id)
        if oldcamp is None:
            raise falcon.HTTPForbidden()
        validate_campaign_sender(db, {**oldcamp, **p})

        db.campaigns.patch(id, p)

        camp = db.campaigns.get(id)

        if camp is None:
            raise falcon.HTTPForbidden()

        if camp.get("finished_at", "") or not camp.get("sent_at", ""):
            return

        # XXX everything below here is untested

        if not camp.get("type") or camp["type"] == "beefree":
            run_task(get_camp_screenshot, id)

        db.set_cid(None)

        (
            demo,
            imagebucket,
            bodydomain,
            headers,
            fromencoding,
            subjectencoding,
            usedkim,
        ) = get_frontend_params(db, camp["cid"])

        if demo:
            return

        html, linkurls = generate_html(
            db, camp, camp["id"], imagebucket, camp.get("disableopens", False)
        )

        databucket = os.environ["s3_databucket"]
        bodyutf8 = html.encode("utf-8")
        bodykey = "templates/camp/%s/%s-%s.html" % (
            camp["cid"],
            id,
            hashlib.md5(bodyutf8).hexdigest(),
        )
        s3_write(databucket, bodykey, bodyutf8)

        fromemail = camp.get("returnpath") or camp["fromemail"]

        fromdomain = ""
        if "@" in fromemail:
            fromdomain = fromemail.split("@")[-1].strip().lower()
        queueobj = {
            "template": bodykey,
            "replyto": camp["replyto"],
            "subject": camp["subject"],
            "fromdomain": fromdomain,
            "returnpath": fromemail,
            "from": email.utils.formataddr(
                (
                    remove_newlines(camp["fromname"]),
                    remove_newlines(camp.get("fromemail") or camp["returnpath"]),
                )
            ),
        }

        db.execute(
            """update campaigns set data = data || jsonb_build_object('linkclicks', to_jsonb(%s::int[]), 'updated_at', %s, 'linkurls', to_jsonb(%s::text[]))
                      where id = %s""",
            [0] * len(linkurls),
            datetime.utcnow().isoformat() + "Z",
            linkurls,
            camp["id"],
        )
        db.execute(
            """update campqueue set data = data || %s where cid = %s and campid = %s""",
            queueobj,
            camp["cid"],
            camp["id"],
        )

        if "sinkstatus" in camp:
            for sinkid in camp["sinkstatus"].keys():
                update_sink_camp(db, sinkid, camp, html)


class CampaignExport(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True, True)

        db = req.context["db"]

        c = db.campaigns.get(id)
        if c is None:
            raise falcon.HTTPForbidden()

        name = re.sub(r"[^A-Za-z0-9 \-_.]", "", c["name"])

        ts = datetime.utcnow()

        if "archive_key" in c:
            path = c["archive_key"]

            s3_copy(
                os.environ["s3_databucket"], path, os.environ["s3_transferbucket"], path
            )

            exportid = db.exports.add(
                {
                    "campaign_id": id,
                    "complete": True,
                    "count": c["archive_count"],
                    "size": c["archive_size"],
                    "started_at": ts.isoformat() + "Z",
                    "name": name,
                    "url": f"{get_webroot()}/transfer/{path}",
                }
            )
        else:
            uuid = shortuuid.uuid()

            path = "exports/%s/%s-%s.zip" % (uuid, name, ts.strftime("%Y%m%d-%H%M%SZ"))

            exportid = db.exports.add(
                {
                    "campaign_id": id,
                    "started_at": ts.isoformat() + "Z",
                    "name": name,
                    "url": f"{get_webroot()}/transfer/{path}",
                }
            )

            run_task(export_campaign, id, c["cid"], exportid, path, True)

        req.context["result"] = {"id": exportid}


def dupe_campaign(db: DB, camp: JsonObj) -> str:
    camp.pop("error", None)
    camp.pop("sent_at", None)
    camp.pop("started", None)
    camp.pop("finished_at", None)
    camp.pop("canceled", None)
    camp.pop("hidden", None)
    camp.pop("scheduled_for", None)
    camp.pop("processed_schedule", None)
    camp.pop("count", None)
    camp.pop("opened", None)
    camp.pop("clicked", None)
    camp.pop("opened_all", None)
    camp.pop("clicked_all", None)
    camp.pop("complained", None)
    camp.pop("bounced", None)
    camp.pop("unsubscribed", None)
    camp.pop("archived", None)
    camp.pop("logdatasize", None)
    camp.pop("loghashlimit", None)
    camp.pop("example", None)
    camp.pop("is_resend", None)
    camp.pop("processed_resend", None)

    camp["when"] = "draft"
    camp["delivered"] = 0
    camp["send"] = 0
    camp["soft"] = 0
    camp["hard"] = 0
    camp["modified"] = datetime.utcnow().isoformat() + "Z"

    try:
        if "from" in camp and "fromname" not in camp:
            camp["fromname"], camp["returnpath"] = email.utils.parseaddr(camp["from"])
    except:
        pass

    if "list" in camp:
        if "where" not in camp or camp["where"] == "list":
            camp["lists"] = [camp["list"]]
            camp["segments"] = []
        else:
            camp["lists"] = []
            camp["segments"] = [camp["segment"]]
        if "supplist" in camp and camp["supplist"]:
            camp["supplists"] = [camp["supplist"]]
        else:
            camp["supplists"] = []
        camp.pop("where", None)
        camp.pop("list", None)
        camp.pop("segment", None)
        camp.pop("supplist", None)
    if "tags" not in camp:
        camp["tags"] = []
        camp["supptags"] = []
    if "openaddtags" not in camp:
        camp["openaddtags"] = []
        camp["openremtags"] = []
        camp["clickaddtags"] = []
        camp["clickremtags"] = []
        camp["sendaddtags"] = []
        camp["sendremtags"] = []
    if "suppsegs" not in camp:
        camp["suppsegs"] = []
    if "disableopens" not in camp:
        camp["disableopens"] = False
    if "randomize" not in camp:
        camp["randomize"] = False
    if "newestfirst" not in camp:
        camp["newestfirst"] = False

    camp["lists"] = [l for l in camp["lists"] if db.lists.get(l) is not None]
    camp["segments"] = [l for l in camp["segments"] if db.segments.get(l) is not None]
    camp["supplists"] = [
        l for l in camp["supplists"] if db.supplists.get(l) is not None
    ]
    camp["suppsegs"] = [l for l in camp["suppsegs"] if db.segments.get(l) is not None]

    orig, i = get_orig(camp["name"])
    while True:
        camp["name"] = "%s (%s)" % (orig, i)
        if db.campaigns.find_one({"name": camp["name"]}) is None:  # XXX bad
            break
        i += 1

    return db.campaigns.add(camp)


class CampaignDuplicate(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        camp = db.campaigns.get(id)

        if camp is None:
            raise falcon.HTTPForbidden()

        req.context["result"] = dupe_campaign(db, camp)


def fake_segment(camp: JsonObj, suppsegs: bool = True) -> JsonObj:
    p = []
    op = "or"
    for lst in camp["lists"]:
        p.append(
            {
                "type": "Lists",
                "operator": "in",
                "list": lst,
            }
        )
    for seg in camp["segments"]:
        p.append(
            {
                "type": "Lists",
                "operator": "insegment",
                "segment": seg,
            }
        )
    if "tags" in camp:
        for tag in camp["tags"]:
            p.append(
                {
                    "type": "Info",
                    "test": "tag",
                    "tag": tag,
                }
            )
    resend = camp.get("is_resend")
    if suppsegs and (len(camp["suppsegs"]) or resend):
        segparts = []
        for suppseg in camp["suppsegs"]:
            segparts.append(
                {
                    "type": "Lists",
                    "operator": "insegment",
                    "segment": suppseg,
                }
            )
        if resend:
            segparts.append(
                {
                    "type": "Responses",
                    "action": "openclicked",
                    "timetype": "anytime",
                    "broadcast": resend,
                    "timenum": 1,
                    "timestart": datetime.utcnow().isoformat() + "Z",
                    "timeend": datetime.utcnow().isoformat() + "Z",
                }
            )
        topparts = [
            {
                "type": "Group",
                "operator": "nor",
                "parts": segparts,
            },
            {
                "type": "Group",
                "operator": op,
                "parts": p,
            },
        ]
        p = topparts
        op = "and"
    return {
        "id": shortuuid.uuid(),
        "cid": camp["cid"],
        "operator": op,
        "parts": p,
        "subset": False,
    }


@tasks.task(priority=HIGH_PRIORITY)
def campaign_calculate_start(
    fakesegment: JsonObj,
    suppsegment: JsonObj | None,
    listfactors: List[str],
    hashlimit: int,
    suppfactors: List[str],
    campaignids: List[str],
    supptags: List[str],
    gatherid: str,
) -> None:
    try:
        taskparams = []
        for i in range(hashlimit):
            taskparams.append(
                (
                    campaign_calculate_segment,
                    fakesegment,
                    suppsegment,
                    i,
                    listfactors,
                    hashlimit,
                    suppfactors,
                    campaignids,
                    supptags,
                    gatherid,
                )
            )
        run_tasks(taskparams)
    except Exception as e:
        log.exception("error")
        with open_db() as db:
            gather_complete(db, gatherid, {"error": str(e)}, False)


class CampaignCalculate(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        camp = json_obj(
            db.row(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s and cid = %s",
                id,
                db.get_cid(),
            )
        )

        if camp is None:
            raise falcon.HTTPForbidden()

        db.set_cid(None)

        fakesegment = fake_segment(camp, False)
        suppsegment = None
        if len(camp["suppsegs"]) or camp.get("is_resend"):
            suppsegment = fake_segment(camp)

        supplists = []
        for sl in camp["supplists"]:
            supplist = db.supplists.get(sl)
            if supplist is None:
                raise falcon.HTTPForbidden()
            if "count" not in supplist or not isinstance(supplist["count"], int):
                raise falcon.HTTPBadRequest(
                    title="Suppression list not loaded",
                    description="Suppression list data is not fully imported, try again soon",
                )
            supplists.append(supplist)

        for l in camp["lists"]:
            if db.lists.get(l) is None:
                raise falcon.HTTPForbidden()
        for l in camp["segments"]:
            if db.segments.get(l) is None:
                raise falcon.HTTPForbidden()
        for l in camp["suppsegs"]:
            if db.segments.get(l) is None:
                raise falcon.HTTPForbidden()

        segments: Dict[str, JsonObj | None] = {}
        suppsegments: Dict[str, JsonObj | None] = {}
        segment_get_segments(db, fakesegment["parts"], segments)
        if suppsegment is not None:
            segment_get_segments(db, suppsegment["parts"], suppsegments)

        campaignids = segment_get_campaignids(fakesegment, list(segments.values()))
        campaignidset = set(campaignids)
        if suppsegment is not None:
            for campaignid in segment_get_campaignids(
                suppsegment, list(suppsegments.values())
            ):
                if campaignid not in campaignidset:
                    campaignids.append(campaignid)

        hashlimit, listfactors = segment_get_params(
            db, camp["cid"], fakesegment, approvedonly=True
        )
        suppseghashlimit, suppseglistfactors = None, None
        if suppsegment is not None:
            suppseghashlimit, suppseglistfactors = segment_get_params(
                db, camp["cid"], suppsegment, approvedonly=True
            )
            hashlimit = max(hashlimit, suppseghashlimit)
            for listfactor in suppseglistfactors:
                if listfactor not in listfactors:
                    listfactors.append(listfactor)

        gatherid = gather_init(db, "campaign_calculate_segment", hashlimit)

        suppfactors = [supplist["id"] for supplist in supplists if supplist is not None]

        run_task(
            campaign_calculate_start,
            fakesegment,
            suppsegment,
            listfactors,
            hashlimit,
            suppfactors,
            campaignids,
            camp.get("supptags", []),
            gatherid,
        )

        req.context["result"] = {"id": gatherid}


class CampaignCalculateStatus(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        db.set_cid(None)

        data = gather_check(db, id)
        if data is None:
            req.context["result"] = {}
        else:
            for d in data:
                if d.get("error", None):
                    req.context["result"] = {"error": d["error"]}
                    return
            req.context["result"] = {
                "complete": True,
                "suppressed": sum(d["suppressed"] for d in data),
                "remaining": sum(d["remaining"] for d in data),
                "unavailable": sum(d["unavailable"] for d in data),
                "count": sum(d["count"] for d in data),
            }


class CampaignTest(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        if "to" not in doc:
            raise falcon.HTTPBadRequest(
                title="Missing parameter", description="No to address specified."
            )

        camp = db.campaigns.get(id)

        if camp is None:
            raise falcon.HTTPForbidden()

        validate_campaign_sender(db, camp)

        db.set_cid(None)

        db.users.patch(
            req.context["uid"], {"lasttest": {"to": doc["to"], "route": doc["route"]}}
        )

        company = db.companies.get(camp["cid"])
        if company is None:
            raise falcon.HTTPForbidden()

        check_test_limit(db, company, doc["to"].strip().lower())

        availroutes = company["routes"]
        if doc.get("route", ""):
            if doc["route"] not in availroutes:
                raise falcon.HTTPForbidden()
        elif len(availroutes) == 1:
            doc["route"] = availroutes[0]
        else:
            raise falcon.HTTPBadRequest(
                title="Missing parameter",
                description="No route specified and multiple are available.",
            )

        route = db.routes.get(doc["route"])
        if route is None or "published" not in route:
            raise falcon.HTTPForbidden()

        imagebucket = os.environ["s3_imagebucket"]
        parentcompany = db.companies.get(company["cid"])
        if parentcompany is not None:
            imagebucket = parentcompany.get("s3_imagebucket", imagebucket)

        html, _ = generate_html(db, camp, "test", imagebucket)

        _, addr = email.utils.parseaddr(doc["to"])
        if not addr:
            addr = remove_newlines(doc["to"])

        fromemail = camp.get("returnpath") or camp["fromemail"]

        fromdomain = ""
        if "@" in fromemail:
            fromdomain = fromemail.split("@")[-1].strip().lower()

        frm = email.utils.formataddr(
            (
                remove_newlines(camp["fromname"]),
                remove_newlines(camp.get("fromemail") or camp["returnpath"]),
            )
        )

        if camp.get("replyto", ""):
            replyto = remove_newlines(camp["replyto"])
        else:
            replyto = remove_newlines(camp.get("fromemail") or camp["returnpath"])

        try:
            send_backend_mail(
                db,
                camp["cid"],
                route,
                html,
                frm,
                fromemail,
                fromdomain,
                replyto,
                remove_newlines(doc["to"]),
                addr,
                remove_newlines(camp["subject"]),
            )
        except Exception as e:
            traceback.print_exc()
            raise falcon.HTTPBadRequest(
                title="Error sending test", description="Error sending test: %s" % e
            )


class RecentCampaigns(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        db = req.context["db"]

        segid = req.get_param("segid")

        campaignids = []
        if segid is not None and segid != "new":
            segment = db.segments.get(segid)
            if segment is not None:
                segments: Dict[str, JsonObj | None] = {}
                segment_get_segments(db, segment["parts"], segments)

                campaignids = segment_get_campaignids(segment, list(segments.values()))

        ret = list(
            json_iter(
                db.execute(
                    "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and data->>'sent_at' is not null and data->>'hidden' is null order by data->>'sent_at' desc limit 150",
                    db.get_cid(),
                )
            )
        )
        for r in ret:
            r["is_bc"] = True

        for mid, mcid, mdata, fname in db.execute(
            """select m.id, m.cid, m.data - 'parts' - 'rawText', f.data->>'name' from messages m inner join funnels f on m.data->>'funnel' = f.id
                                            where m.cid = %s order by m.data->>'modified' desc limit 150""",
            db.get_cid(),
        ):
            msg = json_obj((mid, mcid, mdata))
            msg["name"] = "%s: %s" % (fname, msg["subject"])
            msg["is_bc"] = False

            ret.append(msg)

        for c in campaignids:
            found = False
            for r in ret:
                if r["id"] == c:
                    found = True
                    break
            if not found:
                camp = json_obj(
                    db.row(
                        "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and id = %s",
                        db.get_cid(),
                        c,
                    )
                )
                if camp is None:
                    camp = json_obj(
                        db.row(
                            "select id, cid, data - 'parts' - 'rawText' from messages where cid = %s and id = %s",
                            db.get_cid(),
                            c,
                        )
                    )
                    if camp is not None:
                        funnel = db.funnels.get(camp["funnel"])
                        if funnel is None:
                            camp = None
                        else:
                            camp["name"] = "%s: %s" % (funnel["name"], camp["subject"])
                            camp["is_bc"] = False
                else:
                    camp["is_bc"] = True
                if camp is not None:
                    ret.append(camp)

        ret.sort(
            key=lambda x: cast(str, x.get("sent_at")) or cast(str, x.get("modified")),
            reverse=True,
        )

        req.context["result"] = ret


BROADCAST_SCHEMA = {
    "type": "object",
    "required": ["name", "when", "subject", "fromname", "returnpath", "rawText"],
    "properties": {
        "name": {
            "type": "string",
            "maxLength": 1024,
            "minLength": 1,
        },
        "when": {"enum": ["draft", "now", "schedule", "sendnow"]},
        "scheduled_for": {
            "type": ["string", "null"],
            "if": {"type": "string"},
            "then": {"format": "date-time"},
        },
        "route": {
            "type": "string",
            "maxLength": 22,
        },
        "tags": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 1024,
            },
        },
        "supptags": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 1024,
            },
        },
        "lists": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 22,
            },
        },
        "segments": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 22,
            },
        },
        "supplists": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 22,
            },
        },
        "suppsegs": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 22,
            },
        },
        "subject": {
            "type": "string",
            "maxLength": 1024,
            "minLength": 1,
        },
        "fromname": {
            "type": "string",
            "maxLength": 1024,
            "minLength": 1,
        },
        "returnpath": {
            "type": "string",
            "maxLength": 1024,
            "minLength": 1,
        },
        "fromemail": {
            "type": "string",
            "maxLength": 1024,
        },
        "replyto": {
            "type": "string",
            "maxLength": 1024,
        },
        "rawText": {
            "type": "string",
        },
        "openaddtags": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 1024,
            },
        },
        "openremtags": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 1024,
            },
        },
        "clickaddtags": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 1024,
            },
        },
        "clickremtags": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 1024,
            },
        },
        "sendaddtags": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 1024,
            },
        },
        "sendremtags": {
            "type": "array",
            "items": {
                "type": "string",
                "maxLength": 1024,
            },
        },
        "funnel": {
            "type": "string",
            "maxLength": 22,
        },
        "disableopens": {
            "type": "boolean",
        },
        "randomize": {
            "type": "boolean",
        },
        "newestfirst": {
            "type": "boolean",
        },
        "parts": {
            "type": "array",
        },
        "bodyStyle": {
            "type": "object",
        },
        "preheader": {
            "type": "string",
        },
        "initialize": {
            "type": "boolean",
        },
        "modified": {
            "type": "string",
        },
        "last_calc": {
            "type": ["object", "null"],
        },
        "resend": {
            "type": "boolean",
        },
        "resendwhennum": {
            "type": "integer",
        },
        "resendwhentype": {
            "type": "string",
        },
        "resendsubject": {
            "type": "string",
        },
        "resendpreheader": {
            "type": "string",
        },
        "delivered": {},
        "send": {},
        "soft": {},
        "hard": {},
        "type": {},
    },
    "additionalProperties": False,
}


class Campaigns(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "campaigns"
        self.large = "parts"
        self.useronly = True
        self.schema = BROADCAST_SCHEMA
        self.api = True

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req, True)

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        doc["modified"] = datetime.utcnow().isoformat() + "Z"
        doc["delivered"] = 0
        doc["send"] = 0
        doc["soft"] = 0
        doc["hard"] = 0

        send = False
        if doc.get("when") == "sendnow":
            doc["when"] = "now"
            send = True

        if req.context["api"]:
            doc["type"] = "raw"
            doc["parts"] = []
            doc["bodyStyle"] = {}

        if "tags" not in doc:
            doc["tags"] = []
        if "lists" not in doc:
            doc["lists"] = []
        if "segments" not in doc:
            doc["segments"] = []
        if "supplists" not in doc:
            doc["supplists"] = []
        if "suppsegs" not in doc:
            doc["suppsegs"] = []
        if "supptags" not in doc:
            doc["supptags"] = []
        if "openaddtags" not in doc:
            doc["openaddtags"] = []
        if "openremtags" not in doc:
            doc["openremtags"] = []
        if "clickaddtags" not in doc:
            doc["clickaddtags"] = []
        if "clickremtags" not in doc:
            doc["clickremtags"] = []
        if "sendaddtags" not in doc:
            doc["sendaddtags"] = []
        if "sendremtags" not in doc:
            doc["sendremtags"] = []
        if "funnel" not in doc:
            doc["funnel"] = ""
        if "disableopens" not in doc:
            doc["disableopens"] = False
        if "randomize" not in doc:
            doc["randomize"] = False
        if "newestfirst" not in doc:
            doc["newestfirst"] = False
        if "scheduled_for" not in doc:
            doc["scheduled_for"] = None

        validate_sender_domains(
            req.context["db"],
            req.context["db"].get_cid(),
            doc.get("fromemail"),
            doc.get("returnpath"),
        )

        CRUDCollection.on_post(self, req, resp)

        if send:
            camp = req.context["result"]
            campcid = camp["cid"]

            db = req.context["db"]
            db.set_cid(None)

            company = db.companies.get(campcid)

            if company is None:
                raise Exception(
                    "No postal route configured for you to send mail with. Please contact your administrator."
                )

            ok = db.single(
                """update campaigns set data = data || %s where id = %s and (data->>'sent_at' is null or data->>'sent_at' = '') returning true""",
                {
                    "sent_at": datetime.utcnow().isoformat() + "Z",
                    "count": "counting",
                    "sinkstatus": {},
                },
                camp["id"],
            )
            if ok:
                run_task(campaign_start, camp["id"])

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        ret: List[JsonObj | None] = []

        older = req.get_param("older")
        newer = req.get_param("newer")
        search = req.get_param("search")

        searchquery = ""
        searchparams = []
        if search:
            search = re.escape(search.lower())
            searchquery = "and (lower(data->>'name') ~ %s or lower(data->>'subject') ~ %s or lower(data->>'fromname') ~ %s)"
            searchparams = [search, search, search]

        cid = db.get_cid()
        db.set_cid(None)

        company = db.companies.get(cid)
        frontend = json_obj(
            db.row(
                "select id, cid, data - 'image' from frontends where id = %s",
                company["frontend"],
            )
        )

        domainrates = [dr for dr in frontend["domainrates"] if dr["domain"].strip()]

        def load_campaigns(
            q: str, qparams: List[Any], sort: str
        ) -> Iterable[JsonObj | None]:
            if not len(domainrates):
                return json_iter(
                    db.execute(
                        """select id, cid, data - 'parts' - 'rawText'
                                               from campaigns where cid = %%s and data->>'sent_at' is not null and data->>'hidden' is null %s %s
                                               order by data->>'sent_at' %s limit 100"""
                        % (q, searchquery, sort),
                        *([cid] + qparams + searchparams),
                    )
                )
            else:
                ids = [
                    id
                    for id, in db.execute(
                        """select id from campaigns
                                                   where cid = %%s and data->>'sent_at' is not null and data->>'hidden' is null %s %s
                                                   order by data->>'sent_at' %s limit 100"""
                        % (q, searchquery, sort),
                        *([cid] + qparams + searchparams),
                    )
                ]

                check1params = []
                for dr in domainrates:
                    check1params.extend(
                        [
                            dr["domain"].strip().lower(),
                            dr["bouncerate"],
                            dr["bouncerate"],
                        ]
                    )
                check1 = " or ".join(
                    """(domaingroupid = %s and (((sum(soft)::float / nullif(sum(send)::float, 0)) * 100) >= %s or
                                                               ((sum(hard)::float / nullif(sum(send)::float, 0)) * 100) >= %s))"""
                    for dr in domainrates
                )
                check2params = []
                for dr in domainrates:
                    check2params.extend(
                        [dr["domain"].strip().lower(), dr["complaintrate"]]
                    )
                check2 = " or ".join(
                    "(domaingroupid = %s and ((sum(complaint)::float / nullif(sum(send)::float, 0)) * 100) >= %s)"
                    for dr in domainrates
                )
                query = """
                select c.id, c.cid, c.data, b.overcount, ct.overcount from
                 (select id, cid, data - 'parts' - 'rawText' as data from campaigns where id = any(%%s)) c
                 left join (
                   select campid, count(domaingroupid) overcount from (
                       select domaingroupid, campid
                       from hourstats
                       where campid = any(%%s)
                       group by campid, domaingroupid
                       having %s
                   ) sub
                   group by campid
                 ) b on b.campid = c.id
                 left join (
                   select campid, count(domaingroupid) overcount from (
                       select domaingroupid, campid
                       from hourstats
                       where campid = any(%%s)
                       group by campid, domaingroupid
                       having %s
                   ) sub
                   group by campid
                 ) ct on ct.campid = c.id
                 order by c.data->>'sent_at' desc
                """ % (
                    check1,
                    check2,
                )

                def json_iter_modified(
                    i: Iterable[
                        Tuple[str, str, JsonObj, int | None, int | None] | None
                    ],
                ) -> Iterable[JsonObj | None]:
                    for row in i:
                        if row is None:
                            yield None
                        else:
                            id, cid, data, overbounce, overcomplaint = row
                            data["id"] = id
                            data["cid"] = cid
                            data["overdomainbounce"] = bool(overbounce)
                            data["overdomaincomplaint"] = bool(overcomplaint)
                            yield data

                return json_iter_modified(
                    db.execute(
                        query, *([ids, ids] + check1params + [ids] + check2params)
                    )
                )

        if older is not None:
            ret.extend(load_campaigns(" and data->>'sent_at' < %s", [older], "desc"))
            cnt = db.single(
                "select count(id) from campaigns where cid = %%s and data->>'sent_at' is not null and data->>'hidden' is null and data->>'sent_at' < %%s %s"
                % searchquery,
                *([cid, older] + searchparams),
            )
        elif newer is not None:
            ret.extend(load_campaigns(" and data->>'sent_at' > %s", [newer], "asc"))
            cnt = db.single(
                "select count(id) from campaigns where cid = %%s and data->>'sent_at' is not null and data->>'hidden' is null and data->>'sent_at' > %%s %s"
                % searchquery,
                *([cid, newer] + searchparams),
            )
        else:
            # drafts
            ret.extend(
                json_iter(
                    db.execute(
                        "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and data->>'sent_at' is null order by data->>'modified' desc",
                        cid,
                    )
                )
            )

            # sent
            ret.extend(load_campaigns("", [], "desc"))

            cnt = db.single(
                "select count(id) from campaigns where cid = %%s and data->>'sent_at' is not null and data->>'hidden' is null %s"
                % searchquery,
                *([cid] + searchparams),
            )

        if req.context["api"]:
            for c in ret:
                if c is None:
                    continue
                c.pop(
                    "delivered", None
                )  # delivered has a confusing name so we remove it from API clients
                c.pop("parts", None)
                c.pop("bodyStyle", None)

        req.context["result"] = {
            "campaigns": ret,
            "count": cnt,
        }


class Broadcasts(Campaigns):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        Campaigns.on_get(self, req, resp)

        req.context["result"]["broadcasts"] = req.context["result"]["campaigns"]
        del req.context["result"]["campaigns"]


class Campaign(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "campaigns"
        self.useronly = True
        self.schema = patch_schema(BROADCAST_SCHEMA)
        self.api = True

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        db = req.context["db"]
        exist = json_obj(
            db.row(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and id = %s",
                db.get_cid(),
                id,
            )
        )
        if exist is None:
            raise falcon.HTTPForbidden()
        if exist.get("sent_at", None):
            raise falcon.HTTPBadRequest(
                title="Broadcast started",
                description="This broadcast has already been sent",
            )

        doc["modified"] = datetime.utcnow().isoformat() + "Z"
        doc.pop("type", None)

        validate_campaign_sender(db, {**exist, **doc})

        CRUDSingle.on_patch(self, req, resp, id)

        if (
            not exist.get("example")
            and "parts" in doc
            and len(doc["parts"]) > 0
            and doc["parts"][-1].get("footer", False)
        ):
            mycid = db.get_cid()
            db.set_cid(None)
            doc["parts"][-1].pop("html", None)
            db.companies.patch(mycid, {"lastFooter": doc["parts"][-1]})

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:

        CRUDSingle.on_get(self, req, resp, id)

        if req.context["api"]:
            req.context["result"].pop(
                "delivered", None
            )  # delivered has a confusing name so we remove it from API clients
            req.context["result"].pop("parts", None)
            req.context["result"].pop("bodyStyle", None)
            req.context["result"].pop("preheader", None)

    def on_delete(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        exist = json_obj(
            db.row(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and id = %s",
                db.get_cid(),
                id,
            )
        )

        if exist is not None:
            started = exist.get("sent_at", None)
            finished = (
                exist.get("finished_at") or exist.get("canceled") or exist.get("error")
            )

            if started and not finished:
                raise falcon.HTTPBadRequest(
                    title="Broadcast started",
                    description="This broadcast has been started, cancel it first before deleting",
                )
            if finished:
                db.campaigns.patch(id, {"hidden": True})
                return

        return CRUDSingle.on_delete(self, req, resp, id)


class CampaignClientStats(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        exist = json_obj(
            db.row(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and id = %s",
                db.get_cid(),
                id,
            )
        )
        if exist is None:
            raise falcon.HTTPForbidden()

        devices = []
        for device, count in db.execute(
            "select device, count from campaign_devices where campaign_id = %s order by count desc",
            id,
        ):
            devices.append(
                {
                    "device": device_names[device],
                    "count": count,
                }
            )
        clients = []
        for osname, browser, count in db.execute(
            "select os, browser, count from campaign_browsers where campaign_id = %s order by count desc",
            id,
        ):
            clients.append(
                {
                    "os": os_names[osname],
                    "browser": browser_names[browser],
                    "count": count,
                }
            )
        geo = []
        for country, countrycode, region, count in db.execute(
            """select country, country_code, region, count
                                                                from campaign_locations where campaign_id = %s
                                                                order by count desc""",
            id,
        ):
            geo.append(
                {
                    "country": country,
                    "country_code": countrycode,
                    "region": region,
                    "count": count,
                }
            )

        req.context["result"] = {
            "devices": devices,
            "browsers": clients,
            "locations": geo,
        }


class CampaignDetails:

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        cmd = req.get_param("cmd")
        domain = req.get_param("domain", None)

        if domain:
            domain = "@" + domain.strip().lower()
        else:
            domain = ""

        c = json_obj(
            db.row(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and id = %s",
                db.get_cid(),
                id,
            )
        )
        if c is None:
            c = json_obj(
                db.row(
                    "select id, cid, data - 'parts' - 'rawText' from messages where cid = %s and id = %s",
                    db.get_cid(),
                    id,
                )
            )
            if c is None:
                raise falcon.HTTPForbidden()

        page = int(req.get_param("page", default=1))

        PAGE_SIZE = 500

        records = [
            {
                "email": email,
                "ts": ts.isoformat() + "Z",
                "code": code,
            }
            for email, ts, code in db.execute(
                """
            select email, ts, code
            from camplogs
            where campid = %s and cmd = %s
            and (%s = '' or email like %s)
            order by ts desc, email asc
            limit %s offset %s""",
                id,
                cmd,
                domain,
                "%" + domain,
                PAGE_SIZE,
                PAGE_SIZE * (page - 1),
            )
        ]

        total = db.single(
            """
            select count(email)
            from camplogs
            where campid = %s and cmd = %s
            and (%s = '' or email like %s)
            """,
            id,
            cmd,
            domain,
            "%" + domain,
        )

        req.context["result"] = {
            "records": records,
            "page_size": PAGE_SIZE,
            "total": total,
        }


class TestEmails(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        db = req.context["db"]

        req.context["result"] = db.testemails.get_singleton()

    def on_patch(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        db.testemails.patch_singleton(doc)


CHECK_RESENDS_LOCK = 44918808


def check_resends() -> None:
    with open_db() as db:
        with db.transaction():
            if not db.single(f"select pg_try_advisory_xact_lock({CHECK_RESENDS_LOCK})"):
                return

            ids = [
                id
                for id, in db.execute(
                    """select id from campaigns
                       where data->>'sent_at' is not null
                       and (
                        (data->>'finished_at' is not null and data->>'error' is null)
                        or coalesce((data->>'canceled')::boolean, false)
                       )
                       and data->>'processed_resend' is null
                       and coalesce((data->>'resend')::boolean, false)
                       and data->>'is_resend' is null
                       and data->>'resendwhennum' is not null
                       and (data->>'delivered')::float >= ((data->>'count')::float * .9)"""
                )
            ]
            for id in ids:
                db.campaigns.patch(id, {"processed_resend": True})

            for id in ids:
                try:
                    camp = db.campaigns.get(id)
                    if camp is None:
                        continue

                    db.set_cid(camp["cid"])

                    try:
                        origname = camp["name"]

                        if camp.get("resendwhentype", "days") == "days":
                            ts = timedelta(days=camp["resendwhennum"])
                        else:
                            ts = timedelta(hours=camp["resendwhennum"])

                        dupeid = dupe_campaign(db, camp)
                        db.campaigns.patch(
                            dupeid,
                            {
                                "name": origname + " (resend)",
                                "subject": camp.get("resendsubject") or camp["subject"],
                                "preheader": camp.get("resendpreheader")
                                or camp["preheader"],
                                "resendsubject": "",
                                "resendpreheader": "",
                                "when": "schedule",
                                "scheduled_for": (datetime.utcnow() + ts).isoformat()
                                + "Z",
                                "is_resend": id,
                                "resend": False,
                            },
                        )
                    finally:
                        db.set_cid(None)
                except:
                    log.exception("Resend error for campaign id %s", id)


RUN_SCHEDULED_LOCK = 97136366


def run_scheduled() -> None:
    with open_db() as db:
        with db.transaction():
            if not db.single(f"select pg_try_advisory_xact_lock({RUN_SCHEDULED_LOCK})"):
                return

            ids = [
                id
                for id, in db.execute(
                    """select id from campaigns
                                            where data->>'when' = 'schedule'
                                            and data->>'scheduled_for' is not null
                                            and data->>'sent_at' is null
                                            and data->>'processed_schedule' is null
                                            and data->>'scheduled_for' <= %s""",
                    datetime.utcnow().isoformat() + "Z",
                )
            ]

            for id in ids:
                db.campaigns.patch(id, {"processed_schedule": True})

            for id in ids:
                try:
                    camp = json_obj(
                        db.row(
                            "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
                            id,
                        )
                    )
                    if camp is None:
                        continue

                    ok = db.single(
                        """update campaigns set data = data || %s where id = %s and (data->>'sent_at' is null or data->>'sent_at' = '') returning true""",
                        {
                            "sent_at": datetime.utcnow().isoformat() + "Z",
                            "count": "counting",
                            "sinkstatus": {},
                        },
                        id,
                    )
                    if ok:
                        run_task(campaign_start, id)

                        db.campaigns.patch(
                            id,
                            {
                                "sent_at": datetime.utcnow().isoformat() + "Z",
                                "count": "counting",
                                "sinkstatus": {},
                            },
                        )
                except Exception as e:
                    log.exception("error")
                    db.campaigns.patch(
                        id,
                        {
                            "sent_at": datetime.utcnow().isoformat() + "Z",
                            "finished_at": datetime.utcnow().isoformat() + "Z",
                            "error": str(e),
                        },
                    )

try:
    MAX_SEND_LIMIT = max(1, int(os.environ.get("max_send_limit", "1000")))
except ValueError:
    MAX_SEND_LIMIT = 1000


CHECK_CAMPS_LOCK = 59479592


def check_camps() -> None:
    with open_db() as lock_db:
        try:
            with lock_db.transaction():
                if not lock_db.single(
                    f"select pg_try_advisory_xact_lock({CHECK_CAMPS_LOCK})"
                ):
                    log.info("check_camps already running")
                    return

                while True:
                    lastcid: str | None = None
                    lastcampid: str | None = None
                    lastdomain: str | None = None

                    with open_db() as db:
                        with db.transaction():
                            alltasks = []
                            queue_items = list(
                                db.execute(
                                    """select q.cid, campid, c.data->>'route' r, domain, sum(remaining)
                                       from campqueue q
                                       inner join campaigns c on q.campid = c.id and q.cid = c.cid
                                       where (
                                         %s is null or
                                         row(q.cid, campid, domain) > row(%s, %s, %s)
                                       ) and remaining > 0
                                       group by q.cid, campid, r, domain
                                       order by q.cid, campid, domain
                                       limit 200""",
                                    lastcid,
                                    lastcid,
                                    lastcampid,
                                    lastdomain,
                                )
                            )

                            if len(queue_items) == 0:
                                break

                            for cid, campid, route, domain, cnt in queue_items:
                                lastcid = cid
                                lastcampid = campid
                                lastdomain = domain

                                company = db.companies.get(cid)
                                if company is not None:
                                    requesting = cnt

                                    domainthrottles = load_domain_throttles(db, company)

                                    cnt = check_send_limit(
                                        company, route, domain, domainthrottles, cnt
                                    )
                                    if cnt > 0:
                                        log.debug(
                                            "%s clear to send %s for campaign %s route %s domain %s (requested %s)",
                                            cid,
                                            cnt,
                                            campid,
                                            route,
                                            domain,
                                            requesting,
                                        )
                                        items = list(
                                            db.execute(
                                                "select sendid, count, remaining, data from campqueue where cid = %s and campid = %s and domain = %s",
                                                cid,
                                                campid,
                                                domain,
                                            )
                                        )
                                        cntperitem = 1
                                        if len(items):
                                            cntperitem = int(
                                                math.ceil(cnt / len(items))
                                            )
                                        if cntperitem == 0:
                                            cntperitem = 1
                                        for sendid, sendcount, remaining, data in items:
                                            tosend = min(cntperitem, remaining)

                                            # pre-batch these because they can only send one email at a time
                                            if data["policytype"] in (
                                                "ses",
                                                "smtprelay",
                                                "easylink",
                                            ):
                                                taskoffset = sendcount - remaining
                                                tasktosend = min(tosend, MAX_SEND_LIMIT)
                                                tasksent = 0
                                                while tasksent < tosend:
                                                    alltasks.append(
                                                        (
                                                            send_queued_camp,
                                                            cid,
                                                            campid,
                                                            sendid,
                                                            domain,
                                                            data,
                                                            taskoffset,
                                                            tasktosend,
                                                        )
                                                    )
                                                    tasksent += tasktosend
                                                    taskoffset += tasktosend
                                                    tasktosend = min(
                                                        tosend - tasksent,
                                                        MAX_SEND_LIMIT,
                                                    )
                                            else:  # mailgun, sparkpost, mta can all do batch sends
                                                alltasks.append(
                                                    (
                                                        send_queued_camp,
                                                        cid,
                                                        campid,
                                                        sendid,
                                                        domain,
                                                        data,
                                                        sendcount - remaining,
                                                        tosend,
                                                    )
                                                )

                                            if remaining - tosend <= 0:
                                                db.execute(
                                                    "delete from campqueue where cid = %s and campid = %s and sendid = %s and domain = %s",
                                                    cid,
                                                    campid,
                                                    sendid,
                                                    domain,
                                                )

                                                if (
                                                    db.single(
                                                        "select count(sendid) from campqueue where cid = %s and campid = %s and data->>'sinkid' = %s",
                                                        cid,
                                                        campid,
                                                        data["sinkid"],
                                                    )
                                                    == 0
                                                ):
                                                    db.execute(
                                                        "update campaigns set data = data || jsonb_build_object('sinkstatus', (data->>'sinkstatus')::jsonb || jsonb_build_object(%s, true)) where id = %s",
                                                        data["sinkid"],
                                                        campid,
                                                    )

                                                    camp = json_obj(
                                                        db.row(
                                                            "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
                                                            campid,
                                                        )
                                                    )

                                                    if (
                                                        camp is not None
                                                        and False
                                                        not in list(
                                                            camp["sinkstatus"].values()
                                                        )
                                                    ):
                                                        db.campaigns.patch(
                                                            campid,
                                                            {
                                                                "finished_at": datetime.utcnow().isoformat()
                                                                + "Z"
                                                            },
                                                        )
                                            else:
                                                db.execute(
                                                    "update campqueue set remaining = remaining - %s where cid = %s and campid = %s and sendid = %s and domain = %s",
                                                    tosend,
                                                    cid,
                                                    campid,
                                                    sendid,
                                                    domain,
                                                )

                                            cnt -= tosend

                                            if cnt <= 0:
                                                break

                            run_tasks(alltasks)
        except:
            log.exception("error")


@tasks.task(priority=LOW_PRIORITY)
def send_queued_camp(
    cid: str,
    campid: str,
    sendid: str,
    domain: str | None,
    data: JsonObj,
    offset: int,
    tosend: int,
) -> None:
    with open_db() as db:
        try:
            if domain is None:
                domain = ""

            policytype = data["policytype"]
            sinkid = data["sinkid"]
            sendid = data["sendid"]
            frm = data["from"]
            returnpath = data.get("returnpath", "")
            fromdomain = data["fromdomain"]
            replyto = data["replyto"]
            subject = data["subject"]
            bodykey = data["template"]
            listkey = data["listkey"]
            settingsid = data["settingsid"]

            bodydomain = ""
            headers = ""
            fromencoding = "none"
            subjectencoding = "none"
            usedkim = True
            company = db.companies.get(cid)
            if company is not None:
                frontend = json_obj(
                    db.row(
                        "select id, cid, data - 'image' from frontends where id = %s",
                        company["frontend"],
                    )
                )
                if frontend is not None:
                    bodydomain = frontend.get("bodydomain", "")
                    headers = fix_headers(frontend.get("headers", ""))
                    fromencoding = frontend.get("fromencoding", "")
                    subjectencoding = frontend.get("subjectencoding", "")
                    usedkim = frontend.get("usedkim", True)

            if policytype == "mailgun":
                obj = db.mailgun.get(sinkid)
            elif policytype == "ses":
                obj = db.ses.get(sinkid)
            elif policytype == "sparkpost":
                obj = db.sparkpost.get(sinkid)
            elif policytype == "easylink":
                obj = db.easylink.get(sinkid)
            elif policytype == "smtprelay":
                obj = db.smtprelays.get(sinkid)
            else:
                obj = db.sinks.get(sinkid)

            if obj is None:
                raise Exception("Sink not found")

            mtasettings = {}
            dkim = {}
            allips: Set[str] = set()
            allsinks: Set[str] = set()
            db.set_cid(obj["cid"])
            try:
                for p in db.policies.find():
                    if p.get("published", None) is not None:
                        mtasettings[p["id"]] = p["published"]
                pauses: Dict[str, List[JsonObj]] = {}
                for pause in db.ippauses.find():
                    if pause["sinkid"] not in pauses:
                        pauses[pause["sinkid"]] = []
                    pauses[pause["sinkid"]].append(pause)
                warmups: Dict[str, Dict[str, JsonObj]] = {}
                for warmup in db.warmups.find():
                    if warmup.get("published", None) is not None:
                        if warmup["sink"] not in warmups:
                            warmups[warmup["sink"]] = {}
                        warmups[warmup["sink"]][warmup["id"]] = warmup["published"]
                        warmups[warmup["sink"]][warmup["id"]]["disabled"] = warmup.get(
                            "disabled", False
                        )
                for sink in db.sinks.find():
                    allips.update(d["ip"] for d in sink["ipdata"])
                    allsinks.add(sink["id"])
                dkim = db.dkimentries.get_singleton()
            finally:
                db.set_cid(None)

            html = s3_read(os.environ["s3_databucket"], bodykey).decode("utf-8")

            domaincounts = {}

            with s3_read_stream(os.environ["s3_databucket"], listkey) as stream:
                reader = MPDictReader(stream)

                outfile = BytesIO()
                writer = MPDictWriter(outfile, reader.headers)
                writer.writeheader()
                c = 0
                written = 0
                for row in reader:
                    rowdomain = row["Email"].split("@")[1]

                    if domain and rowdomain != domain:
                        continue

                    if c >= offset:
                        if rowdomain not in domaincounts:
                            domaincounts[rowdomain] = 1
                        else:
                            domaincounts[rowdomain] = domaincounts[rowdomain] + 1

                        writer.writerow(row)
                        written += 1
                    if written >= tosend:
                        break
                    c += 1

            listcomps = listkey.split("/")
            listfile = listcomps[-1]

            if domain:
                newlistkey = "%s/%s-%s-%s" % (
                    "/".join(listcomps[:-1]),
                    offset,
                    domain,
                    listfile,
                )
            else:
                newlistkey = "%s/%s-%s" % ("/".join(listcomps[:-1]), offset, listfile)

            outfile.seek(0, 0)
            s3_write_stream(os.environ["s3_transferbucket"], newlistkey, outfile)

            if db.single(
                "select (data->>'canceled')::boolean from campaigns where id = %s",
                campid,
            ):
                return

            if policytype == "mailgun":
                mailgun_send(
                    obj,
                    client_domain(db, fromdomain, cid, obj["id"]),
                    frm,
                    replyto,
                    subject,
                    html,
                    campid,
                    cid,
                    True,
                    recipkey=newlistkey,
                    write_err=True,
                )
            elif policytype == "ses":
                ses_send(
                    obj,
                    frm,
                    replyto,
                    subject,
                    html,
                    campid,
                    cid,
                    True,
                    recipkey=newlistkey,
                    write_err=True,
                )
            elif policytype == "sparkpost":
                sparkpost_send(
                    obj,
                    frm,
                    replyto,
                    subject,
                    html,
                    campid,
                    cid,
                    True,
                    recipkey=newlistkey,
                    write_err=True,
                )
            elif policytype == "easylink":
                easylink_send(
                    obj,
                    frm,
                    replyto,
                    subject,
                    html,
                    campid,
                    cid,
                    True,
                    recipkey=newlistkey,
                    write_err=True,
                )
            elif policytype == "smtprelay":
                smtprelay_send(
                    obj,
                    frm,
                    replyto,
                    subject,
                    html,
                    campid,
                    cid,
                    True,
                    recipkey=newlistkey,
                    write_err=True,
                )
            else:
                url = fix_sink_url(obj["url"])

                s = {}
                for sid, p in mtasettings.items():
                    s[sid] = sink_get_settings(p, obj["id"])

                r = requests.post(
                    url + "/settings",
                    json={
                        "accesskey": obj["accesskey"],
                        "sinkid": obj["id"],
                        "mtasettings": s,
                        "ippauses": pauses.get(obj["id"], []),
                        "warmups": warmups.get(obj["id"], {}),
                        "allips": list(allips),
                        "allsinks": list(allsinks),
                        "ipdomains": sink_get_ips(obj),
                        "dkim": dkim,
                    },
                    timeout=MTA_TIMEOUT,
                )
                r.raise_for_status()

                db.sinks.patch(obj["id"], {"failed_update": False})

                if db.single(
                    "select (data->>'canceled')::boolean from campaigns where id = %s",
                    campid,
                ):
                    return

                webroot = get_webroot()
                if os.environ.get("development"):
                    webroot = "http://proxy"

                r = requests.post(
                    url + "/send-lists",
                    json={
                        "id": campid,
                        "sendid": "%s-%s-%s" % (sendid, domain, offset),
                        "domaincounts": domaincounts,
                        "from": frm,
                        "returnpath": returnpath,
                        "replyto": replyto,
                        "subject": subject,
                        "accesskey": obj["accesskey"],
                        "template": html,
                        "listurls": [f"{webroot}/transfer/{newlistkey}"],
                        "settingsid": settingsid,
                        "bodydomain": bodydomain,
                        "headers": headers,
                        "fromencoding": fromencoding,
                        "subjectencoding": subjectencoding,
                        "usedkim": usedkim,
                    },
                    timeout=MTA_TIMEOUT,
                )
                r.raise_for_status()
        except Exception as e:
            log.exception("error")
            db.campaigns.patch(
                campid,
                {"finished_at": datetime.utcnow().isoformat() + "Z", "error": str(e)},
            )


class SavedRows(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "savedrows"
        self.useronly = True

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        CRUDCollection.on_get(self, req, resp)

        has_footer = False
        for row in req.context["result"]:
            if (
                row.get("rowJson", {}).get("metadata", {}).get("type")
                == "sticky-footer"
            ):
                has_footer = True
                break

        if not has_footer:
            year = str(datetime.now().year)
            db = req.context["db"]
            cid = db.get_cid()
            db.set_cid(None)
            companyname = db.companies.get(cid).get("name", "")

            rowHtml = open("/setup/beefree-footer/sticky-footer.html").read()
            rowJson = open("/setup/beefree-footer/sticky-footer.json").read()
            pageJson = open("/setup/beefree-footer/sticky-footer.page.json").read()

            rowHtml = rowHtml.replace("{{COMPANYNAME}}", companyname)
            rowHtml = rowHtml.replace("{{YEAR}}", year)
            rowJson = rowJson.replace("{{COMPANYNAME}}", companyname)
            rowJson = rowJson.replace("{{YEAR}}", year)
            pageJson = pageJson.replace("{{COMPANYNAME}}", companyname)
            pageJson = pageJson.replace("{{YEAR}}", year)

            req.context["result"].append(
                {
                    "rowHtml": rowHtml,
                    "rowJson": json.loads(rowJson),
                    "pageJson": json.loads(pageJson),
                }
            )

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        db = req.context["db"]

        check_noadmin(req, True)

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        if "rowJson" not in doc:
            doc["rowJson"] = {}
        if "metadata" not in doc["rowJson"]:
            doc["rowJson"]["metadata"] = {}

        if doc["rowJson"]["metadata"].get("type") == "sticky-footer":
            exist = json_obj(
                db.row(
                    "select id, cid, data from savedrows where cid = %s and data->'rowJson'->'metadata'->>'type' = 'sticky-footer'",
                    db.get_cid(),
                )
            )
            if not exist:
                db.savedrows.add(doc)
            else:
                db.savedrows.patch(exist["id"], doc)
        else:
            CRUDCollection.on_post(self, req, resp)

            id = req.context["result"]["id"]

            doc["rowJson"]["metadata"]["rowId"] = id
            req.context["result"]["rowJson"]["metadata"]["rowId"] = id

            db.savedrows.patch(id, doc)

            req.context["result"] = doc


class SavedRow(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "savedrows"
        self.useronly = True

    def on_delete(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        db = req.context["db"]

        check_noadmin(req, True)

        real_id = db.single(
            "select id from savedrows where cid = %s and data->'rowJson'->'metadata'->>'rowId' = %s",
            db.get_cid(),
            id,
        )

        if real_id is not None:
            db[self.domain].remove(real_id)
