#!/usr/bin/env python

import os
import subprocess
import sys

if len(sys.argv) != 2 or sys.argv[1] not in ('celery', 'gunicorn'):
    sys.stderr.write('usage: num_tasks.py celery|gunicorn')
    sys.exit(-1)

# Explicit per-container control for small hosts. Does not change legacy defaults.
if sys.argv[1] == 'celery' and 'EDCOM_CELERY_CONCURRENCY' in os.environ:
    try:
        concurrency = int(os.environ['EDCOM_CELERY_CONCURRENCY'])
        if not 1 <= concurrency <= 64:
            raise ValueError()
    except ValueError:
        sys.stderr.write('EDCOM_CELERY_CONCURRENCY must be an integer from 1 to 64\n')
        sys.exit(1)
    print(concurrency)
    sys.exit(0)

num_cpus = int(subprocess.check_output('grep processor /proc/cpuinfo | wc -l', shell=True))

if sys.argv[1] == 'celery':
    print(max(min(64, num_cpus * 4), 4))
else:
    print(max(min(32, num_cpus), 4))
