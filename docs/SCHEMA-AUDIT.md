# Read-only database schema preflight

**Development-only. This is not a versioned migration framework, automatic upgrade, or database recovery procedure.**

Before planning an upgrade, stop application writers or use a separately verified offline SQLite backup and run:

```sh
python -m analytics.schema_audit --database /path/to/verified-backup.sqlite3
```

The command refuses absent database files, symlink paths, corrupt SQLite files, schemas missing required tables or columns, missing/incorrect primary keys, expected cascade foreign keys, required index definitions, and foreign-key violations. Its report includes `invalid_primary_keys`, `missing_foreign_keys` and `missing_indexes` fields. This is a known-v1 structural check, not a cryptographic schema attestation or exhaustive SQLite constraint audit. It checks the application's five known tables without modifying schema or records. Exit code **0** means the recognized Analytics structure has `PRAGMA user_version=1` and is ready for this development build; exit code **2** flags an unversioned database requiring migration or an unrecognized schema requiring manual review. An invalid or unreadable database returns a nonzero CLI error.

The early Analytics MVP did not assign a `user_version`, even on newly created databases. An unversioned recognized structure **does not prove** that a database was upgraded safely, is free of semantic corruption, or has a tested rollback. The current application **refuses to start** with existing unversioned databases. Review the new [explicit backup-gated migration](MIGRATION.md) before upgrading; the inspection command itself never performs that migration.

The `mode=ro` read-only SQLite connection never intentionally writes tables, indexes, or data, but SQLite may access its sidecar WAL/SHM metadata when auditing a running database; prefer a disposable offline snapshot. Backup confidentiality, path permissions, tested restore plans, schema versioning, migration rollback, and deployment gates remain required.
