import falcon
import shortuuid
import csv
import re
import os
import json
import zipfile
import requests
from io import BytesIO, StringIO
from datetime import datetime
from jsonschema import validate
from typing import List, Set, Dict, Tuple
from .shared import config as config_module_side_effects  # noqa: F401
from .shared.db import open_db, json_iter, JsonObj, DB
from .shared.utils import (
    run_task,
    run_tasks,
    is_true,
    emailre,
    MPDictWriter,
    MPDictReader,
    unix_time_secs,
    gather_init,
    gather_complete,
    gather_check,
    fix_tag,
    get_contact_id,
    djb2,
    get_webroot,
    device_names,
    os_names,
    browser_names,
    set_onboarding,
    try_decode,
    SECS_IN_DAY,
)
from .shared.segments import (
    segment_lists,
    segment_get_params,
    get_segment_rows,
    segment_eval_parts,
    segment_get_segments,
    segment_get_campaignids,
    get_segment_sentrows,
    segment_get_segmentids,
    get_hashlimit,
    Cache,
)
from .shared.crud import (
    CRUDCollection,
    CRUDSingle,
    get_orig,
    check_noadmin,
    patch_schema,
)
from .shared.tasks import tasks, HIGH_PRIORITY, LOW_PRIORITY
from .shared.s3 import s3_write_stream, s3_list, s3_write, s3_read
from .shared import contacts
from .shared.log import get_logger
from .shared.webhooks import send_webhooks

log = get_logger()


@tasks.task(priority=LOW_PRIORITY)
def check_list_validation(listid: str) -> None:
    try:
        with open_db() as db:
            l = db.lists.get(listid)
            if (
                l is None
                or "validation" not in l
                or l["validation"]["status"] != "pending"
                or "uuid" not in l["validation"]
            ):
                return

            r = requests.get(
                "https://api.mailgun.net/v4/address/validate/bulk/%s-%s"
                % (listid, l["validation"]["uuid"]),
                auth=("api", os.environ["mg_validate_key"]),
            )
            r.raise_for_status()

            o = r.json()

            p = {
                "download_url": o.get("download_url", {}).get("csv", ""),
                "quantity": o["quantity"],
                "records_processed": o["records_processed"],
                "result": o.get("summary", {}).get("result"),
                "risk": o.get("summary", {}).get("risk"),
                "status": "pending",
                "uuid": l["validation"]["uuid"],
            }
            if o["quantity"] == o["records_processed"]:
                p["status"] = "complete"

                log.info(
                    '[NOTIFY] List validation complete:The list "%s" has been validated. To view the results, click here: %s/customers/list-approval?id=%s',
                    l["name"],
                    get_webroot(),
                    l["cid"],
                )

            db.lists.patch(listid, {"validation": p})
    except Exception as e:
        log.exception("error")
        db.lists.patch(listid, {"validation": {"status": "error", "message": str(e)}})


CHECK_LIST_VALIDATIONS_LOCK = 2477099


def check_list_validations() -> None:
    try:
        with open_db() as db:
            with db.transaction():
                if not db.single(
                    f"select pg_try_advisory_xact_lock({CHECK_LIST_VALIDATIONS_LOCK})"
                ):
                    return

                for l in json_iter(
                    db.execute(
                        "select id, cid, data from lists where data->'validation'->>'status' = 'pending' and data->'validation'->>'uuid' is not null"
                    )
                ):
                    run_task(check_list_validation, l["id"])
    except:
        log.exception("error")


@tasks.task(priority=LOW_PRIORITY)
def refresh_bucket_active(
    cid: str, hashval: int, hashlimit: int, gatherid: str, n: int
) -> None:
    with open_db() as db:
        try:
            counts = {}
            for (
                listid,
                active30,
                active60,
                active90,
                bounced,
                unsubscribed,
                complained,
                soft_bounced,
            ) in db.execute(
                f"""
                with stats as (
                    select contact_id, coalesce((nullif(props->'Bounced'->>0, ''))::bool, false) as bounced, coalesce((nullif(props->'Unsubscribed'->>0, ''))::bool, false) as unsubscribed, coalesce((nullif(props->'Complained'->>0, ''))::bool, false) as complained, coalesce((nullif(props->'Soft Bounced'->>0, ''))::bool, false) as soft_bounced
                    from contacts."contacts_{cid}"
                    where ({hashlimit} = 1 or mod(contact_id, {hashlimit}) = %s)
                ), max_open as (
                    select contact_id, max(ts) as ts
                    from contacts."contact_open_logs_{cid}"
                    where ({hashlimit} = 1 or mod(contact_id, {hashlimit}) = %s)
                    group by contact_id
                ), max_click as (
                    select contact_id, max(ts) as ts
                    from contacts."contact_click_logs_{cid}"
                    where ({hashlimit} = 1 or mod(contact_id, {hashlimit}) = %s)
                    group by contact_id
                ), by_list as (
                    select l.list_id, l.contact_id, greatest(op.ts, cl.ts) as ts, s.bounced, s.unsubscribed, s.complained, s.soft_bounced
                    from contacts."contact_lists_{cid}" l
                    join lists li on li.id = l.list_id
                    join stats s on s.contact_id = l.contact_id
                    left join max_open op on op.contact_id = l.contact_id
                    left join max_click cl on cl.contact_id = l.contact_id
                    where ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                    and not (coalesce(li.data->>'example', 'false'))::boolean
                )
                select list_id,
                    count(contact_id) filter (where (%s - ts)/%s < 31) as active30,
                    count(contact_id) filter (where (%s - ts)/%s < 61) as active60,
                    count(contact_id) filter (where (%s - ts)/%s < 91) as active90,
                    count(contact_id) filter (where bounced) as bounced,
                    count(contact_id) filter (where unsubscribed) as unsubscribed,
                    count(contact_id) filter (where complained) as complained,
                    count(contact_id) filter (where soft_bounced) as soft_bounced
                from by_list
                group by list_id
            """,
                hashval,
                hashval,
                hashval,
                hashval,
                n,
                SECS_IN_DAY,
                n,
                SECS_IN_DAY,
                n,
                SECS_IN_DAY,
            ):
                counts[listid] = {
                    "active30": active30,
                    "active60": active60,
                    "active90": active90,
                    "bounced": bounced,
                    "unsubscribed": unsubscribed,
                    "complained": complained,
                    "soft_bounced": soft_bounced,
                }

            info = gather_complete(db, gatherid, {"counts": counts})
            if info is not None:
                counts = {}
                for i in info:
                    for listid, active in i["counts"].items():
                        if listid not in counts:
                            counts[listid] = {}
                        for a, c in active.items():
                            counts[listid][a] = counts[listid].get(a, 0) + c

                for listid, patch in counts.items():
                    db.lists.patch(listid, patch)
        except:
            log.exception("error")


def get_contact_data(db: DB, cid: str, email: str) -> JsonObj:
    alldata = db.single(
        f"""
        with contact_id as (
            select contact_id
            from contacts."contacts_{cid}"
            where email = %s
        ), open_logs as (
            select c.contact_id, array_agg(jsonb_build_object('timestamp', op.ts, 'broadcast_id', op.campid) order by op.ts) filter (where op.campid is not null) as open_logs
            from contacts."contact_open_logs_{cid}" op
            join contact_id c on op.contact_id = c.contact_id
            group by c.contact_id
        ), click_logs as (
            select c.contact_id, array_agg(jsonb_build_object('timestamp', cl.ts, 'broadcast_id', cl.campid, 'link_index', cl.linkindex) order by cl.ts) filter (where cl.campid is not null) as click_logs
            from contacts."contact_click_logs_{cid}" cl
            join contact_id c on cl.contact_id = c.contact_id
            group by c.contact_id
        ), send_logs as (
            select c.contact_id, array_agg(jsonb_build_object('broadcast_id', s.campid)) filter (where s.campid is not null) as send_logs
            from contacts."contact_send_logs_{cid}" s
            join contact_id c on s.contact_id = c.contact_id
            group by c.contact_id
        ), values as (
            select
                c.contact_id,
                array_agg(distinct value) filter (where type = 'tag') as tags,
                array_agg(distinct value::int) filter (where type = 'device') as device,
                array_agg(distinct value::int) filter (where type = 'os') as os,
                array_agg(distinct value::int) filter (where type = 'browser') as browser,
                array_agg(distinct value) filter (where type = 'country') as country,
                array_agg(distinct value) filter (where type = 'region') as region,
                array_agg(distinct value) filter (where type = 'zip') as zip
            from contacts."contact_values_{cid}" v
            join contact_id c on v.contact_id = c.contact_id
            group by c.contact_id
        )
        select c.props ||
            jsonb_build_object(
                'Email', jsonb_build_array(c.email),
                '!!added_at', jsonb_build_array(c.added),
                '!!lists', array_agg(distinct l.list_id),
                '!!open_logs', coalesce(op.open_logs, '{{}}'),
                '!!click_logs', coalesce(cl.click_logs, '{{}}'),
                '!!send_logs', coalesce(s.send_logs, '{{}}'),
                '!!tags', coalesce(v.tags, '{{}}'),
                '!!devices', coalesce(v.device, '{{}}'),
                '!!operating_systems', coalesce(v.os, '{{}}'),
                '!!browsers', coalesce(v.browser, '{{}}'),
                '!!countries', coalesce(v.country, '{{}}'),
                '!!regions', coalesce(v.region, '{{}}'),
                '!!zipcodes', coalesce(v.zip, '{{}}')
            )
        from contacts."contacts_{cid}" c
        join contacts."contact_lists_{cid}" l on l.contact_id = c.contact_id
        join contact_id ci on ci.contact_id = c.contact_id
        left join open_logs op on op.contact_id = c.contact_id
        left join click_logs cl on cl.contact_id = c.contact_id
        left join send_logs s on s.contact_id = c.contact_id
        left join values v on v.contact_id = c.contact_id
        group by c.email, c.added, c.props, op.open_logs, cl.click_logs, s.send_logs, v.tags, v.device, v.os, v.browser, v.country, v.region, v.zip
        """,
        email,
    )

    if alldata is None:
        return {}

    ret = {}
    props: Dict[str, str] = {}

    ret["properties"] = props
    for k in alldata.keys():
        if k == "Email":
            ret["email"] = alldata[k][0]
        elif not k.startswith("!"):
            props[k] = alldata[k][0]
        else:
            val = alldata[k]

            if k == "!!added_at":
                val = datetime.utcfromtimestamp(val[0]).isoformat() + "Z"
            elif k == "!!open_logs" or k == "!!click_logs":
                for i in range(len(val)):
                    val[i]["timestamp"] = (
                        datetime.utcfromtimestamp(val[i]["timestamp"]).isoformat() + "Z"
                    )
            elif k == "!!devices":
                val = [device_names.get(d, "Unknown") for d in val]
            elif k == "!!browsers":
                val = [browser_names.get(d, "Unknown") for d in val]
            elif k == "!!operating_systems":
                val = [os_names.get(d, "Unknown") for d in val]

            ret[k[2:]] = val

    return ret


@tasks.task(priority=HIGH_PRIORITY)
def export_contact(cid: str, email: str, erase: bool, exportid: str, path: str) -> None:
    with open_db() as db:
        try:
            transferbucket = os.environ["s3_transferbucket"]

            alldata = get_contact_data(db, cid, email)

            zipname = "/tmp/%s.zip" % exportid
            outzip = zipfile.ZipFile(zipname, "w", zipfile.ZIP_DEFLATED)
            outzip.writestr(
                "data.json",
                json.dumps(
                    {
                        "data": alldata,
                    },
                    indent=2,
                ),
            )
            outzip.close()

            size = os.path.getsize(zipname)
            outfp = open(zipname, "rb")
            s3_write_stream(transferbucket, path, outfp)
            outfp.close()

            db.exports.patch(exportid, {"complete": True, "count": 1, "size": size})

            if erase:
                contacts.erase(db, cid, [email], unsublog=True)
        except Exception as e:
            log.exception("error")
            db.exports.patch(exportid, {"error": str(e)})


@tasks.task(priority=HIGH_PRIORITY)
def export_segment_final(
    blockpath: str, allprops: List[str], exportid: str, path: str
) -> None:
    with open_db() as db:
        try:
            transferbucket = os.environ["s3_transferbucket"]

            files = {
                "active": "/tmp/active-%s.csv" % exportid,
                "bounced": "/tmp/bounced-%s.csv" % exportid,
                "unsubscribed": "/tmp/unsubscribed-%s.csv" % exportid,
                "complained": "/tmp/complained-%s.csv" % exportid,
            }
            fps = {}
            writers = {}

            cnt = 0
            objlist = s3_list(transferbucket, "%s/" % blockpath)
            for obj in objlist:
                data = s3_read(transferbucket, obj.key)
                if data is not None:
                    for row in MPDictReader(BytesIO(data)):
                        key = "active"
                        if is_true(row.get("Bounced", "")):
                            key = "bounced"
                        elif is_true(row.get("Unsubscribed", "")):
                            key = "unsubscribed"
                        elif is_true(row.get("Complained", "")):
                            key = "complained"

                        if key not in fps:
                            fps[key] = open(files[key], "w", encoding="utf-8")
                            writers[key] = csv.DictWriter(
                                fps[key], allprops, extrasaction="ignore"
                            )
                            writers[key].writeheader()
                        writers[key].writerow(row)
                        cnt += 1

            zipname = "/tmp/%s.zip" % exportid
            outzip = zipfile.ZipFile(zipname, "w", zipfile.ZIP_DEFLATED)
            for key, fp in fps.items():
                fp.close()
                outzip.write(files[key], "%s.csv" % key)
            outzip.close()

            size = os.path.getsize(zipname)
            outfp = open(zipname, "rb")
            s3_write_stream(transferbucket, path, outfp)
            outfp.close()

            db.exports.patch(exportid, {"complete": True, "count": cnt, "size": size})
        except Exception as e:
            log.exception("error")
            db.exports.patch(exportid, {"error": str(e)})


@tasks.task(priority=HIGH_PRIORITY)
def export_list(
    cid: str, listid: str, allprops: List[str], exportid: str, path: str
) -> None:
    with open_db() as db:
        try:
            transferbucket = os.environ["s3_transferbucket"]

            files = {
                "active": "/tmp/active-%s.csv" % exportid,
                "bounced": "/tmp/bounced-%s.csv" % exportid,
                "unsubscribed": "/tmp/unsubscribed-%s.csv" % exportid,
                "complained": "/tmp/complained-%s.csv" % exportid,
            }
            fps = {}
            writers = {}
            cnt = 0

            for email, props in db.execute(
                f"""
                select c.email, c.props
                from contacts."contacts_{cid}" c
                join contacts."contact_lists_{cid}" l on l.contact_id = c.contact_id
                where l.list_id = %s
                                """,
                listid,
            ):

                row = {"Email": email}
                for k, v in props.items():
                    row[k] = v[0]

                key = "active"
                if is_true(row.get("Bounced", "")):
                    key = "bounced"
                elif is_true(row.get("Unsubscribed", "")):
                    key = "unsubscribed"
                elif is_true(row.get("Complained", "")):
                    key = "complained"

                if key not in fps:
                    fps[key] = open(files[key], "w", encoding="utf-8")
                    writers[key] = csv.DictWriter(
                        fps[key], allprops, extrasaction="ignore"
                    )
                    writers[key].writeheader()
                writers[key].writerow(row)
                cnt += 1

            zipname = "/tmp/%s.zip" % exportid
            outzip = zipfile.ZipFile(zipname, "w", zipfile.ZIP_DEFLATED)
            for key, fp in fps.items():
                fp.close()
                outzip.write(files[key], "%s.csv" % key)
            outzip.close()

            size = os.path.getsize(zipname)
            outfp = open(zipname, "rb")
            s3_write_stream(transferbucket, path, outfp)
            outfp.close()

            db.exports.patch(exportid, {"complete": True, "count": cnt, "size": size})
        except Exception as e:
            log.exception("error")
            db.exports.patch(exportid, {"error": str(e)})


builtin_props = [
    "Opened",
    "Clicked",
    "Soft Bounced",
    "Bounced",
    "Complained",
    "Unsubscribed",
]


def _iso_datetime(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat() + ("Z" if value.tzinfo is None else "")
    return str(value)


class ContactEmailHistory(object):

    PAGE_SIZE = 10

    def on_get(self, req: falcon.Request, resp: falcon.Response, email: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]
        cid = db.get_cid()
        page = max(req.get_param_as_int("page") or 1, 1)
        offset = self.PAGE_SIZE * (page - 1)

        contact_id = db.single(
            f"""
            select contact_id
            from contacts."contacts_{cid}"
            where email = %s
            """,
            email,
        )
        if contact_id is None:
            raise falcon.HTTPNotFound(
                title="Contact not found", description="Contact not found"
            )

        rows = db.execute(
            """
            with automation_sends as (
                select
                    'automation:' || sr.id as id,
                    (sr.data->>'created')::timestamptz as sent_at,
                    'automation' as source_type,
                    coalesce(sr.data->>'automation_email_name', a.data->>'name', sr.automation_id) as source_name,
                    coalesce(sr.data->>'subject', '') as subject,
                    case
                        when coalesce(sr.data->>'sent', '') = 'true' then 'sent'
                        else coalesce(sr.data->>'status', '')
                    end as status,
                    jsonb_build_object(
                        'automation_id', sr.automation_id,
                        'automation_email_id', sr.data->>'automation_email_id',
                        'enrolment_id', sr.enrolment_id,
                        'node_id', sr.node_id,
                        'step_run_id', sr.id,
                        'published_revision', sr.data->'published_revision',
                        'route_id', sr.data->>'route_id'
                    ) as metadata
                from automation_step_runs sr
                left join automations a on a.cid = sr.cid and a.id = sr.automation_id
                where sr.cid = %s
                  and sr.contact_id = %s
                  and sr.node_type = 'send_email'
                  and coalesce(sr.data->>'sent', '') = 'true'
                  and sr.data->>'created' is not null
            ), transactional_sends as (
                select
                    'transactional:' || t.id as id,
                    t.ts::timestamptz as sent_at,
                    'transactional' as source_type,
                    coalesce(t.data->>'tag', 'untagged') as source_name,
                    coalesce(t.data->>'subject', '') as subject,
                    coalesce(t.data->>'error', t.data->>'status', t.data->>'event', '') as status,
                    jsonb_build_object(
                        'transactional_send_id', t.id,
                        'msgid', t.msgid,
                        'tag', t.data->>'tag',
                        'event', t.data->>'event',
                        'route', t.data->>'route'
                    ) as metadata
                from txnsends t
                where t.cid = %s
                  and lower(coalesce(t.data->>'to', '')) = lower(%s)
            ), combined as (
                select * from automation_sends
                union all
                select * from transactional_sends
            )
            select id, sent_at, source_type, source_name, subject, status, metadata, count(*) over() as total
            from combined
            order by sent_at desc, id desc
            limit %s
            offset %s
            """,
            cid,
            contact_id,
            cid,
            email,
            self.PAGE_SIZE,
            offset,
        ).fetchall()

        records = []
        total = 0
        for row in rows:
            (
                history_id,
                sent_at,
                source_type,
                source_name,
                subject,
                status,
                metadata,
                total,
            ) = row
            records.append(
                {
                    "id": history_id,
                    "sent_at": _iso_datetime(sent_at),
                    "source_type": source_type,
                    "source_name": source_name or "",
                    "subject": subject or "",
                    "status": status or "",
                    "metadata": metadata or {},
                }
            )

        if not rows:
            total = db.single(
                """
                with automation_sends as (
                    select sr.id
                    from automation_step_runs sr
                    where sr.cid = %s
                      and sr.contact_id = %s
                      and sr.node_type = 'send_email'
                      and coalesce(sr.data->>'sent', '') = 'true'
                      and sr.data->>'created' is not null
                ), transactional_sends as (
                    select t.id
                    from txnsends t
                    where t.cid = %s
                      and lower(coalesce(t.data->>'to', '')) = lower(%s)
                )
                select count(*) from (
                    select id from automation_sends
                    union all
                    select id from transactional_sends
                ) combined
                """,
                cid,
                contact_id,
                cid,
                email,
            )

        req.context["result"] = {
            "records": records,
            "page": page,
            "page_size": self.PAGE_SIZE,
            "total": total or 0,
        }


class ContactData(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, email: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        data = get_contact_data(db, db.get_cid(), email)

        if len(data) == 0:
            raise falcon.HTTPNotFound(
                title="Contact not found", description="Contact not found"
            )

        req.context["result"] = data

    def on_delete(self, req: falcon.Request, resp: falcon.Response, email: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        contacts.erase(db, db.get_cid(), [email], unsublog=True)

    # Unlike /feed this endpoint lets you delete properties from a contact, although it won't change the list's
    # used_properties. "Built-in" properties like Opened, Clicked etc. are preserved.
    def on_patch(self, req: falcon.Request, resp: falcon.Response, email: str) -> None:
        check_noadmin(req, True)

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        db = req.context["db"]
        cid = db.get_cid()

        existing = get_contact_data(db, cid, email)
        if len(existing) == 0:
            raise falcon.HTTPNotFound(
                title="Contact not found", description="Contact not found"
            )

        builtin = set(builtin_props)

        mergedprops = {}
        for prop, value in doc.get("properties", {}).items():
            if prop and prop not in builtin:
                mergedprops[prop] = value
        existingprops = existing.get("properties", {})
        for prop in builtin:
            if prop in existingprops:
                mergedprops[prop] = existingprops[prop]

        contacts.overwrite_props(db, cid, email, mergedprops)

        existingtagset = set(existing.get("tags", []))
        newtags = list(
            set([fix_tag(tag) for tag in doc.get("tags", []) if fix_tag(tag)])
        )

        updatelist = []

        for tag in newtags:
            if tag not in existingtagset:
                updatelist.append(tag)
                db.execute(
                    """insert into alltags (cid, tag, added, count) values (%s, %s, now(), 0)
                             on conflict (cid, tag) do nothing""",
                    cid,
                    tag,
                )
        for tag in existingtagset:
            if tag not in newtags:
                updatelist.append("-" + tag)

        webhook_msgs: List[JsonObj] = []
        if len(updatelist) > 0:
            contacts.update_tags(db, cid, [email], updatelist, webhook_msgs)

        if len(webhook_msgs) > 0:
            send_webhooks(db, cid, webhook_msgs)


class ContactExport(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req, False, True)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        email = doc["email"].strip().lower()
        if not email:
            raise falcon.HTTPBadRequest(
                title="Missing Parameter", description="Email is required"
            )
        erase = doc["erase"]

        uuid = shortuuid.uuid()

        name = email.replace("@", "-")
        name = re.sub(r"[^A-Za-z0-9 \-_.]", "", name)

        ts = datetime.utcnow()

        path = "exports/%s/%s-%s.zip" % (uuid, name, ts.strftime("%Y%m%d-%H%M%SZ"))

        exportid = db.exports.add(
            {
                "contact_email": email,
                "started_at": ts.isoformat() + "Z",
                "name": name,
                "url": f"{get_webroot()}/transfer/{path}",
            }
        )

        run_task(export_contact, db.get_cid(), email, erase, exportid, path)

        req.context["result"] = {"id": exportid}


class ListExport(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True, True)

        db = req.context["db"]

        l = db.lists.get(id)
        if l is None:
            raise falcon.HTTPForbidden()

        uuid = shortuuid.uuid()

        name = re.sub(r"[^A-Za-z0-9 \-_.]", "", l["name"])

        ts = datetime.utcnow()

        path = "exports/%s/%s-%s.zip" % (uuid, name, ts.strftime("%Y%m%d-%H%M%SZ"))

        exportid = db.exports.add(
            {
                "list_id": id,
                "started_at": ts.isoformat() + "Z",
                "name": name,
                "url": f"{get_webroot()}/transfer/{path}",
            }
        )

        run_task(export_list, db.get_cid(), id, l["used_properties"], exportid, path)

        req.context["result"] = {"id": exportid}


class SuppListImport(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                tite="Not JSON", description="A valid JSON document is required."
            )

        l = db.supplists.get(id)
        if l is None:
            raise falcon.HTTPForbidden()
        if l.get("processing", None):
            raise falcon.HTTPBadRequest(
                title="List is already importing",
                description="Already importing data into list; try again later",
            )
        db.supplists.patch(id, {"processing": "Importing data", "processing_error": ""})
        try:
            contacts.add_blocks(l["cid"], id, "supp", doc["key"], ["Email"])
        except Exception as e:
            db.supplists.patch(
                id,
                {
                    "processing": "",
                    "processing_error": "Importing data failed: %s" % str(e),
                },
            )


class SuppListAdd(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        l = req.content_length
        if l is None:
            raise falcon.HTTPBadRequest(
                title="No content length specified",
                description="Content-Length header is required",
            )
        if l > 25 * 1024 * 1024:
            raise falcon.HTTPBadRequest(
                title="File too large", description="Maximum file size is 25MB"
            )

        b = req.bounded_stream.read()

        key = "lists/%s.txt" % shortuuid.uuid()

        s3_write(os.environ["s3_transferbucket"], key, b)

        l = db.supplists.get(id)
        if l is None:
            raise falcon.HTTPForbidden()
        if l.get("processing", None):
            raise falcon.HTTPBadRequest(
                title="List is already importing",
                description="Already importing data into list; try again later",
            )
        db.supplists.patch(id, {"processing": "Importing data", "processing_error": ""})
        try:
            contacts.add_blocks(l["cid"], id, "supp", key, ["Email"])
        except Exception as e:
            db.supplists.patch(
                id,
                {
                    "processing": "",
                    "processing_error": "Importing data failed: %s" % str(e),
                },
            )


class ListFeed(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        try:
            validate(
                doc,
                {
                    "type": "object",
                    "properties": {
                        "email": {"type": "string", "format": "email"},
                        "data": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "removetags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "unsubscribe": {"type": "boolean"},
                        "resubscribe": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                    "required": ["email"],
                },
            )
        except Exception as e:
            raise falcon.HTTPBadRequest(
                title="Input validation error", description=str(e)
            )

        taglist = list(
            set([fix_tag(tag) for tag in doc.get("tags", []) if fix_tag(tag)])
        )
        remtaglist = list(
            set([fix_tag(tag) for tag in doc.get("removetags", []) if fix_tag(tag)])
        )
        doc.pop("removetags", None)
        doc["tags"] = taglist + [("-" + tag) for tag in remtaglist]

        if "data" not in doc:
            doc["data"] = {}
        email = doc["email"].strip().lower()
        m = emailre.search(email)
        if not m:
            raise falcon.HTTPBadRequest(
                title="Invalid email", description="That email address is invalid"
            )
        email = m.group(0)

        doc["data"]["Email"] = email
        doc.pop("email", None)

        if doc.get("unsubscribe", False) and doc.get("resubscribe", False):
            raise falcon.HTTPBadRequest(
                title="Invalid Parameter",
                description="Cannot unsubscribe and resubscribe at the same time.",
            )

        tagstr = ",".join(doc["tags"])
        if len(tagstr) > 16 * 1024:
            raise falcon.HTTPBadRequest(
                title="Too much tag data",
                description="Too much tag data; please enter shorter/fewer tags.",
            )

        data = json.dumps(doc)

        if len(data) > 256 * 1024:
            raise falcon.HTTPBadRequest(
                title="Data too large", description="Maximum data size is 64KB"
            )

        l = db.lists.get(id)
        if l is None:
            raise falcon.HTTPForbidden()

        for tl in (taglist, remtaglist):
            for tag in tl:
                db.execute(
                    """insert into alltags (cid, tag, added, count) values (%s, %s, now(), 0)
                             on conflict (cid, tag) do nothing""",
                    db.get_cid(),
                    tag,
                )

        contacts.feed(
            db,
            id,
            doc["data"],
            doc["tags"],
            override=doc.get("resubscribe", False),
            unsubscribe=doc.get("unsubscribe", False),
        )

        req.context["result"] = {
            "email": email,
            "result": "ok",
        }


class ListAdd(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        l = req.content_length
        if l is None:
            raise falcon.HTTPBadRequest(
                title="No content length specified",
                description="Content-Length header is required",
            )
        if l > 25 * 1024 * 1024:
            raise falcon.HTTPBadRequest(
                title="File too large", description="Maximum file size is 25MB"
            )

        b = req.bounded_stream.read()

        key = "lists/%s.txt" % shortuuid.uuid()

        colmap = None
        for row in csv.reader(StringIO(try_decode(b))):
            colmap = row
            break

        if colmap is None:
            raise falcon.HTTPBadRequest(
                title="Invalid Parameter", description="No CSV data found"
            )
        if "Email" not in colmap:
            raise falcon.HTTPBadRequest(
                title="Invalid Parameter", description="Email column not found"
            )
        for col in colmap:
            if not col.strip():
                raise falcon.HTTPBadRequest(
                    title="Invalid Parameter",
                    description="Empty column names are not allowed",
                )

        s3_write(os.environ["s3_transferbucket"], key, b)

        l = db.lists.get(id)
        if l is None:
            raise falcon.HTTPForbidden()
        if l.get("processing", None):
            raise falcon.HTTPBadRequest(
                title="List is already importing",
                description="Already importing data into list; try again later",
            )
        db.lists.patch(id, {"processing": "Importing data", "processing_error": ""})
        try:
            contacts.add_blocks(l["cid"], id, "list", key, colmap, False)
        except Exception as e:
            db.lists.patch(
                id,
                {
                    "processing": "",
                    "processing_error": "Importing data failed: %s" % str(e),
                },
            )


class ListAddUnsubs(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        l = req.content_length
        if l is None:
            raise falcon.HTTPBadRequest(
                title="No content length specified",
                description="Content-Length header is required",
            )
        if l > 25 * 1024 * 1024:
            raise falcon.HTTPBadRequest(
                title="File too large", description="Maximum file size is 25MB"
            )

        b = req.bounded_stream.read()

        lst = db.lists.get(id)
        if lst is None:
            raise falcon.HTTPForbidden()
        if lst.get("processing", None):
            raise falcon.HTTPBadRequest(
                title="List is already importing",
                description="Already importing data into list; try again later",
            )

        data = b.decode("utf-8")

        fd = BytesIO()

        for line in data.split("\n"):
            li = line.strip().lower()
            if not li:
                continue
            m = emailre.search(li)
            if not m:
                continue
            li = m.group(0)

            db.execute(
                """insert into unsublogs (cid, email, rawhash, unsubscribed, complained, bounced) values (%s, %s, %s, true, false, false)
                          on conflict (cid, email) do update set
                          unsubscribed = true""",
                lst["cid"],
                li,
                get_contact_id(db, lst["cid"], li),
            )

            fd.write(("%s,true\n" % li).encode("utf-8"))

        fd.seek(0)
        key = "lists/%s.txt" % shortuuid.uuid()
        s3_write_stream(os.environ["s3_transferbucket"], key, fd)

        db.lists.patch(id, {"processing": "Importing data", "processing_error": ""})
        try:
            contacts.add_blocks(
                lst["cid"], id, "list", key, ["Email", "Unsubscribed"], unsub=True
            )
        except Exception as e:
            db.lists.patch(
                id,
                {
                    "processing": "",
                    "processing_error": "Importing data failed: %s" % str(e),
                },
            )


class ListImportUnsubs(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        if "data" not in doc:
            raise falcon.HTTPBadRequest(
                title="Invalid Parameter", description="Data not found"
            )

        l = db.lists.get(id)
        if l is None:
            raise falcon.HTTPForbidden()
        if l.get("processing", None):
            raise falcon.HTTPBadRequest(
                title="List is already importing",
                description="Already importing data into list; try again later",
            )

        data = str(doc["data"])

        fd = BytesIO()

        for line in data.split("\n"):
            li = line.strip().lower()
            if not li:
                continue
            m = emailre.search(li)
            if not m:
                continue
            li = m.group(0)

            db.execute(
                """insert into unsublogs (cid, email, rawhash, unsubscribed, complained, bounced) values (%s, %s, %s, true, false, false)
                          on conflict (cid, email) do update set
                          unsubscribed = true""",
                l["cid"],
                li,
                get_contact_id(db, l["cid"], li),
            )

            fd.write(("%s,true\n" % li).encode("utf-8"))

        fd.seek(0)
        key = "lists/%s.txt" % shortuuid.uuid()
        s3_write_stream(os.environ["s3_transferbucket"], key, fd)

        db.lists.patch(id, {"processing": "Importing data", "processing_error": ""})
        try:
            contacts.add_blocks(
                l["cid"], id, "list", key, ["Email", "Unsubscribed"], unsub=True
            )
        except Exception as e:
            db.lists.patch(
                id,
                {
                    "processing": "",
                    "processing_error": "Importing data failed: %s" % str(e),
                },
            )


class ListImport(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        if "Email" not in doc["colmap"]:
            raise falcon.HTTPBadRequest(
                title="Invalid Parameter", description="Email column not found"
            )

        l = db.lists.get(id)
        if l is None:
            raise falcon.HTTPForbidden()
        if l.get("processing", None):
            raise falcon.HTTPBadRequest(
                title="List is already importing",
                description="Already importing data into list; try again later",
            )
        db.lists.patch(id, {"processing": "Importing data", "processing_error": ""})
        try:
            contacts.add_blocks(
                l["cid"], id, "list", doc["key"], doc["colmap"], doc["override"]
            )
        except Exception as e:
            db.lists.patch(
                id,
                {
                    "processing": "",
                    "processing_error": "Importing data failed: %s" % str(e),
                },
            )


class ListDeleteDomains(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        if not isinstance(doc, list):
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A list of domains is required."
            )

        for domain in doc:
            if not isinstance(domain, str) or not re.search(
                r"^[a-zA-Z0-9\.-]+$", domain
            ):
                raise falcon.HTTPBadRequest(
                    title="Not JSON", description="Invalid domain name."
                )

        lst = db.lists.get(id)

        if lst is None:
            raise falcon.HTTPForbidden()

        contacts.remove_list_domains(db, db.get_cid(), lst, doc)


class ListDeleteContacts(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        if not isinstance(doc, list):
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A list of emails is required."
            )

        lst = db.lists.get(id)

        if lst is None:
            raise falcon.HTTPForbidden()

        emails = []
        for email in doc:
            m = emailre.search(email)
            if not m:
                continue
            emails.append(m.group(0))

        if len(emails) > 1000:
            raise falcon.HTTPBadRequest(
                title="Too many emails",
                description="Too many emails; please delete 1000 or less contacts at a time.",
            )

        if len(emails) == 0:
            req.context["result"] = {"count": 0}
            return

        req.context["result"] = {
            "count": contacts.remove_list_contacts(db, db.get_cid(), lst["id"], emails)
        }


class ListBulkDelete(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        lst = db.lists.get(id)

        if lst is None:
            raise falcon.HTTPForbidden()

        if "emails" in doc:
            contacts.remove_list_contacts(db, db.get_cid(), lst["id"], doc["emails"])
        else:
            fakesegment = find_segment(id, doc["segment"])

            contacts.bulk_list_remove(db, db.get_cid(), lst, fakesegment)


class SegmentTag(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        segment = db.segments.get(id)

        if segment is None:
            raise falcon.HTTPForbidden()

        if "tags" in doc:
            tagprop = "tags"
        else:
            tagprop = "removetags"

        taglist = list(set([fix_tag(tag) for tag in doc[tagprop] if fix_tag(tag)]))
        if tagprop == "removetags":
            taglist = ["-" + tag for tag in taglist]
        tagstr = ",".join(taglist)
        if len(tagstr) > 16 * 1024:
            raise falcon.HTTPBadRequest(
                title="Too much tag data",
                description="Too much tag data; please enter shorter/fewer tags.",
            )
        if len(taglist) == 0:
            raise falcon.HTTPBadRequest(
                title="No tags", description="Please enter a tag."
            )

        if tagprop == "tags":
            for tag in taglist:
                db.execute(
                    """insert into alltags (cid, tag, added, count) values (%s, %s, now(), 0)
                             on conflict (cid, tag) do nothing""",
                    db.get_cid(),
                    tag,
                )

        contacts.bulktag(db, db.get_cid(), segment, taglist)


class ListTag(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        lst = db.lists.get(id)

        if lst is None:
            raise falcon.HTTPForbidden()

        if "tags" in doc:
            tagprop = "tags"
        else:
            tagprop = "removetags"

        taglist = list(set([fix_tag(tag) for tag in doc[tagprop] if fix_tag(tag)]))
        if tagprop == "removetags":
            taglist = ["-" + tag for tag in taglist]
        tagstr = ",".join(taglist)
        if len(tagstr) > 16 * 1024:
            raise falcon.HTTPBadRequest(
                title="Too much tag data",
                description="Too much tag data; please enter shorter/fewer tags.",
            )
        if len(taglist) == 0:
            raise falcon.HTTPBadRequest(
                title="No tags", description="Please enter a tag."
            )

        if tagprop == "tags":
            for tag in taglist:
                db.execute(
                    """insert into alltags (cid, tag, added, count) values (%s, %s, now(), 0)
                             on conflict (cid, tag) do nothing""",
                    db.get_cid(),
                    tag,
                )

        if "emails" in doc:
            webhook_msgs: List[JsonObj] = []
            contacts.update_tags(db, db.get_cid(), doc["emails"], taglist, webhook_msgs)
            if len(webhook_msgs):
                send_webhooks(db, db.get_cid(), webhook_msgs)
        else:
            fakesegment = find_segment(id, doc["segment"])

            contacts.bulktag(db, db.get_cid(), fakesegment, taglist)


def find_segment(id: str, doc: JsonObj) -> JsonObj:
    return {
        "id": shortuuid.uuid(),
        "operator": "and",
        "subset": False,
        "subsettype": "percent",
        "subsetpct": 10,
        "subsetnum": 2000,
        "parts": [
            {
                "type": "Lists",
                "operator": "in",
                "list": id,
                "segment": "",
            },
            {
                "type": "Group",
                "operator": doc["operator"],
                "parts": doc["parts"],
            },
        ],
    }


class ListFind(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        lst = db.lists.get(id)

        if lst is None:
            raise falcon.HTTPForbidden()

        db.set_cid(None)

        fakesegment = find_segment(id, doc)

        campaignids = segment_get_campaignids(fakesegment, [])

        hashlimit, listfactors = segment_get_params(
            db, lst["cid"], fakesegment, lists=[lst]
        )

        if hashlimit == 1:
            found = do_list_find(
                db,
                lst["cid"],
                fakesegment,
                doc["sort"],
                doc.get("before"),
                doc.get("after"),
                0,
                listfactors,
                hashlimit,
                campaignids,
            )

            req.context["result"] = list_find_finish([found])
        else:
            gatherid = gather_init(db, "list_find", hashlimit)

            run_task(
                list_find_start,
                lst["cid"],
                fakesegment,
                doc["sort"],
                doc.get("before"),
                doc.get("after"),
                listfactors,
                hashlimit,
                campaignids,
                gatherid,
            )

            req.context["result"] = {"id": gatherid}


@tasks.task(priority=HIGH_PRIORITY)
def list_find_start(
    cid: str,
    segment: JsonObj,
    sort: JsonObj,
    before: str,
    after: str,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
    gatherid: str,
) -> None:
    try:
        taskparams = []
        for i in range(hashlimit):
            taskparams.append(
                (
                    list_find,
                    cid,
                    segment,
                    sort,
                    before,
                    after,
                    i,
                    listfactors,
                    hashlimit,
                    campaignids,
                    gatherid,
                )
            )
        run_tasks(taskparams)
    except Exception as e:
        log.exception("error")
        with open_db() as db:
            gather_complete(db, gatherid, {"error": str(e)}, False)


PAGE_SIZE = 50


def do_list_find(
    db: DB,
    cid: str,
    segment: JsonObj,
    sort: JsonObj,
    before: str | None,
    after: str | None,
    hashval: int,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
) -> JsonObj:
    segments: Dict[str, JsonObj | None] = {}

    sentrows = get_segment_sentrows(db, cid, campaignids, hashval, hashlimit)

    rows = get_segment_rows(db, cid, hashval, listfactors, hashlimit)

    def fix_row(r: JsonObj) -> JsonObj:
        fixedrow = {}
        for prop in r.keys():
            if not prop.startswith("!"):
                fixedrow[prop] = r.get(prop, ("",))[0]
            if prop == "!!tags":
                tagval = ",".join(sorted(r.get("!!tags", ())))
                if tagval:
                    fixedrow[prop] = tagval
        return fixedrow

    cache = Cache()
    tmp = []
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
            tmp.append(fix_row(row))

    tmp.sort(key=lambda r: r.get(sort["id"], ""))
    if sort.get("desc", False):
        tmp.reverse()

    count = len(tmp)

    found = []
    if before is not None:
        for f in tmp:
            if f.get(sort["id"], "") < before:
                found.append(f)
            else:
                break
        has_previous = len(found) > PAGE_SIZE
        has_next = len(tmp) > len(found)
    elif after is not None:
        for f in tmp:
            if f.get(sort["id"], "") > after:
                found.append(f)
        has_previous = len(tmp) > len(found)
        has_next = len(found) > PAGE_SIZE
    else:
        found = tmp
        has_previous = False
        has_next = len(found) > PAGE_SIZE

    if before is not None:
        rows = found[-PAGE_SIZE:]
    else:
        rows = found[:PAGE_SIZE]

    return {
        "rows": rows,
        "count": count,
        "sort": sort,
        "before": before,
        "after": after,
        "has_previous": has_previous,
        "has_next": has_next,
    }


@tasks.task(priority=HIGH_PRIORITY)
def list_find(
    cid: str,
    segment: JsonObj,
    sort: JsonObj,
    before: str,
    after: str,
    hashval: int,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
    gatherid: str,
) -> None:
    with open_db() as db:
        try:
            ret = do_list_find(
                db,
                cid,
                segment,
                sort,
                before,
                after,
                hashval,
                listfactors,
                hashlimit,
                campaignids,
            )

            gather_complete(db, gatherid, ret, False)
        except Exception as e:
            log.exception("error")
            gather_complete(db, gatherid, {"error": str(e)}, False)


def list_find_finish(data: List[JsonObj]) -> JsonObj:
    allprops = set()
    rows = []
    count = 0
    sort = None
    has_previous = False
    has_next = False
    before = None
    for d in data:
        if d.get("error", None):
            return {"error": d["error"]}
        for row in d["rows"]:
            rows.append(row)
        count += d["count"]
        sort = d["sort"]
        if d.get("before"):
            before = d["before"]
        if d.get("has_previous", False):
            has_previous = True
        if d.get("has_next", False):
            has_next = True

    if sort is not None:
        rows.sort(key=lambda r: r.get(sort["id"], ""))
        if sort.get("desc", False):
            rows.reverse()

    if before is not None and not has_previous:
        has_previous = len(rows) > PAGE_SIZE
    elif not has_next:
        has_next = len(rows) > PAGE_SIZE

    if before is not None:
        rows = rows[-PAGE_SIZE:]
    else:
        rows = rows[:PAGE_SIZE]
    for row in rows:
        for p in row.keys():
            if p != "Email":
                allprops.add(p)

    return {
        "complete": True,
        "result": {
            "allprops": sort_props(allprops),
            "rows": rows,
            "count": count,
            "has_previous": has_previous,
            "has_next": has_next,
        },
    }


def sort_props(props: Set[str]) -> List[str]:
    ret = ["Email"]
    if "!!tags" in props:
        props.remove("!!tags")
        ret.append("!!tags")
    builtins = []
    for prop in builtin_props:
        if prop in props:
            props.remove(prop)
            builtins.append(prop)
    ret.extend(sorted(list(props), key=lambda x: x.lower()))
    ret.extend(builtins)

    return ret


class ListFindStatus(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        db.set_cid(None)

        data = gather_check(db, id)
        if data is None:
            req.context["result"] = {}
        else:
            req.context["result"] = list_find_finish(data)


SUPPLIST_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {
            "type": "string",
            "maxLength": 1024,
            "minLength": 1,
        },
    },
    "additionalProperties": False,
}


class SuppLists(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "supplists"
        self.useronly = True
        self.schema = SUPPLIST_SCHEMA
        self.api = True


class SuppList(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "supplists"
        self.useronly = True
        self.schema = patch_schema(SUPPLIST_SCHEMA)
        self.api = True

    def on_delete(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        db = req.context["db"]

        CRUDSingle.on_delete(self, req, resp, id)

        hashlimit = get_hashlimit(db, db.get_cid())

        for hashval in range(hashlimit):
            run_task(delete_supplist_bucket, db.get_cid(), hashval, hashlimit, id)

    def del_check(self, db: DB, id: str) -> None:
        for camp in json_iter(
            db.execute(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and data->>'sent_at' is null",
                db.get_cid(),
            )
        ):
            if id in camp["supplists"]:
                raise falcon.HTTPBadRequest(
                    title="Suppression list in use",
                    description="This list is in use by one or more draft broadcasts",
                )


LIST_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {
            "type": "string",
            "maxLength": 1024,
            "minLength": 1,
        },
        "used_properties": {},
    },
    "additionalProperties": False,
}


class Lists(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "lists"
        self.useronly = True
        self.schema = LIST_SCHEMA
        self.api = True
        self.hide = "validation"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        doc["used_properties"] = []
        doc.pop("validation", None)
        doc.pop("unapproved", None)

        return CRUDCollection.on_post(self, req, resp)


@tasks.task(priority=LOW_PRIORITY)
def delete_list_bucket(cid: str, hashval: int, hashlimit: int, listid: str) -> None:
    with open_db() as db:
        try:
            db.execute(
                f"""
                    delete from contacts."contact_lists_{cid}" l
                    using contacts."contacts_{cid}" c
                    where ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                    and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                    and c.contact_id = l.contact_id
                    and l.list_id = %s
                        """,
                hashval,
                hashval,
                listid,
            )

            tc = {
                tag: cnt
                for tag, cnt in db.execute(
                    f"""
                select value, count(*)
                from contacts."contact_values_{cid}" v
                join contacts."contacts_{cid}" c on v.contact_id = c.contact_id
                where type = 'tag' and ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                and not exists (
                    select true
                    from contacts."contact_lists_{cid}" l
                    where l.contact_id = c.contact_id
                    and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                )
                and not exists (
                    select true
                    from contacts."contact_supplists_{cid}" l
                    where l.contact_id = c.contact_id
                    and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                )
                group by value""",
                    hashval,
                    hashval,
                    hashval,
                )
            }

            for tagname, cnt in tc.items():
                db.execute(
                    "update alltags set count = count - %s where cid = %s and tag = %s",
                    cnt,
                    cid,
                    tagname,
                )
            db.execute("delete from alltags where count <= 0 and cid = %s", cid)

            db.execute(
                f"""
                        delete from contacts."contacts_{cid}" c
                        where ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                        and not exists (
                            select true
                            from contacts."contact_lists_{cid}" l
                            where l.contact_id = c.contact_id
                            and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                        )
                        and not exists (
                            select true
                            from contacts."contact_supplists_{cid}" l
                            where l.contact_id = c.contact_id
                            and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                        )
                        """,
                hashval,
                hashval,
                hashval,
            )
        except:
            log.exception("error")


@tasks.task(priority=LOW_PRIORITY)
def delete_supplist_bucket(
    cid: str, hashval: int, hashlimit: int, supplistid: str
) -> None:
    with open_db() as db:
        try:
            db.execute(
                f"""
                    delete from contacts."contact_supplists_{cid}" l
                    using contacts."contacts_{cid}" c
                    where ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                    and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                    and c.contact_id = l.contact_id
                    and l.supplist_id = %s
                        """,
                hashval,
                hashval,
                supplistid,
            )

            db.execute(
                f"""
                        delete from contacts."contacts_{cid}" c
                        where ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                        and not exists (
                            select true
                            from contacts."contact_lists_{cid}" l
                            where l.contact_id = c.contact_id
                            and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                        )
                        and not exists (
                            select true
                            from contacts."contact_supplists_{cid}" l
                            where l.contact_id = c.contact_id
                            and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                        )
                        """,
                hashval,
                hashval,
                hashval,
            )
        except:
            log.exception("error")


class ListSingle(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "lists"
        self.useronly = True
        self.schema = patch_schema(LIST_SCHEMA)
        self.api = True
        self.hide = "validation"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        doc.pop("validation", None)
        doc.pop("unapproved", None)

        return CRUDSingle.on_patch(self, req, resp, id)

    def on_delete(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        db = req.context["db"]

        CRUDSingle.on_delete(self, req, resp, id)

        hashlimit = get_hashlimit(db, db.get_cid())

        for hashval in range(hashlimit):
            run_task(delete_list_bucket, db.get_cid(), hashval, hashlimit, id)

    def del_check_rule(self, rule: JsonObj, id: str) -> None:
        if rule["type"] == "Lists":
            if rule["list"] == id:
                raise falcon.HTTPBadRequest(
                    title="List in use",
                    description="This list is in use by one or more segments",
                )
            for a in rule.get("addl", ()):
                if a["list"] == id:
                    raise falcon.HTTPBadRequest(
                        title="List in use",
                        description="This list is in use by one or more segments",
                    )
        elif rule["type"] == "Group":
            for r in rule["parts"]:
                self.del_check_rule(r, id)

    def del_check(self, db: DB, id: str) -> None:
        if db.forms.find_one({"list": id}):
            raise falcon.HTTPBadRequest(
                title="List in use", description="List is in use by one or more forms"
            )

        for segment in db.segments.find():
            for rule in segment["parts"]:
                self.del_check_rule(rule, id)

        for camp in json_iter(
            db.execute(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and data->>'sent_at' is null",
                db.get_cid(),
            )
        ):
            if id in camp["lists"]:
                raise falcon.HTTPBadRequest(
                    title="List in use",
                    description="This list is in use by one or more draft broadcasts",
                )


class Exports(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "exports"
        self.useronly = True
        self.checkexports = True
        self.api = True

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        raise falcon.HTTPBadRequest()


SEGMENT_SCHEMA = {
    "type": "object",
    "required": ["name", "parts", "operator"],
    "properties": {
        "name": {
            "type": "string",
            "maxLength": 1024,
            "minLength": 1,
        },
        "operator": {
            "enum": ["and", "or", "nor"],
        },
        "parts": {
            "type": "array",
            "items": {
                "oneOf": [
                    {
                        "$ref": "#/definitions/Responses1",
                    },
                    {
                        "$ref": "#/definitions/Lists1",
                    },
                    {
                        "$ref": "#/definitions/Info1",
                    },
                    {
                        "$ref": "#/definitions/Group1",
                    },
                ]
            },
        },
        "subset": {
            "type": "boolean",
        },
        "subsetnum": {
            "type": "integer",
            "minimum": 1,
        },
        "subsetpct": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
        },
        "subsettype": {
            "enum": ["percent", "count"],
        },
        "modified": {"type": "string"},
        "count": {"type": ["string", "integer"]},
        "last_update": {"type": "string"},
    },
    "additionalProperties": False,
    "definitions": {
        "Lists1": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "maxLength": 1024,
                },
                "type": {
                    "const": "Lists",
                },
                "list": {
                    "type": "string",
                    "maxLength": 22,
                },
                "segment": {
                    "type": "string",
                    "maxLength": 22,
                },
                "addl": {
                    "type": "array",
                    "items": {
                        "$ref": "#/definitions/Lists1",
                    },
                },
                "operator": {
                    "enum": ["in", "notin", "insegment", "notinsegment"],
                },
                "subset": {
                    "type": "boolean",
                },
                "subsetnum": {
                    "type": "integer",
                    "minimum": 1,
                },
                "subsetpct": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                },
                "subsettype": {
                    "enum": ["percent", "count"],
                },
            },
            "required": [
                "type",
                "operator",
            ],
            "additionalProperties": False,
        },
        "Responses1": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "maxLength": 1024,
                },
                "type": {
                    "const": "Responses",
                },
                "action": {
                    "enum": [
                        "opened",
                        "clicked",
                        "openclicked",
                        "notopened",
                        "notclicked",
                        "notopenclicked",
                        "opencnt",
                        "clickcnt",
                        "openclickcnt",
                        "sent",
                        "notsent",
                    ]
                },
                "timestart": {
                    "format": "date-time",
                },
                "timeend": {
                    "format": "date-time",
                },
                "timenum": {
                    "type": "integer",
                    "minimum": 1,
                },
                "campaign": {
                    "type": "string",
                    "maxLength": 22,
                },
                "defaultcampaign": {
                    "type": "string",
                    "maxLength": 22,
                },
                "broadcast": {
                    "type": "string",
                    "maxLength": 22,
                },
                "defaultbroadcast": {
                    "type": "string",
                    "maxLength": 22,
                },
                "cntvalue": {
                    "type": "integer",
                    "minimum": 0,
                },
                "timetype": {
                    "enum": ["anytime", "inpast", "between"],
                },
                "cntoperator": {
                    "enum": ["more", "equal", "less"],
                },
                "addl": {
                    "type": "array",
                    "items": {
                        "$ref": "#/definitions/Responses1",
                    },
                },
            },
            "required": [
                "type",
                "action",
            ],
            "additionalProperties": False,
        },
        "Info1": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "maxLength": 1024,
                },
                "type": {
                    "const": "Info",
                },
                "test": {
                    "enum": ["", "tag", "notag"],
                },
                "tag": {
                    "type": "string",
                    "maxLength": 1024,
                },
                "prop": {
                    "type": "string",
                    "maxLength": 1024,
                },
                "operator": {
                    "enum": [
                        "contains",
                        "notcontains",
                        "equals",
                        "notequals",
                        "startswith",
                        "endswith",
                    ],
                },
                "value": {
                    "type": "string",
                    "maxLength": 1024,
                },
                "addl": {
                    "type": "array",
                    "items": {
                        "$ref": "#/definitions/Info1",
                    },
                },
            },
            "required": [
                "type",
                "test",
            ],
            "additionalProperties": False,
        },
        "Group1": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "maxLength": 1024,
                },
                "type": {
                    "const": "Group",
                },
                "operator": {
                    "enum": ["and", "or", "nor"],
                },
                "parts": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {
                                "$ref": "#/definitions/Responses1",
                            },
                            {
                                "$ref": "#/definitions/Lists1",
                            },
                            {
                                "$ref": "#/definitions/Info1",
                            },
                            {
                                "$ref": "#/definitions/Group2",
                            },
                        ]
                    },
                },
                "level": {
                    "const": 0,
                },
            },
            "required": [
                "type",
                "parts",
                "operator",
            ],
            "additionalProperties": False,
        },
        "Group2": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "maxLength": 1024,
                },
                "type": {
                    "const": "Group",
                },
                "operator": {
                    "enum": ["and", "or", "nor"],
                },
                "parts": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {
                                "$ref": "#/definitions/Responses1",
                            },
                            {
                                "$ref": "#/definitions/Lists1",
                            },
                            {
                                "$ref": "#/definitions/Info1",
                            },
                            {
                                "$ref": "#/definitions/Group3",
                            },
                        ]
                    },
                },
                "level": {
                    "const": 1,
                },
            },
            "required": [
                "type",
                "parts",
                "operator",
            ],
            "additionalProperties": False,
        },
        "Group3": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "maxLength": 1024,
                },
                "type": {
                    "const": "Group",
                },
                "operator": {
                    "enum": ["and", "or", "nor"],
                },
                "parts": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {
                                "$ref": "#/definitions/Responses1",
                            },
                            {
                                "$ref": "#/definitions/Lists1",
                            },
                            {
                                "$ref": "#/definitions/Info1",
                            },
                        ]
                    },
                },
                "level": {
                    "const": 2,
                },
            },
            "required": [
                "type",
                "parts",
                "operator",
            ],
            "additionalProperties": False,
        },
    },
}


class Segments(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "segments"
        self.useronly = True
        # self.schema = SEGMENT_SCHEMA

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        req.context["result"] = list(
            json_iter(
                db.execute(
                    "select id, cid, data - 'parts' from segments where cid = %s",
                    db.get_cid(),
                )
            )
        )

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        ts = datetime.utcnow().isoformat() + "Z"

        if "doc" in req.context:
            req.context["doc"]["count"] = "Loading, please wait"
            req.context["doc"]["modified"] = ts

        CRUDCollection.on_post(self, req, resp)

        segid = req.context["result"]["id"]

        run_task(refresh_segment_count, req.context["db"].get_cid(), [[segid, ts]])


def check_infinite(db: DB, parts: List[JsonObj], loadedids: Set[str]) -> None:
    newids: Set[str] = set()
    segment_get_segmentids(parts, newids)

    if loadedids & newids:
        raise falcon.HTTPBadRequest(
            title="Infinite loop", description="This segment contains an infinite loop"
        )

    for id in newids:
        segment = db.segments.get(id)
        if segment is not None:
            newloaded = set()
            newloaded.update(loadedids)
            newloaded.add(id)
            check_infinite(db, segment["parts"], newloaded)


class Segment(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "segments"
        self.useronly = True
        # self.schema = patch_schema(SEGMENT_SCHEMA)

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        ts = datetime.utcnow().isoformat() + "Z"

        if "doc" in req.context:
            req.context["doc"]["count"] = "Loading, please wait"
            req.context["doc"]["modified"] = ts
            parts = req.context["doc"].get("parts", [])
            loadedids = set()
            loadedids.add(id)
            check_infinite(req.context["db"], parts, loadedids)

        CRUDSingle.on_patch(self, req, resp, id)

        run_task(refresh_segment_count, req.context["db"].get_cid(), [[id, ts]])

    def del_check(self, db: DB, id: str) -> None:
        for camp in json_iter(
            db.execute(
                "select id, cid, data - 'parts' - 'rawText' from campaigns where cid = %s and data->>'sent_at' is null",
                db.get_cid(),
            )
        ):
            if id in camp["segments"] or id in camp["suppsegs"]:
                raise falcon.HTTPBadRequest(
                    title="Segment in use",
                    description="This segment is in use by one or more draft broadcasts",
                )


class SegmentContacts(object):

    def _get_page_param(self, req: falcon.Request, name: str, default: int, maximum: int) -> int:
        value = req.get_param_as_int(name) or default
        return max(1, min(value, maximum))

    def _evaluate_contacts(
        self,
        db: DB,
        cid: str,
        segment: JsonObj,
        search: str,
    ) -> List[JsonObj]:
        segments: Dict[str, JsonObj | None] = {}
        segment_get_segments(db, segment.get("parts", []), segments)
        campaignids = segment_get_campaignids(segment, list(segments.values()))
        hashlimit, listfactors = segment_get_params(db, cid, segment)

        rowset = None
        if search:
            rowset = {
                email
                for (email,) in db.execute(
                    f"""
                    select email
                    from contacts."contacts_{cid}"
                    where lower(email) like %s
                    """,
                    "%%%s%%" % search,
                )
            }
            if not rowset:
                return []

        emails = set()
        cache = Cache()
        for hashval in range(hashlimit):
            sentrows = get_segment_sentrows(db, cid, campaignids, hashval, hashlimit)
            rows = get_segment_rows(db, cid, hashval, listfactors, hashlimit, rowset=rowset)
            segcounts: Dict[str, int] = {}
            numrows = len(rows)
            for row in rows:
                email = row.get("Email", [""])[0]
                if search and search not in email.lower():
                    continue
                if segment_eval_parts(
                    segment.get("parts", []),
                    segment.get("operator", "and"),
                    row,
                    segcounts,
                    numrows,
                    segments,
                    sentrows,
                    segment,
                    hashlimit,
                    cache,
                ):
                    emails.add(email)

        if not emails:
            return []

        return [
            {
                "contact_id": contact_id,
                "email": email,
                "added": added.isoformat() + "Z" if hasattr(added, "isoformat") else added,
            }
            for contact_id, email, added in db.execute(
                f"""
                select contact_id, email, added
                from contacts."contacts_{cid}"
                where email = any(%s)
                order by lower(email), contact_id
                """,
                list(emails),
            )
        ]

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]
        cid = db.get_cid()

        segment = db.segments.get(id)
        if segment is None or segment.get("cid") != cid:
            raise falcon.HTTPForbidden()

        page = self._get_page_param(req, "page", 1, 1000000)
        page_size = self._get_page_param(req, "page_size", 50, 100)
        search = (req.get_param("search") or "").strip().lower()[:255]

        try:
            contacts = self._evaluate_contacts(db, cid, segment, search)
        except Exception as exc:
            raise falcon.HTTPBadRequest(
                title="Unable to evaluate segment",
                description=str(exc),
            )

        total = len(contacts)
        offset = (page - 1) * page_size
        req.context["result"] = {
            "segment": {
                "id": segment["id"],
                "name": segment.get("name", segment["id"]),
                "count": segment.get("count"),
            },
            "contacts": contacts[offset:offset + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "search": search,
        }


class SegmentExport(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, False, True)

        db = req.context["db"]

        s = db.segments.get(id)
        if s is None:
            raise falcon.HTTPForbidden()

        uuid = shortuuid.uuid()

        name = re.sub(r"[^A-Za-z0-9 \-_.]", "", s["name"])

        ts = datetime.utcnow()

        path = "exports/%s/%s-%s.zip" % (uuid, name, ts.strftime("%Y%m%d-%H%M%SZ"))

        exportid = db.exports.add(
            {
                "segment_id": id,
                "started_at": ts.isoformat() + "Z",
                "name": name,
                "url": f"{get_webroot()}/transfer/{path}",
            }
        )

        run_task(export_segment, id, exportid, path)


@tasks.task(priority=HIGH_PRIORITY)
def export_segment_block(
    segid: str,
    hashval: int,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
    gatherid: str,
    exportid: str,
    path: str,
) -> None:
    with open_db() as db:
        try:
            segment = db.segments.get(segid)
            if segment is None:
                raise Exception("segment not found")

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

            allprops = set()
            for row in rows:
                for prop in row.keys():
                    if not prop.startswith("!"):
                        allprops.add(prop)

            if len(rows) > 0:
                fp = BytesIO()
                writer = MPDictWriter(fp, list(allprops))
                writer.writeheader()
                for row in rows:
                    fixedrow = {}
                    for prop in allprops:
                        fixedrow[prop] = row.get(prop, ("",))[0]
                    writer.writerow(fixedrow)

                fp.seek(0, 0)

                s3_write_stream(
                    os.environ["s3_transferbucket"],
                    "segmentexports/%s/%08d.blk" % (gatherid, hashval),
                    fp,
                )

            data = gather_complete(db, gatherid, {"allprops": list(allprops)})
            if data is not None:
                allprops = set()
                for d in data:
                    allprops.update(d["allprops"])

                allprops.remove("Email")
                u = list(allprops)
                u.insert(0, "Email")
                run_task(
                    export_segment_final,
                    "segmentexports/%s" % gatherid,
                    u,
                    exportid,
                    path,
                )
        except Exception as e:
            log.exception("error")
            db.exports.patch(exportid, {"error": str(e)})


@tasks.task(priority=LOW_PRIORITY)
def refresh_segment_block(
    cid: str,
    values: List[Tuple[str, int]],
    hashval: int,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
    gatherid: str,
) -> None:
    with open_db() as db:
        try:
            segmentobjs = []
            for segid, _ in values:
                segment = db.segments.get(segid)
                if segment is None:
                    return
                segmentobjs.append(segment)

            segments: Dict[str, JsonObj | None] = {}
            counts: Dict[str, int] = {}
            segcounts: Dict[str, Dict[str, int]] = {}
            for segment in segmentobjs:
                counts[segment["id"]] = 0
                segcounts[segment["id"]] = {}
                segment_get_segments(db, segment["parts"], segments)

            sentrows = get_segment_sentrows(db, cid, campaignids, hashval, hashlimit)

            rows = get_segment_rows(db, cid, hashval, listfactors, hashlimit)

            cache = Cache()

            numrows = len(rows)
            for row in rows:
                for segment in segmentobjs:
                    segid = segment["id"]
                    if segment_eval_parts(
                        segment["parts"],
                        segment["operator"],
                        row,
                        segcounts[segid],
                        numrows,
                        segments,
                        sentrows,
                        segment,
                        hashlimit,
                        cache,
                    ):
                        counts[segid] = counts[segid] + 1

            data = gather_complete(db, gatherid, {"counts": counts})
            if data is not None:
                counts = {}
                for d in data:
                    for segid, cnt in d["counts"].items():
                        if segid not in counts:
                            counts[segid] = cnt
                        else:
                            counts[segid] = counts[segid] + cnt
                for segid, checkts in values:
                    seg = db.segments.get(segid)
                    if seg is not None and seg["modified"] == checkts:
                        log.debug(
                            "%s: updating count for %s to %s"
                            % (datetime.utcnow().isoformat(), segid, counts[segid])
                        )
                        db.segments.patch(
                            segid,
                            {
                                "count": counts[segid],
                                "last_update": datetime.utcnow().isoformat() + "Z",
                            },
                        )
        except Exception as e:
            log.exception("error")
            db.segments.patch(values[0][0], {"count": "Error: %s" % e})


@tasks.task(priority=HIGH_PRIORITY)
def export_segment(segid: str, exportid: str, path: str) -> None:
    with open_db() as db:
        try:
            segment = db.segments.get(segid)
            if segment is None:
                raise Exception("Segment not found")

            segments: Dict[str, JsonObj | None] = {}
            segment_get_segments(db, segment["parts"], segments)

            campaignids = segment_get_campaignids(segment, list(segments.values()))

            hashlimit, listfactors = segment_get_params(db, segment["cid"], segment)

            gatherid = gather_init(db, "export_segment_block", hashlimit)

            taskparams = []
            for i in range(hashlimit):
                taskparams.append(
                    (
                        export_segment_block,
                        segid,
                        i,
                        listfactors,
                        hashlimit,
                        campaignids,
                        gatherid,
                        exportid,
                        path,
                    )
                )
            run_tasks(taskparams)
        except Exception as e:
            log.exception("error")
            db.exports.patch(exportid, {"error": str(e)})


@tasks.task(priority=LOW_PRIORITY)
def refresh_segment_count(cid: str, values: List[Tuple[str, int]]) -> None:
    with open_db() as db:
        try:
            segmentobjs = []
            for segid, _ in values:
                segment = db.segments.get(segid)
                if segment is None:
                    raise Exception("segment not found")
                segmentobjs.append(segment)

            segments: Dict[str, JsonObj | None] = {}
            campaignids = set()
            for segment in segmentobjs:
                segment_get_segments(db, segment["parts"], segments)

            for segment in segmentobjs:
                campids = segment_get_campaignids(segment, list(segments.values()))
                campaignids.update(campids)

            hashlimit = 0
            listfactors = set()
            for segment in segmentobjs:
                hl, lf = segment_get_params(db, cid, segment)
                hashlimit = max(hashlimit, hl)
                listfactors.update(lf)

            gatherid = gather_init(db, "refresh_segment_block", hashlimit)

            taskparams = []
            for i in range(hashlimit):
                taskparams.append(
                    (
                        refresh_segment_block,
                        cid,
                        values,
                        i,
                        list(listfactors),
                        hashlimit,
                        list(campaignids),
                        gatherid,
                    )
                )
            run_tasks(taskparams)
        except Exception as e:
            log.exception("error")
            db.segments.patch(segid, {"count": "Error: %s" % e})


@tasks.task(priority=LOW_PRIORITY)
def refresh_company_active(cid: str) -> None:
    with open_db() as db:
        try:
            db.set_cid(cid)

            hashlimit = get_hashlimit(db, cid)

            gatherid = gather_init(db, "refresh_company_active", hashlimit)

            n = unix_time_secs(datetime.now())

            for hashval in range(hashlimit):
                run_task(refresh_bucket_active, cid, hashval, hashlimit, gatherid, n)
        except:
            log.exception("error")


@tasks.task(priority=LOW_PRIORITY)
def refresh_company_segments(cid: str, force: bool) -> None:
    with open_db() as db:
        try:
            db.set_cid(cid)

            alllists = db.lists.get_all()

            updatelist = []

            for segment in db.segments.get_all():
                if "last_update" not in segment:
                    continue

                lists = segment_lists(alllists)

                needsupdate = False
                for l in lists:
                    if "last_update" in l and l["last_update"] > segment["last_update"]:
                        needsupdate = True
                        break
                if needsupdate or force:
                    updatelist.append([segment["id"], segment["modified"]])

            if len(updatelist):
                run_task(refresh_segment_count, cid, updatelist)
        except:
            log.exception("error")


def refresh_all_segments(hashval: int, numprocs: int, force: bool) -> None:
    try:
        with open_db() as db:
            for company in list(db.companies.find({"admin": False})):
                if (djb2(company["id"]) % numprocs) != hashval:
                    continue
                parent = db.companies.get(company["cid"])
                if parent is None:
                    continue
                if parent.get("demo", False):
                    continue
                run_task(refresh_company_segments, company["id"], force)
    except:
        log.exception("error")


def rehash_all() -> None:
    with open_db() as db:
        try:
            companies = [company for company in db.companies.find({"admin": False})]
            for company in companies:
                parent = db.companies.get(company["cid"])
                if parent is None:
                    continue
                if parent.get("demo", False):
                    continue
                with db.transaction():
                    contacts.recalculate_hashlimit(db, company["id"])
        except:
            log.exception("error")


def refresh_active_counts() -> None:
    run_task(refresh_active_counts_task)


@tasks.task(priority=LOW_PRIORITY)
def refresh_active_counts_task() -> None:
    with open_db() as db:
        try:
            for company in list(db.companies.find({"admin": False})):
                parent = db.companies.get(company["cid"])
                if parent is None:
                    continue
                if parent.get("demo", False):
                    continue
                run_task(refresh_company_active, company["id"])
        except:
            log.exception("error")


class SegmentDuplicate(object):

    def on_post(self, req: falcon.Request, res: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        s = db.segments.get(id)

        if s is None:
            raise falcon.HTTPForbidden()

        orig, i = get_orig(s["name"])
        while True:
            s["name"] = "%s (%s)" % (orig, i)
            if db.segments.find_one({"name": s["name"]}) is None:
                break
            i += 1

        if not isinstance(s["count"], int):
            s["count"] = "Loading, please wait"

        s["modified"] = datetime.utcnow().isoformat() + "Z"

        req.context["result"] = db.segments.add(s)

        if not isinstance(s["count"], int):
            run_task(
                refresh_segment_count,
                db.get_cid(),
                [[req.context["result"], s["modified"]]],
            )


class RecentTags(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        db = req.context["db"]

        req.context["result"] = [
            tag
            for tag, in db.execute(
                "select tag from alltags where cid = %s order by added desc limit 3000",
                db.get_cid(),
            )
        ]


class ExclusionListAdd(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req, True)

        if id not in ("e", "m", "d"):
            raise falcon.HTTPForbidden()

        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        db = req.context["db"]

        data = doc["data"]

        dataout = []

        for line in data:
            li = line.strip().lower()

            if not li:
                continue

            rh = None
            if id != "d":
                m = emailre.search(li)
                if not m:
                    continue
                li = m.group(0)
                rh = get_contact_id(db, db.get_cid(), li)

            dataout.append(li)

            db.execute(
                "insert into exclusions (cid, item, exclusionid, rawhash) values (%s, %s, %s, %s) on conflict (cid, item, exclusionid) do nothing",
                db.get_cid(),
                li,
                id,
                rh,
            )

        if id == "d":
            contacts.erase_domains(db, db.get_cid(), dataout)
        else:
            contacts.erase(db, db.get_cid(), dataout)

        if id == "e":
            set_onboarding(db, db.get_cid(), "dne", "complete")

        req.context["result"] = {
            "result": "ok",
            "data": dataout,
        }


class AllFields(object):
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        db = req.context["db"]

        r = set(
            fld
            for fld, in db.execute(
                "select distinct jsonb_array_elements_text(coalesce(data->'used_properties', '[]'::jsonb)) from lists where cid = %s",
                db.get_cid(),
            )
            if fld and not fld.startswith("!")
        )

        r.add("Email")
        r.discard("Opened")
        r.discard("Clicked")
        r.discard("Soft Bounced")
        r.discard("Bounced")
        r.discard("Unsubscribed")
        r.discard("Complained")

        req.context["result"] = sorted(r)


class AllTags(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        req.context["result"] = [
            {
                "tag": tag,
                "added": added.isoformat(),
                "count": count,
            }
            for tag, added, count in db.execute(
                "select tag, added, count from alltags where cid = %s and count > 0",
                db.get_cid(),
            )
        ]


class AllTagsRemove(object):

    def on_delete(self, req: falcon.Request, resp: falcon.Response, tag: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        tag = fix_tag(tag)
        if not tag:
            raise falcon.HTTPBadRequest(
                title="Invalid tag", description="Tag parameter is invalid"
            )

        db.execute(
            """delete from alltags where cid = %s and tag = %s""", db.get_cid(), tag
        )

        contacts.remove_tag_all(db, db.get_cid(), tag)


class ExclusionLists(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req, True)

        db = req.context["db"]

        ret = [
            {
                "id": "e",
                "name": "Do Not Email",
                "type": "emails",
            },
            {
                "id": "m",
                "name": "Malicious",
                "type": "emails",
            },
            {
                "id": "d",
                "name": "Domains",
                "type": "domains",
            },
        ]

        for i, cnt in db.execute(
            "select exclusionid, count(item) from exclusions where cid = %s group by exclusionid",
            db.get_cid(),
        ):
            if i == "e":
                ret[0]["count"] = cnt
            elif i == "m":
                ret[1]["count"] = cnt
            elif i == "d":
                ret[2]["count"] = cnt

        req.context["result"] = ret
