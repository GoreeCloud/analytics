# Offline Analytics SQLite recovery drill

**Status:** development-only, non-destructive recovery validation, not a live restore, backup scheduler, encryption system, disaster-recovery SLA, or approval for production.

Use this command against a separately stored **SQLite v2** backup whose authenticity and confidentiality are independently verified:

```sh
mkdir -m 700 /private/analytics-recovery-scratch
python -m analytics.recovery_drill --backup /private/backups/analytics.sqlite3 \
  --scratch-dir /private/analytics-recovery-scratch
```

The command refuses nonregular/symlink inputs, an absent scratch directory, POSIX backup/scratch modes accessible by group or others, and backup files that fail integrity check or the current v2 schema audit. Scratch must be separate from the backup's directory.

It creates a disposable private subdirectory, restores the snapshot through the existing verified SQLite backup API into an **exclusive new file**, checks the restored v2 schema and foreign keys, and compares the complete schema definitions and **every row of all seven current Analytics tables**. After completion or failure the disposable data is removed. The CLI prints aggregate row counts and results, not visitor rows or a digest that could fingerprint a backup's contents.

Source backups and live databases are not modified or switched by this tool. Carefully monitor actual filesystem permissions, available disk space and operator-controlled encryption. A passing isolated drill does not prove that remote storage, secrets, key recovery, DNS, deployment configuration, RPO/RTO, availability, and actual operator rollback will work. Schedule restore exercises on authorized protected infrastructure only after formal planning. Do not upload backups to GitHub or public channels.

See [Security](SECURITY.md), [Migration](MIGRATION.md) and the existing `python -m analytics.backup` CLI.
