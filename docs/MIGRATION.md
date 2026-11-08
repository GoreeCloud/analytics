# Explicit SQLite migration — development implementation

**This is an offline development migration from recognized unversioned Analytics SQLite layouts to schema marker `user_version=1`.** It is not PostgreSQL support, an HA migration, or a validated production upgrade. Operators must stop every Analytics process first and preserve an independent recovery plan.

## Before upgrading an existing database

1. Stop all writers and verify which database path the service is using. Record file ownership and available disk capacity; do not migrate a running production database.
2. Inspect an independently verified offline backup or the stopped database with `python -m analytics.schema_audit --database /path/to/analytics.sqlite3` and review the report.
3. Preview the upgrade with `python -m analytics.migrate --database /path/to/analytics.sqlite3`. Unrecognized or inconsistent schemas are refused, not repaired.
4. After choosing a private existing destination folder, run `python -m analytics.migrate --database /path/to/analytics.sqlite3 --apply --backup-to /private/backups/analytics-before-v1.sqlite3`. The backup is created exclusively, verified, and cannot overwrite an existing backup.
5. Re-run the schema audit, validate the retained sites/sessions/events/goals, and test the site's DNS ownership verification before restarting the service. Store a protected off-host copy of the backup according to your privacy policy.

New databases are created at `user_version=1` automatically. **Existing unversioned databases are not modified on application startup**; startup refuses them until explicitly migrated. The migration preserves historical events and existing confirmed hostname proof rows; newly created legacy domain rows are always pending DNS TXT reverification. Unknown future schema versions fail closed. Backups may contain sensitive visit data and must be protected.

SQLite `PRAGMA user_version` is a schema marker, not proof of an entirely validated deployment. These tests validate known local fixtures; actual stop-the-world coordination, disk failure recovery, encrypted off-host storage, PostgreSQL changes, rolling upgrade behavior, rollback into a live environment, and full browser acceptance remain open release gates.
