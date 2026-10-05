import os
import re
import shortuuid
import time
from datetime import datetime, timedelta

from .shared import config as _  # noqa: F401
from .campaigns import export_campaign
from .shared.db import open_db, json_iter
from .shared.utils import run_task
from .shared.s3 import s3_delete_all
from .shared.log import get_logger

log = get_logger()


def cleanup_db() -> None:
    with open_db() as db:
        try:
            db.execute(
                "delete from statlogs2 where ts < %s",
                (datetime.utcnow() - timedelta(days=90)).isoformat() + "Z",
            )
            db.execute(
                "delete from hourstats where ts < %s",
                (datetime.utcnow() - timedelta(days=90)),
            )
            db.execute(
                "delete from statmsgs where ts < %s",
                (datetime.utcnow() - timedelta(days=90)),
            )
            db.execute(
                "delete from txnstats where ts < %s",
                (datetime.utcnow() - timedelta(days=90)),
            )
            db.execute(
                "delete from txnstatmsgs where ts < %s",
                (datetime.utcnow() - timedelta(days=90)),
            )
            db.execute(
                "delete from txnsends where ts < %s",
                (datetime.utcnow() - timedelta(days=90)),
            )

            db.execute(
                "delete from exports where data->>'started_at' < %s",
                (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z",
            )

            db.execute(
                "delete from taskgather where data->>'ts' < %s",
                (datetime.utcnow() - timedelta(days=3)).isoformat() + "Z",
            )
            db.execute(
                "delete from taskgatherdata where data->>'ts' < %s",
                (datetime.utcnow() - timedelta(days=3)).isoformat() + "Z",
            )

            db.execute(
                "delete from userlogs where data->>'ts' < %s",
                (datetime.utcnow() - timedelta(days=15)).isoformat() + "Z",
            )

            db.execute(
                "delete from cookies where data->>'lastused' < %s",
                (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z",
            )
            db.execute(
                "delete from tempusers where data->>'invited_at' < %s",
                (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z",
            )

            camps = list(
                json_iter(
                    db.execute(
                        "select id, cid, data from campaigns where data->>'sent_at' < %s and not coalesce((data->>'archived')::boolean, false)",
                        (datetime.utcnow() - timedelta(days=365)).isoformat() + "Z",
                    )
                )
            )
            for camp in camps:
                uuid = shortuuid.uuid()

                name = re.sub(r"[^A-Za-z0-9 \-_.]", "", camp["name"])

                path = "exports/%s/%s-%s.zip" % (
                    uuid,
                    name,
                    datetime.utcnow().strftime("%Y%m%d-%H%M%SZ"),
                )

                db.campaigns.patch(camp["id"], {"archived": True})

                run_task(export_campaign, camp["id"], camp["cid"], uuid, path, False)

            db.execute(
                "delete from camplogs where ts < %s",
                (datetime.utcnow() - timedelta(days=367)),
            )
            db.execute(
                "delete from txnlogs where ts < %s",
                (datetime.utcnow() - timedelta(days=367)),
            )
            db.execute(
                "delete from mgtracking where ts < %s",
                (datetime.utcnow() - timedelta(days=367)),
            )
            db.execute(
                "delete from sesmessages where ts < %s",
                (datetime.utcnow() - timedelta(days=367)),
            )
            db.execute(
                "delete from sptracking where ts < %s",
                (datetime.utcnow() - timedelta(days=367)),
            )
            db.execute(
                "delete from eltracking where ts < %s",
                (datetime.utcnow() - timedelta(days=367)),
            )
            db.execute(
                "delete from smtptracking where ts < %s",
                (datetime.utcnow() - timedelta(days=367)),
            )

            db.execute(
                "delete from sparkpost_events where ts < %s",
                (datetime.utcnow() - timedelta(days=2)),
            )

            file_retention_days = int(os.environ.get("file_retention_days", 90))

            for bucket_name in ("s3_transferbucket", "s3_databucket"):
                summary = s3_delete_all(
                    os.environ[bucket_name],
                    time.time() - (file_retention_days * 24 * 60 * 60),
                )
                report = log.warning if summary["errors"] or summary["truncated"] else log.info
                report("File age cleanup %s: %s", bucket_name, summary)

        except:
            log.exception("error")
