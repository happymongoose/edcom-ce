import os
import json
import requests
import falcon
import shortuuid
import dateutil.parser
import redis
from typing import Tuple, List, Dict, Any, Callable
from netaddr import IPAddress
from datetime import datetime, timedelta

from .shared import config as _  # noqa: F401
from .shared.db import open_db, json_obj, statlogs_obj, DB, JsonObj
from .shared.utils import (
    fix_tag,
    get_contact_id,
    redis_connect,
    get_txn,
    get_os,
    get_browser,
    get_device,
    os_names,
    browser_names,
    device_names,
    unix_time_secs,
    GIF,
    emailre,
    paramre,
    openletters,
    clickletters,
    unsubletters,
)
from .shared.send import unencrypt, handle_soft_event
from .shared.crud import check_noadmin
from .shared.s3 import s3_read, s3_delete
from .shared import contacts
from .shared.log import get_logger
from .shared.webhooks import send_webhooks

log = get_logger()

campprops = {
    "open": "opened",
    "click": "clicked",
    "bounce": "bounced",
    "complaint": "complained",
    "unsub": "unsubscribed",
}

mailtimeepoch = datetime(2018, 7, 30, 0, 0, 0, 0)


def hourstats_insert(
    db: DB,
    cid: str,
    campcid: str,
    ts: datetime,
    sinkid: str,
    domain: str,
    ip: str,
    settingsid: str,
    campid: str,
    complaint: int,
    unsub: int,
    open: int,
    click: int,
    send: int = 0,
    soft: int = 0,
    hard: int = 0,
    err: int = 0,
    defercnt: int = 0,
) -> None:
    db.execute(
        """insert into hourstats (id, cid, campcid, ts, sinkid, domaingroupid, ip, settingsid, campid,
                  complaint, unsub, open, click, send, soft, hard, err, defercnt)
                  values (%s, %s, %s, date_trunc('hour', %s), %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s)
                  on conflict on constraint hourstats_uniq do update set
                  complaint = hourstats.complaint + excluded.complaint,
                  unsub =     hourstats.unsub     + excluded.unsub,
                  open =      hourstats.open      + excluded.open,
                  click =     hourstats.click     + excluded.click,
                  send =      hourstats.send      + excluded.send,
                  soft =      hourstats.soft      + excluded.soft,
                  hard =      hourstats.hard      + excluded.hard,
                  err =       hourstats.err       + excluded.err,
                  defercnt =  hourstats.defercnt  + excluded.defercnt""",
        shortuuid.uuid(),
        cid,
        campcid,
        ts,
        sinkid,
        domain,
        ip,
        settingsid,
        campid,
        complaint,
        unsub,
        open,
        click,
        send,
        soft,
        hard,
        err,
        defercnt,
    )


def txnstats_insert(
    db: DB,
    cid: str,
    ts: datetime,
    tag: str,
    domain: str,
    complaint: int,
    unsub: int,
    open: int,
    click: int,
    open_all: int = 0,
    click_all: int = 0,
    send: int = 0,
    soft: int = 0,
    hard: int = 0,
) -> None:
    db.execute(
        """insert into txnstats (id, cid, ts, tag, domain,
                  complaint, unsub, open, click, send, soft, hard, open_all, click_all)
                  values (%s, %s, date_trunc('hour', %s), %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s, %s)
                  on conflict (ts, cid, tag, domain) do update set
                  complaint = txnstats.complaint + excluded.complaint,
                  unsub =     txnstats.unsub     + excluded.unsub,
                  open =      txnstats.open      + excluded.open,
                  click =     txnstats.click     + excluded.click,
                  send =      txnstats.send      + excluded.send,
                  soft =      txnstats.soft      + excluded.soft,
                  hard =      txnstats.hard      + excluded.hard,
                  open_all =  txnstats.open_all  + excluded.open_all,
                  click_all = txnstats.click_all + excluded.click_all
                  """,
        shortuuid.uuid(),
        cid,
        ts,
        tag,
        domain,
        complaint,
        unsub,
        open,
        click,
        send,
        soft,
        hard,
        open_all,
        click_all,
    )


def statmsgs_insert(
    db: DB,
    cid: str,
    ts: datetime,
    sinkid: str,
    domain: str,
    ip: str,
    settingsid: str,
    campid: str,
    msg: str,
    msgtype: str,
    cnt: int = 1,
) -> None:
    db.execute(
        """insert into statmsgs (id, cid, ts, sinkid, domaingroupid, ip, settingsid, campid, message, msgtype, count)
                  values (%s, %s, date_trunc('hour', %s), %s, %s, %s, %s, %s, %s, %s, %s)
                  on conflict on constraint statmsgs_uniq do update
                  set count = statmsgs.count + %s""",
        shortuuid.uuid(),
        cid,
        ts,
        sinkid,
        domain,
        ip,
        settingsid,
        campid,
        msg,
        msgtype,
        cnt,
        cnt,
    )


def txnmsgs_insert(
    db: DB,
    cid: str,
    ts: datetime,
    tag: str,
    domain: str,
    msg: str,
    msgtype: str,
    cnt: int = 1,
) -> None:
    db.execute(
        """insert into txnstatmsgs (id, cid, ts, tag, domain, message, msgtype, count)
                  values (%s, %s, date_trunc('hour', %s), %s, %s, %s, %s, %s)
                  on conflict (ts, cid, tag, domain, message, msgtype) do update
                  set count = txnstatmsgs.count + %s""",
        shortuuid.uuid(),
        cid,
        ts,
        tag,
        domain,
        msg,
        msgtype,
        cnt,
        cnt,
    )


def get_geoloc(
    db: DB, ct: str, email: str, clientip: str, useragent: str
) -> Tuple[
    int | None, int | None, int | None, str | None, str | None, str | None, str | None
]:
    os: int | None = None
    browser: int | None = None
    device: int | None = None
    country: str | None = None
    countrycode: str | None = None
    region: str | None = None
    zp: str | None = None
    if ct in ("open", "unsub", "click"):
        agentl = useragent.lower()

        if "yahoomailproxy" not in agentl:
            ipnum = 0
            try:
                ipnum = int(IPAddress(clientip).ipv4())
            except Exception as e:
                if clientip:
                    log.info(
                        "can't parse client IP: %s %s error %s", email, clientip, e
                    )
            if ipnum != 0:
                row = db.row(
                    "select country_code, country, region, zip from iplocations where iprange @> (%s)::bigint limit 1",
                    ipnum,
                )
                if row is None:
                    log.info("can't find IP: %s %s", email, clientip)
                else:
                    countrycode, country, region, zp = row
            os = get_os(agentl)
            browser = get_browser(agentl)
            device = get_device(agentl)

    return os, browser, device, country, countrycode, region, zp


def write_txn(
    db: DB,
    email: str,
    t: str,
    c: str,
    tag: str,
    msgid: str | None,
    settingsid: str,
    ip: str,
    domain: str,
    cid: str,
    sinkid: str,
    ts: datetime | int | None,
    msg: str,
    linkindex: int,
    linktrack: bool,
    clientip: str,
    useragent: str,
) -> None:
    campcid = c[3:]

    code: str | None = msg
    if not code:
        code = None
    ct = t
    if ct == "hard":
        ct = "bounce"

    if not ts:
        insertts = datetime.utcnow()
    elif not isinstance(ts, datetime):
        insertts = mailtimeepoch + timedelta(hours=ts)
    else:
        insertts = ts

    if t in ("click", "unsub"):
        if not linktrack:
            return

    if (
        db.single(
            """insert into txnlogs (tag, msgid, email, cmd, ts, code) values (%s, %s, %s, %s, %s, %s)
                    on conflict (tag, msgid, email, cmd) do nothing returning ts""",
            tag,
            msgid,
            email,
            ct,
            datetime.utcnow(),
            code,
        )
        is not None
    ):

        if ct in ("bounce", "complaint", "unsub"):
            db.execute(
                """insert into unsublogs (cid, email, rawhash, unsubscribed, complained, bounced) values (%s, %s, %s, %s, %s, %s)
                          on conflict (cid, email) do update set
                          unsubscribed = (unsublogs.unsubscribed or excluded.unsubscribed),
                          complained = (unsublogs.complained or excluded.complained),
                          bounced = (unsublogs.bounced or excluded.bounced)""",
                campcid,
                email,
                get_contact_id(db, campcid, email),
                ct == "unsub",
                ct == "complaint",
                ct == "bounce",
            )

        if ct in ("open", "complaint", "unsub", "click"):
            db.execute(
                """update txnsends set data = data || jsonb_build_object(%s, true) where msgid = %s""",
                ct,
                msgid,
            )

            opens, clicks, complaints, unsubs = 0, 0, 0, 0
            if ct == "open":
                opens += 1
            elif ct == "click":
                clicks += 1
            elif ct == "unsub":
                unsubs += 1
            else:
                complaints += 1

            if settingsid and ip:
                hourstats_insert(
                    db,
                    cid,
                    campcid,
                    insertts,
                    sinkid,
                    domain,
                    ip,
                    settingsid,
                    c,
                    complaints,
                    unsubs,
                    opens,
                    clicks,
                )

            txnstats_insert(
                db,
                campcid,
                insertts,
                tag,
                domain,
                complaints,
                unsubs,
                opens,
                clicks,
                opens,
                clicks,
            )

        webhookev: JsonObj = {
            "type": ct,
            "source": {"tag": tag},
            "email": email,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        if ct in ("open", "click"):
            os, browser, device, country, countrycode, region, zp = get_geoloc(
                db, ct, email, clientip, useragent
            )
            webhookev["agent"] = useragent
            webhookev["ip"] = clientip
            webhookev["device"] = "" if device is None else device_names.get(device, "")
            webhookev["os"] = "" if os is None else os_names.get(os, "")
            webhookev["browser"] = (
                "" if browser is None else browser_names.get(browser, "")
            )
            webhookev["country"] = country
            webhookev["country_code"] = countrycode
            webhookev["region"] = region
            webhookev["zip"] = zp
            if ct == "click":
                webhookev["linkindex"] = linkindex
        elif ct == "bounce":
            webhookev["code"] = code
            webhookev["bouncetype"] = "hard"
        send_webhooks(db, campcid, [webhookev])

    elif ct in ("open", "click"):
        opens, clicks = 0, 0
        if ct == "open":
            opens += 1
        elif ct == "click":
            clicks += 1
        txnstats_insert(
            db, campcid, insertts, tag, domain, 0, 0, 0, 0, opens, clicks
        )  # _all only


def write_list(
    db: DB,
    email: str,
    t: str,
    camp: JsonObj,
    is_camp: bool,
    settingsid: str,
    ip: str,
    domain: str,
    cid: str,
    sinkid: str,
    ts: datetime | int | None,
    msg: str,
    linkindex: int,
    linktrack: bool,
    clientip: str,
    useragent: str,
) -> None:

    campcid = camp["cid"]

    c = camp["id"]

    code: str | None = msg
    if not code:
        code = None
    ct = t
    if ct == "hard":
        ct = "bounce"

    if not ts:
        insertts = datetime.utcnow()
    elif not isinstance(ts, datetime):
        insertts = mailtimeepoch + timedelta(hours=ts)
    else:
        insertts = ts

    updatedts = None
    if is_camp:
        if "updated_at" in camp:
            updatedts = dateutil.parser.parse(camp["updated_at"], ignoretz=True)
    else:
        if "modified" in camp:
            updatedts = dateutil.parser.parse(camp["modified"], ignoretz=True)

    os, browser, device, country, countrycode, region, zp = get_geoloc(
        db, ct, email, clientip, useragent
    )
    if ct in ("open", "unsub", "click") and device is not None:
        if is_camp:
            db.execute(
                """insert into campaign_devices (campaign_id, device, count) values (%s, %s, 1)
                          on conflict (campaign_id, device) do update set
                          count = campaign_devices.count + 1""",
                c,
                device,
            )
            db.execute(
                """insert into campaign_browsers (campaign_id, os, browser, count) values (%s, %s, %s, 1)
                          on conflict (campaign_id, os, browser) do update set
                          count = campaign_browsers.count + 1""",
                c,
                os,
                browser,
            )
            if country:
                db.execute(
                    """insert into campaign_locations (campaign_id, country_code, country, region, count) values (%s, %s, %s, %s, 1)
                              on conflict (campaign_id, country_code, region) do update set
                              count = campaign_locations.count + 1""",
                    c,
                    countrycode,
                    country,
                    region,
                )
        else:
            db.execute(
                """insert into message_devices (message_id, device, count) values (%s, %s, 1)
                          on conflict (message_id, device) do update set
                          count = message_devices.count + 1""",
                c,
                device,
            )
            db.execute(
                """insert into message_browsers (message_id, os, browser, count) values (%s, %s, %s, 1)
                          on conflict (message_id, os, browser) do update set
                          count = message_browsers.count + 1""",
                c,
                os,
                browser,
            )
            if country:
                db.execute(
                    """insert into message_locations (message_id, country_code, country, region, count) values (%s, %s, %s, %s, 1)
                              on conflict (message_id, country_code, region) do update set
                              count = message_locations.count + 1""",
                    c,
                    countrycode,
                    country,
                    region,
                )

    if t in ("click", "unsub"):
        if linkindex >= 0 and (updatedts is None or updatedts < insertts):
            if is_camp:
                db.execute(
                    """update campaigns set data = jsonb_set(data, %s, ((data->'linkclicks'->>%s)::integer + 1)::text::jsonb)
                              where id = %s and jsonb_array_length(data->'linkclicks') > %s""",
                    ["linkclicks", str(linkindex)],
                    linkindex,
                    c,
                    linkindex,
                )
            else:
                db.execute(
                    """update messages set data = jsonb_set(data, %s, ((data->'linkclicks'->>%s)::integer + 1)::text::jsonb)
                              where id = %s and jsonb_array_length(data->'linkclicks') > %s""",
                    ["linkclicks", str(linkindex)],
                    linkindex,
                    c,
                    linkindex,
                )

        if not linktrack:
            return

    if ct in ("click", "open"):
        prop = "%s_all" % campprops[ct]
        if is_camp:
            db.execute(
                "update campaigns set data = data || jsonb_build_object(%s, coalesce((data->>%s)::int, 0) + 1) where id = %s",
                prop,
                prop,
                c,
            )
        else:
            db.execute(
                "update messages set data = data || jsonb_build_object(%s, coalesce((data->>%s)::int, 0) + 1) where id = %s",
                prop,
                prop,
                c,
            )

    unique = False
    if (
        db.single(
            """insert into camplogs (campid, email, cmd, ts, code) values (%s, %s, %s, %s, %s)
                    on conflict (campid, email, cmd) do nothing returning ts""",
            c,
            email,
            ct,
            datetime.utcnow(),
            code,
        )
        is not None
    ):

        unique = True

    upd = {
        "email": email,
        "cmd": ct,
        "campid": c,
    }
    if ct == "click" and linkindex >= 0:
        if updatedts is None:
            upd["updatedts"] = None
        else:
            upd["updatedts"] = unix_time_secs(updatedts)
        upd["linkindex"] = linkindex
    if os is not None:
        upd["os"] = os
    if browser is not None:
        upd["browser"] = browser
    if device is not None:
        upd["device"] = device
    if country is not None:
        upd["country"] = country
    if region is not None:
        upd["region"] = region
    if zp is not None:
        upd["zip"] = zp

    contacts.update(db, campcid, upd)

    if unique:
        webhook_msgs: List[JsonObj] = []

        if ct in ("bounce", "complaint", "unsub"):
            db.execute(
                """insert into unsublogs (cid, email, rawhash, unsubscribed, complained, bounced) values (%s, %s, %s, %s, %s, %s)
                            on conflict (cid, email) do update set
                            unsubscribed = (unsublogs.unsubscribed or excluded.unsubscribed),
                            complained = (unsublogs.complained or excluded.complained),
                            bounced = (unsublogs.bounced or excluded.bounced)""",
                campcid,
                email,
                get_contact_id(db, campcid, email),
                ct == "unsub",
                ct == "complaint",
                ct == "bounce",
            )

        if ct in ("open", "click"):
            addtags = camp.get("%saddtags" % ct, ())
            remtags = camp.get("%sremtags" % ct, ())

            taglist = list(set([fix_tag(tag) for tag in addtags if fix_tag(tag)]))
            taglist.extend(set(["-" + fix_tag(tag) for tag in remtags if fix_tag(tag)]))

            if len(taglist):
                contacts.update_tags(db, campcid, [email], taglist, webhook_msgs)

        prop = campprops[ct]
        if is_camp:
            db.execute(
                "update campaigns set data = data || jsonb_build_object(%s, coalesce((data->>%s)::int, 0) + 1) where id = %s",
                prop,
                prop,
                c,
            )
        else:
            db.execute(
                "update messages set data = data || jsonb_build_object(%s, coalesce((data->>%s)::int, 0) + 1) where id = %s",
                prop,
                prop,
                c,
            )

        if ct in ("open", "complaint", "unsub", "click") and settingsid and ip:
            opens, clicks, complaints, unsubs = 0, 0, 0, 0
            if ct == "open":
                opens += 1
            elif ct == "click":
                clicks += 1
            elif ct == "unsub":
                unsubs += 1
            else:
                complaints += 1

            hourstats_insert(
                db,
                cid,
                camp["cid"],
                insertts,
                sinkid,
                domain,
                ip,
                settingsid,
                c,
                complaints,
                unsubs,
                opens,
                clicks,
            )

        webhooksrc = {}
        if is_camp:
            webhooksrc["broadcast"] = c
        else:
            webhooksrc["funnelmsg"] = c
        webhookev: JsonObj = {
            "type": ct,
            "source": webhooksrc,
            "email": email,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        if ct in ("open", "click"):
            webhookev["agent"] = useragent
            webhookev["ip"] = clientip
            webhookev["device"] = "" if device is None else device_names.get(device, "")
            webhookev["os"] = "" if os is None else os_names.get(os, "")
            webhookev["browser"] = (
                "" if browser is None else browser_names.get(browser, "")
            )
            webhookev["country"] = country
            webhookev["country_code"] = countrycode
            webhookev["region"] = region
            webhookev["zip"] = zp
            if ct == "click":
                webhookev["linkindex"] = linkindex
        elif ct == "bounce":
            webhookev["code"] = code
            webhookev["bouncetype"] = "hard"

        webhook_msgs.append(webhookev)
        send_webhooks(db, camp["cid"], webhook_msgs)


def write_automation_engagement_event(
    db: DB,
    email: str,
    t: str,
    campid: str,
    sinkid: str,
    settingsid: str,
    ip: str,
    ts: datetime | int | None,
    linkindex: int,
    linktrack: bool,
    clientip: str,
    useragent: str,
    link_id: str | None = None,
    link_url: str | None = None,
    tracking_id: str | None = None,
) -> bool:
    if t not in ("open", "click"):
        return False

    step_run = db.row(
        """
        select id, cid, automation_id, enrolment_id, contact_id, node_id, data
        from automation_step_runs
        where id = %s and node_type = 'send_email'
        """,
        campid,
    )
    if step_run is None:
        return False

    (
        send_step_run_id,
        cid,
        automation_id,
        enrolment_id,
        contact_id,
        send_node_id,
        step_data,
    ) = step_run

    if t == "click" and not linktrack:
        return True

    contact_row = db.row(
        f"""
        select contact_id, email
        from contacts."contacts_{cid}"
        where lower(email) = lower(%s)
        """,
        email,
    )
    if contact_row is None:
        log.info("automation engagement ignored: %s (contact not found)", email)
        return True

    event_contact_id, contact_email = contact_row
    if event_contact_id != contact_id:
        log.info(
            "automation engagement ignored: step run %s belongs to contact %s, got %s",
            send_step_run_id,
            contact_id,
            event_contact_id,
        )
        return True

    automation_email_id = step_data.get("automation_email_id")
    if not automation_email_id:
        log.info(
            "automation engagement ignored: step run %s has no automation email id",
            send_step_run_id,
        )
        return True

    if not ts:
        event_ts = datetime.utcnow()
    elif not isinstance(ts, datetime):
        event_ts = mailtimeepoch + timedelta(hours=ts)
    else:
        event_ts = ts

    data: JsonObj = {
        "provider": sinkid,
        "settings_id": settingsid,
        "tracking_id": tracking_id,
        "ip": clientip or ip,
        "user_agent": useragent,
        "created": datetime.utcnow().isoformat() + "Z",
    }
    if t == "click":
        data.update(
            {
                "link_id": link_id or "",
                "link_index": linkindex,
                "link_url": link_url or "",
                "updated_ts": 0,
            }
        )

    db.execute(
        """
        insert into automation_email_events
            (
                id, cid, contact_id, contact_email, automation_id, automation_email_id,
                enrolment_id, send_node_id, send_step_run_id, event_type, ts, data
            )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict do nothing
        """,
        shortuuid.uuid(),
        cid,
        contact_id,
        contact_email,
        automation_id,
        automation_email_id,
        enrolment_id,
        send_node_id,
        send_step_run_id,
        t,
        event_ts,
        data,
    )
    if t == "click":
        inferred_open_data = {
            "provider": sinkid,
            "settings_id": settingsid,
            "tracking_id": tracking_id,
            "ip": clientip or ip,
            "user_agent": useragent,
            "created": datetime.utcnow().isoformat() + "Z",
            "inferred": True,
            "inferred_from_event_type": "click",
            "inferred_from_link_id": link_id or "",
            "inferred_from_link_index": linkindex,
        }
        db.execute(
            """
            insert into automation_email_events
                (
                    id, cid, contact_id, contact_email, automation_id, automation_email_id,
                    enrolment_id, send_node_id, send_step_run_id, event_type, ts, data
                )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'open', %s, %s)
            on conflict do nothing
            """,
            shortuuid.uuid(),
            cid,
            contact_id,
            contact_email,
            automation_id,
            automation_email_id,
            enrolment_id,
            send_node_id,
            send_step_run_id,
            event_ts,
            inferred_open_data,
        )
    return True


def write_txnsend(db: DB, campcid: str, msgid: str, t: str, msg: str) -> None:
    last = db.single(
        "select data from txnsends where msgid = %s order by ts desc limit 1", msgid
    )
    if last is None:
        return

    last.pop("error", None)
    if t == "send":
        last["event"] = "Delivery"
    elif t == "soft":
        last["event"] = "Soft Bounce"
    else:
        last["event"] = "Hard Bounce"
    last["status"] = msg

    db.execute(
        "insert into txnsends (id, cid, ts, msgid, data) values (%s, %s, %s, %s, %s)",
        shortuuid.uuid(),
        campcid,
        datetime.utcnow(),
        msgid,
        last,
    )


class Events(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, sinkid: str) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        with open_db() as db:
            sendingsink = db.sinks.get(sinkid)
            if sendingsink is None:
                raise falcon.HTTPForbidden()

            if sendingsink["accesskey"] != doc["accesskey"]:
                raise falcon.HTTPUnauthorized()

            groups = {}
            camps: Dict[str, Tuple[JsonObj | None, bool]] = {}
            links = {}

            for evlist in (doc["events"], doc["statevents"]):
                if evlist is None:
                    continue
                for ev in evlist:
                    t = ev.get("t", "")
                    c = ev.get("c", "")
                    u = ev.get("u", "")
                    linkid = ev.get("l", "")
                    email = ev.get("e", "")
                    s = ev.get("s", "")
                    ip = ev.get("i", "")
                    domain = ev.get("d", "")
                    msg = ev.get("m", "")
                    count = ev.get("n", "")
                    eventsinkid = ev.get("k", "")
                    ts = ev.get("ts", 0)
                    clientip = ev.get("p", "")
                    useragent = ev.get("a", "")

                    if not c:
                        log.info("event error: %s (no campaign id)", ev)
                        continue
                    txntag = None
                    txnmsgid = None
                    campcid = None
                    if len(c) > 30:
                        campcid, txntag, txnmsgid = get_txn(db, c)
                        if campcid is None:
                            log.info("event error: tag id %s not found", c)
                            continue
                        else:
                            c = "tx-%s" % campcid
                    if t not in (
                        "click",
                        "open",
                        "unsub",
                        "complaint",
                        "send",
                        "hard",
                        "soft",
                        "err",
                        "defer",
                    ):
                        log.info("event error: %s (invalid type)", ev)
                        continue
                    camp = None
                    is_camp = True
                    if c != "test" and not c.startswith("tx-"):
                        if c in camps:
                            camp, is_camp = camps[c]
                        else:
                            camp = json_obj(
                                db.row(
                                    "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
                                    c,
                                )
                            )
                            if camp is None:
                                camp = json_obj(
                                    db.row(
                                        "select id, cid, data - 'parts' - 'rawText' from messages where id = %s",
                                        c,
                                    )
                                )
                                if camp is None:
                                    log.info("event error: %s (no campaign)", ev)
                                else:
                                    is_camp = False
                            camps[c] = (camp, is_camp)
                        if camp is not None and camp.get("archived", False):
                            camp = None
                        if camp is not None:
                            campcid = camp["cid"]

                    if not eventsinkid:
                        eventsinkid = sendingsink["id"]

                    if (
                        t in ("click", "open")
                        or (
                            t in ("unsub", "complaint", "hard")
                            and (c.startswith("tx-") or camp is not None)
                        )
                    ):
                        if not u and not email:
                            log.info("event error: %s (no uid/email)", ev)
                            continue
                        if not email:
                            email = unencrypt(u)
                            if email is None:
                                log.info("event error: %s (invalid uid)", ev)
                                continue
                        if not domain:
                            if "@" not in email:
                                log.info("event error: %s (invalid email)", ev)
                                continue
                            domain = email.split("@")[1]
                        try:
                            index = -1
                            track = True
                            link_url = None
                            if t in ("click", "unsub") and linkid:
                                if linkid not in links:
                                    links[linkid] = db.row(
                                        "select url, index, track from links where id = %s",
                                        linkid,
                                    )
                                linkobj = links[linkid]
                                if linkobj is not None:
                                    link_url, index, track = linkobj
                            if write_automation_engagement_event(
                                db,
                                email,
                                t,
                                c,
                                sendingsink["id"],
                                s,
                                ip,
                                ts,
                                index,
                                track,
                                clientip,
                                useragent,
                                link_id=linkid or None,
                                link_url=link_url,
                            ):
                                continue
                            if camp is None and not c.startswith("tx-"):
                                continue
                            if c.startswith("tx-"):
                                if txntag is not None:
                                    write_txn(
                                        db,
                                        email,
                                        t,
                                        c,
                                        txntag,
                                        txnmsgid,
                                        s,
                                        ip,
                                        domain,
                                        sendingsink["cid"],
                                        eventsinkid,
                                        ts,
                                        msg,
                                        index,
                                        track,
                                        clientip,
                                        useragent,
                                    )
                            else:
                                assert camp is not None
                                write_list(
                                    db,
                                    email,
                                    t,
                                    camp,
                                    is_camp,
                                    s,
                                    ip,
                                    domain,
                                    sendingsink["cid"],
                                    eventsinkid,
                                    ts,
                                    msg,
                                    index,
                                    track,
                                    clientip,
                                    useragent,
                                )
                        except:
                            log.exception("%s", ev)
                    elif t == "soft":
                        if not u and not email:
                            log.info("event error: %s (no uid/email)", ev)
                            continue
                        if not email:
                            email = unencrypt(u)
                            if email is None:
                                log.info("event error: %s (invalid uid)", ev)
                                continue
                        if c.startswith("tx-") or camp is not None:
                            assert campcid is not None
                            handle_soft_event(db, email, c, campcid, is_camp, msg)

                    if t in ("send", "soft", "hard") and txnmsgid is not None:
                        assert campcid is not None
                        write_txnsend(db, campcid, txnmsgid, t, msg)

                    try:
                        if (
                            t in ("send", "soft", "hard", "err", "defer")
                            and s
                            and domain
                        ):
                            if eventsinkid not in groups:
                                kgroup: Dict[
                                    str, Dict[str, Dict[str, Dict[str, List[Any]]]]
                                ] = {}
                                groups[eventsinkid] = kgroup
                            else:
                                kgroup = groups[eventsinkid]
                            if domain not in kgroup:
                                dgroup: Dict[str, Dict[str, Dict[str, List[Any]]]] = {}
                                kgroup[domain] = dgroup
                            else:
                                dgroup = kgroup[domain]
                            if ip not in dgroup:
                                ipgroup: Dict[str, Dict[str, List[Any]]] = {}
                                dgroup[ip] = ipgroup
                            else:
                                ipgroup = dgroup[ip]
                            if s not in ipgroup:
                                sgroup: Dict[str, List[Any]] = {}
                                ipgroup[s] = sgroup
                            else:
                                sgroup = ipgroup[s]
                            if c not in sgroup:
                                cgroup: List[Any] = [0, 0, 0, 0, 0, {}, txntag, campcid]
                                sgroup[c] = cgroup
                            else:
                                cgroup = sgroup[c]

                            if t == "send":
                                cgroup[0] += count
                            elif t == "soft":
                                cgroup[1] += count
                            elif t == "hard":
                                cgroup[2] += count
                            elif t == "err":
                                cgroup[3] += count
                            else:
                                cgroup[4] += count
                            msg = msg.strip()
                            if msg:
                                tup = (msg, t)
                                msgdict: Dict[Tuple[str, str], int] = cgroup[5]
                                if tup in msgdict:
                                    msgdict[tup] = msgdict[tup] + count
                                else:
                                    msgdict[tup] = count
                    except Exception:
                        log.exception("%s", ev)

            for eventsinkid, kgroup in groups.items():
                for domain, dgroup in kgroup.items():
                    for ip, ipgroup in dgroup.items():
                        for settingsid, sgroup in ipgroup.items():
                            for campid, cgroup in sgroup.items():
                                (
                                    send,
                                    soft,
                                    hard,
                                    err,
                                    defercnt,
                                    msgs,
                                    txntag,
                                    campcid,
                                ) = cgroup

                                assert campcid is not None

                                hourstats_insert(
                                    db,
                                    sendingsink["cid"],
                                    campcid,
                                    datetime.utcnow(),
                                    eventsinkid,
                                    domain,
                                    ip,
                                    settingsid,
                                    campid,
                                    0,
                                    0,
                                    0,
                                    0,
                                    send,
                                    soft,
                                    hard,
                                    err,
                                    defercnt,
                                )

                                if campid.startswith("tx-"):
                                    assert txntag is not None

                                    txnstats_insert(
                                        db,
                                        campcid,
                                        datetime.utcnow(),
                                        txntag,
                                        domain,
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                        0,
                                        send,
                                        soft,
                                        hard,
                                    )

                                if (
                                    (send > 0 or soft > 0 or hard > 0)
                                    and campid != "transactional"
                                    and camps.get(campid, None) is not None
                                ):
                                    if camps[campid][1]:
                                        db.execute(
                                            """update campaigns set data = data || jsonb_build_object('delivered', (data->>'delivered')::int + %s,
                                                                                                            'send', (data->>'send')::int + %s,
                                                                                                            'hard', (data->>'hard')::int + %s,
                                                                                                            'soft', (data->>'soft')::int + %s) where id = %s""",
                                            send + soft + hard,
                                            send,
                                            hard,
                                            soft,
                                            campid,
                                        )
                                    else:
                                        db.execute(
                                            """update messages set data = data || jsonb_build_object('delivered', (data->>'delivered')::int + %s,
                                                                                                            'send', (data->>'send')::int + %s,
                                                                                                            'hard', (data->>'hard')::int + %s,
                                                                                                            'soft', (data->>'soft')::int + %s) where id = %s""",
                                            send + soft + hard,
                                            send,
                                            hard,
                                            soft,
                                            campid,
                                        )

                                for msgt, cnt in msgs.items():
                                    msg, msgtype = msgt

                                    statmsgs_insert(
                                        db,
                                        sendingsink["cid"],
                                        datetime.utcnow(),
                                        eventsinkid,
                                        domain,
                                        ip,
                                        settingsid,
                                        campid,
                                        msg,
                                        msgtype,
                                        cnt,
                                    )

                                    if campid.startswith("tx-"):
                                        assert txntag is not None
                                        txnmsgs_insert(
                                            db,
                                            campcid,
                                            datetime.utcnow(),
                                            txntag,
                                            domain,
                                            msg,
                                            msgtype,
                                            cnt,
                                        )


class Limits(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, sinkid: str) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        with open_db() as db:
            sink = db.sinks.get(sinkid)
            if sink is None:
                raise falcon.HTTPForbidden()

            if sink["accesskey"] != doc["accesskey"]:
                raise falcon.HTTPUnauthorized()

            db.execute("delete from iplimits where sinkid = %s", sinkid)

            limits = doc["limits"]
            if limits is not None:
                for i in range(0, len(limits), 200):
                    value_params: List[Any] = []
                    num_limits = 0
                    for limit in limits[i : i + 200]:
                        settingsid = limit["s"]
                        domain = limit["d"]
                        ip = limit["i"]
                        sendlimit = limit["l"]
                        warmup = limit.get("w", None)

                        value_params.extend(
                            (sinkid, settingsid, domain, warmup, ip, sendlimit)
                        )
                        num_limits += 1

                    if num_limits:
                        db.execute(
                            f"""insert into iplimits (sinkid, settingsid, domain, warmupid, ip, sendlimit)
                                       values {", ".join(["(%s, %s, %s, %s, %s, %s)"] * num_limits)}""",
                            *value_params,
                        )


class Queue(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, sinkid: str) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        with open_db() as db:
            sink = db.sinks.get(sinkid)
            if sink is None:
                raise falcon.HTTPForbidden()

            if sink["accesskey"] != doc["accesskey"]:
                raise falcon.HTTPUnauthorized()

            db.sinks.patch(sinkid, {"queue": doc["queue"]})
            db.execute("delete from sinkdomainqueues where sinkid = %s", sinkid)

            if doc.get("domainqueues", None) is not None:
                for domain, cnt in doc["domainqueues"].items():
                    db.execute(
                        "insert into sinkdomainqueues (sinkid, domain, queue) values (%s, %s, %s)",
                        sinkid,
                        domain,
                        cnt,
                    )

            if doc.get("completecampaigns", None) is None:
                return

            for campid in doc["completecampaigns"]:
                if len(campid) > 30:
                    continue

                if db.single(
                    "select count(sendid) from campqueue where campid = %s and data->>'sinkid' = %s",
                    campid,
                    sinkid,
                ):
                    continue

                db.execute(
                    "update campaigns set data = data || jsonb_build_object('sinkstatus', (data->>'sinkstatus')::jsonb || jsonb_build_object(%s, true)) where id = %s",
                    sinkid,
                    campid,
                )

                camp = json_obj(
                    db.row(
                        "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
                        campid,
                    )
                )

                if camp is not None and False not in list(camp["sinkstatus"].values()):
                    db.campaigns.patch(
                        campid, {"finished_at": datetime.utcnow().isoformat() + "Z"}
                    )


class Stats(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, sinkid: str) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        with open_db() as db:
            sink = db.sinks.get(sinkid)
            if sink is None:
                raise falcon.HTTPForbidden()

            if sink["accesskey"] != doc["accesskey"]:
                raise falcon.HTTPUnauthorized()

            db.set_cid(sink["cid"])

            now = datetime.utcnow()

            for ipstats in doc["ipstats"]:
                domaingroupid, ip = ipstats["key"].split(":")

                if ipstats["defermsg"]:
                    ipstats["send"] += ipstats["dsend"]
                    ipstats["soft"] += ipstats["dsoft"]
                    ipstats["hard"] += ipstats["dhard"]
                    ipstats["err"] += ipstats["derr"]
                elif (
                    ipstats["dsend"]
                    or ipstats["dsoft"]
                    or ipstats["dhard"]
                    or ipstats["derr"]
                ):
                    lastsend = statlogs_obj(
                        db.row(
                            """select * from statlogs2 where cid = %s and defermsg = '' and sinkid = %s and
                                                    domaingroupid = %s and ip = %s and settingsid = %s order by ts desc limit 1""",
                            db.get_cid(),
                            sinkid,
                            domaingroupid,
                            ip,
                            ipstats["settingsid"],
                        )
                    )
                    if lastsend is not None:
                        db.execute(
                            "update statlogs2 set send = %s, soft = %s, hard = %s, err = %s where id = %s",
                            lastsend["send"] + ipstats["dsend"],
                            lastsend["soft"] + ipstats["dsoft"],
                            lastsend["hard"] + ipstats["dhard"],
                            lastsend["err"] + ipstats["derr"],
                            lastsend["id"],
                        )

                stats = []
                if (
                    ipstats["send"]
                    or ipstats["soft"]
                    or ipstats["hard"]
                    or ipstats["err"]
                ):
                    stats.append(
                        {
                            "sinkid": sinkid,
                            "domaingroupid": domaingroupid,
                            "ip": ip,
                            "settingsid": ipstats["settingsid"],
                            "ts": now.isoformat() + "Z",
                            "send": ipstats["send"],
                            "soft": ipstats["soft"],
                            "hard": ipstats["hard"],
                            "err": ipstats["err"],
                            "defermsg": "",
                            "deferlen": 0,
                            "count": 1,
                        }
                    )
                if ipstats["defermsg"]:
                    stats.append(
                        {
                            "sinkid": sinkid,
                            "domaingroupid": domaingroupid,
                            "ip": ip,
                            "settingsid": ipstats["settingsid"],
                            "ts": (now + timedelta(seconds=1)).isoformat() + "Z",
                            "send": 0,
                            "soft": 0,
                            "hard": 0,
                            "err": 0,
                            "defermsg": ipstats["defermsg"],
                            "deferlen": ipstats["deferlen"],
                            "count": 1,
                        }
                    )

                laststat = statlogs_obj(
                    db.row(
                        """select * from statlogs2 where cid = %s and sinkid = %s and
                                                domaingroupid = %s and ip = %s and settingsid = %s order by ts desc limit 1""",
                        db.get_cid(),
                        sinkid,
                        domaingroupid,
                        ip,
                        ipstats["settingsid"],
                    )
                )

                def merge_stats(old: JsonObj | None, new: JsonObj) -> None:
                    updated = False
                    if (
                        old is not None
                        and old["defermsg"] == new["defermsg"]
                        and old["deferlen"] == new["deferlen"]
                    ):
                        oldts = dateutil.parser.parse(old["ts"], ignoretz=True)
                        newts: datetime | None = dateutil.parser.parse(
                            new["ts"], ignoretz=True
                        )

                        assert newts is not None

                        if new["defermsg"] or (newts - oldts < timedelta(minutes=5)):
                            new["send"] += old["send"]
                            new["soft"] += old["soft"]
                            new["hard"] += old["hard"]
                            new["err"] += old.get("err", 0)
                            new["count"] = old.get("count", 1) + 1
                            db.execute(
                                "update statlogs2 set send = %s, soft = %s, hard = %s, err = %s, count = %s, ts = %s where id = %s",
                                new["send"],
                                new["soft"],
                                new["hard"],
                                new["err"],
                                new["count"],
                                new["ts"],
                                old["id"],
                            )
                            new["id"] = old["id"]
                            new["lastts"] = old["lastts"]
                            updated = True
                    if not updated:
                        newts = None
                        if old is not None and old["defermsg"] != new["defermsg"]:
                            oldts = dateutil.parser.parse(
                                old["ts"], ignoretz=True
                            ) + timedelta(seconds=old["deferlen"])
                            newts = dateutil.parser.parse(new["ts"], ignoretz=True)
                            diff = newts - oldts
                            if diff >= timedelta(seconds=60):
                                new["lastts"] = oldts.isoformat() + "Z"
                        if "lastts" not in new:
                            if newts is None:
                                newts = dateutil.parser.parse(new["ts"], ignoretz=True)
                            new["lastts"] = (
                                newts - timedelta(minutes=1)
                            ).isoformat() + "Z"
                        db.execute(
                            """insert into statlogs2 (id, cid, ip, ts, err, hard, send, soft, count, lastts, sinkid, deferlen, defermsg, settingsid, domaingroupid)
                                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            shortuuid.uuid(),
                            db.get_cid(),
                            new.get("ip"),
                            new.get("ts"),
                            new.get("err"),
                            new.get("hard"),
                            new.get("send"),
                            new.get("soft"),
                            new.get("count"),
                            new.get("lastts"),
                            new.get("sinkid"),
                            new.get("deferlen"),
                            new.get("defermsg"),
                            new.get("settingsid"),
                            new.get("domaingroupid"),
                        )

                for s in stats:
                    merge_stats(laststat, s)
                    laststat = s


class Link(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        with open_db() as db:
            url = db.single("select url from links where id = %s", id)
            if url is None:
                raise falcon.HTTPForbidden()

            resp.content_type = "text/plain"
            resp.text = url


class TestLogsGet(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        db = req.context["db"]

        req.context["result"] = db.testlogs.get_all()


class TestLogs(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, sinkid: str) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        with open_db() as db:
            sink = db.sinks.get(sinkid)
            if sink is None:
                raise falcon.HTTPForbidden()

            if sink["accesskey"] != doc["accesskey"]:
                raise falcon.HTTPUnauthorized()

            db.set_cid(doc["cid"])
            db.testlogs.add(
                {
                    "to": doc["to"],
                    "ts": datetime.utcnow().isoformat() + "Z",
                    "msg": doc["msg"],
                }
            )

            db.execute(
                "delete from testlogs where cid = %s and id not in (select id from testlogs where cid = %s order by data->>'ts' desc limit 12)",
                doc["cid"],
                doc["cid"],
            )


class SendLogs(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, sinkid: str) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        with open_db() as db:
            sink = db.sinks.get(sinkid)
            if sink is None:
                raise falcon.HTTPForbidden()

            if sink["accesskey"] != doc["accesskey"]:
                raise falcon.HTTPUnauthorized()

            transferbucket = os.environ["s3_transferbucket"]
            data = s3_read(transferbucket, doc["key"])

            emails = [
                line.strip()
                for line in data.decode("utf-8").split("\n")
                if line.strip()
            ]
            if len(emails):
                contacts.add_send(db, doc["campid"], emails)

            s3_delete(transferbucket, doc["key"])


UNSUB = """<html><head><title>Unsubscribe Successful</title><link href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-BVYiiSIFeK1dGmJRAkycuHAHRg32OmUcww7on3RYdg4Va+PmSTsz/K68vbdEjh4u" crossorigin="anonymous"></head><body><div class="container"><div class="row" style="margin-top:25px"><div class="col-xs-4 col-xs-offset-4 text-center"><div class="panel panel-default"><div class="panel-body">You have been unsubscribed from this mailing list. Sorry to see you go!</div></div></div></div></div></body></html>"""


def process_track_event(
    db: DB,
    t: str,
    c: str,
    u: str,
    sinkid: str,
    settingsid: str,
    txntag: str | None,
    txnmsgid: str | None,
    ip: str,
    ts: datetime | None,
    index: int,
    track: bool,
    clientip: str,
    useragent: str,
    link_id: str | None = None,
    link_url: str | None = None,
    tracking_id: str | None = None,
) -> None:
    camp = None
    is_camp = True
    if c != "test" and not c.startswith("tx-"):
        camp = json_obj(
            db.row(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
                c,
            )
        )
        if camp is None:
            camp = json_obj(
                db.row(
                    "select id, cid, data - 'parts' - 'rawText' from messages where id = %s",
                    c,
                )
            )
            if camp is None:
                log.info("event error: %s (no campaign)", c)
            else:
                is_camp = False
        if camp is not None and camp.get("archived", False):
            camp = None

    if camp is not None or c.startswith("tx-") or t in ("open", "click"):
        email = unencrypt(u)
        if email is None or "@" not in email:
            log.info("event error: %s (invalid email)", u)
        else:
            domain = email.split("@")[1]
            if sinkid == "mailgun":
                cid = db.single("select cid from mailgun where id = %s", settingsid)
            elif sinkid == "ses":
                cid = db.single("select cid from ses where id = %s", settingsid)
            elif sinkid == "sparkpost":
                cid = db.single("select cid from sparkpost where id = %s", settingsid)
            elif sinkid == "easylink":
                cid = db.single("select cid from easylink where id = %s", settingsid)
            elif sinkid == "smtprelay":
                cid = db.single("select cid from smtprelays where id = %s", settingsid)
            if cid is None:
                log.info("event error: %s (api account not found)", settingsid)
            else:
                if write_automation_engagement_event(
                    db,
                    email,
                    t,
                    c,
                    sinkid,
                    settingsid,
                    ip,
                    ts,
                    index,
                    track,
                    clientip,
                    useragent,
                    link_id=link_id,
                    link_url=link_url,
                    tracking_id=tracking_id,
                ):
                    return
                if camp is None and not c.startswith("tx-"):
                    return
                if c.startswith("tx-"):
                    if txntag is not None:
                        write_txn(
                            db,
                            email,
                            t,
                            c,
                            txntag,
                            txnmsgid,
                            settingsid,
                            ip,
                            domain,
                            cid,
                            sinkid,
                            ts,
                            "",
                            index,
                            track,
                            clientip,
                            useragent,
                        )
                else:
                    assert camp is not None
                    write_list(
                        db,
                        email,
                        t,
                        camp,
                        is_camp,
                        settingsid,
                        ip,
                        domain,
                        cid,
                        sinkid,
                        ts,
                        "",
                        index,
                        track,
                        clientip,
                        useragent,
                    )


class Track(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        return self.on_get(req, resp)

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        sinkid = "mailgun"

        t = req.get_param("t")
        c = req.get_param("c")
        u = req.get_param("u")
        linkid = req.get_param("l")
        tr = req.get_param("r")
        p = req.get_param_as_list("p")
        useragent = req.user_agent or ""
        if len(req.access_route) > 0:
            clientip = req.access_route[0]
        else:
            clientip = ""

        if not t or not c or not u:
            raise falcon.HTTPBadRequest(title="Missing parameter")

        firstt = t[0]
        if firstt in clickletters:
            t = "click"
        elif firstt in openletters:
            t = "open"
        elif firstt in unsubletters:
            t = "unsub"
        else:
            raise falcon.HTTPBadRequest(title="Bad request type")

        url, index, track = None, -1, True

        with open_db() as db:
            if linkid:
                row = db.row(
                    "select url, index, track from links where id = %s", linkid
                )
                if row is None:
                    log.info("event error: %s (link not found)", linkid)
                else:
                    url, index, track = row

                    # replace any dynamic variables in the output
                    if p:
                        for val in p:
                            url = paramre.sub(val, url, count=1)

            txntag = None
            txnmsgid = None
            if len(c) > 30:
                campcid, txntag, txnmsgid = get_txn(db, c)
                if campcid is None:
                    log.info("event error: tag id %s not found", c)
                else:
                    c = "tx-%s" % campcid

            settingsid, ip, ts = None, None, None
            if c != "test":
                if not tr:
                    log.info("event error: no tracking id")
                else:
                    row = db.row(
                        "select settingsid, ip, ts from mgtracking where id = %s", tr
                    )
                    if row is None:
                        row = db.row(
                            "select settingsid, ts from sesmessages where trackingid = %s",
                            tr,
                        )
                        if row is None:
                            row = db.row(
                                "select settingsid, ip, ts from sptracking where id = %s",
                                tr,
                            )
                            if row is None:
                                row = db.row(
                                    "select settingsid, ts from eltracking where id = %s",
                                    tr,
                                )
                                if row is None:
                                    row = db.row(
                                        "select settingsid, ts from smtptracking where id = %s",
                                        tr,
                                    )
                                    if row is None:
                                        log.info(
                                            "event pending: %s (no values for tracking id, saving to redis)",
                                            tr,
                                        )
                                        trackingkey = "tracking-%s" % (tr,)
                                        rdb = redis_connect()
                                        rdb.pipeline().lpush(
                                            trackingkey,
                                            json.dumps(
                                                {
                                                    "t": t,
                                                    "c": c,
                                                    "u": u,
                                                    "index": index,
                                                    "track": track,
                                                    "txntag": txntag,
                                                    "txnmsgid": txnmsgid,
                                                    "useragent": useragent,
                                                    "clientip": clientip,
                                                    "link_id": linkid,
                                                    "link_url": url,
                                                    "tracking_id": tr,
                                                    "added": datetime.utcnow().isoformat()
                                                    + "Z",
                                                }
                                            ),
                                        ).expire(trackingkey, 60 * 60 * 72).execute()
                                    else:
                                        settingsid, ts = row
                                        ip = "pool"
                                        sinkid = "smtprelay"
                                else:
                                    settingsid, ts = row
                                    ip = "pool"
                                    sinkid = "easylink"
                            else:
                                settingsid, ip, ts = row
                                sinkid = "sparkpost"
                        else:
                            settingsid, ts = row
                            ip = "pool"
                            sinkid = "ses"
                    else:
                        settingsid, ip, ts = row

            if settingsid is not None:
                assert ip is not None
                process_track_event(
                    db,
                    t,
                    c,
                    u,
                    sinkid,
                    settingsid,
                    txntag,
                    txnmsgid,
                    ip,
                    ts,
                    index,
                    track,
                    clientip,
                    useragent,
                    link_id=linkid,
                    link_url=url,
                    tracking_id=tr,
                )

            if t == "open":
                resp.content_type = falcon.MEDIA_GIF
                resp.data = GIF
            else:
                if url:
                    resp.status = falcon.HTTP_301
                    resp.location = url
                elif t == "unsub":
                    resp.content_type = falcon.MEDIA_HTML
                    resp.text = UNSUB
                else:
                    raise falcon.HTTPBadRequest(title="Invalid parameter")


class SESWebHook(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        body = req.bounded_stream.read()
        if not body:
            raise falcon.HTTPBadRequest(
                title="Empty request body",
                description="A valid JSON document is required.",
            )
        try:
            doc = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise falcon.HTTPError(
                status=falcon.HTTP_753,
                title="Malformed JSON",
                description="Could not decode the request body. The "
                "JSON was incorrect or not encoded as "
                "UTF-8.",
            )

        msgtype = req.get_header("x-amz-sns-message-type", required=True)

        log.debug("SNS: %s" % msgtype)
        log.debug("SNS: %s" % json.dumps(doc, indent=2))

        if msgtype == "SubscriptionConfirmation":
            requests.get(doc["SubscribeURL"]).raise_for_status()
            return
        if msgtype != "Notification":
            return

        if "Message" not in doc:
            event = doc
        else:
            event = json.loads(doc["Message"])

        if "notificationType" in event:
            eventtype = event["notificationType"]
        else:
            eventtype = event["eventType"]
        if eventtype not in ("Bounce", "Complaint", "Delivery"):
            return

        for email in event["mail"]["destination"]:
            emailmatch = emailre.search(email)
            if emailmatch:
                email = emailmatch.group(0)
            else:
                log.error("SES event: bad destination email address '%s'", email)
                continue

            domain = email.split("@")[1]
            sinkid = "ses"
            ip = "pool"
            ts = event["mail"]["timestamp"]
            hardbounce = False
            msg = ""
            if eventtype == "Delivery":
                msg = event["delivery"]["smtpResponse"]
            elif eventtype == "Bounce":
                hardbounce = event["bounce"]["bounceType"] == "Permanent"
                msg = "none found"
                for r in event["bounce"]["bouncedRecipients"]:
                    msg = r.get("diagnosticCode", "none provided")

            messageid = event["mail"]["messageId"]

            rdb = redis_connect()

            rdb.lpush(
                "webhooks-pending",
                json.dumps(
                    {
                        "type": "ses",
                        "eventtype": eventtype,
                        "email": email,
                        "domain": domain,
                        "sinkid": sinkid,
                        "ip": ip,
                        "ts": ts,
                        "hardbounce": hardbounce,
                        "msg": msg,
                        "messageid": messageid,
                    }
                ),
            )


def process_ses_webhook(db: DB, jsonobj: JsonObj) -> None:
    eventtype = jsonobj["eventtype"]
    email = jsonobj["email"]
    domain = jsonobj["domain"]
    sinkid = jsonobj["sinkid"]
    ip = jsonobj["ip"]
    ts = jsonobj["ts"]
    hardbounce = jsonobj["hardbounce"]
    msg = jsonobj["msg"]
    messageid = jsonobj["messageid"]

    ts = dateutil.parser.parse(ts).replace(tzinfo=None)

    row = db.row(
        "select settingsid, cid, campid, is_camp, trackingid, ts from sesmessages where id = %s",
        messageid,
    )
    if row is None:
        return

    settingsid, usercid, campid, is_camp, trackingid, msgts = row

    co = db.companies.get(usercid)
    if co is None:
        log.error("Company %s not found", usercid)
        return
    cid = co["cid"]

    if campid == "test":
        db.set_cid(usercid)
        db.testlogs.add(
            {
                "to": email,
                "ts": ts.isoformat() + "Z",
                "msg": msg,
            }
        )
        db.execute(
            "delete from testlogs where cid = %s and id not in (select id from testlogs where cid = %s order by data->>'ts' desc limit 12)",
            usercid,
            usercid,
        )
        db.set_cid(None)
        return

    camp = None
    campcid = None
    txntag = None
    txnmsgid = None
    if len(campid) <= 30:
        if is_camp:
            camp = json_obj(
                db.row(
                    "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
                    campid,
                )
            )
        else:
            camp = json_obj(
                db.row(
                    "select id, cid, data - 'parts' - 'rawText' from messages where id = %s",
                    campid,
                )
            )
        if camp is None or camp.get("archived", False):
            return
        campcid = camp["cid"]
    else:
        campcid, txntag, txnmsgid = get_txn(db, campid)
        if campcid is None:
            return
        campid = "tx-%s" % campcid

    msgtype = None

    send, soft, hard, err, defercnt = 0, 0, 0, 0, 0
    if eventtype == "Complaint":
        msgtype = "complaint"
    elif eventtype == "Delivery":
        msgtype = "send"
        send += 1
    else:
        if hardbounce:
            hard += 1
            msgtype = "hard"
        else:
            soft += 1
            msgtype = "soft"

    if msgtype == "send":
        contacts.add_send(db, campid, [email], txntag=txntag)
    elif msgtype in ("hard", "complaint"):
        if campid.startswith("tx-"):
            assert txntag is not None
            write_txn(
                db,
                email,
                msgtype,
                campid,
                txntag,
                txnmsgid,
                settingsid,
                ip,
                domain,
                cid,
                sinkid,
                msgts,
                msg,
                -1,
                True,
                "",
                "",
            )
        else:
            assert camp is not None
            write_list(
                db,
                email,
                msgtype,
                camp,
                is_camp,
                settingsid,
                ip,
                domain,
                cid,
                sinkid,
                msgts,
                msg,
                -1,
                True,
                "",
                "",
            )
    elif msgtype == "soft":
        if campid.startswith("tx-") or camp is not None:
            handle_soft_event(db, email, campid, campcid, is_camp, msg)

    if msgtype in ("send", "soft", "hard") and txnmsgid is not None:
        write_txnsend(db, campcid, txnmsgid, msgtype, msg)

    if msgtype != "complaint":
        hourstats_insert(
            db,
            cid,
            campcid,
            ts,
            sinkid,
            domain,
            ip,
            settingsid,
            campid,
            0,
            0,
            0,
            0,
            send,
            soft,
            hard,
            err,
            defercnt,
        )
        if campid.startswith("tx-"):
            assert txntag is not None
            txnstats_insert(
                db, campcid, ts, txntag, domain, 0, 0, 0, 0, 0, 0, send, soft, hard
            )

        if (send > 0 or soft > 0 or hard > 0) and not campid.startswith("tx-"):
            if is_camp:
                db.execute(
                    """update campaigns set data = data || jsonb_build_object('delivered', (data->>'delivered')::int + %s,
                                                                                     'send', (data->>'send')::int + %s,
                                                                                     'hard', (data->>'hard')::int + %s,
                                                                                     'soft', (data->>'soft')::int + %s) where id = %s""",
                    send + soft + hard,
                    send,
                    hard,
                    soft,
                    campid,
                )
            else:
                db.execute(
                    """update messages set data = data || jsonb_build_object('delivered', (data->>'delivered')::int + %s,
                                                                                    'send', (data->>'send')::int + %s,
                                                                                    'hard', (data->>'hard')::int + %s,
                                                                                    'soft', (data->>'soft')::int + %s) where id = %s""",
                    send + soft + hard,
                    send,
                    hard,
                    soft,
                    campid,
                )

        if msgtype != "send" and msg:
            statmsgs_insert(
                db, cid, ts, sinkid, domain, ip, settingsid, campid, msg, msgtype
            )
            if campid.startswith("tx-"):
                assert txntag is not None
                txnmsgs_insert(db, campcid, ts, txntag, domain, msg, msgtype)


def process_sp_webhook(db: DB, rdb: redis.StrictRedis, jsonobj: JsonObj) -> None:  # type: ignore
    event_id = jsonobj.get("event_id")
    eventtype = jsonobj["eventtype"]
    bounceclass = jsonobj["bounceclass"]
    ip = jsonobj["ip"]
    msg = jsonobj["msg"]
    email = jsonobj["email"]
    domain = jsonobj["domain"]
    sinkid = jsonobj["sinkid"]
    ts = jsonobj["ts"]
    settingsid = jsonobj["settingsid"]
    usercid = jsonobj["usercid"]
    campid = jsonobj["campid"]
    is_camp = jsonobj["is_camp"]
    trackingid = jsonobj["trackingid"]

    is_new = db.single(
        "insert into sparkpost_events (id) values (%s) on conflict (id) do nothing returning id",
        event_id,
    )
    if not is_new:
        log.info("Duplicate Sparkpost event ID %s, ignoring", event_id)
        return

    ts = datetime.utcfromtimestamp(int(ts))

    co = db.companies.get(usercid)
    if co is None:
        log.error("Company %s not found", usercid)
        return
    cid = co["cid"]
    if cid is None:
        log.error("Company %s has no parent", usercid)
        return

    if campid == "test":
        db.set_cid(usercid)
        db.testlogs.add(
            {
                "to": email,
                "ts": ts.isoformat() + "Z",
                "msg": msg,
            }
        )
        db.execute(
            "delete from testlogs where cid = %s and id not in (select id from testlogs where cid = %s order by data->>'ts' desc limit 12)",
            usercid,
            usercid,
        )
        db.set_cid(None)
        return

    camp = None
    txntag = None
    txnmsgid = None
    if len(campid) <= 30:
        if is_camp:
            camp = json_obj(
                db.row(
                    "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
                    campid,
                )
            )
        else:
            camp = json_obj(
                db.row(
                    "select id, cid, data - 'parts' - 'rawText' from messages where id = %s",
                    campid,
                )
            )
        if camp is None or camp.get("archived", False):
            return
        campcid = camp["cid"]
    else:
        campcid, txntag, txnmsgid = get_txn(db, campid)
        if campcid is None:
            return
        campid = "tx-%s" % campcid

    msgtype = None

    send, soft, hard, err, defercnt = 0, 0, 0, 0, 0
    if eventtype == "spam_complaint":
        msgtype = "complaint"
    elif eventtype == "delivery":
        send += 1
        msgtype = "send"
    elif eventtype == "delay":
        defercnt += 1
        msgtype = "defer"
    else:
        if bounceclass in ("10", "30", "90", "25", "26"):
            hard += 1
            msgtype = "hard"
        else:
            soft += 1
            msgtype = "soft"

    if msgtype == "send":
        db.execute(
            """insert into sptracking (id, ip, settingsid, ts) values (%s, %s, %s, %s)
                      on conflict (id) do update set ip = excluded.ip, settingsid = excluded.settingsid, ts = excluded.ts""",
            trackingid,
            ip,
            settingsid,
            ts,
        )
        contacts.add_send(db, campid, [email], txntag=txntag)

        trackingkey = "tracking-%s" % trackingid
        pendingevents = (
            rdb.pipeline().lrange(trackingkey, 0, -1).delete(trackingkey).execute()[0]
        )
        if pendingevents:
            for ev in pendingevents:
                log.info("Got pending event %s for tracking ID %s", ev, trackingid)
                evo = json.loads(ev)
                process_track_event(
                    db,
                    evo["t"],
                    evo["c"],
                    evo["u"],
                    sinkid,
                    settingsid,
                    evo["txntag"],
                    evo["txnmsgid"],
                    ip,
                    ts,
                    evo["index"],
                    evo["track"],
                    evo["clientip"],
                    evo["useragent"],
                    link_id=evo.get("link_id"),
                    link_url=evo.get("link_url"),
                    tracking_id=evo.get("tracking_id"),
                )
    elif msgtype in ("hard", "complaint"):
        trackrow = db.row("select ip, ts from sptracking where id = %s", trackingid)
        msgts = None
        if trackrow is not None:
            if not ip:
                ip = trackrow[0]
            msgts = trackrow[1]
        if not ip:
            ip = "pool"
        if campid.startswith("tx-"):
            assert txntag is not None
            write_txn(
                db,
                email,
                msgtype,
                campid,
                txntag,
                txnmsgid,
                settingsid,
                ip,
                domain,
                cid,
                sinkid,
                msgts,
                msg,
                -1,
                True,
                "",
                "",
            )
        else:
            assert camp is not None
            write_list(
                db,
                email,
                msgtype,
                camp,
                is_camp,
                settingsid,
                ip,
                domain,
                cid,
                sinkid,
                msgts,
                msg,
                -1,
                True,
                "",
                "",
            )
    elif msgtype == "soft":
        if campid.startswith("tx-") or camp is not None:
            handle_soft_event(db, email, campid, campcid, is_camp, msg)

    if msgtype in ("send", "soft", "hard") and txnmsgid is not None:
        write_txnsend(db, campcid, txnmsgid, msgtype, msg)

    if msgtype != "complaint":
        if not ip:
            ip = "pool"
        hourstats_insert(
            db,
            cid,
            campcid,
            ts,
            sinkid,
            domain,
            ip,
            settingsid,
            campid,
            0,
            0,
            0,
            0,
            send,
            soft,
            hard,
            err,
            defercnt,
        )
        if campid.startswith("tx-"):
            assert txntag is not None
            txnstats_insert(
                db, campcid, ts, txntag, domain, 0, 0, 0, 0, 0, 0, send, soft, hard
            )

        if (send > 0 or soft > 0 or hard > 0) and not campid.startswith("tx-"):
            if is_camp:
                db.execute(
                    """update campaigns set data = data || jsonb_build_object('delivered', (data->>'delivered')::int + %s,
                                                                                     'send', (data->>'send')::int + %s,
                                                                                     'hard', (data->>'hard')::int + %s,
                                                                                     'soft', (data->>'soft')::int + %s) where id = %s""",
                    send + soft + hard,
                    send,
                    hard,
                    soft,
                    campid,
                )
            else:
                db.execute(
                    """update messages set data = data || jsonb_build_object('delivered', (data->>'delivered')::int + %s,
                                                                                    'send', (data->>'send')::int + %s,
                                                                                    'hard', (data->>'hard')::int + %s,
                                                                                    'soft', (data->>'soft')::int + %s) where id = %s""",
                    send + soft + hard,
                    send,
                    hard,
                    soft,
                    campid,
                )

        if msgtype != "send":
            statmsgs_insert(
                db, cid, ts, sinkid, domain, ip, settingsid, campid, msg, msgtype
            )
            if campid.startswith("tx-"):
                assert txntag is not None
                txnmsgs_insert(db, campcid, ts, txntag, domain, msg, msgtype)


def process_mg_webhook(db: DB, rdb: redis.StrictRedis, jsonobj: JsonObj) -> None:  # type: ignore
    eventtype = jsonobj["eventtype"]
    severity = jsonobj["severity"]
    reason = jsonobj["reason"]
    ip = jsonobj["ip"]
    msg = jsonobj["msg"]
    email = jsonobj["email"]
    domain = jsonobj["domain"]
    sinkid = jsonobj["sinkid"]
    ts = jsonobj["ts"]
    settingsid = jsonobj["settingsid"]
    usercid = jsonobj["usercid"]
    campid = jsonobj["campid"]
    is_camp = jsonobj["is_camp"]
    trackingid = jsonobj["trackingid"]

    ts = datetime.utcfromtimestamp(ts)

    co = db.companies.get(usercid)
    if co is None:
        log.error("Company %s not found", usercid)
        return
    cid = co["cid"]
    if cid is None:
        log.error("Company %s has no parent", usercid)
        return

    if campid == "test":
        db.set_cid(usercid)
        db.testlogs.add(
            {
                "to": email,
                "ts": ts.isoformat() + "Z",
                "msg": msg,
            }
        )
        db.execute(
            "delete from testlogs where cid = %s and id not in (select id from testlogs where cid = %s order by data->>'ts' desc limit 12)",
            usercid,
            usercid,
        )
        db.set_cid(None)
        return

    camp = None
    txntag = None
    txnmsgid = None
    if len(campid) <= 30:
        if is_camp:
            camp = json_obj(
                db.row(
                    "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
                    campid,
                )
            )
        else:
            camp = json_obj(
                db.row(
                    "select id, cid, data - 'parts' - 'rawText' from messages where id = %s",
                    campid,
                )
            )
        if camp is None or camp.get("archived", False):
            return
        campcid = camp["cid"]
    else:
        campcid, txntag, txnmsgid = get_txn(db, campid)
        if campcid is None:
            return
        campid = "tx-%s" % campcid

    msgtype = None

    send, soft, hard, err, defercnt = 0, 0, 0, 0, 0
    if eventtype == "complained":
        msgtype = "complaint"
    elif eventtype == "delivered":
        send += 1
        msgtype = "send"
    else:
        if severity == "temporary":
            defercnt += 1
            msgtype = "defer"
        else:
            if reason == "bounce":
                hard += 1
                msgtype = "hard"
            else:
                soft += 1
                msgtype = "soft"

    if msgtype == "send":
        db.execute(
            """insert into mgtracking (id, ip, settingsid, ts) values (%s, %s, %s, %s)
                      on conflict (id) do update set ip = excluded.ip, settingsid = excluded.settingsid, ts = excluded.ts""",
            trackingid,
            ip,
            settingsid,
            ts,
        )
        contacts.add_send(db, campid, [email], txntag=txntag)

        trackingkey = "tracking-%s" % trackingid
        pendingevents = (
            rdb.pipeline().lrange(trackingkey, 0, -1).delete(trackingkey).execute()[0]
        )
        if pendingevents:
            for ev in pendingevents:
                log.info("Got pending event %s for tracking ID %s", ev, trackingid)
                evo = json.loads(ev)
                process_track_event(
                    db,
                    evo["t"],
                    evo["c"],
                    evo["u"],
                    sinkid,
                    settingsid,
                    evo["txntag"],
                    evo["txnmsgid"],
                    ip,
                    ts,
                    evo["index"],
                    evo["track"],
                    evo["clientip"],
                    evo["useragent"],
                    link_id=evo.get("link_id"),
                    link_url=evo.get("link_url"),
                    tracking_id=evo.get("tracking_id"),
                )
    elif msgtype in ("hard", "complaint"):
        trackrow = db.row("select ip, ts from mgtracking where id = %s", trackingid)
        msgts = None
        if trackrow is not None:
            if not ip:
                ip = trackrow[0]
            msgts = trackrow[1]
        if ip is None:
            ip = ""
        if ip:
            if campid.startswith("tx-"):
                assert txntag is not None
                write_txn(
                    db,
                    email,
                    msgtype,
                    campid,
                    txntag,
                    txnmsgid,
                    settingsid,
                    ip,
                    domain,
                    cid,
                    sinkid,
                    msgts,
                    msg,
                    -1,
                    True,
                    "",
                    "",
                )
            else:
                assert camp is not None
                write_list(
                    db,
                    email,
                    msgtype,
                    camp,
                    is_camp,
                    settingsid,
                    ip,
                    domain,
                    cid,
                    sinkid,
                    msgts,
                    msg,
                    -1,
                    True,
                    "",
                    "",
                )
    elif msgtype == "soft":
        if campid.startswith("tx-") or camp is not None:
            handle_soft_event(db, email, campid, campcid, is_camp, msg)

    if msgtype in ("send", "soft", "hard") and txnmsgid is not None:
        write_txnsend(db, campcid, txnmsgid, msgtype, msg)

    if msgtype != "complaint":
        hourstats_insert(
            db,
            cid,
            campcid,
            ts,
            sinkid,
            domain,
            ip,
            settingsid,
            campid,
            0,
            0,
            0,
            0,
            send,
            soft,
            hard,
            err,
            defercnt,
        )
        if campid.startswith("tx-"):
            assert txntag is not None
            txnstats_insert(
                db, campcid, ts, txntag, domain, 0, 0, 0, 0, 0, 0, send, soft, hard
            )

        if (send > 0 or soft > 0 or hard > 0) and not campid.startswith("tx-"):
            if is_camp:
                db.execute(
                    """update campaigns set data = data || jsonb_build_object('delivered', (data->>'delivered')::int + %s,
                                                                                     'send', (data->>'send')::int + %s,
                                                                                     'hard', (data->>'hard')::int + %s,
                                                                                     'soft', (data->>'soft')::int + %s) where id = %s""",
                    send + soft + hard,
                    send,
                    hard,
                    soft,
                    campid,
                )
            else:
                db.execute(
                    """update messages set data = data || jsonb_build_object('delivered', (data->>'delivered')::int + %s,
                                                                                    'send', (data->>'send')::int + %s,
                                                                                    'hard', (data->>'hard')::int + %s,
                                                                                    'soft', (data->>'soft')::int + %s) where id = %s""",
                    send + soft + hard,
                    send,
                    hard,
                    soft,
                    campid,
                )

        if msgtype != "send":
            statmsgs_insert(
                db, cid, ts, sinkid, domain, ip, settingsid, campid, msg, msgtype
            )
            if campid.startswith("tx-"):
                assert txntag is not None
                txnmsgs_insert(db, campcid, ts, txntag, domain, msg, msgtype)


def process_webhooks(checkcancel: Callable[[], bool]) -> None:
    try:
        with open_db() as db:
            rdb = redis_connect()

            lname = "webhooks-pending"

            cnt = 0

            while True:
                jsondata = rdb.rpop(lname)
                if jsondata is None:
                    break

                log.info("Got: %s", jsondata)
                obj = json.loads(jsondata)

                if obj["type"] == "mg":
                    process_mg_webhook(db, rdb, obj)
                elif obj["type"] == "sp":
                    process_sp_webhook(db, rdb, obj)
                else:
                    process_ses_webhook(db, obj)

                cnt += 1

                if checkcancel():
                    log.info("Process terminated")
                    return

            if cnt > 0:
                log.info("Processed %s webhooks", cnt)
    except:
        log.exception("error")


class SPWebHook(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPNotAcceptable(title="A valid JSON document is required.")

        for msys in doc:
            event = msys["msys"]["message_event"]
            event_id = event["event_id"]
            eventtype = event["type"]
            bounceclass = event.get("bounce_class", "")
            reason = event.get("reason", "")
            ip = event.get("ip_address", "")

            msg = "Delivered"
            if event.get("error_code", ""):
                msg = ("%s %s" % (event.get("error_code", ""), reason)).strip()
            email = event["rcpt_to"]
            domain = email.split("@")[1]
            sinkid = "sparkpost"
            ts = event["timestamp"]

            if "rcpt_meta" not in event or "settingsid" not in event["rcpt_meta"]:
                return  # probably for an internal transactional email

            emailmatch = emailre.search(email)
            if emailmatch:
                email = emailmatch.group(0)
            else:
                log.error(
                    "Sparkpost webhook error: bad destination email address '%s'", email
                )
                return

            uservars = event["rcpt_meta"]

            settingsid = uservars["settingsid"]
            usercid = uservars["cid"]
            campid = uservars["campid"]
            is_camp = uservars["is_camp"] == "True"
            trackingid = uservars["trackingid"]

            rdb = redis_connect()

            rdb.lpush(
                "webhooks-pending",
                json.dumps(
                    {
                        "type": "sp",
                        "event_id": event_id,
                        "eventtype": eventtype,
                        "bounceclass": bounceclass,
                        "reason": reason,
                        "ip": ip,
                        "msg": msg,
                        "email": email,
                        "domain": domain,
                        "sinkid": sinkid,
                        "ts": ts,
                        "settingsid": settingsid,
                        "usercid": usercid,
                        "campid": campid,
                        "is_camp": is_camp,
                        "trackingid": trackingid,
                    }
                ),
            )


class MGWebHook(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPNotAcceptable(title="A valid JSON document is required.")

        event = doc["event-data"]
        eventtype = event["event"]
        severity = event.get("severity", "")
        reason = event.get("reason", "")
        ip = event.get("envelope", {}).get("sending-ip", "")

        deliverystatus = event.get("delivery-status", {})
        desc = deliverystatus.get("message", "")
        if not desc:
            desc = deliverystatus.get("description", "")
        msg = ("%s %s" % (deliverystatus.get("code", ""), desc)).strip()
        email = event["recipient"]
        domain = email.split("@")[1]
        sinkid = "mailgun"
        ts = event["timestamp"]

        if "user-variables" not in event or "settingsid" not in event["user-variables"]:
            return  # probably for an internal transactional email

        emailmatch = emailre.search(email)
        if emailmatch:
            email = emailmatch.group(0)
        else:
            log.error(
                "Sparkpost webhook error: bad destination email address '%s'", email
            )
            return

        uservars = event["user-variables"]

        settingsid = uservars["settingsid"]
        usercid = uservars["cid"]
        campid = uservars["campid"]
        is_camp = uservars["is_camp"] == "True"
        trackingid = uservars["trackingid"]

        rdb = redis_connect()

        rdb.lpush(
            "webhooks-pending",
            json.dumps(
                {
                    "type": "mg",
                    "eventtype": eventtype,
                    "severity": severity,
                    "reason": reason,
                    "ip": ip,
                    "desc": desc,
                    "msg": msg,
                    "email": email,
                    "domain": domain,
                    "sinkid": sinkid,
                    "ts": ts,
                    "settingsid": settingsid,
                    "usercid": usercid,
                    "campid": campid,
                    "is_camp": is_camp,
                    "trackingid": trackingid,
                }
            ),
        )
