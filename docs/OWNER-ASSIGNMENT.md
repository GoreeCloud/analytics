# Offline owner assignment — development, not Identity login

This operator-only command supports the first explicit binding of a **known**
Analytics site to an **independently reviewed** Identity tenant and subject.
It requires a recoverable, exclusive SQLite backup, exact site/tenant
confirmation and explicit site permissions. It neither authenticates the
subject nor queries a running Keycloak service; do **not** invent or derive
ownership from a JWT tenant claim, site ID, DNS verification, Origin header or
shared admin token.

## Safe workflow (stopped local development installation)

1. Independently verify which tenant controls the site and which authenticated
   subject is entitled to the requested site/action permissions. Document the
   evidence in an approved private operational record; do not put token values
   or identifying visitor data in command-line arguments or output.
2. Stop all Analytics writers. Verify SQLite schema `user_version=2`, data
   backup/restore posture, site ID and file permissions. No assignment is made
   if the target site is missing or has an existing owner.
3. Preview, which **never writes**:

   ```sh
   python -m analytics.ownership_admin --database /private/analytics.sqlite3 \
      --site-id SITE_ID --tenant-id VERIFIED_TENANT_ID \
      --subject-id VERIFIED_SUBJECT_ID \
      --permissions analytics:read,analytics:export
   ```

4. After reviewing the precise IDs and requested permissions, explicitly apply:

   ```sh
   python -m analytics.ownership_admin --database /private/analytics.sqlite3 \
      --site-id SITE_ID --tenant-id VERIFIED_TENANT_ID \
      --subject-id VERIFIED_SUBJECT_ID \
      --permissions analytics:read,analytics:export \
      --apply --confirm-site-id SITE_ID --confirm-tenant-id VERIFIED_TENANT_ID \
      --backup-to /private/backups/analytics-before-site-owner.sqlite3
   ```

5. The tool verifies its backup, takes the SQLite writer lock, refuses an
   ownership/site race, inserts only the requested owner and subject/action
   records, and verifies every requested permission before commit. Check the
   schema audit, the independent backup and restored snapshot before enabling
   any future Identity enforcement.

## Intentional restrictions

- Only **initial** owner binding is implemented. Existing site owners cannot be
  changed by this command. Reassignment, subject revocation, membership
  lifecycle, and audit-evidence retention require separately reviewed tools.
- The command requires a pre-existing private backup folder and refuses to
  overwrite a backup. Operators must stop the service; it cannot prove that
  external processes have stopped. Historical backups retain prior site data.
- The subject identifier is an exact, operator-reviewed value, not a signed
  bearer token. A future API must authenticate using GoreeCloud Identity's
  **licensed and reviewed** token verifier, validate the tenant claim, and
  evaluate the stored exact site/subject/action binding. No current endpoint
  uses the new permission lookup or changes the legacy shared-admin mode.
- Network-edge protection, production TLS, token revocation and OIDC BFF/CSRF
  remain open. This utility is **not** a production authorization system.

See [Site Ownership](SITE-OWNERSHIP.md) and [Identity Integration](IDENTITY-INTEGRATION.md).
