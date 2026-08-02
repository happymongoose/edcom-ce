import falcon
import re
import dateutil.parser
import requests
import shortuuid
import random
import socket
import struct
from typing import Dict, List
from netaddr import IPAddress, IPNetwork, IPRange, IPSet
from dateutil.tz import tzutc
from datetime import timedelta, datetime
from Crypto.PublicKey import RSA
from .shared import config as _  # noqa: F401
from .shared.db import open_db, statlogs_iter, DB, JsonObj
from .shared.crud import CRUDCollection, CRUDSingle, get_orig, check_noadmin
from .shared.utils import (
    run_task,
    gather_init,
    gather_complete,
    handle_mg_error,
    MTA_TIMEOUT,
    fix_sink_url,
    check_automation_diagnostics,
)
from .shared.send import (
    sink_get_settings,
    sink_get_ips,
    setup_ses_webhooks,
    setup_sparkpost_webhooks,
    mg_domain,
)
from .shared.tasks import tasks, HIGH_PRIORITY
from .shared.log import get_logger

log = get_logger()


def _dns_nameservers() -> List[str]:
    nameservers = []
    try:
        with open("/etc/resolv.conf") as fp:
            for line in fp:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    nameservers.append(parts[1])
    except Exception:
        log.exception("error reading resolv.conf")

    return nameservers or ["1.1.1.1", "8.8.8.8"]


def _dns_encode_name(name: str) -> bytes:
    return b"".join(
        bytes([len(part)]) + part.encode("ascii")
        for part in name.rstrip(".").split(".")
        if part
    ) + b"\x00"


def _dns_read_name(data: bytes, offset: int) -> tuple[str, int]:
    labels = []
    jumped = False
    end = offset

    while True:
        length = data[offset]
        if length & 0xC0 == 0xC0:
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                end = offset + 2
            offset = pointer
            jumped = True
            continue
        if length == 0:
            if not jumped:
                end = offset + 1
            break
        offset += 1
        labels.append(data[offset : offset + length].decode("ascii"))
        offset += length

    return ".".join(labels).lower(), end


def _dns_query(name: str, qtype: int) -> List[str]:
    query_id = random.randint(0, 65535)
    question = _dns_encode_name(name) + struct.pack("!HH", qtype, 1)
    packet = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + question

    for nameserver in _dns_nameservers():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(4)
                sock.sendto(packet, (nameserver, 53))
                data, _ = sock.recvfrom(4096)

            (
                response_id,
                flags,
                qdcount,
                ancount,
                _nscount,
                _arcount,
            ) = struct.unpack("!HHHHHH", data[:12])
            if response_id != query_id or flags & 0x000F:
                continue

            offset = 12
            for _ in range(qdcount):
                _, offset = _dns_read_name(data, offset)
                offset += 4

            results = []
            for _ in range(ancount):
                _, offset = _dns_read_name(data, offset)
                rtype, _rclass, _ttl, rdlength = struct.unpack(
                    "!HHIH", data[offset : offset + 10]
                )
                offset += 10
                rdata = data[offset : offset + rdlength]
                offset += rdlength

                if rtype != qtype:
                    continue
                if qtype == 16:
                    txt_offset = 0
                    chunks = []
                    while txt_offset < len(rdata):
                        chunk_len = rdata[txt_offset]
                        txt_offset += 1
                        chunks.append(rdata[txt_offset : txt_offset + chunk_len])
                        txt_offset += chunk_len
                    results.append(b"".join(chunks).decode("utf-8", "replace"))
                elif qtype == 15:
                    preference = struct.unpack("!H", rdata[:2])[0]
                    exchange, _ = _dns_read_name(data, offset - rdlength + 2)
                    results.append("%s %s" % (preference, exchange.rstrip(".")))

            if results:
                return results
        except Exception:
            log.exception("error querying DNS for %s", name)

    return []


def _dns_record_verified(entry: JsonObj) -> bool:
    record_type = entry["type"].upper()
    expected_name = entry["name"].strip().lower().rstrip(".")
    expected_value = entry["value"].strip()

    if record_type == "TXT":
        values = _dns_query(expected_name, 16)
        return expected_value in values
    if record_type == "MX":
        values = [value.lower().rstrip(".") for value in _dns_query(expected_name, 15)]
        return expected_value.lower().rstrip(".") in values

    return True


def verify_client_dkim_dns(ret: JsonObj) -> None:
    missing = []
    for key in ("mgentry", "serverentry", "spfentry", "mx1entry", "mx2entry"):
        entry = ret.get(key)
        if entry is not None and not _dns_record_verified(entry):
            missing.append("%s %s" % (entry["type"], entry["name"]))

    if missing:
        raise falcon.HTTPBadRequest(
            title="Unable to verify domain",
            description="Could not find required DNS records: %s" % ", ".join(missing),
        )


@tasks.task(priority=HIGH_PRIORITY)
def update_sinks(cid: str, force: List[JsonObj] | None) -> None:
    with open_db() as db:
        company = db.companies.get(cid)
        if company is not None and company.get("demo", False):
            return

        db.set_cid(cid)

        settings = {}
        for policy in db.policies.find():
            if policy.get("published", None) is not None:
                settings[policy["id"]] = policy["published"]

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

        dkim = db.dkimentries.get_singleton()

        if force is None:
            force = []

        allips: set[str] = set()
        allsinks = set()
        sinks = db.sinks.get_all()
        for sink in sinks:
            allips.update(d["ip"] for d in sink.get("ipdata", ()))
            allsinks.add(sink["id"])

        for sink in sinks:
            url = fix_sink_url(sink["url"])

            s = {}
            for sid, policy in settings.items():
                s[sid] = sink_get_settings(policy, sink["id"])

            try:
                r = requests.post(
                    url + "/settings",
                    json={
                        "accesskey": sink["accesskey"],
                        "sinkid": sink["id"],
                        "mtasettings": s,
                        "ippauses": pauses.get(sink["id"], []),
                        "warmups": warmups.get(sink["id"], {}),
                        "forcestart": [f for f in force if f["sinkid"] == sink["id"]],
                        "allips": list(allips),
                        "allsinks": list(allsinks),
                        "ipdomains": sink_get_ips(sink),
                        "dkim": dkim,
                    },
                    timeout=MTA_TIMEOUT,
                )
                r.raise_for_status()

                db.sinks.patch(sink["id"], {"failed_update": False})
            except:
                log.exception("error")
                db.sinks.patch(sink["id"], {"failed_update": True})


class Warmups(CRUDCollection):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "warmups"
        self.userlog = "warmup"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        db = req.context["db"]

        doc["modified"] = datetime.utcnow().isoformat() + "Z"
        doc["dirty"] = True
        doc["published"] = None

        sink = None
        if "sink" in doc:
            sink = db.sinks.get(doc["sink"])
        if sink is None:
            raise falcon.HTTPForbidden()

        allips = list(
            (set(get_ips(doc, "ips")) & set(d["ip"] for d in sink["ipdata"]))
            - set(get_ips(doc, "excludeips"))
        )

        doc["allips"] = allips

        CRUDCollection.on_post(self, req, resp)


class Warmup(CRUDSingle):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "warmups"
        self.userlog = "warmup"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        db = req.context["db"]

        e = db.warmups.get(id)

        doc.pop("published", None)
        doc.pop("id", None)
        doc.pop("modified", None)
        doc.pop("dirty", None)
        doc.pop("disabled", None)

        if e is not None:
            changed = False
            for prop in list(doc.keys()):
                if prop != "name" and doc[prop] != e.get(prop, None):
                    changed = True
                    break
            if changed:
                doc["dirty"] = True

        doc["modified"] = datetime.utcnow().isoformat() + "Z"

        CRUDSingle.on_patch(self, req, resp, id)

        e = db.warmups.get(id)
        if e is not None:
            sink = db.sinks.get(e["sink"])
            if sink is None:
                raise falcon.HTTPForbidden()
            allips = list(
                (set(get_ips(e, "ips")) & set(d["ip"] for d in sink["ipdata"]))
                - set(get_ips(e, "excludeips"))
            )
            db.warmups.patch(id, {"allips": allips})


class WarmupEnable(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        db.warmups.patch(id, {"disabled": False})

        run_task(update_sinks, db.get_cid(), None)


class WarmupDisable(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        db.warmups.patch(id, {"disabled": True})

        run_task(update_sinks, db.get_cid(), None)


class WarmupDuplicate(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        w = db.warmups.get(id)

        if w is None:
            raise falcon.HTTPForbidden()

        w.pop("published", None)
        w["dirty"] = True
        w["modified"] = datetime.utcnow().isoformat() + "Z"

        orig, i = get_orig(w["name"])
        while True:
            w["name"] = "%s (%s)" % (orig, i)
            if db.warmups.find_one({"name": w["name"]}) is None:
                break
            i += 1

        req.context["result"] = db.warmups.add(w)


class WarmupRevert(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]
        warmup = db.warmups.get(id)
        if not warmup:
            raise falcon.HTTPForbidden()

        published = warmup["published"]
        published["dirty"] = False

        db.warmups.patch(id, published)


class WarmupPublish(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]
        warmup = db.warmups.get(id)
        if not warmup:
            raise falcon.HTTPForbidden()

        warmup.pop("id", None)
        warmup.pop("cid", None)
        warmup.pop("name", None)
        warmup.pop("modified", None)
        warmup.pop("dirty", None)
        warmup.pop("published", None)
        warmup.pop("disabled", None)

        db.warmups.patch(id, {"published": warmup, "dirty": False})

        run_task(update_sinks, db.get_cid(), None)


class AllSettings(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        req.context["result"] = (
            db.policies.get_all()
            + db.mailgun.get_all()
            + db.ses.get_all()
            + db.sparkpost.get_all()
            + db.easylink.get_all()
            + db.smtprelays.get_all()
        )


class SettingsSumStats(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        end = req.get_param("end", required=True)
        try:
            end = dateutil.parser.parse(end).astimezone(tzutc()).replace(tzinfo=None)
        except:
            raise falcon.HTTPBadRequest(
                title="Invalid parameter", description="invalid date parameter"
            )

        domains = [
            d.strip().lower()
            for d in re.split(r"\s*,\s*", (req.get_param("domains") or ""))
            if d.strip()
        ]

        domainfilter = ""
        if domains:
            domainfilter = db.cur.mogrify(
                " and domaingroupid = any(%s)", [domains]
            ).decode("utf-8")

        dayarray = []
        for i in range(20):
            dayarray.append(end - timedelta(days=19 - i))

        now = datetime.utcnow()
        hourarray = []
        for i in range(24):
            hourarray.append(now - timedelta(hours=23 - i))

        stats = {}
        for row in db.execute(
            """select width_bucket(ts, %%s) hourbucket,
                                 sum(send), sum(soft), sum(hard), sum(err), sum(open), sum(defercnt)
                                 from hourstats
                                 where cid = %%s and settingsid = %%s and ts > %%s
                                 %s
                                 group by hourbucket
                                 order by hourbucket"""
            % (domainfilter,),
            hourarray,
            db.get_cid(),
            id,
            hourarray[0] - timedelta(hours=1),
        ):
            if row[0] >= len(hourarray):
                break
            ts = hourarray[row[0]].isoformat() + "Z"
            stats[ts] = {
                "ts": ts,
                "send": row[1],
                "soft": row[2],
                "hard": row[3],
                "err": row[4],
                "open": row[5],
                "defercnt": row[6],
            }
        for ts in hourarray:
            t = ts.isoformat() + "Z"
            if t not in stats:
                stats[t] = {
                    "ts": t,
                    "send": 0,
                    "soft": 0,
                    "hard": 0,
                    "err": 0,
                    "open": 0,
                    "defercnt": 0,
                }

        days = {}
        for row in db.execute(
            """select width_bucket(ts, %%s) daybucket,
            sum(send), sum(soft), sum(hard), sum(err), sum(open), sum(defercnt)
            from hourstats
            where cid = %%s and settingsid = %%s and ts > %%s
            %s
            group by daybucket
            order by daybucket"""
            % (domainfilter,),
            dayarray,
            db.get_cid(),
            id,
            dayarray[0] - timedelta(days=1),
        ):
            if row[0] >= len(dayarray):
                break
            ts = dayarray[row[0]].isoformat() + "Z"
            days[ts] = {
                "ts": ts,
                "send": row[1],
                "soft": row[2],
                "hard": row[3],
                "err": row[4],
                "open": row[5],
                "defercnt": row[6],
            }
        for ts in dayarray:
            t = ts.isoformat() + "Z"
            if t not in days:
                days[t] = {
                    "ts": t,
                    "send": 0,
                    "soft": 0,
                    "hard": 0,
                    "err": 0,
                    "open": 0,
                    "defercnt": 0,
                }

        req.context["result"] = {
            "hours": sorted(iter(stats.values()), key=lambda s: s["ts"], reverse=True),
            "summary": sorted(iter(days.values()), key=lambda d: d["ts"], reverse=True),
        }


class RoutePolicies(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        ret = [
            {"id": p["id"], "name": p["name"]}
            for p in db.policies.find()
            if "published" in p
        ]

        ret.extend({"id": m["id"], "name": m["name"]} for m in db.mailgun.find())
        ret.extend({"id": m["id"], "name": m["name"]} for m in db.ses.find())
        ret.extend({"id": m["id"], "name": m["name"]} for m in db.sparkpost.find())
        ret.extend({"id": m["id"], "name": m["name"]} for m in db.easylink.find())
        ret.extend({"id": m["id"], "name": m["name"]} for m in db.smtprelays.find())
        ret.extend(
            {"id": m["id"], "name": m["name"]} for m in db.debug_email_backends.find()
        )

        req.context["result"] = ret


class DebugEmailLogs(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)
        check_automation_diagnostics(req)

        db = req.context["db"]
        cid = db.get_cid()
        limit = req.get_param_as_int("limit") or 100
        limit = max(1, min(limit, 100))

        rows = db.execute(
            """
            select id, cid, ts, data
            from debug_email_logs
            where cid = %s
            order by ts desc, id desc
            limit %s
            """,
            cid,
            limit,
        ).fetchall()

        ret = []
        for log_id, row_cid, ts, data in rows:
            item = dict(data)
            item["id"] = log_id
            item["cid"] = row_cid
            item["timestamp"] = item.get("timestamp") or ts.isoformat() + "Z"
            ret.append(item)

        req.context["result"] = ret


def clean_policy(p: JsonObj) -> None:
    # remove unselected ip list entries to save db space
    for sink in p["sinks"]:
        iplist = {}
        for ip, entry in sink["iplist"].items():
            if entry.get("selected"):
                iplist[ip] = entry
        sink["iplist"] = iplist


class Policies(CRUDCollection):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "policies"
        self.userlog = "delivery policy"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        if "doc" in req.context:
            req.context["doc"]["modified"] = datetime.utcnow().isoformat() + "Z"
            req.context["doc"]["dirty"] = True
            if "domains" in req.context["doc"]:
                req.context["doc"]["domaincount"] = len(
                    [s for s in req.context["doc"]["domains"].split() if s]
                )

            clean_policy(req.context["doc"])

        return CRUDCollection.on_post(self, req, resp)


class Policy(CRUDSingle):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "policies"
        self.userlog = "delivery policy"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        db = req.context["db"]

        e = db.policies.get(id)
        if "doc" in req.context and e is not None:
            req.context["doc"].pop("published", None)
            req.context["doc"].pop("id", None)
            req.context["doc"].pop("modified", None)
            req.context["doc"].pop("dirty", None)

            clean_policy(req.context["doc"])

            changed = False
            for prop in list(req.context["doc"].keys()):
                if prop != "name" and req.context["doc"][prop] != e.get(prop, None):
                    changed = True
                    break
            if changed:
                req.context["doc"]["dirty"] = True

            req.context["doc"]["modified"] = datetime.utcnow().isoformat() + "Z"
            if "domains" in req.context["doc"]:
                req.context["doc"]["domaincount"] = len(
                    [s for s in req.context["doc"]["domains"].split() if s]
                )

        return CRUDSingle.on_patch(self, req, resp, id)

    def del_check(self, db: DB, id: str) -> None:
        for route in db.routes.find():
            for rule in route["rules"]:
                for s in rule["splits"]:
                    if s["policy"] == id:
                        raise falcon.HTTPBadRequest(
                            title="Policy in use",
                            description="This policy is used by one or more postal routes",
                        )


class PolicyDuplicate(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        p = db.policies.get(id)

        if p is None:
            raise falcon.HTTPForbidden()

        p.pop("published", None)
        p["dirty"] = True
        p["modified"] = datetime.utcnow().isoformat() + "Z"

        orig, i = get_orig(p["name"])
        while True:
            p["name"] = "%s (%s)" % (orig, i)
            if db.policies.find_one({"name": p["name"]}) is None:
                break
            i += 1

        req.context["result"] = db.policies.add(p)


class PolicyRevert(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]
        policy = db.policies.get(id)
        if not policy:
            raise falcon.HTTPForbidden()

        published = policy["published"]
        published["dirty"] = False

        db.policies.patch(id, published)


class PolicyPublish(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]
        policy = db.policies.get(id)
        if not policy:
            raise falcon.HTTPForbidden()

        policy.pop("id", None)
        policy.pop("cid", None)
        policy.pop("name", None)
        policy.pop("modified", None)
        policy.pop("dirty", None)
        policy.pop("published", None)

        db.policies.patch(id, {"published": policy, "dirty": False})

        run_task(update_sinks, db.get_cid(), None)


class Routes(CRUDCollection):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "routes"
        self.userlog = "postal route"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        doc["modified"] = datetime.utcnow().isoformat() + "Z"
        doc["dirty"] = True
        doc["published"] = None

        return CRUDCollection.on_post(self, req, resp)


class Route(CRUDSingle):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "routes"
        self.userlog = "postal route"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        db = req.context["db"]

        e = db.routes.get(id)

        doc.pop("published", None)
        doc.pop("id", None)
        doc.pop("modified", None)
        doc.pop("dirty", None)
        doc.pop("disabled", None)

        if e is not None:
            changed = False
            for prop in list(doc.keys()):
                if prop != "name" and doc[prop] != e.get(prop, None):
                    changed = True
                    break
            if changed:
                doc["dirty"] = True

        doc["modified"] = datetime.utcnow().isoformat() + "Z"

        return CRUDSingle.on_patch(self, req, resp, id)

    def del_check(self, db: DB, id: str) -> None:
        for company in db.companies.find():
            if "routes" in company and id in company["routes"]:
                raise falcon.HTTPBadRequest(
                    title="Route in use",
                    description="This route is assigned to one or more customers",
                )


class RouteDuplicate(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        r = db.routes.get(id)

        if r is None:
            raise falcon.HTTPForbidden()

        r.pop("published", None)
        r["dirty"] = True
        r["modified"] = datetime.utcnow().isoformat() + "Z"

        orig, i = get_orig(r["name"])
        while True:
            r["name"] = "%s (%s)" % (orig, i)
            if db.routes.find_one({"name": r["name"]}) is None:
                break
            i += 1

        req.context["result"] = db.routes.add(r)


class RouteRevert(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]
        route = db.routes.get(id)
        if not route:
            raise falcon.HTTPForbidden()

        published = route["published"]
        published["dirty"] = False

        db.routes.patch(id, published)


class RoutePublish(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]
        route = db.routes.get(id)
        if not route:
            raise falcon.HTTPForbidden()

        route.pop("id", None)
        route.pop("cid", None)
        route.pop("name", None)
        route.pop("modified", None)
        route.pop("dirty", None)
        route.pop("published", None)

        db.routes.patch(id, {"published": route, "dirty": False})

        run_task(update_sinks, db.get_cid(), None)


class DomainGroups(CRUDCollection):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "domaingroups"
        self.userlog = "domain group"


class DomainGroup(CRUDSingle):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "domaingroups"
        self.userlog = "domain group"

    def del_check(self, db: DB, id: str) -> None:
        for route in db.routes.find():
            for rule in route["rules"]:
                if rule["domaingroup"] == id:
                    raise falcon.HTTPBadRequest(
                        title="Domain group in use",
                        description="This group is used by one or more postal routes",
                    )


domainre = re.compile(r"^[a-z0-9\.\-]+$")


def check_ips(doc: JsonObj) -> None:
    if "ipdata" not in doc:
        return

    allips = IPSet()

    newipdata = []

    for ipdata in doc["ipdata"]:
        ip = ipdata.get("ip", "").strip()
        if not ip:
            continue

        ipdata["ip"] = ip

        try:
            ipparsed = IPAddress(ip)
            if ipparsed in allips:
                raise falcon.HTTPBadRequest(
                    title="Duplicate IP",
                    description="IP '%s' appears more than once" % (ip,),
                )
            allips.add(ipparsed)
        except:
            raise falcon.HTTPBadRequest(
                title="Invalid IP", description="Cannot parse '%s'" % (ip,)
            )

        domain = ipdata.get("domain", "").strip().lower()
        if not domain:
            raise falcon.HTTPBadRequest(
                title="Missing domain", description="No domain for '%s'" % (ip,)
            )
        if not domainre.search(domain):
            raise falcon.HTTPBadRequest(
                title="Invalid domain", description="Domain '%s' is invalid" % (domain,)
            )
        ipdata["domain"] = domain

        linkdomain = ipdata.get("linkdomain", "").strip().lower()
        if linkdomain and not domainre.search(linkdomain):
            raise falcon.HTTPBadRequest(
                title="Invalid domain",
                description="Domain '%s' is invalid" % (linkdomain,),
            )
        ipdata["linkdomain"] = linkdomain

        newipdata.append(ipdata)

    doc["ipdata"] = newipdata

    def range_desc(r: IPRange) -> str:
        if r.first == r.last:
            return str(IPAddress(r.first))
        else:
            return "%s-%s" % (IPAddress(r.first), IPAddress(r.last))

    doc["ips"] = "\n".join(range_desc(r) for r in allips.iter_ipranges())


def get_ips(doc: JsonObj, prop: str) -> List[str]:
    LIMIT = 100

    if prop in doc:
        ips = doc[prop]
        allips = set()

        for line in ips.split("\n"):
            ls = line.strip()

            if not ls:
                continue

            try:
                start, end = ls.split("-")
                start = IPAddress(start.strip())
                end = IPAddress(end.strip())
                if start > end:
                    start, end = end, start
                r = IPRange(start, end)
                for ip in r:
                    allips.add(ip)
                    if len(allips) > LIMIT:
                        raise falcon.HTTPBadRequest(
                            title="Too many IPs",
                            description="Configuration contains too many IPs",
                        )
            except:
                try:
                    cidr = IPNetwork(ls)
                    cnt = 0
                    for ip in cidr:
                        if cnt == 0 and ip.words[-1] == 0:
                            cnt += 1
                            continue
                        if cnt == len(cidr) - 1 and ip.words[-1] == 255:
                            cnt += 1
                            continue
                        cnt += 1
                        allips.add(ip)
                        if len(allips) > LIMIT:
                            raise falcon.HTTPBadRequest(
                                title="Too many IPs",
                                description="Configuration contains too many IPs",
                            )
                except:
                    try:
                        ip = IPAddress(ls)
                        allips.add(ip)
                        if len(allips) > LIMIT:
                            raise falcon.HTTPBadRequest(
                                title="Too many IPs",
                                description="Configuration contains too many IPs",
                            )
                    except:
                        raise falcon.HTTPBadRequest(
                            title="Invalid IP Range",
                            description="Cannot parse '%s'" % (ls,),
                        )
        allipslist = sorted(allips)
        return [str(ip) for ip in allipslist]
    else:
        return []


class Sinks(CRUDCollection):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "sinks"
        self.userlog = "server"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        check_ips(doc)

        db = req.context["db"]

        if db.sinks.find_one({"url": doc.get("url")}) is not None:
            raise falcon.HTTPBadRequest(
                title="Duplicate Management IP",
                description="A server with this management IP already exists",
            )

        CRUDCollection.on_post(self, req, resp)

        run_task(update_sinks, db.get_cid(), None)


class Sink(CRUDSingle):

    def __init__(self) -> None:
        self.adminonly = True
        self.domain = "sinks"
        self.userlog = "server"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        db = req.context["db"]
        sink = db.sinks.get(id)

        if sink is None:
            raise falcon.HTTPForbidden()

        if not sink.get("type"):
            doc = req.context.get("doc")
            if not doc:
                raise falcon.HTTPBadRequest(
                    title="Not JSON", description="A valid JSON document is required."
                )

            check_ips(doc)

        db = req.context["db"]

        exist = db.sinks.find_one({"url": doc.get("url")})
        if exist is not None and exist["id"] != id:
            raise falcon.HTTPBadRequest(
                title="Duplicate Management IP",
                description="A server with this management IP already exists",
            )

        CRUDSingle.on_patch(self, req, resp, id)

        run_task(update_sinks, db.get_cid(), None)

    def del_check(self, db: DB, id: str) -> None:
        for policy in db.policies.find():
            for sink in policy["sinks"]:
                if sink["sink"] == id:
                    raise falcon.HTTPBadRequest(
                        title="Server in use",
                        description="This server is used by one or more delivery policies",
                    )
        for warmup in db.warmups.find():
            if warmup["sink"] == id:
                raise falcon.HTTPBadRequest(
                    title="Server in use",
                    description="This server is used by one or more warmups",
                )


class AllStats(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        end = req.get_param("end", required=True)
        try:
            end = dateutil.parser.parse(end).astimezone(tzutc()).replace(tzinfo=None)
        except:
            raise falcon.HTTPBadRequest(
                title="Invalid parameter", description="invalid date parameter"
            )

        domains = [
            d.strip().lower()
            for d in re.split(r"\s*,\s*", (req.get_param("domains") or ""))
            if d.strip()
        ]
        servers = [
            s.strip().lower()
            for s in re.split(r"\s*,\s*", (req.get_param("servers") or ""))
            if s.strip()
        ]

        sinks = []
        if servers:
            for (name,) in db.execute(
                """select id from sinks where cid = %s and lower(data->>'name') = any(%s)""",
                db.get_cid(),
                servers,
            ):
                sinks.append(name)

        domainfilter = ""
        if domains:
            domainfilter = db.cur.mogrify(
                " and domaingroupid = any(%s)", [domains]
            ).decode("utf-8")
        serverfilter = ""
        if servers:
            serverfilter = db.cur.mogrify(" and sinkid = any(%s)", [sinks]).decode(
                "utf-8"
            )

        dayarray = []
        for i in range(20):
            dayarray.append(end - timedelta(days=19 - i))

        now = datetime.utcnow()
        hourarray = []
        for i in range(24):
            hourarray.append(now - timedelta(hours=23 - i))

        stats = {}
        for row in db.execute(
            """select width_bucket(ts, %%s) hourbucket,
                                 sum(send), sum(soft), sum(hard), sum(err), sum(open), sum(defercnt)
                                 from hourstats
                                 where cid = %%s and ts > %%s
                                 %s
                                 %s
                                 group by hourbucket
                                 order by hourbucket"""
            % (domainfilter, serverfilter),
            hourarray,
            db.get_cid(),
            hourarray[0] - timedelta(hours=1),
        ):
            if row[0] >= len(hourarray):
                break
            ts = hourarray[row[0]].isoformat() + "Z"
            stats[ts] = {
                "ts": ts,
                "send": row[1],
                "soft": row[2],
                "hard": row[3],
                "err": row[4],
                "open": row[5],
                "defercnt": row[6],
            }
        for ts in hourarray:
            t = ts.isoformat() + "Z"
            if t not in stats:
                stats[t] = {
                    "ts": t,
                    "send": 0,
                    "soft": 0,
                    "hard": 0,
                    "err": 0,
                    "open": 0,
                    "defercnt": 0,
                }

        days = {}
        for row in db.execute(
            """select width_bucket(ts, %%s) daybucket,
            sum(send), sum(soft), sum(hard), sum(err), sum(open), sum(defercnt)
            from hourstats
            where cid = %%s and ts > %%s
            %s
            %s
            group by daybucket
            order by daybucket"""
            % (domainfilter, serverfilter),
            dayarray,
            db.get_cid(),
            dayarray[0] - timedelta(days=1),
        ):
            if row[0] >= len(dayarray):
                break
            ts = dayarray[row[0]].isoformat() + "Z"
            days[ts] = {
                "ts": ts,
                "send": row[1],
                "soft": row[2],
                "hard": row[3],
                "err": row[4],
                "open": row[5],
                "defercnt": row[6],
            }
        for ts in dayarray:
            t = ts.isoformat() + "Z"
            if t not in days:
                days[t] = {
                    "ts": t,
                    "send": 0,
                    "soft": 0,
                    "hard": 0,
                    "err": 0,
                    "open": 0,
                    "defercnt": 0,
                }

        req.context["result"] = {
            "hours": sorted(iter(stats.values()), key=lambda s: s["ts"], reverse=True),
            "summary": sorted(iter(days.values()), key=lambda d: d["ts"], reverse=True),
        }


class SinkSumStats(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        end = req.get_param("end", required=True)
        try:
            end = dateutil.parser.parse(end).astimezone(tzutc()).replace(tzinfo=None)
        except:
            raise falcon.HTTPBadRequest(
                title="Invalid parameter", description="invalid date parameter"
            )

        domains = [
            d.strip().lower()
            for d in re.split(r"\s*,\s*", (req.get_param("domains") or ""))
            if d.strip()
        ]

        domainfilter = ""
        if domains:
            domainfilter = db.cur.mogrify(
                " and domaingroupid = any(%s)", [domains]
            ).decode("utf-8")

        dayarray = []
        for i in range(20):
            dayarray.append(end - timedelta(days=19 - i))

        now = datetime.utcnow()
        hourarray = []
        for i in range(24):
            hourarray.append(now - timedelta(hours=23 - i))

        stats = {}
        for row in db.execute(
            """select width_bucket(ts, %%s) hourbucket,
                                 sum(send), sum(soft), sum(hard), sum(err), sum(open), sum(defercnt)
                                 from hourstats
                                 where cid = %%s and sinkid = %%s and ts > %%s
                                 %s
                                 group by hourbucket
                                 order by hourbucket"""
            % (domainfilter,),
            hourarray,
            db.get_cid(),
            id,
            hourarray[0] - timedelta(hours=1),
        ):
            if row[0] >= len(hourarray):
                break
            ts = hourarray[row[0]].isoformat() + "Z"
            stats[ts] = {
                "ts": ts,
                "send": row[1],
                "soft": row[2],
                "hard": row[3],
                "err": row[4],
                "open": row[5],
                "defercnt": row[6],
            }
        for ts in hourarray:
            t = ts.isoformat() + "Z"
            if t not in stats:
                stats[t] = {
                    "ts": t,
                    "send": 0,
                    "soft": 0,
                    "hard": 0,
                    "err": 0,
                    "open": 0,
                    "defercnt": 0,
                }

        days = {}
        for row in db.execute(
            """select width_bucket(ts, %%s) daybucket,
            sum(send), sum(soft), sum(hard), sum(err), sum(open), sum(defercnt)
            from hourstats
            where cid = %%s and sinkid = %%s and ts > %%s
            %s
            group by daybucket
            order by daybucket"""
            % (domainfilter,),
            dayarray,
            db.get_cid(),
            id,
            dayarray[0] - timedelta(days=1),
        ):
            if row[0] >= len(dayarray):
                break
            ts = dayarray[row[0]].isoformat() + "Z"
            days[ts] = {
                "ts": ts,
                "send": row[1],
                "soft": row[2],
                "hard": row[3],
                "err": row[4],
                "open": row[5],
                "defercnt": row[6],
            }
        for ts in dayarray:
            t = ts.isoformat() + "Z"
            if t not in days:
                days[t] = {
                    "ts": t,
                    "send": 0,
                    "soft": 0,
                    "hard": 0,
                    "err": 0,
                    "open": 0,
                    "defercnt": 0,
                }

        req.context["result"] = {
            "hours": sorted(iter(stats.values()), key=lambda s: s["ts"], reverse=True),
            "summary": sorted(iter(days.values()), key=lambda d: d["ts"], reverse=True),
        }


class SinkDomainOptions(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        r = []
        for (name,) in db.execute(
            """select distinct domaingroupid from statlogs2 s
                                   where s.cid = %s and s.sinkid = %s""",
            db.get_cid(),
            id,
        ):
            r.append({"id": name, "name": name})

        req.context["result"] = r


class SinkStats(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        domaingroupid = req.get_param("domaingroup", default="")
        settingsid = req.get_param("settings", required=True)
        ip = req.get_param("ip", required=True)
        end = req.get_param("end", required=True)
        dayend = req.get_param("dayend")

        if not dayend:
            dayend = end

        try:
            end = dateutil.parser.parse(end).astimezone(tzutc()).replace(tzinfo=None)
            dayend = (
                dateutil.parser.parse(dayend).astimezone(tzutc()).replace(tzinfo=None)
            )
        except:
            raise falcon.HTTPBadRequest(
                title="Invalid parameter", description="invalid date parameter"
            )

        start = end - timedelta(days=1)

        dayarray = []
        for i in range(20):
            dayarray.append(dayend - timedelta(days=19 - i))

        hourarray = []
        for i in range(24):
            hourarray.append(end - timedelta(hours=23 - i))

        hours = {}
        for row in db.execute(
            """select width_bucket(ts, %s) hourbucket,
                                 sum(send), sum(soft), sum(hard), sum(err), sum(open), sum(defercnt)
                                 from hourstats
                                 where cid = %s and sinkid = %s and ts > %s and domaingroupid = %s
                                 and settingsid = %s and ip = %s
                                 group by hourbucket
                                 order by hourbucket""",
            hourarray,
            db.get_cid(),
            id,
            hourarray[0] - timedelta(hours=1),
            domaingroupid,
            settingsid,
            ip,
        ):
            if row[0] >= len(hourarray):
                break
            ts = hourarray[row[0]].isoformat() + "Z"
            hours[ts] = {
                "ts": ts,
                "send": row[1],
                "soft": row[2],
                "hard": row[3],
                "err": row[4],
                "open": row[5],
                "defercnt": row[6],
            }
        for ts in hourarray:
            t = ts.isoformat() + "Z"
            if t not in hours:
                hours[t] = {
                    "ts": t,
                    "send": 0,
                    "soft": 0,
                    "hard": 0,
                    "err": 0,
                    "open": 0,
                    "defercnt": 0,
                }

        days = {}
        for row in db.execute(
            """select width_bucket(ts, %s) daybucket,
            sum(send), sum(soft), sum(hard), sum(err), sum(open), sum(defercnt)
            from hourstats
            where cid = %s and sinkid = %s and ts > %s and domaingroupid = %s
            and settingsid = %s and ip = %s
            group by daybucket
            order by daybucket""",
            dayarray,
            db.get_cid(),
            id,
            dayarray[0] - timedelta(days=1),
            domaingroupid,
            settingsid,
            ip,
        ):
            if row[0] >= len(dayarray):
                break
            ts = dayarray[row[0]].isoformat() + "Z"
            days[ts] = {
                "ts": ts,
                "send": row[1],
                "soft": row[2],
                "hard": row[3],
                "err": row[4],
                "open": row[5],
                "defercnt": row[6],
            }
        for ts in dayarray:
            t = ts.isoformat() + "Z"
            if t not in days:
                days[t] = {
                    "ts": t,
                    "send": 0,
                    "soft": 0,
                    "hard": 0,
                    "err": 0,
                    "open": 0,
                    "defercnt": 0,
                }

        stats = list(
            statlogs_iter(
                db.execute(
                    """select *
                                             from statlogs2
                                             where cid = %s and sinkid = %s and domaingroupid = %s
                                             and settingsid = %s and ip = %s
                                             and ts >= %s and ts <= %s
                                             order by ts desc, defermsg desc""",
                    db.get_cid(),
                    id,
                    domaingroupid,
                    settingsid,
                    ip,
                    start.isoformat() + "Z",
                    end.isoformat() + "Z",
                )
            )
        )

        limit, warmup = None, None
        limitrow = db.row(
            "select sendlimit, warmupid from iplimits where sinkid = %s and settingsid = %s and domain = %s and ip = %s",
            id,
            settingsid,
            domaingroupid,
            ip,
        )
        if limitrow is not None:
            limit, warmup = limitrow

        queue = db.single(
            "select queue from sinkdomainqueues where sinkid = %s and domain = %s",
            id,
            domaingroupid,
        )

        req.context["result"] = {
            "stats": stats,
            "hours": sorted(iter(hours.values()), key=lambda s: s["ts"], reverse=True),
            "days": sorted(iter(days.values()), key=lambda s: s["ts"], reverse=True),
            "limit": limit,
            "warmup": warmup,
            "queue": queue or 0,
        }


class IPMsgs(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        start = req.get_param("start", required=True)
        end = req.get_param("end", required=True)
        domaingroupid = req.get_param("domaingroupid")
        ip = req.get_param("ip")
        settingsid = req.get_param("settingsid")
        sinkid = req.get_param("sinkid")
        msgtype = req.get_param("type", required=True)
        cid = req.get_param("cid")
        campid = req.get_param("campid")
        bcid = req.get_param("bcid")
        if bcid:
            campid = bcid

        try:
            start = (
                dateutil.parser.parse(start).astimezone(tzutc()).replace(tzinfo=None)
            )
            end = dateutil.parser.parse(end).astimezone(tzutc()).replace(tzinfo=None)
        except:
            raise falcon.HTTPBadRequest(
                title="Invalid parameter", description="invalid date parameter"
            )

        if cid is not None:
            it = db.execute(
                """
                select message, sinkid, ip, sum(count) cnt from statmsgs
                where ts >= %s and ts <= %s
                and campid in (select id from campaigns where cid = %s union all select id from messages where cid = %s)
                and msgtype = %s
                group by message, sinkid, ip
                order by cnt desc
                limit 100""",
                start,
                end,
                cid,
                cid,
                msgtype,
            )
        elif campid is not None:
            it = db.execute(
                """
                select message, sinkid, ip, sum(count) cnt from statmsgs
                where ts >= %s and ts <= %s
                and campid = %s
                and msgtype = %s
                group by message, sinkid, ip
                order by cnt desc
                limit 100""",
                start,
                end,
                campid,
                msgtype,
            )
        else:
            if (
                domaingroupid is None
                or ip is None
                or settingsid is None
                or sinkid is None
            ):
                raise falcon.HTTPBadRequest()
            it = db.execute(
                """
                select message, sinkid, ip, sum(count) cnt from statmsgs
                where ts >= %s and ts <= %s
                and domaingroupid = %s and ip = %s and settingsid = %s and sinkid = %s
                and msgtype = %s
                group by message, sinkid, ip
                order by cnt desc
                limit 100""",
                start,
                end,
                domaingroupid,
                ip,
                settingsid,
                sinkid,
                msgtype,
            )

        req.context["result"] = [
            {"msg": msg, "sinkid": sinkid, "ip": ip, "count": cnt}
            for msg, sinkid, ip, cnt in it
        ]


class IPStats(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        if not req.context["admin"]:
            raise falcon.HTTPUnauthorized()

        db = req.context["db"]

        start = req.get_param("start", required=True)
        end = req.get_param("end", required=True)

        try:
            start = (
                dateutil.parser.parse(start).astimezone(tzutc()).replace(tzinfo=None)
            )
            end = dateutil.parser.parse(end).astimezone(tzutc()).replace(tzinfo=None)
        except:
            raise falcon.HTTPBadRequest(
                title="Invalid parameter", description="invalid date parameter"
            )

        # postgres can't handle joining to this subquery for some reason so we do it ourselves
        statlogs = {}
        for ts, defermsg, deferlen, sinkid, ip, settingsid, domain in db.execute(
            """select ts, defermsg, deferlen, sinkid, ip, settingsid, domaingroupid
                                 from (
                                 select sinkid, ip, settingsid, domaingroupid,
                                 max(ts) as ts
                                 from statlogs2
                                 where cid = %s and
                                 domaingroupid != ''
                                 group by sinkid, ip, settingsid, domaingroupid
                                 ) o1
                                 inner join lateral
                                 (select defermsg, deferlen
                                 from statlogs2
                                 where cid = %s and
                                 ts = o1.ts and sinkid = o1.sinkid and ip = o1.ip and
                                 settingsid = o1.settingsid and domaingroupid = o1.domaingroupid
                                 ) o2 on true""",
            db.get_cid(),
            db.get_cid(),
        ):
            statlogs[(sinkid, ip, settingsid, domain)] = (ts, defermsg, deferlen)

        result = []
        for row in db.execute(
            """select h.sinkid, h.domaingroupid, h.ip, h.settingsid,
                               sum(send), sum(soft), sum(hard),
                               sum(complaint), sum(open), sum(err), sum(defercnt),
                               p.id, (p.data->>'discard')::boolean,
                               l.sendlimit, q.queue
                               from hourstats h
                               left join iplimits l on
                                 h.domaingroupid = l.domain and
                                 h.ip            = l.ip and
                                 h.settingsid    = l.settingsid and
                                 h.sinkid        = l.sinkid
                               left join ippauses p on
                                 h.domaingroupid = p.data->>'domaingroupid' and
                                 h.ip            = p.data->>'ip' and
                                 h.settingsid    = p.data->>'settingsid' and
                                 h.sinkid        = p.data->>'sinkid'
                               left join sinkdomainqueues q on
                                 h.domaingroupid = q.domain and
                                 h.sinkid        = q.sinkid
                               where h.ts >= %s and h.ts <= %s
                               and h.send+h.hard+h.soft+h.defercnt+h.err > 0
                               and h.cid = %s
                               group by h.sinkid, h.domaingroupid, h.ip, h.settingsid, p.id, p.data->>'discard',
                                        l.sendlimit, q.queue""",
            start,
            end,
            db.get_cid(),
        ):
            logresult = statlogs.get(
                (row[0], row[2], row[3], row[1]), (None, None, None)
            )
            result.append(
                {
                    "sinkid": row[0],
                    "domaingroupid": row[1],
                    "ip": row[2],
                    "settingsid": row[3],
                    "send": row[4],
                    "soft": row[5],
                    "hard": row[6],
                    "complaint": row[7],
                    "open": row[8],
                    "err": row[9],
                    "defercnt": row[10],
                    "ispaused": row[11] is not None,
                    "discard": row[12],
                    "sendlimit": row[13],
                    "queue": row[14] or 0,
                    "ts": logresult[0],
                    "defermsg": logresult[1],
                    "deferlen": logresult[2],
                }
            )

        req.context["result"] = result


class IPPauses(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        db = req.context["db"]

        force = []
        for pause in doc:
            if "$delete" in pause or "$forceStart" in pause:
                db.execute(
                    """delete from ippauses where data->>'domaingroupid' = %s and
                              data->>'ip' = %s and data->>'settingsid' = %s and
                              data->>'sinkid' = %s""",
                    pause["domaingroupid"],
                    pause["ip"],
                    pause["settingsid"],
                    pause["sinkid"],
                )
                if "$forceStart" in pause:
                    force.append(pause)
            else:
                pause.pop("id", None)
                pause.pop("cid", None)
                db.execute(
                    """insert into ippauses (id, cid, data) values (%s, %s, %s)
                              on conflict ((data->>'domaingroupid'), (data->>'ip'), (data->>'settingsid'), (data->>'sinkid'))
                              do update set data = excluded.data""",
                    shortuuid.uuid(),
                    db.get_cid(),
                    pause,
                )

        run_task(update_sinks, db.get_cid(), force)

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        db = req.context["db"]

        req.context["result"] = db.ippauses.get_all()


@tasks.task(priority=HIGH_PRIORITY)
def dkim_generate(cid: str, domain: str, gatherid: str) -> None:
    try:
        with open_db() as db:
            key = RSA.generate(1024)
            public = "v=DKIM1; p=%s" % "".join(
                key.publickey().exportKey().decode("ascii").split("\n")[1:-1]
            )
            private = key.exportKey().decode("ascii")

            db.execute(
                """update dkimentries set data = data ||
                            jsonb_build_object('entries', data->'entries' ||
                                jsonb_build_object(%s, data->'entries'->%s ||
                                    jsonb_build_object('txtvalue', %s, 'private', %s))) where cid = %s and data->'entries'->%s is not null""",
                domain,
                domain,
                public,
                private,
                cid,
                domain,
            )

            if gather_complete(db, gatherid, {}) is not None:
                run_task(update_sinks, cid, None)
    except:
        log.exception("error")


class DKIMEntries(object):

    def on_patch(self, req: falcon.Request, resp: falcon.Response) -> None:
        db = req.context["db"]
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        # load private keys or generate key
        existing = db.dkimentries.get_singleton()

        togenerate = []

        for domain, e in list(doc.get("entries", {}).items()):
            if e.get("txtvalue"):
                for edomain, ee in list(existing.get("entries", {}).items()):
                    if edomain == domain:
                        e["private"] = ee["private"]
                        break
            else:
                togenerate.append(domain)

        if len(togenerate):
            gatherid = gather_init(db, "dkim_generate", len(togenerate))
            for domain in togenerate:
                run_task(dkim_generate, db.get_cid(), domain, gatherid)

        db.dkimentries.patch_singleton(doc)

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        db = req.context["db"]
        req.context["result"] = db.dkimentries.get_singleton()
        for e in list(req.context["result"].get("entries", {}).values()):
            e.pop("private", None)


class ClientDKIMVerify(object):

    def on_post(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        mycid = db.get_cid()

        ret = db.clientdkim.get(id)
        if ret is None:
            raise falcon.HTTPForbidden()

        db.set_cid(None)
        company = db.companies.get(mycid)
        if company is None:
            raise falcon.HTTPForbidden()
        parentcompany = db.companies.get(company["cid"])
        if parentcompany is None:
            raise falcon.HTTPForbidden()
        demo = parentcompany.get("demo", False)
        db.set_cid(company["cid"])

        mgtarget = None
        if ret["mgentry"] is not None:
            mgtarget = db.mailgun.get(ret["mgentry"]["id"])
        if mgtarget is not None and not demo:
            try:
                res = requests.put(
                    f'{mg_domain(mgtarget)}/v3/domains/{ret["name"]}/verify',
                    auth=("api", mgtarget["apikey"]),
                )
                handle_mg_error(res)

                if res.json()["domain"]["state"] != "active":
                    raise Exception("Could not find required DNS records")
            except Exception as e:
                raise falcon.HTTPBadRequest(
                    title="Unable to verify domain",
                    description="Error verifying domain: %s" % e,
                )

        if not demo:
            verify_client_dkim_dns(ret)

        db.set_cid(mycid)

        db.clientdkim.patch(id, {"verified": True})


class ClientDKIMEntry(object):

    def on_delete(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        check_noadmin(req)

        db = req.context["db"]

        mycid = db.get_cid()

        ret = db.clientdkim.get(id)
        if ret is None:
            raise falcon.HTTPForbidden()

        db.set_cid(None)
        company = db.companies.get(mycid)
        if company is None:
            raise falcon.HTTPForbidden()
        parentcompany = db.companies.get(company["cid"])
        if parentcompany is None:
            raise falcon.HTTPForbidden()
        demo = parentcompany.get("demo", False)
        db.set_cid(company["cid"])

        mgtarget = None
        if ret["mgentry"] is not None:
            mgtarget = db.mailgun.get(ret["mgentry"]["id"])
        if mgtarget is not None and not demo:
            try:
                res = requests.delete(
                    f'{mg_domain(mgtarget)}/v3/domains/{ret["name"]}',
                    auth=("api", mgtarget["apikey"]),
                )
                handle_mg_error(res)
            except Exception as e:
                raise falcon.HTTPBadRequest(
                    title="Unable to remove domain",
                    description="Error removing domain: %s" % e,
                )

        db.set_cid(mycid)

        db.clientdkim.remove(id)


class ClientDKIMEntries(object):

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        db = req.context["db"]
        req.context["result"] = db.clientdkim.get_all()
        for e in req.context["result"]:
            if e["serverentry"]:
                e["serverentry"].pop("private", None)

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        check_noadmin(req)

        db = req.context["db"]
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        name = doc["name"].strip().lower()

        if db.clientdkim.find_one({"name": name}):
            raise falcon.HTTPBadRequest(
                title="Domain exists", description="Custom domain already exists"
            )
        if (
            db.single("select count(id) from clientdkim where cid = %s", db.get_cid())
            >= 10
        ):
            raise falcon.HTTPBadRequest(
                title="Domain limit reached",
                description="You have too many custom domains, please contact support",
            )

        mycid = db.get_cid()

        db.set_cid(None)
        company = db.companies.get(mycid)
        if company is None:
            raise falcon.HTTPForbidden()
        parentcompany = db.companies.get(company["cid"])
        if parentcompany is None:
            raise falcon.HTTPForbidden()
        demo = parentcompany.get("demo", False)
        db.set_cid(company["cid"])

        ret = {
            "name": name,
            "mgentry": None,
            "serverentry": None,
            "spfentry": None,
            "mx1entry": None,
            "mx2entry": None,
        }

        mgtarget = None
        for mg in db.mailgun.find():
            if mg.get("domaintarget", False):
                mgtarget = mg
                break
        if mgtarget is not None:
            if demo:
                js = {
                    "sending_dns_records": [
                        {
                            "record_type": "TXT",
                            "name": "e._domainkey.%s" % name,
                            "value": "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDeIhtCv3vUinyhKiKtZ8efjHGGo8gE1T+o7gLrvo6yRtdz9ICe6Fz5sgz0WYFW5nCV4DmaTcS25TfgWKsLggGSBdDxzShyvgdKJkG3b4+73rT/5opnRceqQf1qndnMZfkb/0/YciMKNQmigj9IGwKypj6CoIr1s46jRGy4Ws7LQIDAQAB",
                        }
                    ]
                }
            else:
                try:
                    res = requests.post(
                        f"{mg_domain(mgtarget)}/v3/domains",
                        auth=("api", mgtarget["apikey"]),
                        data={
                            "name": name,
                        },
                    )
                    handle_mg_error(res)

                    js = res.json()

                    if "sending_dns_records" not in js:
                        raise Exception(js["message"])
                except Exception as e:
                    raise falcon.HTTPBadRequest(
                        title="Unable to add domain",
                        description="Error adding domain: %s" % e,
                    )

            for rec in js["sending_dns_records"]:
                if rec["record_type"] == "TXT" and "p=" in rec["value"]:
                    ret["mgentry"] = {
                        "id": mgtarget["id"],
                        "type": "TXT",
                        "name": rec["name"],
                        "value": rec["value"],
                    }
            ret["spfentry"] = {
                "type": "TXT",
                "name": name,
                "value": "v=spf1 include:%s ~all" % mgtarget["domain"],
            }
            ret["mx1entry"] = {
                "type": "MX",
                "name": name,
                "value": "10 mx1.%s" % mgtarget["domain"],
            }
            ret["mx2entry"] = {
                "type": "MX",
                "name": name,
                "value": "10 mx2.%s" % mgtarget["domain"],
            }

        has_local_mta = db.single("select count(id) from sinks where cid = %s", db.get_cid())
        if has_local_mta or mgtarget is None:
            key = RSA.generate(1024)
            public = "v=DKIM1; p=%s" % "".join(
                key.publickey().exportKey().decode("ascii").split("\n")[1:-1]
            )
            private = key.exportKey().decode("ascii")

            mgselector = None
            if ret["mgentry"]:
                mgselector = ret["mgentry"]["name"].split(".")[0]
            selector = "edcom"
            i = 2
            while selector == mgselector:
                selector = "edcom%s" % i
                i += 1

            ret["serverentry"] = {
                "name": "%s._domainkey.%s" % (selector, name),
                "type": "TXT",
                "value": public,
                "private": private,
                "selector": selector,
            }

        db.set_cid(mycid)

        req.context["result"] = db.clientdkim.get(db.clientdkim.add(ret))
        if req.context["result"]["serverentry"]:
            req.context["result"]["serverentry"].pop("private", None)


class Mailguns(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "mailgun"
        self.adminonly = True
        self.userlog = "Mailgun account"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        doc["policytype"] = "mailgun"

        if doc.get("domaintarget", False):
            db = req.context["db"]
            db.execute(
                """update mailgun set data = data || '{"domaintarget": false}' where cid = %s""",
                db.get_cid(),
            )

        CRUDCollection.on_post(self, req, resp)


class Mailgun(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "mailgun"
        self.adminonly = True
        self.userlog = "Mailgun account"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        doc.pop("policytype", None)

        if doc.get("domaintarget", False):
            db = req.context["db"]
            db.execute(
                """update mailgun set data = data || '{"domaintarget": false}' where cid = %s""",
                db.get_cid(),
            )

        return CRUDSingle.on_patch(self, req, resp, id)

    def del_check(self, db: DB, id: str) -> None:
        for route in db.routes.find():
            for rule in route["rules"]:
                for s in rule["splits"]:
                    if s["policy"] == id:
                        raise falcon.HTTPBadRequest(
                            title="Account in use",
                            description="This account is used by one or more postal routes",
                        )


class SESs(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "ses"
        self.adminonly = True
        self.userlog = "SES account"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        doc["policytype"] = "ses"

        CRUDCollection.on_post(self, req, resp)

        db = req.context["db"]

        ses = db.ses.get(req.context["result"]["id"])
        if ses is None:
            raise falcon.HTTPForbidden()
        try:
            setup_ses_webhooks(ses)
        except Exception as e:
            db.ses.remove(ses["id"])
            del req.context["result"]
            raise falcon.HTTPBadRequest(title="SES Error", description=str(e))


class SES(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "ses"
        self.adminonly = True
        self.userlog = "SES account"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        doc.pop("policytype", None)

        try:
            setup_ses_webhooks(doc)
        except Exception as e:
            raise falcon.HTTPBadRequest(title="SES Error", description=str(e))

        return CRUDSingle.on_patch(self, req, resp, id)

    def del_check(self, db: DB, id: str) -> None:
        for route in db.routes.find():
            for rule in route["rules"]:
                for s in rule["splits"]:
                    if s["policy"] == id:
                        raise falcon.HTTPBadRequest(
                            title="Account in use",
                            description="This account is used by one or more postal routes",
                        )


class Sparkposts(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "sparkpost"
        self.adminonly = True
        self.userlog = "Sparkpost account"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        doc["policytype"] = "sparkpost"

        CRUDCollection.on_post(self, req, resp)

        db = req.context["db"]

        sparkpost = db.sparkpost.get(req.context["result"]["id"])
        if sparkpost is None:
            raise falcon.HTTPForbidden()
        try:
            setup_sparkpost_webhooks(sparkpost)
        except Exception as e:
            db.sparkpost.remove(sparkpost["id"])
            del req.context["result"]
            raise falcon.HTTPBadRequest(title="Sparkpost Error", description=str(e))


class Sparkpost(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "sparkpost"
        self.adminonly = True
        self.userlog = "Sparkpost account"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        doc.pop("policytype", None)

        try:
            setup_sparkpost_webhooks(doc)
        except Exception as e:
            raise falcon.HTTPBadRequest(title="Sparkpost Error", description=str(e))

        return CRUDSingle.on_patch(self, req, resp, id)

    def del_check(self, db: DB, id: str) -> None:
        for route in db.routes.find():
            for rule in route["rules"]:
                for s in rule["splits"]:
                    if s["policy"] == id:
                        raise falcon.HTTPBadRequest(
                            title="Account in use",
                            description="This account is used by one or more postal routes",
                        )


class Easylinks(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "easylink"
        self.adminonly = True
        self.userlog = "Easylink account"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        doc["policytype"] = "easylink"

        return CRUDCollection.on_post(self, req, resp)


class Easylink(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "easylink"
        self.adminonly = True
        self.userlog = "Easylink account"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        doc.pop("policytype", None)

        return CRUDSingle.on_patch(self, req, resp, id)

    def del_check(self, db: DB, id: str) -> None:
        for route in db.routes.find():
            for rule in route["rules"]:
                for s in rule["splits"]:
                    if s["policy"] == id:
                        raise falcon.HTTPBadRequest(
                            title="Account in use",
                            description="This account is used by one or more postal routes",
                        )


class SMTPRelays(CRUDCollection):

    def __init__(self) -> None:
        self.domain = "smtprelays"
        self.adminonly = True
        self.userlog = "SMTP Relay"

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        doc = req.context.get("doc")
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )

        doc["policytype"] = "smtprelay"

        return CRUDCollection.on_post(self, req, resp)


class SMTPRelay(CRUDSingle):

    def __init__(self) -> None:
        self.domain = "smtprelays"
        self.adminonly = True
        self.userlog = "SMTP Relay"

    def on_patch(self, req: falcon.Request, resp: falcon.Response, id: str) -> None:
        doc = req.context["doc"]
        if not doc:
            raise falcon.HTTPBadRequest(
                title="Not JSON", description="A valid JSON document is required."
            )
        doc.pop("policytype", None)

        return CRUDSingle.on_patch(self, req, resp, id)

    def del_check(self, db: DB, id: str) -> None:
        for route in db.routes.find():
            for rule in route["rules"]:
                for s in rule["splits"]:
                    if s["policy"] == id:
                        raise falcon.HTTPBadRequest(
                            title="Relay in use",
                            description="This relay is used by one or more postal routes",
                        )
