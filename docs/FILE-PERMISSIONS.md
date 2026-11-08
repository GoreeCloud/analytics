# Analytics SQLite file permissions — development hardening

**Scope:** local POSIX SQLite file-mode checks at application startup. This is **not** at-rest encryption, an off-host backup procedure, OS hardening, or a production security review.

## Current policy

New database files are created with `0600` permissions. On POSIX systems, the application refuses to open **existing** database files that grant any group or other permission bits. Paths resolving to nonregular files (including directories, FIFOs or sockets) and direct database-file symlinks are rejected. This prevents easy accidental exposure of analytics records via permissive existing files.

## Safe remediation for a stopped development installation

1. Stop any writer, take and independently verify an authorized backup, and confirm the precise file path and expected owner.
2. Inspect permissions: `stat -c '%a %U %n' /path/to/analytics.sqlite3` on Linux. Review access to backups, `-wal` and `-shm` sibling files, parent directories, and network shares separately.
3. For a file that you own and have verified, apply `chmod 600 /path/to/analytics.sqlite3`. Do **not** recursively chmod unrelated data, replace ownership blindly, or delete the database.
4. Re-run read-only `python -m analytics.schema_audit --database /path/to/analytics.sqlite3` on a safe snapshot and start Analytics only when compatible. Existing versioned schema requirements still apply.

The check runs at startup; it is not a continuous filesystem-monitoring guarantee and does not close concurrent file replacement races. Systems with intentionally shared Unix-group access need an independently reviewed access strategy and currently cannot run under this MVP policy.

## Test evidence

The regression suite covers new `0600` files, rejection of modes `0640`, `0604`, `0644`, `0666`, safe `0600` recovery and nonregular/symlink paths. It never touches a live installation.
