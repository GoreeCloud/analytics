# Offline retention — backup snapshot integrity

**Development only.** Preview is read-only. `--apply` requires a new, verified SQLite backup inside a private destination directory; applying directly through Python's `retention_report(..., apply=True)` without an exact snapshot fingerprint is now rejected.

Run only after independently confirming all writers are stopped:

```sh
python -m analytics.maintenance --database /private/analytics.sqlite3 --days 90
python -m analytics.maintenance --database /private/analytics.sqlite3 --days 90 --apply \
  --backup-to /private/backups/pre-retention-20261108.sqlite3
```

The application computes a typed streaming SHA-256 fingerprint of every row across the current seven SQLite v2 Analytics tables **from the verified backup**. Before pruning, it rechecks the entire source database under `BEGIN IMMEDIATE`. Any intervening same-count edit, grant change, event rewrite or site mutation causes a rollback; the private backup is retained for the operator to inspect. This does not prove exclusive control over all writers or protect from hostile file path replacement or tampering after the transaction. No fingerprint or visitor data is written to the command result.

Backups may retain expired or deleted events until their separately governed storage lifetime ends. Do not treat this CLI as proof of GDPR/CCPA handling, complete data erasure or an automated retention policy. Only planned, encrypted, off-host retention/backup expiry controls can address copies outside the SQLite database. See [Security](SECURITY.md), [Site Deletion](DATA-DELETION.md), and [Recovery Drill](RECOVERY-DRILL.md).
