#!/usr/bin/env python3
"""Read-only queue and filesystem snapshot; no message bodies or worker commands."""
import json
import os
import sys
from datetime import datetime, timezone


def observe(callback):
    try:
        return {"available": True, **callback()}
    except Exception as error:
        # Connection errors can include credentials or hostnames. Never print them.
        return {"available": False, "error_type": type(error).__name__}


def filesystem(path):
    stats = os.statvfs(path)
    return {
        "bytes_total": stats.f_blocks * stats.f_frsize,
        "bytes_available": stats.f_bavail * stats.f_frsize,
        "inodes_total": stats.f_files,
        "inodes_available": stats.f_favail,
    }


def queue_depths(broker):
    # Match the current Kombu Redis priority_steps and configured ':' separator.
    result = {}
    for queue in ("celery", "interactive", "transactional"):
        pipe = broker.pipeline(transaction=False)
        for suffix in ("", ":3", ":6", ":9"):
            pipe.llen(queue + suffix)
        result[queue] = sum(pipe.execute())
    return {"waiting_tasks": result, "unacknowledged_tasks": broker.hlen("unacked")}


def event_depths(cache):
    from api.shared import webhook_inbox
    pipe = cache.pipeline(transaction=False)
    for key in (webhook_inbox.PENDING, webhook_inbox.PROCESSING, webhook_inbox.HELD):
        pipe.llen(key)
    pending, processing, held = pipe.execute()
    return {"pending": pending, "processing": processing, "held_requires_review": held}


def snapshot(broker, cache, paths):
    return {
        "format": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "broker": observe(lambda: queue_depths(broker)),
        "events": observe(lambda: event_depths(cache)),
        "filesystems": {label: observe(lambda path=path: filesystem(path))
                        for label, path in paths.items()},
    }


def exit_status(result):
    if not all(section["available"] for section in
               [result["broker"], result["events"], *result["filesystems"].values()]):
        return 2
    if result["events"]["held_requires_review"]:
        return 1
    for disk in result["filesystems"].values():
        for total, available in (("bytes_total", "bytes_available"),
                                 ("inodes_total", "inodes_available")):
            if disk[total] and disk[available] / disk[total] <= .1:
                return 1
    return 0


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from redis import Redis
    from api.shared.tasks import tasks  # Loads the same configuration as workers.
    if not tasks.conf.broker_url.startswith(("redis://", "rediss://")):
        raise SystemExit("This check supports the configured Redis broker only.")
    broker = Redis.from_url(tasks.conf.broker_url, socket_connect_timeout=3,
                            socket_timeout=3, retry_on_timeout=False)
    cache = Redis(host=os.environ["redis_host"], port=int(os.environ["redis_port"]),
                  password=os.environ["redis_pass"] or None,
                  socket_connect_timeout=3, socket_timeout=3, retry_on_timeout=False)
    result = snapshot(broker, cache, {"buckets": "/buckets", "logs": "/logs"})
    print(json.dumps(result, indent=2))
    return exit_status(result)


if __name__ == "__main__":
    sys.exit(main())
