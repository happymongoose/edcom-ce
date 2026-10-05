#!/usr/bin/env python3
"""Bounded read-only age-cleanup inventory; never prints recipient paths."""
import argparse
import json
import os
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from api.shared import config  # noqa: F401
from api.shared.s3 import s3_delete_all
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--limit', type=int, default=10000)
args = parser.parse_args()
cutoff = time.time() - int(os.environ.get('file_retention_days', 90)) * 86400
print(json.dumps({name: s3_delete_all(os.environ[name], cutoff, dry_run=True, limit=args.limit)
                  for name in ('s3_databucket', 's3_transferbucket')}, indent=2))
