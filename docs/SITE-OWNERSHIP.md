# Site ownership schema v2 — development, not enabled SSO

GoreeCloud Analytics now has SQLite v2 site-to-tenant ownership and per-site,
per-subject permission tables. These tables are **empty** for new and upgraded
databases; no existing site is silently claimed. A DNS TXT record, site ID,
shared bearer token or JWT tenant claim alone is not ownership or permission.
The current Analytics admin API still uses the development shared token.

## Explicit offline upgrade

1. Stop every Analytics database writer, identify the exact file path, validate
   permissions and preserve a verified independent recovery copy.
2. Preview `python -m analytics.migrate --database /path/to/analytics.sqlite3`.
   Only recognized v0/v1 layouts are eligible; partial/unknown layouts fail.
3. Apply with `--apply --backup-to /private/new-exclusive-backup.sqlite3`.
   The backup is verified, and schema changes are atomic. Historical events,
   visits, goals and existing DNS verification timestamps remain unchanged.
   Only newly backfilled v0 domain proofs remain pending.
4. Audit `python -m analytics.schema_audit --database /path/to/analytics.sqlite3`.
   Test snapshot restoration and reconcile site counts before restarting.

`site_owners(site_id, tenant_id, assigned_at, assigned_by)` is intentionally
empty until a separately reviewed operator-controlled ownership action exists.
`site_permissions(site_id, subject_id, permission, granted_at)` binds a
trusted Identity subject to an independently owned site and explicit action.
No Identity authorization is enabled merely by creating these tables.

## Deny-by-default future authorization

- A verified signed `goreecloud_tenant` claim must exactly match the independently
  stored site owner and a verified subject must have a site-specific permission.
- Proposed permission labels are `analytics:read`, `analytics:export`,
  `analytics:manage`, `analytics:admin` and `analytics:delete`; these are not
  currently deployed Keycloak roles.
- Legacy sites and new sites begin unowned. Do not auto-bind to the first login,
  the dashboard token, event origin, or DNS proof. A reviewed operator mapping,
  licensing of the Identity adapter, signed token verification, BFF/CSRF,
  membership lifecycle, and full API checks are still outstanding.
- Existing v0/v1 databases cannot start under v2 without explicit backup-gated
  migration. Production migration and rollback acceptance are not claimed.

See [Identity Integration](IDENTITY-INTEGRATION.md) and [Migration Guide](MIGRATION.md).
