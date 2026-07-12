import os
import re
import csv
import shortuuid
import requests
import msgpack
import time
import random
from typing import Dict, Tuple, List, Any, Callable
from io import BytesIO, TextIOWrapper, IOBase
from datetime import datetime
from .block import read_block, list_blocks
from .utils import (
    MPDictReader,
    fix_tag,
    get_funnels,
    insert_funnel,
    insert_funnel_tag,
    incr_funnel_counts,
    run_task,
    gather_init,
    gather_complete,
    emailre,
    md5re,
    open_ticket,
    set_onboarding,
    unix_time_secs,
    SECS_IN_DAY,
    get_txn,
)
from .s3 import s3_delete, s3_read_stream, s3_open_write
from .db import open_db, json_obj, JsonObj, DB
from .tasks import tasks, HIGH_PRIORITY, LOW_PRIORITY
from .segments import (
    get_hashlimit,
    segment_get_campaignids,
    segment_get_params,
    get_segment_sentrows,
    get_segment_rows,
    segment_eval_parts,
    Cache,
)
from .log import get_logger
from .webhooks import send_webhooks

log = get_logger()

WRITE_BLOCK_SIZE = 32 * 1024
HASH_BLOCK_SIZE = 1024 * 1024
# Max hash buckets to prevent runaway rehashing/task fan-out. Can be overridden via env.
HASHLIMIT_CAP = int(os.environ.get("hashlimit_max", "128"))


def load_campaign_or_message(db: DB, campid: str) -> Tuple[JsonObj | None, bool]:
    camp = json_obj(
        db.row(
            "select id, cid, data - 'parts' - 'rawText' from campaigns where id = %s",
            campid,
        )
    )
    if camp is None:
        is_msg = True
        camp = json_obj(
            db.row(
                "select id, cid, data - 'parts' - 'rawText' from messages where id = %s",
                campid,
            )
        )
    else:
        is_msg = False
    return camp, is_msg


def add_send(db: DB, campid: str, emails: List[str], txntag: str | None = None) -> None:
    webhook_msgs = []

    ts = datetime.utcnow().isoformat() + "Z"

    if txntag is not None or len(campid) > 30:
        if txntag is None:
            cid, txntag, _ = get_txn(db, campid)
            if cid is None:
                return
            campid = "tx-%s" % cid
        else:
            cid = campid[3:]  # strip tx- prefix

        for email in emails:
            webhook_msgs.append(
                {
                    "type": "send",
                    "source": {
                        "tag": txntag,
                    },
                    "email": email,
                    "timestamp": ts,
                }
            )
    else:
        camp, is_msg = load_campaign_or_message(db, campid)

        if camp is None:
            return

        cid = camp["cid"]

        assert cid is not None

        funnel = None
        if is_msg:
            funnel = db.funnels.get(camp["funnel"])
            if funnel is not None:
                msgvals = {}
                for mid, who, days, dayoffset in db.execute(
                    "select id, data->>'who', data->'days', data->'dayoffset' from messages where data->>'funnel' = %s",
                    funnel["id"],
                ):
                    msgvals[mid] = (who or "all", days, dayoffset or 0)
                msgs = funnel["messages"]
                for i, m in zip(range(len(msgs)), msgs):
                    if m["id"] not in msgvals:
                        m["who"] = "all"
                        m["days"] = None
                        m["dayoffset"] = 0
                    else:
                        vals = msgvals[m["id"]]
                        m["who"] = vals[0]
                        m["days"] = vals[1]
                        m["dayoffset"] = vals[2]
                    if i == 0:
                        m["who"] = "all"

        contactids = list(
            db.execute(
                f"""select email, contact_id from contacts."contacts_{cid}" where email = any(%s)""",
                emails,
            )
        )

        for email, contact_id in contactids:
            inserted = db.execute(
                f"""
                insert into contacts."contact_send_logs_{cid}" (contact_id, campid) values (%s, %s) on conflict (contact_id, campid) do nothing returning contact_id
            """,
                contact_id,
                camp["id"],
            )

            if inserted:
                msg: JsonObj = {
                    "type": "send",
                    "source": {},
                    "email": email,
                    "timestamp": ts,
                }
                if is_msg:
                    msg["source"]["funnelmsg"] = campid
                else:
                    msg["source"]["broadcast"] = campid
                webhook_msgs.append(msg)

            if (
                inserted
                and funnel is not None
                and funnel.get("active")
                and len(funnel["messages"]) > 0
            ):
                currindex = -1
                for m in funnel["messages"]:
                    currindex += 1
                    if m["id"] == campid:
                        break
                while currindex >= 0 and currindex < len(funnel["messages"]) - 1:
                    if funnel["messages"][currindex + 1].get("unpublished"):
                        currindex += 1
                        continue
                    msg = funnel["messages"][currindex + 1]
                    if msg["who"] in ("all", "openany", "clickany"):
                        insert_funnel(
                            db, funnel["cid"], email, funnel, currindex + 1, None
                        )
                    break

        taglist = list(
            set([fix_tag(tag) for tag in camp.get("sendaddtags", ()) if fix_tag(tag)])
        )
        taglist.extend(
            set(
                [
                    "-" + fix_tag(tag)
                    for tag in camp.get("sendremtags", ())
                    if fix_tag(tag)
                ]
            )
        )

        update_tags(db, cid, emails, taglist, webhook_msgs, contactids)

    if len(webhook_msgs):
        send_webhooks(db, cid, webhook_msgs)


def update_tags(
    db: DB,
    cid: str,
    emails: List[str],
    tags: List[str],
    webhook_msgs: List[JsonObj],
    email_contact_ids: List[Tuple[str, int]] | None = None,
    funnel: str | None = None,
) -> None:
    if email_contact_ids is None:
        email_contact_ids = list(
            db.execute(
                f"""select email, contact_id from contacts."contacts_{cid}" where email = any(%s)""",
                emails,
            )
        )

    add_tags = []
    remove_tags = []
    for tag in tags:
        if tag.startswith("-"):
            remove_tags.append(tag[1:])
        else:
            add_tags.append(tag)

    tagfunnels = None
    respfunnels = None
    funnelcounts: Dict[str, int] = {}
    tagcounts: Dict[str, int] = {}
    if len(add_tags) or funnel is not None:
        tagfunnels, respfunnels = get_funnels(db, cid)

    for email, contact_id in email_contact_ids:
        for tag in add_tags:
            assert tagfunnels is not None
            add_tag(
                db,
                cid,
                email,
                contact_id,
                tag,
                tagfunnels,
                funnelcounts,
                tagcounts,
                webhook_msgs,
            )

        for tag in remove_tags:
            remove_tag(db, cid, email, contact_id, tag, tagcounts, webhook_msgs)

        if funnel is not None:
            assert respfunnels is not None
            fun = respfunnels.get(funnel, None)
            if fun is not None:
                insert_funnel(db, cid, email, fun, 0, funnelcounts)

    incr_funnel_counts(db, funnelcounts)

    for tagname, cnt in tagcounts.items():
        db.execute(
            "update alltags set count = count + %s where cid = %s and tag = %s",
            cnt,
            cid,
            tagname,
        )


def add_tag(
    db: DB,
    cid: str,
    email: str,
    contact_id: int,
    tag: str,
    tagfunnels: Dict[str, List[JsonObj]],
    funnelcounts: Dict[str, int],
    tagcounts: Dict[str, int],
    webhook_msgs: List[JsonObj],
) -> None:
    is_new = db.single(
        f"""insert into contacts."contact_values_{cid}" (contact_id, type, value) values (%s, 'tag', %s)
                           on conflict (contact_id, type, value) do nothing returning contact_id""",
        contact_id,
        tag,
    )

    if is_new:
        tagcounts[tag] = tagcounts.get(tag, 0) + 1

        webhook_msgs.append(
            {
                "type": "tag_add",
                "tag": tag,
                "email": email,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )

        if tagfunnels is not None:
            insert_funnel_tag(db, cid, email, tag, tagfunnels, funnelcounts)


def remove_tag(
    db: DB,
    cid: str,
    email: str,
    contact_id: int,
    tag: str,
    tagcounts: Dict[str, int],
    webhook_msgs: List[JsonObj],
) -> None:
    is_del = db.execute(
        f"""delete from contacts."contact_values_{cid}"
                            where contact_id = %s and type = 'tag' and value = %s""",
        contact_id,
        tag,
    ).rowcount

    if is_del:
        tagcounts[tag] = tagcounts.get(tag, 0) - 1

        webhook_msgs.append(
            {
                "type": "tag_remove",
                "tag": tag,
                "email": email,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )


def erase(db: DB, cid: str, emails: List[str], unsublog: bool = False) -> None:
    with db.transaction():
        listemails = {
            listid: emaillist
            for listid, emaillist in db.execute(
                f"""
            select l.list_id, array_agg(c.email)
            from contacts."contact_lists_{cid}" l
            join contacts."contacts_{cid}" c on c.contact_id = l.contact_id
            where c.email = any(%s)
            group by l.list_id
        """,
                emails,
            )
        }

        emailstats = {
            email: (bounced, unsubscribed, complained, soft_bounced)
            for email, bounced, unsubscribed, complained, soft_bounced in db.execute(
                f"""
            select email, coalesce((nullif(props->'Bounced'->>0, ''))::bool, false), coalesce((nullif(props->'Unsubscribed'->>0, ''))::bool, false), coalesce((nullif(props->'Complained'->>0, ''))::bool, false), coalesce((nullif(props->'Soft Bounced'->>0, ''))::bool, false)
            from contacts."contacts_{cid}"
            where email = any(%s)
        """,
                emails,
            )
        }

        tc = {
            tag: cnt
            for tag, cnt in db.execute(
                f"""
            select value, count(*)
            from contacts."contact_values_{cid}" v
            join contacts."contacts_{cid}" c on v.contact_id = c.contact_id
            where type = 'tag' and c.email = any(%s)
            group by value""",
                emails,
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

        for listid, emaillist in listemails.items():
            domaincounts: Dict[str, int] = {}
            bounced = 0
            unsubscribed = 0
            complained = 0
            soft_bounced = 0
            for email in emaillist:
                domain = email.split("@")[1]
                domaincounts[domain] = domaincounts.get(domain, 0) + 1

                b, u, c, s = emailstats.get(email, (0, 0, 0, 0))
                if b:
                    bounced += 1
                if u:
                    unsubscribed += 1
                if c:
                    complained += 1
                if s:
                    soft_bounced += 1

            for domain, count in domaincounts.items():
                db.execute(
                    """
                    update list_domains set count = count - %s where domain = %s and list_id = %s
                """,
                    count,
                    domain,
                    listid,
                )

            db.execute(
                """
                delete from list_domains where list_id = %s and count <= 0
            """,
                listid,
            )

            patch_list(
                db,
                listid,
                -len(emaillist),
                -bounced,
                -unsubscribed,
                -complained,
                -soft_bounced,
            )

        db.execute(
            f"""delete from contacts."contacts_{cid}" where email = any(%s)""", emails
        )

        if unsublog:
            db.execute(
                "delete from unsublogs where cid = %s and email = any(%s)",
                cid,
                emails,
            )


def clear_unsublogs(db: DB, cid: str, emails: List[str]) -> None:
    if not emails:
        return

    db.execute(
        "delete from unsublogs where cid = %s and email = any(%s)",
        cid,
        emails,
    )


def overwrite_props(db: DB, cid: str, email: str, props: JsonObj) -> None:
    fixedprops = {}
    for k, v in props.items():
        if valid_prop(k):
            fixedprops[k] = [v]

    db.execute(
        f"""update contacts."contacts_{cid}" set props = %s where email = %s""",
        fixedprops,
        email,
    )

    listids = [
        listid
        for listid, in db.execute(
            f"""
        select distinct l.list_id
        from contacts."contact_lists_{cid}" l
        join contacts."contacts_{cid}" c on l.contact_id = c.contact_id
        where c.email = %s
    """,
            email,
        )
    ]

    for listid in listids:
        patch_list(db, listid, 0, 0, 0, 0, 0, list(fixedprops.keys()))


def feed(
    db: DB,
    listid: str,
    data: JsonObj,
    tags: List[str],
    funnel: str | None = None,
    override: bool = False,
    unsubscribe: bool = False,
) -> None:
    lst = db.lists.get(listid)
    if lst is None or lst.get("unapproved", False):
        return

    cid = lst["cid"]
    email = data["Email"]
    domain = email.split("@")[1]

    if db.single(
        "select true from exclusions where cid = %s and item in (%s, %s)",
        cid,
        email,
        domain,
    ):
        return

    d = {}
    for k, v in data.items():
        if (
            k.strip()
            and not k.startswith("!")
            and k
            not in ("Email", "Bounced", "Unsubscribed", "Complained", "Soft Bounced")
        ):
            d[k] = [v]

    bounced = False
    unsubscribed = False
    complained = False
    soft_bounced = False
    existing = db.row(
        f"""select coalesce((nullif(props->'Bounced'->>0, ''))::bool, false), coalesce((nullif(props->'Unsubscribed'->>0, ''))::bool, false), coalesce((nullif(props->'Complained'->>0, ''))::bool, false), coalesce((nullif(props->'Soft Bounced'->>0, ''))::bool, false)
                          from contacts."contacts_{cid}"
                          where email = %s""",
        email,
    )
    if existing is not None:
        bounced, unsubscribed, complained, soft_bounced = existing
    else:
        # check unsublog to see if we are re-adding a previously unsubbed contact
        existing = db.row(
            "select unsubscribed, bounced, complained, false from unsublogs where cid = %s and email = %s and (unsubscribed or complained or bounced)",
            cid,
            email,
        )
        if existing is not None:
            bounced, unsubscribed, complained, soft_bounced = existing
            if bounced:
                d["Bounced"] = ["true"]
            if unsubscribed:
                d["Unsubscribed"] = ["true"]
            if complained:
                d["Complained"] = ["true"]

    if override:
        if unsubscribed:
            d["Unsubscribed"] = [""]
        if bounced:
            d["Bounced"] = [""]
        if complained:
            d["Complained"] = [""]
        if soft_bounced:
            d["Soft Bounced"] = [""]
    elif unsubscribe and not unsubscribed:
        d["Unsubscribed"] = ["true"]

    webhook_msgs: List[JsonObj] = []

    contact_id = db.single(
        f"""
                           insert into contacts."contacts_{cid}" (email, added, props)
                           values (%s, %s, %s)
                           on conflict (email) do update set props = contacts."contacts_{cid}".props || excluded.props
                           returning contact_id
                           """,
        email,
        unix_time_secs(datetime.now()),
        d,
    )

    is_new = db.single(
        f"""
                            insert into contacts."contact_lists_{cid}" (contact_id, list_id)
                            values (%s, %s)
                            on conflict do nothing
                            returning list_id
                            """,
        contact_id,
        listid,
    )

    update_tags(db, cid, [email], tags, webhook_msgs, [(email, contact_id)], funnel)

    ob, ou, oc, os = 0, 0, 0, 0
    if is_new:
        webhook_msgs.append(
            {
                "type": "list_add",
                "list": listid,
                "email": email,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )
        db.execute(
            """
            insert into list_domains (list_id, domain, count) values (%s, %s, %s)
            on conflict (list_id, domain) do update set count = list_domains.count + excluded.count""",
            listid,
            domain,
            1,
        )

        count = 1
        b = 1 if bounced else 0
        u = 1 if unsubscribed else 0
        c = 1 if complained else 0
        s = 1 if soft_bounced else 0
        if override:
            b, u, c, s = 0, 0, 0, 0
        elif unsubscribe:
            u = 1
    else:
        count, b, u, c, s = 0, 0, 0, 0, 0
        if override:
            if bounced:
                b = -1
            if unsubscribed:
                u = -1
            if complained:
                c = -1
            if soft_bounced:
                s = -1
        elif unsubscribe and not unsubscribed:
            u = 1

    if override:
        if bounced:
            ob = -1
        if unsubscribed:
            ou = -1
        if complained:
            oc = -1
        if soft_bounced:
            os = -1
    elif unsubscribe and not unsubscribed:
        ou = 1

    patch_list(db, listid, count, b, u, c, s, list(d.keys()))

    otherlists = [
        listid
        for listid, in db.execute(
            f"""
        select distinct l.list_id
        from contacts."contact_lists_{cid}" l
        where l.contact_id = %s and l.list_id != %s
    """,
            contact_id,
            listid,
        )
    ]

    for otherlist in otherlists:
        patch_list(db, otherlist, 0, ob, ou, oc, os, list(d.keys()))

    if override:
        clear_unsublogs(db, cid, [email])
    elif unsubscribe:
        db.execute(
            """insert into unsublogs (cid, email, rawhash, unsubscribed, complained, bounced) values (%s, %s, %s, true, false, false)
                          on conflict (cid, email) do update set
                          unsubscribed = true""",
            cid,
            email,
            contact_id,
        )

    if len(webhook_msgs):
        send_webhooks(db, cid, webhook_msgs)


cmdprops = {
    "bounce": ("Bounced", True),
    "complaint": ("Complained", True),
    "unsub": ("Unsubscribed", True),
    "soft": ("Soft Bounced", True),
    "open": ("Opened", False),
    "click": ("Clicked", False),
}

clientprops = ["device", "os", "browser", "country", "region", "zip"]


class ChangeEntry(object):

    def __init__(self, j: JsonObj) -> None:
        self.email, self.cmd = j["email"], j["cmd"]
        self.campid = ""
        self.logprop = ""
        for cp in clientprops:
            setattr(self, cp, None)

        self.updatedts: int | None = 0
        self.linkindex = -1

        self.campid = j["campid"]
        self.prop, nolog = cmdprops[self.cmd]
        if not nolog:
            self.logprop = self.cmd
        for cp in clientprops:
            setattr(self, cp, j.get(cp))

        if "updatedts" in j:
            self.updatedts = j["updatedts"]
            self.linkindex = j["linkindex"]


def update(db: DB, cid: str, upd: JsonObj) -> None:
    fn = ChangeEntry(upd)

    contact_id = db.single(
        f"""select contact_id, props from contacts."contacts_{cid}" where email = %s""",
        fn.email,
    )
    if contact_id is None:
        return

    active30 = 0
    active60 = 0
    active90 = 0
    counts = {
        "bounced": 0,
        "complained": 0,
        "unsubscribed": 0,
        "soft_bounced": 0,
    }

    # set Clicked / Opened etc. properties to true
    written = db.single(
        f"""update contacts."contacts_{cid}" set props = contacts."contacts_{cid}".props || %s
                            where contact_id = %s and (props->>%s is null or (props->%s in (
                                '[""]'::jsonb, '["false"]'::jsonb, '["f"]'::jsonb, '["n"]'::jsonb, '["no"]'::jsonb
                            ))) returning contact_id""",
        {fn.prop: ["true"]},
        contact_id,
        fn.prop,
        fn.prop,
    )

    count_prop = fn.prop.lower().replace(" ", "_")
    if written and count_prop in counts:
        counts[count_prop] = 1

    # add browser, device etc
    for clientname in clientprops:
        nc = getattr(fn, clientname)
        if nc:
            db.execute(
                f"""insert into contacts."contact_values_{cid}" (contact_id, type, value) values (%s, %s, %s)
                           on conflict (contact_id, type, value) do nothing
                       """,
                contact_id,
                clientname,
                nc,
            )

    # add open or click log
    changed = False
    if fn.logprop and fn.campid:
        oldactive = db.single(
            f"""
                                select max(ts) from (
                                    select ts from contacts."contact_open_logs_{cid}"
                                    where contact_id = %s
                                    union all
                                    select ts from contacts."contact_click_logs_{cid}"
                                    where contact_id = %s
                                ) s
                                """,
            contact_id,
            contact_id,
        )

        n = unix_time_secs(datetime.now())
        if oldactive is not None:
            days = (n - oldactive) / SECS_IN_DAY
            if days > 30:
                active30 = 1
            if days > 60:
                active60 = 1
            if days > 90:
                active90 = 1
        else:
            active30 = 1
            active60 = 1
            active90 = 1

        if fn.logprop == "open":
            changed = bool(
                db.execute(
                    f"""
                        insert into contacts."contact_open_logs_{cid}" (contact_id, campid, ts) values (%s, %s, %s)
                        on conflict (contact_id, campid) do nothing
                       """,
                    contact_id,
                    fn.campid,
                    n,
                ).rowcount
            )
        else:
            updatedts = fn.updatedts
            if updatedts is None:
                updatedts = 0
            changed = bool(
                db.execute(
                    f"""
                        insert into contacts."contact_click_logs_{cid}" (contact_id, campid, linkindex, updatedts, ts) values (%s, %s, %s, %s, %s)
                        on conflict (contact_id, campid, linkindex, updatedts) do nothing
                       """,
                    contact_id,
                    fn.campid,
                    fn.linkindex,
                    updatedts,
                    n,
                ).rowcount
            )

    if changed and fn.prop in ("Opened", "Clicked"):
        funnelcounts: Dict[str, int] = {}
        _, respfunnels = get_funnels(db, cid)
        is_msg = False
        fid = db.single(
            "select data->>'funnel' from campaigns where id = %s", fn.campid
        )
        if not fid:
            fid = db.single(
                "select data->>'funnel' from messages where id = %s", fn.campid
            )
            is_msg = True
        if fid is not None:
            fun = respfunnels.get(fid, None)
            if fun is not None:
                if is_msg:
                    currindex = None
                    ind = 0
                    for m in fun["messages"]:
                        if m["id"] == fn.campid:
                            currindex = ind
                            break
                        ind += 1
                    if currindex is not None and currindex < len(fun["messages"]) - 1:
                        who = fun["messages"][currindex + 1]["who"]
                        if (
                            who == "clicklast" and fn.prop == "Clicked"
                        ) or who == "openlast":
                            insert_funnel(db, cid, fn.email, fun, currindex + 1, None)
                else:
                    insert_funnel(db, cid, fn.email, fun, 0, funnelcounts)

        incr_funnel_counts(db, funnelcounts)

    patch = {
        "last_update": datetime.utcnow().isoformat() + "Z",
        "count_dirty": True,
    }

    listids = [
        id
        for id, in db.execute(
            f"""
            select l.list_id
            from contacts."contact_lists_{cid}" l
            join contacts."contacts_{cid}" c on c.contact_id = l.contact_id
            where c.email = %s""",
            fn.email,
        )
    ]

    for listid in listids:
        db.execute(
            """
            update lists set data = data || %s || jsonb_build_object(
                'used_properties', (select '["Email"]' || (jsonb_agg(distinct p) - 'Email')
                                    from jsonb_array_elements(coalesce(data->'used_properties', '[]'::jsonb) || array_to_json(%s)::jsonb) as p),
                'active30', coalesce((data->'active30')::int, 0) + %s,
                'active60', coalesce((data->'active60')::int, 0) + %s,
                'active90', coalesce((data->'active90')::int, 0) + %s,
                'bounced', coalesce((data->'bounced')::int, 0) + %s,
                'complained', coalesce((data->'complained')::int, 0) + %s,
                'unsubscribed', coalesce((data->'unsubscribed')::int, 0) + %s,
                'soft_bounced', coalesce((data->'soft_bounced')::int, 0) + %s
            )
            where id = %s""",
            patch,
            [fn.prop],
            active30,
            active60,
            active90,
            counts["bounced"],
            counts["complained"],
            counts["unsubscribed"],
            counts["soft_bounced"],
            listid,
        )


@tasks.task(priority=HIGH_PRIORITY)
def erase_domains_bucket(
    cid: str, hashval: int, hashlimit: int, domains: List[str], tmpid: str
) -> None:
    with open_db() as db:
        try:
            domain_or_expr = " or ".join(
                ["c.email like ('%%@' || %s)" for _ in domains]
            )
            domain_params = [domain.lower() for domain in domains]

            listids = [
                listid
                for listid, in db.execute(
                    f"""
                select distinct l.list_id
                from contacts."contact_lists_{cid}" l
                join contacts."contacts_{cid}" c on l.contact_id = c.contact_id
                where ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                and (
                    {domain_or_expr}
                )
            """,
                    hashval,
                    *domain_params,
                )
            ]

            liststats = {}
            for listid, bounced, unsubscribed, complained, soft_bounced in db.execute(
                f"""
                select l.list_id,
                       count(c.contact_id) filter (where coalesce((nullif(props->'Bounced'->>0, ''))::bool, false)),
                       count(c.contact_id) filter (where coalesce((nullif(props->'Unsubscribed'->>0, ''))::bool, false)),
                       count(c.contact_id) filter (where coalesce((nullif(props->'Complained'->>0, ''))::bool, false)),
                       count(c.contact_id) filter (where coalesce((nullif(props->'Soft Bounced'->>0, ''))::bool, false))
                from contacts."contact_lists_{cid}" l
                join contacts."contacts_{cid}" c on l.contact_id = c.contact_id
                where ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                and (
                    {domain_or_expr}
                )
                group by l.list_id
            """,
                hashval,
                *domain_params,
            ):
                liststats[listid] = (bounced, unsubscribed, complained, soft_bounced)

            tc = {
                tag: cnt
                for tag, cnt in db.execute(
                    f"""
                select value, count(*)
                from contacts."contact_values_{cid}" v
                join contacts."contacts_{cid}" c on v.contact_id = c.contact_id
                where type = 'tag' and (({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s))
                and (
                    {domain_or_expr}
                )
                group by value""",
                    hashval,
                    *domain_params,
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
                and (
                    {domain_or_expr}
                )
            """,
                hashval,
                *domain_params,
            )

            bucketinfo = gather_complete(
                db, tmpid, {"listids": listids, "liststats": liststats}
            )
            if bucketinfo is not None:
                listidset = set()
                allliststats = {}
                for info in bucketinfo:
                    listidset.update(info["listids"])
                    for listid, stats in info["liststats"].items():
                        if listid not in allliststats:
                            allliststats[listid] = [0, 0, 0, 0]
                        for i in range(4):
                            allliststats[listid][i] += stats[i]

                listids = list(listidset)

                listidcounts = {
                    listid: count
                    for listid, count in db.execute(
                        """
                        select list_id, sum(count) from list_domains
                        where list_id = any(%s) and domain = any(%s)
                        group by list_id
                    """,
                        listids,
                        domain_params,
                    )
                }

                db.execute(
                    """
                    delete from list_domains where domain = any(%s) and list_id = any(%s)
                """,
                    domain_params,
                    listids,
                )
                for listid, count in listidcounts.items():
                    stats = allliststats.get(listid, [0, 0, 0, 0])
                    b, u, c, s = stats
                    patch_list(db, listid, -count, -b, -u, -c, -s)
        except:
            log.exception("error")


def patch_list(
    db: DB,
    listid: str,
    count: int,
    bounced: int,
    unsubscribed: int,
    complained: int,
    soft_bounced: int,
    properties: List[str] | None = None,
) -> None:
    patch = {
        "last_update": datetime.utcnow().isoformat() + "Z",
        "count_dirty": True,
    }

    db.execute(
        """update lists set data = data
            || jsonb_build_object('used_properties',
                                    case when jsonb_array_length(coalesce(data->'used_properties', '[]'::jsonb)) = 0 and %s = 0 then
                                        '["Email"]'::jsonb
                                    else
                                        (select '["Email"]'::jsonb || (jsonb_agg(distinct p) - 'Email')
                                        from jsonb_array_elements(coalesce(data->'used_properties', '[]'::jsonb) || array_to_json(%s::text[])::jsonb) as p)
                                    end,
                                  'count', coalesce((data->>'count')::int, 0) + %s::int,
                                  'bounced', coalesce((data->>'bounced')::int, 0) + %s::int,
                                  'unsubscribed', coalesce((data->>'unsubscribed')::int, 0) + %s::int,
                                  'complained', coalesce((data->>'complained')::int, 0) + %s::int,
                                  'soft_bounced', coalesce((data->>'soft_bounced')::int, 0) + %s::int,
                                  'domaincount', (
                                    select count(domain) from list_domains where list_id = lists.id
                                  ))
            || %s
            where id = %s""",
        len(properties or []),
        properties or [],
        count,
        bounced,
        unsubscribed,
        complained,
        soft_bounced,
        patch,
        listid,
    )


def erase_domains(db: DB, cid: str, domains: List[str]) -> None:
    hashlimit = get_hashlimit(db, cid)

    tmpid = gather_init(db, "erase_domains", hashlimit)

    for hashval in range(hashlimit):
        run_task(erase_domains_bucket, cid, hashval, hashlimit, domains, tmpid)


def remove_list_contacts(db: DB, cid: str, listid: str, emails: List[str]) -> int:
    with db.transaction():
        domaincounts = {}
        total = 0
        for domain, count in db.execute(
            f"""
            select split_part(c.email, '@', 2) as domain, count(c.contact_id) as count
            from contacts."contacts_{cid}" c
            join contacts."contact_lists_{cid}" l on c.contact_id = l.contact_id
            where l.list_id = %s
            and c.email = any(%s)
            group by split_part(c.email, '@', 2)
        """,
            listid,
            emails,
        ):
            domaincounts[domain] = count
            total += count

        bounced, unsubscribed, complained, soft_bounced = db.row_or_error(
            f"""
            select count(c.contact_id) filter(where coalesce((nullif(props->'Bounced'->>0, ''))::bool, false)),
                   count(c.contact_id) filter(where coalesce((nullif(props->'Unsubscribed'->>0, ''))::bool, false)),
                   count(c.contact_id) filter(where coalesce((nullif(props->'Complained'->>0, ''))::bool, false)),
                   count(c.contact_id) filter(where coalesce((nullif(props->'Soft Bounced'->>0, ''))::bool, false))
            from contacts."contact_lists_{cid}" l
            join contacts."contacts_{cid}" c on l.contact_id = c.contact_id
            where l.list_id = %s
            and c.email = any(%s)
        """,
            listid,
            emails,
        )

        ret = db.execute(
            f"""
            delete from contacts."contact_lists_{cid}" l
            using contacts."contacts_{cid}" c
            where l.contact_id = c.contact_id
            and l.list_id = %s
            and c.email = any(%s)
        """,
            listid,
            emails,
        ).rowcount

        tc = {
            tag: cnt
            for tag, cnt in db.execute(
                f"""
            select value, count(*)
            from contacts."contact_values_{cid}" v
            join contacts."contacts_{cid}" c on v.contact_id = c.contact_id
            where type = 'tag' and c.email = any(%s)
            and not exists (
                select true
                from contacts."contact_lists_{cid}" l
                where l.contact_id = c.contact_id
            )
            and not exists (
                select true
                from contacts."contact_supplists_{cid}" l
                where l.contact_id = c.contact_id
            )
            group by value""",
                emails,
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
            where c.email = any(%s)
            and not exists (
                select true
                from contacts."contact_lists_{cid}" l
                where l.contact_id = c.contact_id
            )
            and not exists (
                select true
                from contacts."contact_supplists_{cid}" l
                where l.contact_id = c.contact_id
            )
        """,
            emails,
        )

        for domain, count in domaincounts.items():
            db.execute(
                """
                update list_domains set count = count - %s where domain = %s and list_id = %s
            """,
                count,
                domain,
                listid,
            )

        db.execute(
            """
            delete from list_domains where list_id = %s and count <= 0
        """,
            listid,
        )

        patch_list(
            db, listid, -ret, -bounced, -unsubscribed, -complained, -soft_bounced
        )

        return ret


@tasks.task(priority=HIGH_PRIORITY)
def remove_list_domains_bucket(
    cid: str, hashval: int, hashlimit: int, listid: str, domains: List[str], tmpid: str
) -> None:
    with open_db() as db:
        try:
            domain_or_expr = " or ".join(
                ["c.email like ('%%@' || %s)" for _ in domains]
            )
            domain_params = [domain.lower() for domain in domains]

            bounced, unsubscribed, complained, soft_bounced = db.row_or_error(
                f"""
                select count(c.contact_id) filter (where coalesce((nullif(props->'Bounced'->>0, ''))::bool, false)),
                       count(c.contact_id) filter (where coalesce((nullif(props->'Unsubscribed'->>0, ''))::bool, false)),
                       count(c.contact_id) filter (where coalesce((nullif(props->'Complained'->>0, ''))::bool, false)),
                       count(c.contact_id) filter (where coalesce((nullif(props->'Soft Bounced'->>0, ''))::bool, false))
                from contacts."contact_lists_{cid}" l
                join contacts."contacts_{cid}" c on l.contact_id = c.contact_id
                where ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                and c.contact_id = l.contact_id
                and l.list_id = %s
                and (
                    {domain_or_expr}
                )
            """,
                hashval,
                hashval,
                listid,
                *domain_params,
            )

            db.execute(
                f"""
                delete from contacts."contact_lists_{cid}" l
                using contacts."contacts_{cid}" c
                where ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                and ({hashlimit} = 1 or mod(l.contact_id, {hashlimit}) = %s)
                and c.contact_id = l.contact_id
                and l.list_id = %s
                and (
                    {domain_or_expr}
                )
                    """,
                hashval,
                hashval,
                listid,
                *domain_params,
            )

            tc = {
                tag: cnt
                for tag, cnt in db.execute(
                    f"""
                select value, count(*)
                from contacts."contact_values_{cid}" v
                join contacts."contacts_{cid}" c on v.contact_id = c.contact_id
                where type = 'tag' and (({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s))
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

            bucketinfo = gather_complete(
                db, tmpid, {"stats": [bounced, unsubscribed, complained, soft_bounced]}
            )
            if bucketinfo is not None:
                sums = [0, 0, 0, 0]
                for info in bucketinfo:
                    for i in range(4):
                        sums[i] += info["stats"][i]
                b, u, c, s = sums
                cnt = db.single(
                    "select sum(count) from list_domains where list_id = %s and domain = any(%s)",
                    listid,
                    domain_params,
                )
                db.execute(
                    "delete from list_domains where list_id = %s and domain = any(%s)",
                    listid,
                    domain_params,
                )
                patch_list(db, listid, -cnt, -b, -u, -c, -s)
        except:
            log.exception("error")


def remove_list_domains(db: DB, cid: str, lst: JsonObj, domains: List[str]) -> None:
    hashlimit = get_hashlimit(db, cid, [lst])

    tmpid = gather_init(db, "remove_list_domains", hashlimit)

    for hashval in range(hashlimit):
        run_task(
            remove_list_domains_bucket,
            cid,
            hashval,
            hashlimit,
            lst["id"],
            domains,
            tmpid,
        )


def valid_prop(c: str) -> bool:
    return bool(c.strip() and ("!" not in c) and ("," not in c))


@tasks.task(priority=HIGH_PRIORITY)
def open_list_ticket(listid: str) -> None:
    try:
        with open_db() as db:
            lst = db.lists.get(listid)
            if lst is None:
                raise Exception("List not found to open list ticket for")

            user = json_obj(
                db.row("select id, cid, data from users where cid = %s", lst["cid"])
            )
            if user is None:
                raise Exception("User not found to open list ticket for")

            ticketid = open_ticket(
                "List Data Review",
                "Your list data has been received and is being reviewed for deliverability.\n\nYou can reply to this message with any questions or information which might influence our decision (where your contacts came from, how recently they've received a message from you, your list hygiene practices, etc.).\n\nOtherwise, you will receive an update when the review proccess is complete. Thank you for your patience.",
                user,
            )

            db.lists.patch(listid, {"approval_ticket": ticketid})

            if not lst.get("example"):
                set_onboarding(db, lst["cid"], "contacts", "complete")
    except:
        log.exception("error")


@tasks.task(priority=HIGH_PRIORITY)
def validate_list(listid: str) -> None:
    try:
        with open_db() as db:
            if os.environ["mg_validate_key"]:
                f = "/tmp/export-%s.csv" % shortuuid.uuid()
                fp = open(f, "w")
                fp.write("email\n")

                l = db.lists.get(listid)
                if l is None:
                    raise Exception("List not found")

                if l["count"] > 12000:
                    db.lists.patch(listid, {"validation": {"status": "skipped"}})
                    log.info(
                        '[NOTIFY] The list "%s" will not be sent to the validation API because it is too large (%s records).',
                        l["name"],
                        l["count"],
                    )
                    return

                for (email,) in db.execute(
                    f"""
                                        select c.email
                                        from contacts.contacts_{l['cid']} c
                                        join contacts.contact_lists_{l['cid']} l on l.contact_id = c.contact_id
                                        where l.list_id = %s""",
                    listid,
                ):
                    fp.write("%s\n" % email)
                fp.close()

                uuid = shortuuid.uuid()

                r = requests.post(
                    "https://api.mailgun.net/v4/address/validate/bulk/%s-%s"
                    % (listid, uuid),
                    auth=("api", os.environ["mg_validate_key"]),
                    files={
                        "file": open(f, "rb"),
                    },
                )
                os.unlink(f)

                if r.status_code >= 400:
                    raise Exception(r.text)

                db.lists.patch(
                    listid, {"validation": {"status": "pending", "uuid": uuid}}
                )
            else:
                p = {
                    "status": "error",
                    "message": "To enable auto list validation, configure the mg_validate_key setting",
                }
                db.lists.patch(listid, {"validation": p})
    except Exception as e:
        log.exception("error")
        db.lists.patch(listid, {"validation": {"status": "error", "message": str(e)}})


def retry_deadlock(
    name: str, func: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    retries = 0
    while True:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            log.exception("Deadlock in %s", name)
            if "deadlock detected" in str(e) and retries < 100:
                log.info("Retrying %s due to deadlock", name)
                retries += 1
                # sleep for a random amount of time between 0 and .5 seconds
                time.sleep(random.random() / 2)
            else:
                raise


def write_rows(
    db: DB, cid: str, listid: str, key: str, keytype: str, override: bool, unsub: bool
) -> Tuple[int, Dict[str, int], Tuple[int, int, int, int]]:
    count = 0
    domaincounts: Dict[str, int] = {}
    values_query = []
    values = []
    webhook_msgs = []
    emails = []
    override_emails = []
    unsublogs = {}
    if keytype == "list":
        list_table = f'contacts."contact_lists_{cid}"'
        list_column = "list_id"
        webhook_count = db.single(
            "select count(id) from resthooks where cid = %s and data->>'event' = 'list_add'",
            cid,
        )
    else:
        list_table = f'contacts."contact_supplists_{cid}"'
        list_column = "supplist_id"
        webhook_count = 0
    with db.transaction():
        with s3_read_stream(os.environ["s3_transferbucket"], key) as fp:
            lines = [
                (email, props)
                for email, props in msgpack.Unpacker(fp, strict_map_key=False)
            ]
            if keytype == "list":
                for email, bounced, unsubscribed, complained in db.execute(
                    """
                    select email, bounced, unsubscribed, complained
                    from unsublogs
                    where cid = %s and email = any(%s)
                """,
                    cid,
                    [email for email, _ in lines],
                ):
                    unsublogs[email] = (bounced, unsubscribed, complained)
            for email, props in lines:
                if override:
                    override_emails.append(email)
                    props["Bounced"] = [""]
                    props["Unsubscribed"] = [""]
                    props["Complained"] = [""]
                elif email in unsublogs:
                    bounced, unsubscribed, complained = unsublogs[email]
                    if bounced:
                        props["Bounced"] = ["true"]
                    if unsubscribed:
                        props["Unsubscribed"] = ["true"]
                    if complained:
                        props["Complained"] = ["true"]
                if keytype == "list":
                    emails.append(email)
                values_query.append("(%s, %s, %s)")
                values.append(email)
                values.append(unix_time_secs(datetime.now()))
                values.append(props)
            values.append(listid)

            if override:
                stats: Tuple[int, int, int, int] = db.row_or_error(
                    f"""
                    select -count(distinct c.contact_id) filter (where coalesce((nullif(props->'Bounced'->>0, ''))::bool, false)),
                           -count(distinct c.contact_id) filter (where coalesce((nullif(props->'Unsubscribed'->>0, ''))::bool, false)),
                           -count(distinct c.contact_id) filter (where coalesce((nullif(props->'Complained'->>0, ''))::bool, false)),
                           0
                    from contacts."contacts_{cid}" c
                    join {list_table} l on l.contact_id = c.contact_id and l.{list_column} = %s
                    where c.email = any(%s)
                """,
                    listid,
                    emails,
                )
            elif unsub:
                stats = db.row_or_error(
                    f"""
                    select sum(bounced), sum(unsubscribed), sum(complained), sum(soft_bounced)
                    from (
                        select count(distinct c.contact_id) filter (where coalesce((nullif(props->'Bounced'->>0, ''))::bool, false)) as bounced,
                               count(distinct c.contact_id) as unsubscribed,
                               count(distinct c.contact_id) filter (where coalesce((nullif(props->'Complained'->>0, ''))::bool, false)) as complained,
                               count(distinct c.contact_id) filter (where coalesce((nullif(props->'Soft Bounced'->>0, ''))::bool, false)) as soft_bounced
                        from contacts."contacts_{cid}" c
                        left join {list_table} l on l.contact_id = c.contact_id
                        where email = any(%s)
                        and (l.contact_id is null or l.{list_column} != %s)
                        union all
                        select count(email) filter (where bounced) as bounced,
                               0 as unsubscribed,
                               count(email) filter (where complained) as complained,
                               0 as soft_bounced
                        from unsublogs
                        where cid = %s and email = any(%s)
                    ) s
                """,
                    emails,
                    listid,
                    cid,
                    emails,
                )

                existunsubs = db.single(
                    f"""
                    select count(c.contact_id)
                    from contacts."contacts_{cid}" c
                    join {list_table} l on l.contact_id = c.contact_id and l.{list_column} = %s
                    where email = any(%s)
                """,
                    listid,
                    emails,
                )
                stats = (stats[0], stats[1] + existunsubs, stats[2], stats[3])
            else:
                stats = db.row_or_error(
                    f"""
                    select sum(bounced), sum(unsubscribed), sum(complained), sum(soft_bounced)
                    from (
                        select count(distinct c.contact_id) filter (where coalesce((nullif(props->'Bounced'->>0, ''))::bool, false)) as bounced,
                               count(distinct c.contact_id) filter (where coalesce((nullif(props->'Unsubscribed'->>0, ''))::bool, false)) as unsubscribed,
                               count(distinct c.contact_id) filter (where coalesce((nullif(props->'Complained'->>0, ''))::bool, false)) as complained,
                               count(distinct c.contact_id) filter (where coalesce((nullif(props->'Soft Bounced'->>0, ''))::bool, false)) as soft_bounced
                        from contacts."contacts_{cid}" c
                        left join {list_table} l on l.contact_id = c.contact_id
                        where email = any(%s)
                        and (l.{list_column} is null or l.{list_column} != %s)
                        union all
                        select count(email) filter (where bounced) as bounced,
                               count(email) filter (where unsubscribed) as unsubscribed,
                               count(email) filter (where complained) as complained,
                               0 as soft_bounced
                        from unsublogs
                        where cid = %s and email = any(%s)
                    ) s
                """,
                    emails,
                    listid,
                    cid,
                    emails,
                )

            if webhook_count > 0:
                for (email,) in db.execute(
                    f"""
                    with c as (
                        insert into contacts."contacts_{cid}" (email, added, props) values
                        {", ".join(values_query)}
                        on conflict (email) do update set props = contacts."contacts_{cid}".props || excluded.props
                        returning contact_id, email
                    ), l as (
                        insert into {list_table} (contact_id, {list_column})
                        select c.contact_id, %s
                        from c
                        on conflict (contact_id, {list_column}) do nothing
                        returning contact_id
                    )
                    select c.email
                    from c
                    join l on c.contact_id = l.contact_id
                """,
                    *values,
                ):
                    count += 1
                    domain = email.split("@")[1]
                    domaincounts[domain] = domaincounts.get(domain, 0) + 1

                    webhook_msgs.append(
                        {
                            "type": "list_add",
                            "list": listid,
                            "email": email,
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                        }
                    )
            else:
                for domain, domaincount in db.execute(
                    f"""
                    with c as (
                        insert into contacts."contacts_{cid}" (email, added, props) values
                        {", ".join(values_query)}
                        on conflict (email) do update set props = contacts."contacts_{cid}".props || excluded.props
                        returning contact_id, email
                    ), l as (
                        insert into {list_table} (contact_id, {list_column})
                        select c.contact_id, %s
                        from c
                        on conflict (contact_id, {list_column}) do nothing
                        returning contact_id
                    )
                    select split_part(c.email, '@', 2) as domain, count(c.contact_id) as count
                    from c
                    join l on c.contact_id = l.contact_id
                    group by split_part(c.email, '@', 2)
                """,
                    *values,
                ):
                    count += domaincount
                    domaincounts[domain] = domaincount

            if len(override_emails):
                clear_unsublogs(db, cid, override_emails)

    if len(webhook_msgs):
        send_webhooks(db, cid, webhook_msgs)

    return count, domaincounts, stats


@tasks.task(priority=LOW_PRIORITY)
def write_block(
    cid: str,
    key: str,
    tmpid: str,
    listid: str,
    keytype: str,
    used: List[str],
    skipvalidation: bool,
    override: bool,
    unsub: bool,
) -> None:
    with open_db() as db:
        try:
            count, domaincounts, stats = retry_deadlock(
                "write_rows",
                write_rows,
                db,
                cid,
                listid,
                key,
                keytype,
                override,
                unsub,
            )

            s3_delete(os.environ["s3_transferbucket"], key)

            bucketinfo = gather_complete(
                db,
                tmpid,
                {"count": count, "domaincounts": domaincounts, "stats": stats},
            )
            if bucketinfo is not None:
                count = 0
                domaincounts = {}
                stats = [0, 0, 0, 0]

                with db.transaction():
                    recalculate_hashlimit(db, cid)

                for info in bucketinfo:
                    count += info["count"]
                    for domain, cnt in info["domaincounts"].items():
                        domaincounts[domain] = domaincounts.get(domain, 0) + cnt
                    for i in range(4):
                        stats[i] += info["stats"][i]

                patch = {
                    "processing": "",
                    "processing_error": "",
                    "last_update": datetime.utcnow().isoformat() + "Z",
                    "count_dirty": True,
                }

                if keytype == "list" and count > 0 and not skipvalidation:
                    patch["unapproved"] = True
                    patch["validation"] = {"status": "pending"}

                if keytype == "supp":
                    db.execute(
                        """update supplists set data = data ||
                            jsonb_build_object('count', coalesce((data->>'count')::int, 0) + %s) || %s
                            where id = %s""",
                        count,
                        patch,
                        listid,
                    )
                else:
                    for domain, cnt in domaincounts.items():
                        db.execute(
                            """
                            insert into list_domains (list_id, domain, count) values (%s, %s, %s)
                            on conflict (list_id, domain) do update set count = list_domains.count + excluded.count""",
                            listid,
                            domain,
                            cnt,
                        )
                    patch["domaincount"] = db.single(
                        "select count(domain) from list_domains where list_id = %s",
                        listid,
                    )

                    b, u, c, s = stats
                    db.execute(
                        """update lists set data = data ||
                            jsonb_build_object(
                                'used_properties',
                                    case when jsonb_array_length(coalesce(data->'used_properties', '[]'::jsonb)) = 0 and %s = 0 then
                                        '["Email"]'::jsonb
                                    else
                                        (select '["Email"]' || (jsonb_agg(distinct p) - 'Email')
                                        from jsonb_array_elements(coalesce(data->'used_properties', '[]'::jsonb) || array_to_json(%s::text[])::jsonb) as p)
                                    end,
                                'count', coalesce((data->>'count')::int, 0) + %s::int,
                                'bounced', coalesce((data->>'bounced')::int, 0) + %s::int,
                                'unsubscribed', coalesce((data->>'unsubscribed')::int, 0) + %s::int,
                                'complained', coalesce((data->>'complained')::int, 0) + %s::int,
                                'soft_bounced', coalesce((data->>'soft_bounced')::int, 0) + %s::int
                            ) || %s
                            where id = %s""",
                        len(used),
                        used,
                        count,
                        b,
                        u,
                        c,
                        s,
                        patch,
                        listid,
                    )

                if keytype == "list" and count > 0 and not skipvalidation:
                    if os.environ.get("zendesk_host"):
                        run_task(open_list_ticket, listid)
                    run_task(validate_list, listid)
        except Exception as e:
            log.exception("error")
            if keytype == "supp":
                db.supplists.patch(
                    listid,
                    {
                        "processing": "",
                        "processing_error": "Importing data failed: %s" % str(e),
                    },
                )
            elif keytype == "list":
                db.lists.patch(
                    listid,
                    {
                        "processing": "",
                        "processing_error": "Importing data failed: %s" % str(e),
                    },
                )


CONTACTS_PER_BLOCK = 500


@tasks.task(priority=LOW_PRIORITY)
def dedupe_blocks(
    cid: str,
    listid: str,
    keytype: str,
    key: str,
    colmap: List[str],
    override: bool,
    unsub: bool,
) -> None:
    with open_db() as db:
        try:
            l = len(colmap)
            strippedcols = [c for c in colmap if valid_prop(c)]
            s = len(strippedcols)
            emailindex = strippedcols.index("Email")

            used = set()
            skipvalidation = False
            excludemails = None
            excludedomains = None
            if keytype == "list":
                excludemails = set()
                excludedomains = set()
                for item, rh in db.execute(
                    "select item, rawhash from exclusions where cid = %s", cid
                ):
                    if rh is None:
                        excludedomains.add(item)
                    else:
                        excludemails.add(item)
                skipvalidation = db.single(
                    "select (data->>'skip_list_validation')::boolean from companies where id = %s",
                    cid,
                )

            for encoding in ["utf-8", "iso-8859-1", "ascii"]:
                try:
                    files: List[str] = []
                    writefp: IOBase | None = None
                    writecount = 0
                    emails = set()

                    with s3_read_stream(os.environ["s3_transferbucket"], key) as fp:
                        with TextIOWrapper(
                            fp,
                            encoding,
                            newline="",
                            errors="ignore" if encoding == "ascii" else None,
                        ) as text:
                            for row in csv.reader(text):
                                r = [
                                    row[i].strip()
                                    for i in range(min(len(row), l))
                                    if valid_prop(colmap[i])
                                ]

                                if len(r) <= emailindex:
                                    continue

                                emailmatch = emailre.search(r[emailindex])
                                if not emailmatch and not (
                                    keytype == "supp" and md5re.search(r[emailindex])
                                ):
                                    continue

                                if emailmatch:
                                    email = emailmatch.group(0).lower()
                                    if len(email) > 254:
                                        continue
                                else:
                                    email = r[emailindex].lower()

                                if email in emails:
                                    continue
                                emails.add(email)

                                while len(r) < s:
                                    r.append("")

                                props = {}
                                for i in range(len(r)):
                                    if i != emailindex:
                                        colname = strippedcols[i]
                                        if not unsub and colname in (
                                            "Bounced",
                                            "Unsubscribed",
                                            "Complained",
                                            "Soft Bounced",
                                        ):
                                            continue
                                        props[colname] = [r[i]]
                                        used.add(colname)

                                if keytype == "list":
                                    domain = email.split("@")[1]

                                    if (email in excludemails) or (
                                        domain in excludedomains
                                    ):
                                        continue

                                if writefp is None or writecount >= CONTACTS_PER_BLOCK:
                                    if writefp is not None:
                                        writefp.close()
                                    filename = f"{key}.dedupe.{len(files):05d}"
                                    writefp = s3_open_write(
                                        os.environ["s3_transferbucket"], filename
                                    )
                                    files.append(filename)
                                    writecount = 0
                                msgpack.pack([email, props], writefp)
                                writecount += 1
                    if writefp is not None:
                        writefp.close()
                    break
                except UnicodeDecodeError:
                    if encoding == "ascii":
                        raise

            if len(files):
                tmpid = gather_init(db, "write_block", len(files))

                for filename in files:
                    run_task(
                        write_block,
                        cid,
                        filename,
                        tmpid,
                        listid,
                        keytype,
                        list(used),
                        skipvalidation,
                        override,
                        unsub,
                    )
            else:
                if keytype == "supp":
                    db.supplists.patch(
                        listid, {"processing": "", "processing_error": ""}
                    )
                elif keytype == "list":
                    db.lists.patch(listid, {"processing": "", "processing_error": ""})
            s3_delete(os.environ["s3_transferbucket"], key)
        except Exception as e:
            log.exception("error")
            if keytype == "supp":
                db.supplists.patch(
                    listid,
                    {
                        "processing": "",
                        "processing_error": "Importing data failed: %s" % str(e),
                    },
                )
            elif keytype == "list":
                db.lists.patch(
                    listid,
                    {
                        "processing": "",
                        "processing_error": "Importing data failed: %s" % str(e),
                    },
                )


def add_blocks(
    cid: str,
    listid: str,
    keytype: str,
    key: str,
    colmap: List[str],
    override: bool = False,
    unsub: bool = False,
) -> None:
    run_task(dedupe_blocks, cid, listid, keytype, key, colmap, override, unsub)


@tasks.task(priority=HIGH_PRIORITY)
def list_remove_bucket(
    hashval: int,
    cid: str,
    segment: JsonObj,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
    listid: str,
) -> None:
    with open_db() as db:
        try:
            segments: Dict[str, JsonObj | None] = {}

            sentrows = get_segment_sentrows(db, cid, campaignids, hashval, hashlimit)

            rows = get_segment_rows(db, cid, hashval, listfactors, hashlimit)

            cache = Cache()

            found = set()
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
                    found.add(row["Email"][0])

            remove_list_contacts(db, cid, listid, list(found))
        except:
            log.exception("error")


@tasks.task(priority=HIGH_PRIORITY)
def tag_bucket(
    hashval: int,
    cid: str,
    segment: JsonObj,
    listfactors: List[str],
    hashlimit: int,
    campaignids: List[str],
    tags: List[str],
) -> None:
    with open_db() as db:
        try:
            webhook_msgs: List[JsonObj] = []
            segments: Dict[str, JsonObj | None] = {}

            sentrows = get_segment_sentrows(db, cid, campaignids, hashval, hashlimit)

            rows = get_segment_rows(db, cid, hashval, listfactors, hashlimit)

            cache = Cache()

            found = set()
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
                    found.add(row["Email"][0])

            update_tags(db, cid, list(found), tags, webhook_msgs)

            if len(webhook_msgs):
                send_webhooks(db, cid, webhook_msgs)
        except:
            log.exception("error")


def bulk_list_remove(db: DB, cid: str, lst: JsonObj, segment: JsonObj) -> None:
    campaignids = segment_get_campaignids(segment, [])

    hashlimit, listfactors = segment_get_params(db, cid, segment)

    for hashval in range(hashlimit):
        run_task(
            list_remove_bucket,
            hashval,
            cid,
            segment,
            listfactors,
            hashlimit,
            campaignids,
            lst["id"],
        )


def bulktag(db: DB, cid: str, segment: JsonObj, tags: List[str]) -> None:
    campaignids = segment_get_campaignids(segment, [])

    hashlimit, listfactors = segment_get_params(db, cid, segment)

    for hashval in range(hashlimit):
        run_task(
            tag_bucket, hashval, cid, segment, listfactors, hashlimit, campaignids, tags
        )


@tasks.task(priority=HIGH_PRIORITY)
def remove_tag_all_bucket(cid: str, hashval: int, hashlimit: int, tag: str) -> None:
    with open_db() as db:
        try:
            webhook_count = db.single(
                "select count(id) from resthooks where cid = %s and data->>'event' = 'tag_remove'",
                cid,
            )
            webhook_msgs = []

            if not webhook_count:
                db.execute(
                    f"""
                    delete from contacts."contact_values_{cid}"
                    where type = 'tag' and value = %s
                    and ({hashlimit} = 1 or mod(contact_id, {hashlimit}) = %s)
                """,
                    tag,
                    hashval,
                )
            else:
                for (email,) in db.execute(
                    f"""
                    with d as (
                        delete from contacts."contact_values_{cid}"
                        where type = 'tag' and value = %s
                        and ({hashlimit} = 1 or mod(contact_id, {hashlimit}) = %s)
                        returning contact_id
                    )
                    select c.email from contacts."contacts_{cid}" c
                    join d on d.contact_id = c.contact_id
                    where ({hashlimit} = 1 or mod(c.contact_id, {hashlimit}) = %s)
                """,
                    tag,
                    hashval,
                ):
                    webhook_msgs.append(
                        {
                            "type": "tag_remove",
                            "tag": tag,
                            "email": email,
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                        }
                    )

            if len(webhook_msgs):
                send_webhooks(db, cid, webhook_msgs)
        except:
            log.exception("error")


def remove_tag_all(db: DB, cid: str, tag: str) -> None:
    hashlimit = get_hashlimit(db, cid)
    for hashval in range(hashlimit):
        run_task(remove_tag_all_bucket, cid, hashval, hashlimit, tag)


REHASH_LOCK = 164287603


def recalculate_hashlimit(db: DB, cid: str) -> None:
    db.execute(f"select pg_advisory_xact_lock({REHASH_LOCK})")

    try:
        # For stability, keep hashlimit fixed at the capped value.
        desired_hashlimit = HASHLIMIT_CAP

        sz = db.single(
            f"""
            select pg_relation_size('contacts.' || quote_ident('contacts_{cid}')) +
                    pg_relation_size('contacts.' || quote_ident('contact_lists_{cid}')) +
                    pg_relation_size('contacts.' || quote_ident('contact_supplists_{cid}')) +
                    pg_relation_size('contacts.' || quote_ident('contact_values_{cid}')) +
                    pg_relation_size('contacts.' || quote_ident('contact_open_logs_{cid}')) +
                    pg_relation_size('contacts.' || quote_ident('contact_click_logs_{cid}')) +
                    pg_relation_size('contacts.' || quote_ident('contact_send_logs_{cid}'))
        """
        )

        db_hashlimit = db.single(
            "select hashlimit from contacts.contacts_hashlimit where cid = %s", cid
        )
        if db_hashlimit is not None and db_hashlimit >= desired_hashlimit:
            return

        log.info(
            "Contact storage size for %s is %s bytes, hashlimit has changed from %s to %s, reindexing...",
            cid,
            sz,
            db_hashlimit,
            desired_hashlimit,
        )

        if db_hashlimit is None:
            db.execute(
                "insert into contacts.contacts_hashlimit (cid, hashlimit) values (%s, %s)",
                cid,
                desired_hashlimit,
            )
        else:
            db.execute(
                "update contacts.contacts_hashlimit set hashlimit = %s where cid = %s",
                desired_hashlimit,
                cid,
            )

        db.execute(
            f"""
            set lock_timeout = '1000000s';
            set statement_timeout = '1000000s';

            drop index if exists contacts."contacts_{cid}_hash_idx_old";
            drop index if exists contacts."contact_lists_{cid}_hash_idx_old";
            drop index if exists contacts."contact_supplists_{cid}_hash_idx_old";
            drop index if exists contacts."contact_values_{cid}_hash_idx_old";
            drop index if exists contacts."contact_open_logs_{cid}_hash_idx_old";
            drop index if exists contacts."contact_click_logs_{cid}_hash_idx_old";
            drop index if exists contacts."contact_send_logs_{cid}_hash_idx_old";

            alter index if exists contacts."contacts_{cid}_hash_idx" rename to "contacts_{cid}_hash_idx_old";
            alter index if exists contacts."contact_lists_{cid}_hash_idx" rename to "contact_lists_{cid}_hash_idx_old";
            alter index if exists contacts."contact_supplists_{cid}_hash_idx" rename to "contact_supplists_{cid}_hash_idx_old";
            alter index if exists contacts."contact_values_{cid}_hash_idx" rename to "contact_values_{cid}_hash_idx_old";
            alter index if exists contacts."contact_open_logs_{cid}_hash_idx" rename to "contact_open_logs_{cid}_hash_idx_old";
            alter index if exists contacts."contact_click_logs_{cid}_hash_idx" rename to "contact_click_logs_{cid}_hash_idx_old";
            alter index if exists contacts."contact_send_logs_{cid}_hash_idx" rename to "contact_send_logs_{cid}_hash_idx_old";
        """
        )
        if hashlimit > 1:
            log.info("Creating indexes")
            db.execute(
                f"""
                create index "contacts_{cid}_hash_idx" on contacts."contacts_{cid}" ((mod(contact_id, {hashlimit})));
                create index "contact_lists_{cid}_hash_idx" on contacts."contact_lists_{cid}" ((mod(contact_id, {hashlimit})));
                create index "contact_supplists_{cid}_hash_idx" on contacts."contact_supplists_{cid}" ((mod(contact_id, {hashlimit})));
                create index "contact_values_{cid}_hash_idx" on contacts."contact_values_{cid}" ((mod(contact_id, {hashlimit})));
                create index "contact_open_logs_{cid}_hash_idx" on contacts."contact_open_logs_{cid}" ((mod(contact_id, {hashlimit})));
                create index "contact_click_logs_{cid}_hash_idx" on contacts."contact_click_logs_{cid}" ((mod(contact_id, {hashlimit})));
                create index "contact_send_logs_{cid}_hash_idx" on contacts."contact_send_logs_{cid}" ((mod(contact_id, {hashlimit})));
            """
            )
            log.info("Clustering tables")
            db.execute(
                f"""
                cluster contacts."contacts_{cid}" using "contacts_{cid}_hash_idx";
                cluster contacts."contact_lists_{cid}" using "contact_lists_{cid}_hash_idx";
                cluster contacts."contact_supplists_{cid}" using "contact_supplists_{cid}_hash_idx";
                cluster contacts."contact_values_{cid}" using "contact_values_{cid}_hash_idx";
                cluster contacts."contact_open_logs_{cid}" using "contact_open_logs_{cid}_hash_idx";
                cluster contacts."contact_click_logs_{cid}" using "contact_click_logs_{cid}_hash_idx";
                cluster contacts."contact_send_logs_{cid}" using "contact_send_logs_{cid}_hash_idx";
            """
            )

        log.info("..complete")
    except Exception as e:
        log.exception("error")
        if "deadlock detected" not in str(e):
            raise


def initialize_cid(db: DB, cid: str) -> None:
    db.execute(
        f"""
        create table contacts."contacts_{cid}" (
            contact_id serial primary key,
            email text not null,
            added bigint not null,
            opened boolean,
            clicked boolean,
            hard_bounced boolean,
            soft_bounced boolean,
            unsubscribed boolean,
            complained boolean,
            props jsonb not null,
            unique (email)
        ) inherits (contacts.contacts);
        create table contacts."contact_lists_{cid}" (
            list_id text not null,
            contact_id int not null references contacts."contacts_{cid}" on delete cascade,
            unique (list_id, contact_id)
        ) inherits (contacts.contact_lists);
        create index "contact_lists_{cid}_contact_id_idx" on contacts."contact_lists_{cid}" (contact_id);
        create table contacts."contact_supplists_{cid}" (
            supplist_id text not null,
            contact_id int not null references contacts."contacts_{cid}" on delete cascade,
            unique (supplist_id, contact_id)
        ) inherits (contacts.contact_supplists);
        create index "contact_supplists_{cid}_contact_id_idx" on contacts."contact_supplists_{cid}" (contact_id);
        create table contacts."contact_values_{cid}" (
            contact_id int not null references contacts."contacts_{cid}" on delete cascade,
            type contacts.value_type not null,
            value text not null,
            unique (contact_id, type, value)
        ) inherits (contacts.contact_values);
        create table contacts."contact_open_logs_{cid}" (
            contact_id int not null references contacts."contacts_{cid}" on delete cascade,
            campid text not null,
            ts bigint not null
        ) inherits (contacts.contact_open_logs);
        create unique index "contact_open_logs_{cid}_unique_idx" on contacts."contact_open_logs_{cid}" (contact_id, campid) include (ts);
        create table contacts."contact_click_logs_{cid}" (
            contact_id int not null references contacts."contacts_{cid}" on delete cascade,
            campid text not null,
            linkindex int not null,
            updatedts bigint not null,
            ts bigint not null
        ) inherits (contacts.contact_click_logs);
        create unique index "contact_click_logs_{cid}_unique_idx" on contacts."contact_click_logs_{cid}" (contact_id, campid, linkindex, updatedts) include (ts);
        create table contacts."contact_send_logs_{cid}" (
            contact_id int not null references contacts."contacts_{cid}" on delete cascade,
            campid text,
            unique (contact_id, campid)
        ) inherits (contacts.contact_send_logs);
        create index "contact_send_logs_{cid}_campid_idx" on contacts."contact_send_logs_{cid}" (campid);
        -- Create hash indexes at the capped hashlimit for new tenants.
        create index "contacts_{cid}_hash_idx" on contacts."contacts_{cid}" ((mod(contact_id, {HASHLIMIT_CAP})));
        create index "contact_lists_{cid}_hash_idx" on contacts."contact_lists_{cid}" ((mod(contact_id, {HASHLIMIT_CAP})));
        create index "contact_supplists_{cid}_hash_idx" on contacts."contact_supplists_{cid}" ((mod(contact_id, {HASHLIMIT_CAP})));
        create index "contact_values_{cid}_hash_idx" on contacts."contact_values_{cid}" ((mod(contact_id, {HASHLIMIT_CAP})));
        create index "contact_open_logs_{cid}_hash_idx" on contacts."contact_open_logs_{cid}" ((mod(contact_id, {HASHLIMIT_CAP})));
        create index "contact_click_logs_{cid}_hash_idx" on contacts."contact_click_logs_{cid}" ((mod(contact_id, {HASHLIMIT_CAP})));
        create index "contact_send_logs_{cid}_hash_idx" on contacts."contact_send_logs_{cid}" ((mod(contact_id, {HASHLIMIT_CAP})));
        insert into contacts.contacts_hashlimit (cid, hashlimit) values (%s, %s) on conflict (cid) do nothing;
    """
        ,
        cid,
        HASHLIMIT_CAP,
    )


def initialize(db: DB) -> None:
    if db.single(
        "select exists (select from pg_tables where tablename = 'contacts_hashlimit' and schemaname = 'contacts')"
    ):
        return

    log.info("  Initializing contact storage engine, this may take a while...")
    count = 0
    db.execute(
        """
        create schema contacts;
        create table contacts.contacts (
            contact_id int,
            email text,
            added bigint,
            props jsonb
        );
        create table contacts.contact_lists (
            list_id text,
            contact_id int
        );
        create table contacts.contact_supplists (
            supplist_id text,
            contact_id int
        );
        create type contacts.value_type as enum ('tag', 'device', 'os', 'browser', 'country', 'region', 'zip');
        create table contacts.contact_values (
            contact_id int,
            type contacts.value_type,
            value text
        );
        create table contacts.contact_open_logs (
            contact_id int,
            campid text,
            ts bigint
        );
        create table contacts.contact_click_logs (
            contact_id int,
            campid text,
            linkindex int,
            updatedts bigint,
            ts bigint
        );
        create table contacts.contact_send_logs (
            contact_id int,
            campid text
        );
        create table contacts.contacts_hashlimit (
            cid text primary key,
            hashlimit int not null
        );
    """
    )

    cids = []
    for (cid,) in db.execute(
        "select id from companies where not coalesce(data->>'admin', 'false')::bool"
    ):
        cids.append(cid)
    for cid in cids:
        initialize_cid(db, cid)

    for lst in db.lists.get_all():
        if "hashlimit" not in lst:
            continue

        cid = lst["cid"]

        for obj in list_blocks(f"lists/{lst['id']}/{lst['hashlimit']}/"):
            block = read_block(obj.key)

            if block is None:
                continue

            for row in MPDictReader(BytesIO(block)):
                email = row.pop("Email")
                added = row.pop("!!added")
                tags = row.pop("!!tags", "")
                devices: List[int] = row.pop("!!device", [])
                oses: List[int] = row.pop("!!os", [])
                browsers: List[int] = row.pop("!!browser", [])
                countries: List[str] = row.pop("!!country", [])
                regions: List[str] = row.pop("!!region", [])
                zips: List[str] = row.pop("!!zip", [])
                open_logs: List[List[Any]] = row.pop("!!open-logs", [])
                click_logs: List[List[Any]] = row.pop("!!click-logs", [])

                props = {prop: [val] for prop, val in row.items()}

                contact_id = db.single(
                    f"""
                    insert into contacts."contacts_{cid}" (email, added, props) values (%s, %s, %s) on conflict (email) do update set email = excluded.email returning contact_id
                """,
                    email,
                    added,
                    props,
                )

                db.execute(
                    f"""
                    insert into contacts."contact_lists_{cid}" (contact_id, list_id) values (%s, %s) on conflict (contact_id, list_id) do nothing
                """,
                    contact_id,
                    lst["id"],
                )

                for tag in tags.split(","):
                    if tag:
                        db.execute(
                            f"""
                            insert into contacts."contact_values_{cid}" (contact_id, type, value) values (%s, 'tag', %s) on conflict (contact_id, type, value) do nothing
                        """,
                            contact_id,
                            tag,
                        )
                for device in devices:
                    db.execute(
                        f"""
                        insert into contacts."contact_values_{cid}" (contact_id, type, value) values (%s, 'device', %s) on conflict (contact_id, type, value) do nothing
                    """,
                        contact_id,
                        device,
                    )
                for osname in oses:
                    db.execute(
                        f"""
                        insert into contacts."contact_values_{cid}" (contact_id, type, value) values (%s, 'os', %s) on conflict (contact_id, type, value) do nothing
                    """,
                        contact_id,
                        osname,
                    )
                for browser in browsers:
                    db.execute(
                        f"""
                        insert into contacts."contact_values_{cid}" (contact_id, type, value) values (%s, 'browser', %s) on conflict (contact_id, type, value) do nothing
                    """,
                        contact_id,
                        browser,
                    )
                for country in countries:
                    db.execute(
                        f"""
                        insert into contacts."contact_values_{cid}" (contact_id, type, value) values (%s, 'country', %s) on conflict (contact_id, type, value) do nothing
                    """,
                        contact_id,
                        country,
                    )
                for region in regions:
                    db.execute(
                        f"""
                        insert into contacts."contact_values_{cid}" (contact_id, type, value) values (%s, 'region', %s) on conflict (contact_id, type, value) do nothing
                    """,
                        contact_id,
                        region,
                    )
                for zip in zips:
                    db.execute(
                        f"""
                        insert into contacts."contact_values_{cid}" (contact_id, type, value) values (%s, 'zip', %s) on conflict (contact_id, type, value) do nothing
                    """,
                        contact_id,
                        zip,
                    )
                for ts, campid in open_logs:
                    db.execute(
                        f"""
                        insert into contacts."contact_open_logs_{cid}" (contact_id, ts, campid) values (%s, %s, %s) on conflict (contact_id, campid) do nothing
                    """,
                        contact_id,
                        ts,
                        campid,
                    )
                for ts, vals in click_logs:
                    campid, linkindex, updatedts = vals
                    if updatedts is None:
                        updatedts = 0
                    db.execute(
                        f"""
                        insert into contacts."contact_click_logs_{cid}" (contact_id, ts, campid, linkindex, updatedts) values (%s, %s, %s, %s, %s) on conflict (contact_id, campid, linkindex, updatedts) do nothing
                    """,
                        contact_id,
                        ts,
                        campid,
                        linkindex,
                        updatedts,
                    )

                count += 1
                if (count % 10000) == 0:
                    log.info("Migrated %s contacts", count)

    for supplist in db.supplists.get_all():
        cid = supplist["cid"]
        for obj in list_blocks(f"supplists/{supplist['id']}/"):
            block = read_block(obj.key)

            if block is None:
                continue

            for row in MPDictReader(BytesIO(block)):
                email = row["Email"]

                contact_id = db.single(
                    f"""
                    insert into contacts."contacts_{cid}" (email, added, props) values (%s, %s, %s) on conflict (email) do update set email = excluded.email returning contact_id
                """,
                    email,
                    unix_time_secs(datetime.now()),
                    {},
                )

                db.execute(
                    f"""
                    insert into contacts."contact_supplists_{cid}" (contact_id, supplist_id) values (%s, %s) on conflict (contact_id, supplist_id) do nothing
                """,
                    contact_id,
                    supplist["id"],
                )

                count += 1
                if (count % 10000) == 0:
                    log.info("Migrated %s contacts", count)
    count = 0
    for obj in list_blocks("sendlogs/"):
        m = re.search(r"^sendlogs/([a-zA-Z0-9]+)/\d{8}.blk$", obj.key)
        if m:
            campid = m.group(1)

            cid = db.single("select cid from campaigns where id = %s", campid)
            if cid is None:
                cid = db.single("select cid from messages where id = %s", campid)
            if cid is None:
                continue

            block = read_block(obj.key)

            if block is None:
                continue

            for row in MPDictReader(BytesIO(block)):
                email = row["Email"]

                contact_id = db.single(
                    f"""
                    insert into contacts."contacts_{cid}" (email, added, props) values (%s, %s, %s) on conflict (email) do update set email = excluded.email returning contact_id
                """,
                    email,
                    unix_time_secs(datetime.now()),
                    {},
                )

                db.execute(
                    f"""
                    insert into contacts."contact_send_logs_{cid}" (contact_id, campid) values (%s, %s) on conflict (contact_id, campid) do nothing
                """,
                    contact_id,
                    campid,
                )

                count += 1
                if (count % 10000) == 0:
                    log.info("Migrated %s send logs", count)

    for cid in cids:
        recalculate_hashlimit(db, cid)

    log.info("  ...contacts migrated")
