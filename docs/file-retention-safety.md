# Delivery-file retention safety guard

This slice prevents scheduled age cleanup from deleting the supported sending paths. It does not identify finished files or complete milestone 19's orphan pruning.

## Why the guard is conservative

Campaign preparation writes recipient blocks under `lists/` and bodies under `templates/camp/`. Transactional bodies use `templates/txn/`. Broadcast dispatch creates transfer `lists/` chunks. Provider adapters queue HTML under `sessend/`, `sphtml/`, `smtphtml/`, `elhtml/` and `mghtml/`.

A file can remain needed after a campqueue row is allocated to Celery, and Velocity fetches recipient URLs asynchronously after accepting the HTTP request. Inspecting current database rows or changing retention from 90 to a larger number cannot establish completion. Snapshot reference checks also race with new references.

The existing `s3_delete_all` age-cleanup helper now ALWAYS preserves these seven top-level namespaces in both data and transfer buckets. It does not consult campaign status, so scheduling, throttle/warmup delays, paused work, handoff and pending retries cannot remove that protection. This is a namespace invariant, not an assertion that every preserved file is active. Existing direct consumer-owned `s3_delete` calls remain unchanged. No send, queue, trigger, database schema or database-log retention semantics changed.

Protection covers the repository's current supported generated send paths, not arbitrary files referenced through custom code or every import/export/screenshot lifecycle. New sending-file namespaces must extend the protection and tests until a reliable ownership protocol supersedes it.

## Operational trade-off

Protected files can now outlive `file_retention_days` indefinitely. This prevents the demonstrated referenced-file deletion, but DOES NOT solve inode/disk exhaustion. Never claim that a protected file is safe to delete merely because it is old, has no current campqueue row or its campaign says finished.

Monitor protected growth and actual filesystem free bytes/inodes (`df -h` and `df -i` in the relevant server environment). The next lifecycle slice needs creation/ownership/handoff/completion tracking and safe bounded reclamation. External consumers and ambiguous retries must participate; deleting old protected directories manually bypasses this guard.

Other namespaces retain the existing age-based policy; their safety has not been universally audited by this slice. Nonregular files/symlinks are skipped. Missing or inaccessible buckets/files are reported without exposing recipient filenames. This does not attempt a general hostile-filesystem security redesign.

## Read-only inspection

```sh
docker compose exec api python /scripts/file_retention_status.py
```

Defaults to at most 10,000 file entries and 10,000 visited directories per bucket. `--limit` accepts 1–1,000,000. Returns counts, protected bytes, old unprotected candidates and errors. It never deletes files or displays recipient keys. `truncated: true` means PARTIAL results, not a total inventory. Protected counts include recent files too; zero old candidates does not imply no disk pressure.

Daily cleanup uses the same helper and logs its summary for both buckets. It is similarly bounded; a large tree can repeatedly hit the limit before reaching later files. No cursor/fair reclamation is claimed. Directory enumeration itself still uses os.walk, so these budgets are not strict wall-clock/memory guarantees. Inventory pagination is deferred to lifecycle work. Existing earlier cleanup SQL errors can still prevent the file-cleanup phase; this slice does not refactor the whole cleanup job.

Deploy the shared helper and cleanup code together. The cron process imports current code on its next run; rebuild/deploy the appropriate image as usual. No data migration or existing-file deletion is required. Rolling back removes this protection: do not roll back into active age cleanup without considering pending send files. No running sending workers were restarted during local testing.

## Tests

`test/test_file_retention.py` covers all namespaces, campaign/transactional templates, exact prefix boundaries, unchanged non-send retention, read-only inventory, partial-scan reporting, empty directory budgets, symlink handling, missing buckets, consumer-owned deletion and concurrent creation of old send files.

The real-worker benchmark now requires an aged template referenced by a pending campqueue row to survive cleanup. Historical results in `queue-baseline-results.md` describe the pre-fix defect. No production/test-server files are aged or deleted by these tests; all fixtures are disposable.

Acceptance: **11 focused tests passed**, **822 full backend tests passed**, and the **2,000-contact real-Celery/fake-delivery baseline passed** with `referenced_old_file_deleted: false`, all recipients counted once, and the failed event retained by the previous slice. Final Python syntax/whitespace checks passed, including the final warning-level reporting adjustment. Tests used current repository sources and disposable Docker services; no real emails, existing data deletion or production changes.
