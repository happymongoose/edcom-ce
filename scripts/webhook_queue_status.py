#!/usr/bin/env python3
"""Read-only operator summary. No payloads, automatic replay or deletions."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from api.shared.utils import redis_connect
from api.shared import webhook_inbox as inbox
rdb = redis_connect()
recent = [json.loads(raw) for raw in rdb.lrange(inbox.HELD, 0, 9)]
print(json.dumps({"recent_held": [{k: row[k] for k in ('id', 'held_at', 'reason')} for row in recent],"pending": rdb.llen(inbox.PENDING),
                  "processing": rdb.llen(inbox.PROCESSING),
                  "held_requires_review": rdb.llen(inbox.HELD)}, indent=2))
