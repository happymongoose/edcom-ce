import os
import re
import msgpack
import json
import base64
import random
import hashlib
import requests
import string
import time
from functools import wraps
import falcon
import redis
import shortuuid
import dateutil.parser
from datetime import datetime, timedelta
from dateutil.tz import tzutc, tzlocal, tzoffset
from io import StringIO, IOBase
from random_words.random_words import Random as RandomWordDB
from urllib.parse import urlparse
from html import escape as html_escape
from typing import Tuple, Dict, List, Any, cast, Callable

from .db import json_iter, json_obj, JsonObj, DB
from .s3 import s3_write, s3_size
from . import jsnotify
from . import foundation
from .html_sanitizer import sanitize_email_html
from .log import get_logger

log = get_logger()

PERIOD_CREDITS = 100000000
REFILL_CREDITS = 50000
REFILL_CHARGE = 25.00
TRIAL_DAYS = 10

SECS_IN_DAY = 60 * 60 * 24

MTA_TIMEOUT = 10

GIF = b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00\xFF\xFF\xFF\x21\xF9\x04\x01\x00\x00\x01\x00\x2C\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x4C\x01\x00\x3B"

rdb: redis.StrictRedis | None = None  # type: ignore


def debug() -> None:
    import debugpy

    debugpy.listen(("0.0.0.0", 5678))
    print("⏳ VS Code debugger can now be attached, press F5 in VS Code ⏳", flush=True)
    debugpy.wait_for_client()


def find_user(db: DB, username: str) -> JsonObj | None:
    return json_obj(
        db.row(
            "select id, cid, data from users where lower(trim(data->>'username')) = lower(trim(%s))",
            username,
        )
    )


def get_webhost() -> str:
    try:
        o = urlparse(os.environ["webroot"])
        return o.netloc
    except:
        return "localhost"


def get_webroot() -> str:
    webroot = os.environ["webroot"]
    while webroot.endswith("/"):
        webroot = webroot[:-1]
    return webroot


def get_webscheme() -> str:
    try:
        o = urlparse(os.environ["webroot"])
        return o.scheme
    except:
        return "http"


def fix_sink_url(url: str) -> str:
    if url.lower().startswith("http://") or url.lower().startswith("https://"):
        if url.endswith("/"):
            return url[:-1]
        return url
    return "http://" + url + ":81"


# for user input that may or may not be a valid url
def domain_only(url: str) -> str | None:
    try:
        parsed_url = urlparse(url)
        if parsed_url.scheme and parsed_url.netloc:
            return parsed_url.hostname
        else:
            return url
    except:
        return url


def fix_empty_limit(limit: None | str | int) -> None | int:
    if isinstance(limit, str):
        return None
    return limit


nlre = re.compile(r"[\r\n]")


def remove_newlines(s: str) -> str:
    return nlre.sub("", s)


printable = set(string.printable)


def try_decode(data: bytes) -> str:
    try:
        strdata = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            strdata = data.decode("iso-8859-1")
        except UnicodeDecodeError:
            strdata = "".join(chr(x) for x in data if chr(x) in printable)

    return strdata


def handle_sp_error(r: requests.Response) -> None:
    if r.status_code < 200 or r.status_code > 299:
        log.error("Sparkpost Error for %s: %s %s", r.url, r.status_code, r.text)
        try:
            raise Exception(r.json()["errors"][0]["message"])
        except:
            raise Exception(r.text)


def handle_mg_error(r: requests.Response) -> None:
    if r.status_code < 200 or r.status_code > 299:
        log.error("Mailgun Error for %s: %s %s", r.url, r.status_code, r.text)
        try:
            raise Exception(r.json()["message"])
        except ValueError:
            raise Exception(r.text)


def open_ticket(subject: str, message: str, user: JsonObj) -> str:
    r = requests.post(
        "https://%s/api/v2/users/create_or_update.json" % (os.environ["zendesk_host"],),
        json={
            "user": {
                "email": user["username"],
                "name": user["fullname"],
                "verified": True,
            }
        },
        auth=("%s/token" % os.environ["zendesk_user"], os.environ["zendesk_key"]),
    )
    r.raise_for_status()

    userid = r.json()["user"]["id"]

    r = requests.post(
        "https://%s/api/v2/tickets.json" % (os.environ["zendesk_host"],),
        json={
            "ticket": {
                "subject": subject,
                "comment": {"body": message},
                "requester_id": userid,
            },
        },
        auth=("%s/token" % os.environ["zendesk_user"], os.environ["zendesk_key"]),
    )
    r.raise_for_status()

    return cast(str, r.json()["ticket"]["id"])


def set_onboarding(db: DB, cid: str, id: str, status: str) -> None:
    db.execute(
        "update companies set data = data || jsonb_build_object('onboarding', coalesce(data->'onboarding', '{}'::jsonb) || jsonb_build_object(%s, %s)) where id = %s",
        id,
        status,
        cid,
    )


def create_txnid(tagid: str) -> str:
    msgid = shortuuid.uuid()
    return "".join(a + b for a, b in zip(msgid, tagid))


def parse_txnid(txnid: str) -> Tuple[str, str]:
    msgid = "".join(txnid[x] for x in range(len(txnid)) if (x % 2) == 0)
    tagid = "".join(txnid[x] for x in range(len(txnid)) if (x % 2) != 0)
    return msgid, tagid


def get_txn(db: DB, campid: str) -> Tuple[str, str, str] | Tuple[None, None, None]:
    msgid, tagid = parse_txnid(campid)
    tagrow = db.row("select cid, tag from txntags where id = %s", tagid)
    if tagrow is None:
        return None, None, None
    campcid, tag = tagrow
    return campcid, tag, msgid


def funnel_published(funnel: JsonObj) -> None:
    msgs = funnel["messages"]
    funnel["messages"] = [
        msgs[i] for i in range(len(msgs)) if i == 0 or not msgs[i].get("unpublished")
    ]


def get_funnels(
    db: DB, cid: str
) -> Tuple[Dict[str, List[JsonObj]], Dict[str, JsonObj]]:
    tagret: Dict[str, List[JsonObj]] = {}
    respret: Dict[str, JsonObj] = {}

    oldcid = db.get_cid()
    db.set_cid(cid)
    try:
        msgvals = {}
        for mid, who, days, dayoffset in db.execute(
            "select id, data->>'who', data->'days', data->'dayoffset' from messages where cid = %s",
            cid,
        ):
            msgvals[mid] = (who or "all", days, dayoffset or 0)

        for funnel in db.funnels.find({"active": True}):
            funnel_published(funnel)
            msgs = funnel["messages"]
            if len(msgs):
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
                if funnel["type"] == "tags":
                    for tag in funnel["tags"]:
                        fixed = fix_tag(tag)
                        if not fixed:
                            continue
                        if fixed not in tagret:
                            tagret[fixed] = []
                        tagret[fixed].append(funnel)
                respret[funnel["id"]] = funnel
    finally:
        db.set_cid(oldcid)

    return tagret, respret


def insert_funnel_tag(
    db: DB,
    cid: str,
    email: str,
    tag: str,
    funnels: Dict[str, List[JsonObj]],
    funnelcounts: Dict[str, int],
) -> None:
    for funnel in funnels.get(tag, ()):
        insert_funnel(db, cid, email, funnel, 0, funnelcounts)


def funnel_next_time(m: JsonObj) -> datetime:
    offset = m["dayoffset"]
    days = m["days"]

    tz = tzoffset("", timedelta(minutes=offset))
    ts = datetime.now(tz)
    if m["whentype"] == "mins":
        ts += timedelta(minutes=m["whennum"])
    elif m["whentype"] == "hours":
        ts += timedelta(hours=m["whennum"])
    else:
        ts += timedelta(days=(m["whennum"] - 1))

        if not m.get("whentime"):
            whentime = datetime(2019, 1, 1, 9, 0, 0, 0, tz)
        else:
            whentime = dateutil.parser.parse(m["whentime"]).astimezone(tz)

        # time is after the time we want, need to jump to the next day
        if whentime.time() < ts.time():
            ts += timedelta(days=1)

        ts = ts.replace(
            hour=whentime.hour,
            minute=whentime.minute,
            second=whentime.second,
            microsecond=whentime.microsecond,
        )

    while True:
        if days is None or days[ts.weekday()]:
            break
        ts += timedelta(days=1)

    return ts


def insert_funnel(
    db: DB,
    cid: str,
    email: str,
    funnel: JsonObj,
    index: int,
    funnelcounts: Dict[str, int] | None,
) -> None:
    if not funnel.get("multiple", False):
        # make sure they werent sent this message already
        if db.single(
            "select count(id) from funnelqueue where email = %s and messageid = %s",
            email,
            funnel["messages"][index]["id"],
        ):
            return
    else:
        # make sure they arent about to be sent this message already
        if db.single(
            "select count(id) from funnelqueue where email = %s and messageid = %s and not sent",
            email,
            funnel["messages"][index]["id"],
        ):
            return

    # figure out when to send it
    ts = funnel_next_time(funnel["messages"][index])

    domain = email.split("@")[1]

    db.execute(
        "insert into funnelqueue (email, rawhash, messageid, domain, ts, cid) values (%s, %s, %s, %s, %s, %s)",
        email,
        get_contact_id(db, cid, email),
        funnel["messages"][index]["id"],
        domain,
        ts,
        cid,
    )
    if funnelcounts is not None:
        funnelcounts[funnel["id"]] = funnelcounts.get(funnel["id"], 0) + 1


def incr_funnel_counts(db: DB, funnelcounts: Dict[str, int]) -> None:
    for fid, cnt in funnelcounts.items():
        db.execute(
            "update funnels set data = data || jsonb_build_object('count', (data->>'count')::integer + %s) where id = %s",
            cnt,
            fid,
        )


def get_contact_id(db: DB, cid: str, email: str) -> int:
    contact_id: int | None = db.single(
        f"""
        select contact_id from contacts."contacts_{cid}" where email = %s
    """,
        email,
    )
    if contact_id is None:
        contact_id = 999999999
    return contact_id


BROWSER_UNKNOWN = 0
BROWSER_FIREFOX = 1
BROWSER_CHROMIUM = 2
BROWSER_CHROME = 3
BROWSER_SAFARI = 4
BROWSER_OPERA = 5
BROWSER_MSIE = 6
BROWSER_ROBOT = 7
BROWSER_OUTLOOK = 8
BROWSER_THUNDERBIRD = 9

browser_names = {
    BROWSER_UNKNOWN: "Unknown",
    BROWSER_FIREFOX: "Firefox",
    BROWSER_CHROMIUM: "Chromium",
    BROWSER_CHROME: "Chrome",
    BROWSER_SAFARI: "Safari",
    BROWSER_OPERA: "Opera",
    BROWSER_MSIE: "MSIE",
    BROWSER_ROBOT: "Robot",
    BROWSER_OUTLOOK: "Outlook",
    BROWSER_THUNDERBIRD: "Thunderbird",
}


def get_browser(agent: str) -> int:
    if "firefox" in agent:
        return BROWSER_FIREFOX
    if "chromium" in agent:
        return BROWSER_CHROMIUM
    if "chrome" in agent:
        return BROWSER_CHROME
    if ("safari" in agent) or ("applewebkit" in agent):
        return BROWSER_SAFARI
    if "opr" in agent or "opera" in agent:
        return BROWSER_OPERA
    if "msie" in agent or "trident" in agent:
        return BROWSER_MSIE
    if "bot" in agent:
        return BROWSER_ROBOT
    if "outlook" in agent:
        return BROWSER_OUTLOOK
    if "thunderbird" in agent:
        return BROWSER_THUNDERBIRD
    return BROWSER_UNKNOWN


OS_UNKNOWN = 0
OS_WINDOWS = 1
OS_IOS = 2
OS_ANDROID = 3
OS_MAC = 4
OS_LINUX = 5

os_names = {
    OS_UNKNOWN: "Unknown",
    OS_WINDOWS: "Windows",
    OS_IOS: "iOS",
    OS_ANDROID: "Android",
    OS_MAC: "Mac",
    OS_LINUX: "Linux",
}


def get_os(agent: str) -> int:
    if "windows" in agent:
        return OS_WINDOWS
    if ("ios" in agent) or ("iphone" in agent) or ("ipad" in agent):
        return OS_IOS
    if "android" in agent:
        return OS_ANDROID
    if "macintosh" in agent:
        return OS_MAC
    if "linux" in agent:
        return OS_LINUX
    return OS_UNKNOWN


DEVICE_UNKNOWN = 0
DEVICE_PHONE = 1
DEVICE_TABLET = 2
DEVICE_PC = 3

device_names = {
    DEVICE_UNKNOWN: "Unknown",
    DEVICE_PHONE: "Phone",
    DEVICE_TABLET: "Tablet",
    DEVICE_PC: "PC",
}


def get_device(agent: str) -> int:
    if "ipad" in agent:
        return DEVICE_TABLET
    if "mobi" in agent:
        return DEVICE_PHONE
    os = get_os(agent)
    if os == OS_UNKNOWN:
        return DEVICE_UNKNOWN
    elif os in (OS_IOS, OS_ANDROID):
        return DEVICE_TABLET
    else:
        return DEVICE_PC


def run_tasks(paramsets: List[Tuple[Any, ...]]) -> None:
    for paramset in paramsets:
        run_task(*paramset)
    return


def redis_connect() -> Any:
    global rdb
    if rdb is None:
        rdb = redis.StrictRedis(
            host=os.environ["redis_host"],
            port=int(os.environ["redis_port"]),
            password=os.environ["redis_pass"],
        )
    return rdb


def djb2(s: str) -> int:
    h = 5381
    for x in s.encode("utf-8"):
        h = ((h << 5) + h) + x
    return h & 0xFFFFFFFF


fixtagre = re.compile(r"[^a-zA-Z0-9_ .#]")


def fix_tag(t: str) -> str:
    return fixtagre.sub("", t.lower().strip())


emailre = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

md5re = re.compile(r"^[A-Fa-f0-9]{32}$")


def is_true(s: str | None) -> bool:
    if s is None:
        return False
    s = s.strip().lower()
    return s not in ("", "false", "f", "n", "no")


class MPDictWriter(object):

    def __init__(self, stream: IOBase, headers: List[str] | Tuple[str, ...]) -> None:
        headers = list(headers)

        self.stream = stream
        self.headers = headers
        self.headerdict = {}
        for i in range(len(headers)):
            self.headerdict[headers[i]] = i

    def writeheader(self) -> None:
        msgpack.pack(self.headers, self.stream)

    def writerow(self, row: Dict[str, str]) -> None:
        r = {}
        for k, v in row.items():
            if k in self.headerdict and v:
                r[self.headerdict[k]] = v
        msgpack.pack(r, self.stream)


class MPDictReader(object):

    def __init__(self, stream: IOBase) -> None:
        self.unpacker = msgpack.Unpacker(stream, strict_map_key=False)
        self.headers = self.unpacker.unpack()

    def __iter__(self) -> "MPDictReader":
        return self

    def __next__(self) -> JsonObj:
        try:
            row = self.unpacker.unpack()
            r = {}
            for i in range(len(self.headers)):
                r[self.headers[i]] = row.get(i, "")
            return r
        except msgpack.exceptions.OutOfData:
            raise StopIteration()


urlstartre = re.compile(r"^[a-zA-Z]+:")
linkre = re.compile(r'(<\s*a\s+[^>]*href\s*=\s*")([^"]+)("[^>]*>)', re.I)
imgre = re.compile(r'(<\s*img\s+[^>]*src\s*=\s*")(data:[^"]+)', re.I)
localimgre = re.compile(r'(<\s*img\s+[^>]*src\s*=\s*")(https?:[^"]+)', re.I)
unsubre = re.compile(r"\{\{!!unsublink\}\}")
unsublinkre = re.compile(r"\{\{!!unsublink\|")
notrackre = re.compile(r"\{\{!!notrack\|")
paramre = re.compile(r"\{\{[^\}]+\}\}")
bodystartre = re.compile(r"<\s*body\s*>", re.I)
bodyre = re.compile(r"<\s*/\s*body\s*>", re.I)
socialre = re.compile(
    r'src="/img/(facebook|twitter|instagram|pinterest|linkedin)-icon.png"'
)

socialimgs = {
    "facebook": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAAEi6oPRAAAAAXNSR0IArs4c6QAAA3ZJREFUeAHtm79rFUEQxxPzVBARxMJGsLEWbG0kjf4jqfwbBNNH0MJCEP8DWysRbYKWdhYSCYgW4g9UEoKQPL+T3B379s3e7N7eT/guTN7uzOzs7Of29l7u7q2sdFbm8/kryHEJDlLYH7sOq25DHNz2KorbrupFpIeVApVTbiNUj3IKde5LX8xuAcXS2D4rcViA5ToEQUov11HaUqI4RTmdxBvVX0x4BtmFHEF+acktoNQc0HHpAGmYUyA9kgBStAFVpThqmZQBQsFKu/opAYuycIb5zilT8/uyPWoCOPxbxRI4CiU6CxlKvQQo6/gMLuDadYQYD5wgzasIdCAZSbGi1GZkdXbtaiAksFlkcbZ0lraUsu1/qoF8p+w2EhgJoyZTaY1Ra4GazIJ9SGDEBLBFvJSNKlRSUjevIHXBkMBp2P/V+aTashLCYB+UAffwHey8oo9S5e5EV5RRniq6blQ4RPdC66ROn5JNKqHcQ2zmlprQezPissPPZVVHGhym6huBc8hq/y+wUkklZMXLtjMhC+HoCFkJ004CJEACJNCUAK72dyBvIXvFlV/ulh5C1lNiZn/hwoCXMOB3ZVC5pSRyC/JasauqrGsZkllDVC0ZdbAYZVZCGGAnZpAUn9yErkYM9jXCpx0XHDKtXM6JHryXGRNUsvH9Gt2od4LkHjInVDvVaSfkLxiNie+D9nXNL6Trg5DsVdGlj4SikxHHySd0mDTdE+fdlD7chyxak19D1gSz7SRkISQhErII0E4CJEACJEACJEACJEACkyeAW1prkA3IDiS1bHYFIPuZQm5iICHPJN5BruXG6qL/oP+xAs4GJiXPSEYJR4APBghwbmP8/l7Cktk2KFl3FhuMV3UBoG00blaK+so3mJ9A5CGYvBblPln5g/Y2nqwEX2GHfXoFgH5DYsrzIWc32CmGSVfv1RsAPhv2Ts1DAup0Ym0F72wPwrkjV6YtyIVAsuvQx4wvK+hjIIaoxXZ3cnsQAB3/RCVmk2nB50YNwCwTTzEDHwERkEHAMMdskkaIsBl7y0VYzwU8PkF/JmBz1c/QuO8qvPoPbNAHnq615qy1SEogJC6/X1Z/wywbs9JFU/1FnC+aoQ8d9yCDMgERkEHAMHMFEZBBwDBzBRGQQcAwcwWNGNALIzcx70PeSIWFBEiABEiABEgglcB/25l4td3evzYAAAAASUVORK5CYII=",
    "twitter": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAAEi6oPRAAAAAXNSR0IArs4c6QAABXNJREFUeAHtm0+oVUUcx59a/nn0h17PLHrQorRCiXBRtKgWQmUS0a6iWtSmoqBFy2oTFGQUBKVQESXUIheF6cJQsWhjkgYWaWWKEQhmoJVW6uvztTOXOfPmzJlzztz7Lq/5wffNzG9+/873zDvnnrnnjoz0XSYnJ2eZJLNNB+Wk0z+D6qB0PWvbyBjPQtTvRTIKY2C3PaNCuc5MhpyMzdC10PGktyjDk1ojxrBEgSbNhN3aRt/YEzZPvdMiAzuSbWQ7z/i+TYJ9sNI78qU9P6XvGGv4mUfnPXelYDjt8jm6upJT1QCnD1xHa3y6yq+ktxzc7o0lwzz4PzHAWhgHD0YdM4av+gzdBaWxz66nY35P4fRsT0mn0JUae97bL1n/N3jRozvjdTZKHHZ6nHyqN42PaUsXZCnlZSarWt/F2r78G78tptOknVKRnENV+aqRj6+ikSpj7OfIySelQFTylKqRuMYKjoTPluuUx5mBzMDwMsD/+byz/+1T/xxS1cX8Ztorq46idAVxjXA8ZMWe587bY+y+YnzS1ln9CcVh/D1QnI+tufguMR5SII887Ubx2HhVrp87DjKE8fVg1HVivNrN5rHxqfb4lLbOexsyBiS9gv4BM07QjnPj+DUUJ8gQzgeBin4jFCRybjOhgsUoTrAgK9E+q9+m+wnF3N7GMejDKdS/9UbwD4iVc4JB20yS+Q4Q+wlOhdaemqo6Yk/ZtwTYWxHkb/SvgFGtt0IurrDN6sxAZiAzkBnIDMx4BoKfGNsePXf7e/BdArZysw1vATdJQuB7G9q/g49PblIcJlaCuA1dX+Ii8mrfnKvD9v3Cvq5Z4PpGj63Ia+ucLNtQ93Umfwfn1cXzzjuR/2A832eI/nHHNjRc6othdLGfGGWv57MTZNLT7CUmQNEuc8ZVwwkWeenbI9ewrqDHXAfGE+BwQcFx2ncZj3vsfKrDPmWUjkTzwWKwHiSRmMTB65CqiAkSa6MHgDrbulN2qi5Ag/movde6gi5skLDO9IU6A83XUshZ05Onnr1qbRWwSmJOl3zrGJLN3WATOKFBS/ki1i/qqLsu7lh2VHQMQ7LrsmGwQgH6IjD1KLD3HUVeSDb2pRATlMyLQtmduTXGL2lLkovAS06yumGjz1FRBZNxLjhSl9mZ3xoVvKsRSZ8A+53kZribTvrtuq5FZ//MQGYgM5AZyAxkBjIDmYHMQGYgM5AZmFkM8PB5M9gCTgGfaNPjOeB7negsGczdAFYOlBkSXgskUV+BNCmOmNqJ/lzBG4r2858HG4C+cDCiN0AGK2TebrIX7cspKiDWnU7cLsMdOI+BUXAfeCRFjVExSHYM+ES/57g6KohjhN8SX8AEuqPEuMpJFzWM3Xn1BdvmU6LT64XfFQf1E+0DIHbn9uGKmG3VO3G8jK3oMfBD2yCt/DjoBeA30EROY7wNaFfwOjDHTs74GZBSFtnx2/SjvkwIBeZoPmJe34AMmxxh1SzsWlTrfzGI+RPoW7hrwAZwvGsxif13p4jXmiCS62dIWoG6IN8FzgfDJG9PezGsoNfAMMqOVOSkuAZdQDEfgttSFZUgznKuP7sSxEkbgqW0DKwFP0/jsro15VHFfj4J5oQMvSG1H1waNOz/5CpWzvaUabpcpHt1UJRecLgcvNdTDrbzC+kWUodethhuYTXNBvr10AEwCIl6v2aoWYOlVSD1dUk/uz93qA+8qjgKXwreAidBahnuFcPR3gI2ga+BVsVfoN+yngTTfQOoWg/VeorWA+v94FOgB9EUom2UNWB5debBzXT+oFhVKgeoJ+nFQL/fEsbAXKBntmPgKNDvwH7k7tP+zW4CZMkMZAYyA5mBzEBmIDOQGUjPwL/eSCbbMp5NfgAAAABJRU5ErkJggg==",
    "instagram": "data:image/png;base64,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",
    "pinterest": "data:image/png;base64,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",
    "linkedin": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAAEi6oPRAAAAAXNSR0IArs4c6QAABM1JREFUeAHtWz1oFEEUTmIwIgaREEFFbYIYsFMbxUKwUHsR8YeIhYVgY6lgIVpoI9pYqYUgQQsR0UYRtbAQRBGrNCaI/6IYTdTEn+/t7ey+nXszs7d7e3PRGXg3b97/fDM3e7e319HR9PYHrVTQTuVNkTrR9Igk61JGvCcFNSUTjZRS9bmMlHEre0z7kT71YvkRZR9FQttZ62qvKpoOQbR+HEgy1I26lTfvdaMermwTHnN/ANpdqhwEGKyB2Phu10FaxytBULVW0TKoJNRzO+L1QLp+Qgng+zVezymS6cFcgRI9gsyjAOhnU6+3xFBXxGPRyWAbxF4QwN5YAHpRJHly8pIz32T6YeIKbtpHN1yOrdHT1OL2ijKqAfpR0Gk2th8zzFAPNMV0il3Ip2fCiNsQ303gU2OKt4x3HiPKdlIxpj5vRe9NAZQ8byBlb+zbL5Cx1KAICLQPAjhx+tWpw/qz3ipEEc9ZIQnrrSBKjCrWgr7F1Zz0WkwzkmMiPaClzYhF6CQfZWOEqIsudJQA/B4mVyxdQZ+pgaG/ZCuwzKE/LQReBtkqQc5F9L3qJRdwvkxBdR/6KXDtep6+QtTPE8b8EkEWicoUJPmO6YlQ2gddZhtLQW32XFfGl8fJ8GWCzspEatLgnypIvHfQJKBCmIBAQCAgEBDIhQA+t5wCfQJdz+VQpRGKeAfKtCrzOWNnKkkHu5yOJQ0avdpHN2VL5rS685tHGUOA8h2CzI1++mCaMapgYEQIuecg3/045xj6uRXk/89DYtkXgTLLXhiS9I2VcjxYKk050mPUC5pMpQlHy+5sxk1KYXRvvqklPex7QeO6Hx/zGFyueOOmVgYN9tZiKBYm8sUWs9kF2XIpHS2p8QtCFQVtp2Whhgq2qSq0/qA2dg9pj+iNe+m6eHyR2xAP+Q/B9rFu5xwLQTKbXNJDVoc4ZEcF28+mAuoCmAzzyLFKvwW7J4JsviCLRE0tyJDkp0EuiltRkJjYJAwFmZBR8oCQQsLUB4RMyAR5QCAgEBAICAQEAgIBgYBAQKASBPAtfRPojfBtXYlugan85nElkysbFBM/o1Bw9L+gHyibb8b5Y9LjDmC4+sSMm6BWcJEvrNe0GLZhI7a2ODNLhy1yADTNt4rGj2BsfFRpZs22ZLUAogs0ADLevSyZIri3MwLGX6RMRWOnrIBug0nP5BO4d36ZjSMW/ivBrNflwpj+QTTM5fBdjPEh0GbQIIjX/xHjuyD6z8YwfOln4tY3FCk9hApxXUseTOVVwmqozlIWjJIfVH2g6J97splVeg7aUs8PFrmK8fkW4aWHZsU4mNx5KOjR0DWigVu4HyZ0MRlym8oWPgCSfrKSqqMnjfdKigKyCwDpSAG/DuNvr0WC5fTJ/BCZ04fMHoLugUZAfaAtoI2gvO0YQLqDs4niVNeQpOwZtAMx8jZ6e2y1zQb6w3mDwe6KLZak8/EW65QKMchWY8VvGnSRGPrjYK7abJiu4bPMB0CsXiv7GpN/arVIlbdT1sott2oFpQ+A8u6gKaFek2jMpNDkeXMnbu0MUFKkTyYA5EDfB0A+cjpgMKt9FNvwOWAuv3qND4B85CyMpI9ifeQMABVGwOHoYzV95HTAENQBgYBAQCAgEBD4FxH4C3drhmk8CEZ3AAAAAElFTkSuQmCC",
}


def style(p: Dict[str, Any], form: bool) -> str:
    s = {
        "box-sizing": "border-box",
        "-webkit-box-sizing": "border-box",
        "-moz-box-sizing": "border-box",
        "border-spacing": "0",
        "border-collapse": "collapse",
        "text-align": p.get("align", "center") or "center",
        "padding-top": "%spx" % p.get("paddingTop", 0) or 0,
        "padding-right": "%spx" % p.get("paddingRight", 0) or 0,
        "padding-bottom": "%spx" % p.get("paddingBottom", 0) or 0,
        "padding-left": "%spx" % p.get("paddingLeft", 0) or 0,
    }

    if form:
        s["width"] = "100%"
        if p.get("bodyType", "fixed") == "fixed":
            s["min-width"] = "%spx" % (p.get("bodyWidth", 580),)
    else:
        if p.get("bodyType", "fixed") == "fixed":
            s["width"] = "%spx" % (p.get("bodyWidth", 580),)
        else:
            s["width"] = "100%"
    if not form:
        if p.get("backgroundColor", None) is not None:
            s["background-color"] = p["backgroundColor"] or "#ffffff"
        if p.get("backgroundType", "color") == "img":
            s["background"] = "url(%s)" % p.get("backgroundImage", "")
            if p.get("backgroundSize", None) == "cover":
                s["background-size"] = "cover"
    if p.get("color", None) is not None:
        s["color"] = p["color"]
    if p.get("fontSize", None):
        s["font-size"] = "%spx" % p["fontSize"]
    if p.get("fontFamily", None) is not None:
        s["font-family"] = p["fontFamily"]
    if p.get("lineHeight", None) is not None:
        s["line-height"] = p["lineHeight"]

    return ' style="%s"' % ("; ".join("%s: %s" % (k, v) for k, v in list(s.items())))


defaultBodyStyle = {
    "margin": 0,
    "paddingTop": 0,
    "paddingBottom": 0,
    "paddingLeft": 0,
    "paddingRight": 0,
    "borderStyle": "none",
    "borderColor": "#333333",
    "borderWidth": 1,
    "borderRadius": 0,
    "align": "center",
    "color": "#333333",
    "backgroundType": "color",
    "backgroundColor": "#ffffff",
    "fontFamily": "Helvetica, Arial, sans-serif",
    "fontSize": 16,
    "lineHeight": 1.3,
}


def unescape(s: str) -> str:
    s = s.replace("&lt;", "<")
    s = s.replace("&gt;", ">")
    s = s.replace("&quot;", '"')
    s = s.replace("&apos;", "'")
    s = s.replace("&amp;", "&")
    return s


# there is only one instance of chrome running so we must use a lock
# to prevent concurrent access
GEN_SCREENSHOT_LOCK = 48127569


def gen_screenshot(db: DB, id: str, table: str, beefreeonly: bool = False) -> None:
    t = db[table].get(id)
    if t is None:
        return

    if beefreeonly:
        if t.get("type") != "beefree":
            return
    else:
        if t.get("type") and t["type"] != "beefree":
            return

    with db.transaction():
        db.execute(f"select pg_advisory_xact_lock({GEN_SCREENSHOT_LOCK})")

        imagebucket = os.environ["s3_imagebucket"]
        company = db.companies.get(t["cid"])
        if company is not None:
            parentcompany = db.companies.get(company["cid"])
            if parentcompany is not None:
                imagebucket = parentcompany.get("s3_imagebucket", imagebucket)

        if not t.get("type"):
            defaultBodyType = t.get("bodyStyle", {}).get("bodyType", "fixed")
            defaultBodyWidth = t.get("bodyStyle", {}).get("bodyWidth", 580)
            hasfull = defaultBodyType != "fixed"
            bodyWidth = defaultBodyWidth

            for part in t.get("parts", []):
                bodyWidth = max(bodyWidth, part.get("bodyWidth", defaultBodyWidth))
                hasfull = hasfull or (part.get("bodyType", defaultBodyType) != "fixed")

            if hasfull and bodyWidth < 1024:
                bodyWidth = 1024
            elif bodyWidth < 750:
                bodyWidth = 750

            html, _ = generate_html(
                db, t, "ss", imagebucket, noopens=True, nolinks=True, screenshot=True
            )
        else:
            parsed = json.loads(t["rawText"])
            html = parsed["html"]
            bodyWidth = 1024

        filename = "tmp/%s.html" % shortuuid.uuid()

        s3_write(os.environ["s3_transferbucket"], filename, html.encode("utf-8"))

        url = f"http://proxy/transfer/{filename}"

        resp = requests.post(
            "http://screenshot:4000", json={"url": url, "width": bodyWidth}, timeout=15
        )
        if resp.status_code > 299:
            log.error("Screenshot error: %s", resp.text)
        resp.raise_for_status()

        b = base64.b64decode(resp.text)

        filename = "%s.png" % (hashlib.md5(b).hexdigest(),)
        try:
            s3_size(imagebucket, filename)
        except:
            s3_write(imagebucket, filename, b)
        url = f"{get_webroot()}/i/{filename}"

        db[table].patch(id, {"image": url})


def generate_html(
    db: DB,
    obj: JsonObj,
    campid: str,
    imagebucket: str,
    noopens: bool = False,
    nolinks: bool = False,
    form: bool = False,
    formclose: bool = False,
    screenshot: bool = False,
) -> Tuple[str, List[str]]:
    if not obj.get("type"):
        return parts_to_html(
            db,
            obj["cid"],
            obj["parts"],
            obj["bodyStyle"],
            obj.get("preheader", ""),
            campid,
            imagebucket,
            noopens,
            nolinks,
            form,
            formclose,
            screenshot,
        )
    elif obj["type"] == "beefree":
        return raw_to_html(
            db,
            obj["cid"],
            json.loads(obj["rawText"])["html"],
            obj.get("preheader", ""),
            campid,
            noopens,
            nolinks,
        )
    else:
        return raw_to_html(
            db,
            obj["cid"],
            obj["rawText"],
            obj.get("preheader", ""),
            campid,
            noopens,
            nolinks,
        )


def parse_balanced_vars(s: str) -> str:
    count = 0

    index = 0
    while True:
        first = s[index : index + 2]
        if first == "":
            break
        elif first == "{{":
            count += 1
            index += 2
        elif first == "}}":
            if count == 0:
                break
            count -= 1
            index += 2
        else:
            index += 1

    return s[:index]


clickletters = ["a", "c", "f", "g", "m", "p", "q", "s", "w"]
openletters = ["b", "k", "j", "l", "o", "t", "y", "n"]
unsubletters = ["d", "e", "h", "i", "r", "u", "v"]


class RandomWords(RandomWordDB):  # type: ignore

    def __init__(self) -> None:
        super(RandomWords, self).__init__("nouns")

    def random_word(self, cid: str, letters: List[str]) -> str:
        r = random.Random()
        r.seed(djb2(cid))
        return cast(str, r.choice(self.nouns[r.choice(letters)])).lower()


randomwords = RandomWords()


def newlink(
    db: DB,
    cid: str,
    webroot: str,
    campid: str,
    linkurls: List[str],
    nolinks: bool,
    m: re.Match[str],
) -> str:
    tag = m.group(1)
    url = m.group(2)
    rest = m.group(3)

    t = randomwords.random_word(cid, clickletters)
    track = True

    unsubmatch = unsubre.search(url)
    if unsubmatch:
        t = randomwords.random_word(cid, unsubletters)
        url = ""
    else:
        unsublinkmatch = unsublinkre.search(url)
        if unsublinkmatch:
            t = randomwords.random_word(cid, unsubletters)
            url = parse_balanced_vars(url[unsublinkmatch.end() :])
        else:
            notrackmatch = notrackre.search(url)
            if notrackmatch:
                track = False
                url = parse_balanced_vars(url[notrackmatch.end() :])

    if not url:
        url = ""

    url = unescape(url)

    if url and not urlstartre.search(url) and not url.startswith("{{"):
        url = "http://%s" % url

    if not nolinks:
        l = db.single(
            """insert into links (id, url, campaign, index, track) values (%s, %s, %s, %s, %s)
                         on conflict (url, campaign, index, track) do update set track = excluded.track returning id""",
            shortuuid.uuid(),
            url,
            campid,
            len(linkurls),
            track,
        )
    else:
        l = "nl"

    if not url:
        linkurls.append("Unsubscribe")
    else:
        linkurls.append(url)

    urlparams = [
        ("t", t),
        ("r", "{{!!trackingid}}"),
        ("c", campid),
        ("u", "{{!!uid}}"),
        ("l", l),
    ]
    # random.shuffle(urlparams)

    returl = "%s/l?%s" % (webroot, "&".join("%s=%s" % (n, v) for n, v in urlparams))

    for var in paramre.findall(url):
        returl += "&p=%s" % (var,)

    return "%s%s%s" % (tag, returl, rest)


def raw_to_html(
    db: DB,
    cid: str,
    rawText: str,
    preheader: str,
    campid: str,
    noopens: bool,
    nolinks: bool,
) -> Tuple[str, List[str]]:
    webroot = "{{!!webroot}}"

    linkurls: List[str] = []

    nlfunc = lambda m: newlink(db, cid, webroot, campid, linkurls, nolinks, m)
    localimgfunc = lambda m: localimgurl(m, webroot)

    html = linkre.sub(nlfunc, rawText)
    html = localimgre.sub(localimgfunc, html)

    if not bodystartre.search(html):
        html = f"""<html>
<body>
{html}
</body>
</html>"""

    if preheader:
        ph = (
            '\n<span style="display:none;font-size:0px;line-height:0px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;visibility:hidden;mso-hide:all">%s</span>\n'
            % (html_escape(preheader, quote=True),)
        )
        m = bodystartre.search(html)
        if m:
            html = html[: m.end()] + ph + html[m.end() :]
        else:
            html = ph + html

    if not noopens:
        t = randomwords.random_word(cid, openletters)
        urlparams = [
            ("t", t),
            ("r", "{{!!trackingid}}"),
            ("c", campid),
            ("u", "{{!!uid}}"),
        ]
        # random.shuffle(urlparams)

        pixel = '<img src="%s/l?%s" height="1" width="1" alt="">\n' % (
            webroot,
            "&".join("%s=%s" % (n, v) for n, v in urlparams),
        )

        m = bodyre.search(html)
        if m:
            html = html[: m.start()] + pixel + html[m.start() :]
        else:
            html += "\r\n\r\n%s" % pixel

    return html, linkurls


fontProps: Dict[str, Any] = {
    "Arial": {
        "fallback": "sans-serif",
    },
    "Arial Black": {
        "fallback": "sans-serif",
    },
    "Bitter": {
        "fallback": "serif",
        "web": True,
    },
    "Cabin": {
        "fallback": "sans-serif",
        "web": True,
    },
    "Courier": {
        "fallback": "serif",
    },
    "Courier New": {
        "fallback": "serif",
    },
    "Garamond": {
        "fallback": "serif",
    },
    "Georgia": {
        "fallback": "serif",
    },
    "Helvetica": {
        "fallback": "sans-serif",
    },
    "Impact": {
        "fallback": "sans-serif",
    },
    "Karla": {
        "fallback": "sans-serif",
        "web": True,
    },
    "Lato": {
        "fallback": "sans-serif",
        "web": True,
    },
    "Lobster": {
        "fallback": "serif",
        "web": True,
    },
    "Lora": {
        "fallback": "serif",
        "web": True,
    },
    "Montserrat": {
        "fallback": "sans-serif",
        "web": True,
    },
    "Open Sans": {
        "fallback": "sans-serif",
        "web": True,
    },
    "Oswald": {
        "fallback": "sans-serif",
        "web": True,
    },
    "Palatino": {
        "fallback": "serif",
    },
    "Playfair Display": {
        "fallback": "serif",
        "web": True,
    },
    "Roboto": {
        "fallback": "sans-serif",
        "web": True,
    },
    "Times": {
        "fallback": "serif",
    },
    "Trebuchet MS": {
        "fallback": "sans-serif",
    },
    "Verdana": {
        "fallback": "sans-serif",
    },
}

fontre = re.compile(r'font-family\s*:\s*([^;}"]+)', re.I)
headre = re.compile(r"</head>")


def fix_fonts(s: str, screenshot: bool, imageroot: str) -> str:
    webfonts = set()

    def fallback(m: re.Match[str]) -> str:
        font = m.group(1)
        if font in fontProps:
            if fontProps[font].get("web"):
                webfonts.add(font)
            return "font-family: %s, %s" % (font, fontProps[font]["fallback"])
        return m.group(0)

    s = fontre.sub(fallback, s)

    webfontstr = ""
    if len(webfonts):
        webfontstr = "\n".join(
            '<link href="https://fonts.googleapis.com/css?family=%s" rel="stylesheet">'
            % (wf.replace(" ", "+"),)
            for wf in webfonts
        )

    # Avoid embedding bundled Helvetica font; rely on system fallbacks instead.
    # if screenshot:
    #     pass

    if webfontstr:
        s = headre.sub("%s\n</head>" % webfontstr, s, 1)

    return s


def localimgurl(m: re.Match[str], imageroot: str) -> str:
    htmltag = m.group(1)
    src = m.group(2)

    webroot = get_webroot()

    if not src.startswith(webroot):
        return f"{htmltag}{src}"

    return f"{htmltag}{imageroot}{src[len(webroot):]}"


def parts_to_html(
    db: DB,
    cid: str,
    parts: List[JsonObj],
    bodystyle: Dict[str, str],
    preheader: str,
    campid: str,
    imagebucket: str,
    noopens: bool,
    nolinks: bool,
    form: bool,
    formclose: bool,
    screenshot: bool,
) -> Tuple[str, List[str]]:
    s = defaultBodyStyle.copy()
    s.update(bodystyle)

    if form:
        s["paddingTop"] = 0
        s["paddingLeft"] = 0
        s["paddingRight"] = 0
        s["paddingBottom"] = 0

    webroot = "{{!!webroot}}"

    if screenshot:
        imageroot = "http://proxy"
    elif form:
        imageroot = get_webroot()
    else:
        imageroot = webroot

    html = StringIO()
    html.write(
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">\n'
    )
    html.write('<html xmlns="http://www.w3.org/1999/xhtml"><head>\n')
    html.write(
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />\n'
    )
    html.write('<meta name="viewport" content="width=device-width"/>\n')
    html.write("<style>\n")
    if form:
        html.write(foundation.formcss)
    else:
        html.write(foundation.css)
    if not form:
        html.write(foundation.mediaq)
    else:
        html.write(
            "input[type=text],input[type=email],input[type=number],input[type=password],input[type=tel],input[type=url] { -webkit-appearance: none; -moz-appearance: none; appearance: none; }\n"
        )
    html.write("</style>\n")
    html.write(
        '</head><body style="width: 100%; min-width: 100%; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; margin: 0; Margin: 0; padding: 0; -moz-box-sizing: border-box; -webkit-box-sizing: border-box; box-sizing: border-box">\n'
    )
    html.write(
        '<table class="body" style="border-spacing: 0; border-collapse: collapse; padding: 0; vertical-align: top; text-align: left; height: 100%; width: 100%">\n'
    )
    html.write(
        '<tr style="padding: 0; vertical-align: top; text-align: left"><td class="float-center" align="center" valign="top" style="border-collapse: collapse; padding: 0; vertical-align: top; text-align: left">\n'
    )
    html.write(
        f'<table style="border: 0; margin: 0; padding: 0; width: 100%; border-spacing: 0; border-collapse: collapse"><tr style="padding: 0, border-spacing: 0, border-collapse: collapse"><td {style(s, form)}>\n'
    )

    formid = shortuuid.uuid()

    if form:
        html.write(
            '<form style="margin: 0; padding: 0" method="POST" id="%s">\n' % (formid,)
        )
        html.write('<button type="submit" style="display: none"></button>\n')
        html.write("<style>\n")
        html.write(jsnotify.css)
        html.write("</style>\n")

    if bodystyle.get("bodyType", "fixed") == "fixed" and not bodystyle.get(
        "version", ""
    ):
        html.write(
            '<table align="center" class="container" style="border-spacing: 0; border-collapse: collapse; padding: 0; vertical-align: top; width: %spx; margin: 0 auto; Margin: 0 auto">\n'
            % (bodystyle.get("bodyWidth", 580),)
        )
        html.write('<tr style="padding: 0; vertical-align: top; text-align: left">\n')
        html.write(
            '<td style="border-collapse: collapse; padding: 0; vertical-align: top; text-align: left">\n'
        )

    if preheader:
        html.write(
            '<span style="display:none;font-size:0px;line-height:0px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;visibility:hidden;mso-hide:all">%s</span>\n'
            % (html_escape(preheader, quote=True),)
        )

    def part_contains_html(part: JsonObj) -> bool:
        if part.get("type") == "HTML":
            return True
        if part.get("type") != "Columns":
            return False
        for subparts in part.get("parts", []):
            if not subparts:
                continue
            if isinstance(subparts, list):
                for subpart in subparts:
                    if subpart and part_contains_html(subpart):
                        return True
            elif part_contains_html(subparts):
                return True
        return False

    for part in parts:
        if part["type"] == "Invisible":
            continue
        part_html = part["html"]
        if part_contains_html(part):
            part_html = sanitize_email_html(part_html)
        html.write("%s\n" % part_html)

    basehtml = html.getvalue()

    def imgurl(m: re.Match[str]) -> str:
        htmltag = m.group(1)
        src = m.group(2)

        tag, b = src.split(",", 1)
        b = base64.b64decode(b)
        ext = tag.split(";")[0].split("/")[1]
        filename = "%s.%s" % (hashlib.md5(b).hexdigest(), ext)
        try:
            s3_size(imagebucket, filename)
        except:
            s3_write(imagebucket, filename, b)
        url = f"{imageroot}/i/{filename}"

        return "%s%s" % (htmltag, url)

    linkurls: List[str] = []

    nlfunc = lambda m: newlink(db, cid, webroot, campid, linkurls, nolinks, m)
    localimgfunc = lambda m: localimgurl(m, imageroot)

    containerend = ""
    if bodystyle.get("bodyType", "fixed") == "fixed" and not bodystyle.get(
        "version", ""
    ):
        containerend = "</td></tr></table>"

    def socialfunc(m: re.Match[str]) -> str:
        return 'src="%s"' % socialimgs[m.group(1)]

    if not form:
        basehtml = linkre.sub(nlfunc, basehtml)

    basehtml = socialre.sub(socialfunc, basehtml)
    basehtml = imgre.sub(imgurl, basehtml)
    if not form:
        basehtml = localimgre.sub(localimgfunc, basehtml)

    basehtml = fix_fonts(basehtml, screenshot, imageroot)

    pixel = ""
    if not noopens:
        t = randomwords.random_word(cid, openletters)
        urlparams = [
            ("t", t),
            ("r", "{{!!trackingid}}"),
            ("c", campid),
            ("u", "{{!!uid}}"),
        ]
        # random.shuffle(urlparams)

        pixel = '<img src="%s/l?%s" height="1" width="1" alt="">\n' % (
            webroot,
            "&".join("%s=%s" % (n, v) for n, v in urlparams),
        )

    formend = ""
    postbody = ""
    if form:
        if formclose:
            formclosestr = "true"
        else:
            formclosestr = "false"

        formend = "</form>"
        postbody = (
            "<script>\n"
            + jsnotify.js
            + """
window.onload = function() {
  if (window !== window.top) {
    var sh = function () {
      window.parent.postMessage(JSON.stringify({
        id: '%s',
        cmd: 'setHeight',
        height: document.body.scrollHeight,
      }), "*");
    }
    setInterval(sh, 200);
    window.addEventListener("message", function(e) {
      if (e.data.toString() === 'getHeight') {
        sh();
      }
    }, false);
  }

  var form = document.getElementById("%s");
  var inputs = form.getElementsByTagName("INPUT");

  form.onsubmit = function(e) {
    e.preventDefault();

    var xhr = new XMLHttpRequest();
    var ued = "";
    var dp = [];
    var i;
    for (i = 0; i < inputs.length; i++) {
        var input = inputs[i];
        dp.push(encodeURIComponent(input.getAttribute("name")) + '=' + encodeURIComponent(input.value));
    }

    ued = dp.join('&').replace(/%%20/g, '+');

    xhr.addEventListener('load', function() {
      if (xhr.status >= 200 && xhr.status <= 299) {
        if (xhr.response.action == 'url') {
          if (window !== window.top) {
            window.parent.postMessage(JSON.stringify({
              id: '%s',
              cmd: 'setLocation',
              url: xhr.response.data,
            }), "*");
          } else {
            window.location.assign(xhr.response.data);
          }
        } else {
            window.createNotification({theme:'success'})({title: 'Success', message: xhr.response.data, theme: 'success'});
            if ((window !== window.top) && %s) {
              setTimeout(function() {
                window.parent.postMessage(JSON.stringify({
                  id: '%s',
                  cmd: 'closeForm',
                }), "*");
              }, 2000);
            } else {
              for (i = 0; i < inputs.length; i++) {
                var input = inputs[i];
                input.value = "";
              }
            }
        }
      } else {
        var d = xhr.response;
        var errmsg;
        if (d.description) {
          errmsg = d.description;
        } else if (d.title) {
          errmsg = d.title;
        } else {
          errmsg = d.toString();
        }
        window.createNotification({theme:'error'})({title: 'Error', message: errmsg, theme: 'error'});
      }
    });
    xhr.addEventListener('error', function() {
        var errmsg = xhr.statusText.toString();
        window.createNotification({theme:'error'})({title: 'Error', message: errmsg, theme: 'error'});
    });

    xhr.open('POST', "%s/api/postform/%s.json");
    xhr.responseType = "json";
    xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    xhr.send(ued);
  }
  var links = form.getElementsByClassName("edcom-button");
  var li;
  for (li = 0; li < links.length; li++) {
    links[li].onclick = function(e) {
      e.preventDefault();
      form.getElementsByTagName("BUTTON")[0].click();
    }
  }
  var dismiss = form.getElementsByClassName("edcom-button-dismiss");
  var d;
  for (d = 0; d < dismiss.length; d++) {
    dismiss[d].onclick = function(e) {
      e.preventDefault();
      if (window !== window.top) {
        window.parent.postMessage(JSON.stringify({
          id: '%s',
          cmd: 'closeForm',
        }), "*");
      }
    }
  }
}
</script>"""
            % (
                campid,
                formid,
                campid,
                formclosestr,
                campid,
                get_webroot(),
                campid,
                campid,
            )
        )

    ending = "</body></html>\n"

    return (
        (
            basehtml
            + containerend
            + formend
            + "</td></tr></table></td></tr></table>"
            + pixel
            + postbody
            + ending
        ),
        linkurls,
    )


epoch = datetime(1970, 1, 1, tzinfo=tzutc())


def unix_time_millis(dt: datetime) -> int:
    if dt.tzinfo is None:
        # assume a naive datetime is in local time; note that python's
        # datetime module is a shitty pile of fuck
        dt = dt.replace(tzinfo=tzlocal())
    dt = dt.astimezone(tzutc())
    return int((dt - epoch).total_seconds() * 1000)


def unix_time_secs(dt: datetime) -> int:
    return int(unix_time_millis(dt) / 1000)


def gather_init(db: DB, name: str, count: int) -> str:
    return db.taskgather.add(
        {
            "name": name,
            "count": 0,
            "limit": count,
            "ts": datetime.utcnow().isoformat() + "Z",
        }
    )


def gather_check(db: DB, gatherid: str) -> List[JsonObj] | None:
    if db.single(
        "select 1 from taskgather where id = %s and (data->>'count')::int >= (data->>'limit')::int",
        gatherid,
    ):
        db.taskgather.remove(gatherid)
        ret = list(
            json_iter(
                db.execute(
                    "select id, cid, data from taskgatherdata where data->>'gatherid' = %s",
                    gatherid,
                )
            )
        )
        if len(ret):
            db.execute(
                "delete from taskgatherdata where data->>'gatherid' = %s", gatherid
            )
        return ret
    return None


def gather_complete(
    db: DB, gatherid: str, data: JsonObj | None, remove: bool = True
) -> List[JsonObj] | None:
    if data is not None:
        data["gatherid"] = gatherid
        data["ts"] = datetime.utcnow().isoformat() + "Z"
        db.taskgatherdata.add(data)

    if remove:
        if db.single(
            "update taskgather set data = data || jsonb_build_object('count', (data->>'count')::int + 1) where id = %s returning (data->>'count')::int >= (data->>'limit')::int",
            gatherid,
        ):
            db.taskgather.remove(gatherid)
            ret = list(
                json_iter(
                    db.execute(
                        "select id, cid, data from taskgatherdata where data->>'gatherid' = %s",
                        gatherid,
                    )
                )
            )
            if len(ret):
                db.execute(
                    "delete from taskgatherdata where data->>'gatherid' = %s", gatherid
                )
            return ret
    else:
        db.execute(
            "update taskgather set data = data || jsonb_build_object('count', (data->>'count')::int + 1) where id = %s",
            gatherid,
        )
    return None


def user_log(
    req: falcon.Request,
    icon: str,
    premsg: str,
    linktype: str | None = None,
    linkid: str | None = None,
    postmsg: str | None = None,
    color: str | None = None,
) -> None:
    db = req.context["db"]
    uid = req.context["uid"]

    user = db.users.get(uid)

    if user is None:
        return

    name = None
    if linktype is not None:
        name = "<Unknown>"
        obj = getattr(db, linktype).get(linkid)
        if obj is not None:
            if "name" in obj:
                name = obj["name"]
            elif "username" in obj:
                name = obj["username"]

    db.userlogs.add(
        {
            "ts": datetime.utcnow().isoformat() + "Z",
            "icon": icon,
            "pre_msg": premsg,
            "link_msg": name,
            "post_msg": postmsg,
            "link_type": linktype,
            "link_id": linkid,
            "user_id": uid,
            "user_name": user.get("fullname", user.get("username")),
        }
    )


def run_task(f: Any, *args: Any, **kwargs: Any) -> str | None:
    if not os.environ.get("SYNC_TASKS"):
        log.debug("Running %s with args = %s, kwargs = %s", f.name, args, kwargs)
        r = f.delay(*args, **kwargs)
        log.debug("%s dispatched (%s)", f.name, r.id)
        return cast(str, r.id)
    else:
        f(*args, **kwargs)
        return None


def run_task_delay(f: Any, delay: int, *args: Any, **kwargs: Any) -> str | None:
    if not os.environ.get("SYNC_TASKS"):
        log.debug(
            "Running %s with args = %s, kwargs = %s, delay = %s",
            f.name,
            args,
            kwargs,
            delay,
        )
        r = f.apply_async(args=args, kwargs=kwargs, countdown=delay)
        log.debug("%s dispatched (%s)", f.name, r.id)
        return cast(str, r.id)
    else:
        f(*args, **kwargs)
        return None


def timer(f: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        start = time.time()
        try:
            return f(*args, **kwargs)
        finally:
            log.info(
                "[TIME] %s.%s: %s",
                type(args[0]).__name__,
                f.__name__,
                time.time() - start,
            )

    return decorated
