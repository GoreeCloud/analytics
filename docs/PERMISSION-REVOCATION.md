# Offline site permission revocation — development-only

**Status:** Tested SQLite v2 maintenance command, not an Identity user-management API, browser control, or JWT/session revocation service.

## What it does

`python -m analytics.permissions_admin` targets **one exact persisted grant**: site ID, independently assigned tenant ID, authenticated subject ID (recorded by the operator) and one allowlisted Analytics action permission. It refuses missing/mismatched ownership, missing or malformed grants, unknown schema versions, and unknown permissions. Preview is read-only and does not create a backup or revoke anything.

Before `--apply`, **stop all Analytics writers** and verify the tenant/site/principal permission against independent operator evidence. The command then requires all four exact confirmations, writes an exclusive integrity-verified SQLite backup to an existing protected destination folder, compares a SHA-256 digest of the complete site-grant roster at preview/backup and the exact owner/grants under the SQLite `BEGIN IMMEDIATE` transaction, then verifies that **only** the requested grant changed, removes only the exact grant, and checks the resulting schema. The backup must not be automatically erased or overwritten.

## Usage on a stopped, independently verified development database

Preview:

```sh
python -m analytics.permissions_admin --database /private/analytics.sqlite3 \
  --site-id SITE_ID --tenant-id VERIFIED_TENANT_ID \
  --subject-id VERIFIED_SUBJECT_ID --permission analytics:export
```

Apply **only after reviewing the preview, ownership evidence and recovery plan**:

```sh
python -m analytics.permissions_admin --database /private/analytics.sqlite3 \
  --site-id SITE_ID --tenant-id VERIFIED_TENANT_ID \
  --subject-id VERIFIED_SUBJECT_ID --permission analytics:export \
  --apply --backup-to /private/backup-before-revoke.sqlite3 \
  --confirm-site-id SITE_ID --confirm-tenant-id VERIFIED_TENANT_ID \
  --confirm-subject-id VERIFIED_SUBJECT_ID --confirm-permission analytics:export
```

The backup contains sensitive visit data and old permission records; encrypt/protect/retain and later expire it under the approved GoreeShield policy. **This command changes only a database grant.** It does not contact Keycloak, disable accounts, revoke signed or bearer tokens, end browser sessions, invalidate a cached authorization check, or remove already-authorized in-flight responses. Offline writers must remain stopped, and changing a permission does not retroactively prevent prior data access. It can remove the last administrative permission; keep a separately reviewed recovery mechanism.

The default legacy shared administrator token is not subject to these v2 grants. In optional Identity-mode API authorization, the next new request consults current v2 membership, but the actual cryptographic verifier, client session, role revocation and production gateway are not yet integrated. No production use is approved by these development tests.

See [Owner Assignment](OWNER-ASSIGNMENT.md), [Identity API Gate](IDENTITY-API-GATE.md), [Data Deletion](DATA-DELETION.md), and [Security](SECURITY.md).


The preview prints `site_grant_snapshot_sha256`, a fingerprint of the operator-reviewed owner/grant set, not its full roster. The apply command compares it against the verified backup, then compares the exact stored roster inside the writer lock and after deletion. It refuses same-count subject/permission swaps and trigger-induced unrelated grant edits. This is concurrency defense for a stopped-writer maintenance workflow, not approval for running destructive changes against active services.
