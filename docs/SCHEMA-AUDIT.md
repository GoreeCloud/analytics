# Read-only database schema preflight

**Development-only. This is not a versioned migration framework, automatic upgrade, or database recovery procedure.**

Before planning an upgrade, stop application writers or use a separately verified offline SQLite backup and run:

```sh
python -m analytics.schema_audit --database /path/to/verified-backup.sqlite3
```

The command refuses absent database files, symlink paths, corrupt SQLite files, schemas missing required tables or columns, and foreign-key errors. It checks the application's five known tables without modifying schema or records. Exit code **0** means the source has the recognized Analytics v0.1.2 structure with `PRAGMA user_version=0`; exit code **2** means manual schema review is required. An invalid or unreadable database returns a nonzero CLI error.

The early Analytics MVP did not assign a `user_version`, even on newly created databases. An unversioned recognized structure **does not prove** that a database was upgraded safely, is free of semantic corruption, or has a tested rollback. Existing startup behavior may automatically add `site_domains` on older installations. **Do not start new application code against an active legacy database without taking and validating a consistent backup first.** This audit does not disable that startup behavior.

The `mode=ro` read-only SQLite connection never intentionally writes tables, indexes, or data, but SQLite may access its sidecar WAL/SHM metadata when auditing a running database; prefer a disposable offline snapshot. Backup confidentiality, path permissions, tested restore plans, schema versioning, migration rollback, and deployment gates remain required.