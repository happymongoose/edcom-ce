# Read-only operating checks

From the installed EDCOM directory, type:

```sh
docker compose exec -T api python /scripts/platform_status.py
```

This prints a small JSON snapshot without sending email, changing queues, requesting worker commands, reading message bodies or listing contact data. It uses the application's configured broker and the separate event-cache connection. It counts all four current Redis priority buckets for the default, interactive and transactional queues. Unacknowledged tasks are broker-wide and can be executing or awaiting acknowledgement; they are not necessarily stuck.

Check `waiting_tasks` over several observations: a backlog should drain when input stops. One snapshot cannot prove workers are healthy or establish throughput. Queue counts and event counts are advisory observations, not one atomic snapshot. An empty queue does not prove there is no in-flight send. The command deliberately does not report a guessed oldest-task age.

`bytes_available` and `inodes_available` describe the filesystems backing the API container's mounted buckets/logs. Do not add the two totals together if they share a filesystem. Check database, Redis and Docker storage separately on the host using `df -h`, `df -i` and `docker system df`. Do not use `docker system prune` as routine remediation.

Exit codes:

- **0:** all observations succeeded; no held event or <=10% disk/inode warning. This is not a delivery or release approval.
- **1:** held incoming events need review, or observed free bytes/inodes are at most 10%. Investigate before increasing load. Do not blindly replay held events or delete sending files.
- **2:** an observation failed. The unavailable section is explicitly unknown, never zero. Only the exception class is printed; inspect private service logs for details.

The fixed threshold is an early-warning aid, not a capacity model: monitor growth and planned sending volume too. A filesystem without inode accounting can report a total of zero; its inode threshold is then not evaluated.

For protected transfer-file inventory, use `python /scripts/file_retention_status.py --limit 10000` in the API container. This scans a bounded number of entries and may report partial results. There is still no safe automatic reclamation of every completed recipient file: an external Velocity server may fetch asynchronously. Neither age nor an empty Celery queue is proof that a file is unused.
