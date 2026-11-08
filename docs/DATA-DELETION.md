# Offline site deletion — development-only

**Status:** original single-node SQLite deletion utility; tested on disposable databases. This is **not** an automated retention service, a per-person data-subject request flow, a certified privacy compliance control, a production operating procedure, or evidence of live deployment.

## Scope and impact

`python -m analytics.purge` can irreversibly delete **one entire registered site** and the site's associated DNS-proof rows, sessions, events and saved goals in a single SQLite transaction. It does not delete other sites. Because Analytics uses rotating anonymous daily HMAC identifiers and deliberately avoids persistent individual IDs, the service **cannot reliably identify or purge one person's events** from a data-subject request. It must not misrepresent this site-wide operation as per-visitor erasure.

## Operator procedure (stop the service first)

1. **Stop all Analytics writers** and independently confirm the target SQLite path and site ID. Do not run against a live production installation. This CLI cannot establish that other processes are stopped.
2. Review the current database and schema: `python -m analytics.schema_audit --database /path/to/analytics.sqlite3`. Any unknown or incomplete schema must be resolved separately; this command will not migrate or repair it.
3. Preview site-specific counts **without writing or creating a backup**:

   ```bash
   python -m analytics.purge --database /path/to/analytics.sqlite3 --site-id SITE_ID
   ```

4. Choose a new destination filename inside an existing **private** backup directory with sufficient storage. After reviewing the preview and confirming the target, explicitly apply:

   ```bash
   python -m analytics.purge --database /path/to/analytics.sqlite3 --site-id SITE_ID \
     --apply --backup-to /private/backups/before-site-deletion.sqlite3 \
     --confirm-site-id SITE_ID
   ```

5. Verify the resulting counts, absence of the deleted site and expected unaffected sites. Independently confirm the backup can be inspected and restored to a different path using `python -m analytics.backup`. Do not automatically deploy a restored database.

## Protections and remaining limitations

- The command refuses a missing, symbolic-link, unrecognized or inconsistent source database, unknown site ID, missing exact confirmation and any existing backup destination.
- Before deletion it creates an **exclusive, verified SQLite online snapshot** with file permissions `0600`. The deletion runs in an immediate, foreign-key-enabled transaction. Counts from the backup are compared with those in the locked database to catch common concurrent-write races; changing counts fail closed and leave the backup for review. This **does not prove all writers were stopped** and cannot detect all same-count mutations.
- It verifies post-deletion row counts for all affected tables and checks foreign keys. Other sites and their records remain intact. An integrity or transaction failure raises an error; keep the verified backup for operator-directed recovery.
- **The snapshot contains the records being deleted.** Such backups must be encrypted, access-controlled, kept off-host under policy where required, and ultimately expired or securely erased in accordance with the user's privacy and recovery obligations. Restoring an old backup can reintroduce deleted site data; restore procedures must reapply current deletion decisions.
- This command does not delete browser caches, CDN or reverse-proxy logs, third-party copies, analytics exports, external integrations, or data outside this particular SQLite database.
- No scheduled automation, irreversible database erasure guarantee, privacy request identity verification, or audit-logging workflow is implemented.

The security and GoreeShield governance release gates remain open. Independent identity-based authorization, governed per-user rights handling and production backup/restore validation are separate future work.