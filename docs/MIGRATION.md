# Explicit SQLite migration — development implementation

**This is an offline development migration from recognized v0/v1 Analytics SQLite layouts to schema marker `user_version=2`.** It is not PostgreSQL support, an HA migration, or a validated production upgrade. Operators must stop every Analytics process first and preserve an independent recovery plan.

## Before upgrading an existing database

1. Stop all writers and verify which database path the service is using. Record file ownership and available disk capacity; do not migrate a running production database.
2. Inspect an independently verified offline backup or the stopped database with `python -m analytics.schema_audit --database /path/to/analytics.sqlite3` and review the report.
3. Preview the upgrade with `python -m analytics.migrate --database /path/to/analytics.sqlite3`. Unrecognized or inconsistent schemas are refused, not repaired.
4. After choosing a private existing destination folder, run `python -m analytics.migrate --database /path/to/analytics.sqlite3 --apply --backup-to /private/backups/analytics-before-v2.sqlite3`. The backup is created exclusively, verified, and cannot overwrite an existing backup.
5. Re-run the schema audit, validate the retained sites/sessions/events/goals, and test the site's DNS ownership verification before restarting the service. Store a protected off-host copy of the backup according to your privacy policy.

New databases are created at `user_version=2` automatically. **Existing v0/v1 databases are not modified on application startup**; startup refuses them until explicitly migrated. The migration preserves historical events and existing confirmed hostname proof rows; newly created legacy v0 domain rows are pending DNS TXT reverification; existing verified rows are retained. Unknown future schema versions fail closed. Backups may contain sensitive visit data and must be protected.

SQLite `PRAGMA user_version` is a schema marker, not proof of an entirely validated deployment. These tests validate known local fixtures; actual stop-the-world coordination, disk failure recovery, encrypted off-host storage, PostgreSQL changes, rolling upgrade behavior, rollback into a live environment, and full browser acceptance remain open release gates.

### Independent ownership boundary

The v2 upgrade creates **empty** `site_owners` and `site_permissions` tables.
It never assigns an existing site to a tenant or principal. Current shared-token
admin routes are unchanged; actual signed-token Identity integration and an
operator-reviewed ownership assignment procedure remain outstanding. See
[Site Ownership](SITE-OWNERSHIP.md).
