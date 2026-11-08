# GoreeCloud Analytics — Security Model (Early MVP)

**Status:** preliminary implementation review, NOT a penetration test, a compliance certification, or production clearance.

## Trust boundaries

1. **Collector (public):** anyone with a site ID can submit events **after** the site hostname has passed administrator-triggered DNS TXT ownership proof. Each request is streamed with an enforced 4 KB cap, must identify a DNS-verified exact-match domain, and must use a matching `Origin` header when present. These are abuse-reduction signals, **not proof of visitor authenticity**. Network edge rate limiting, bot defense, quotas, and ingestion integrity are not yet provided.
2. **Administrator API:** requires an environment-supplied bearer token of at least 32 characters. Token is kept only in the dashboard tab's JS memory, not browser storage. There is no multi-user authentication or RBAC. Restrict admin access to localhost or a trusted VPN until GoreeCloud Identity integration is implemented.
3. **Database:** SQLite contains event times, sanitized paths, referrer hostnames, coarse browser family, UTM tags, constrained event properties and daily HMAC visitor hashes. It does **not** intentionally store full IP addresses, complete referrer URLs, raw user-agent strings, cookies, or user-supplied distinct IDs.
4. **Infrastructure:** Docker/Compose is local-only by default; reverse-proxy/TLS and trusted client IP handling are unverified. No external database or SaaS dependency is required for the MVP.

## Existing measures

- Explicit admin and HMAC secrets, no fallback defaults, distinct 32+ character requirements.
- Strict authorization on all admin/reporting routes, including exports.
- Bounded streaming event body (4 KB) and field length limits; allowlisted event names and property keys, basic value detection.
- Registered-host equality check and collection origin matching, plus an administrator-triggered per-host DNS TXT challenge before intake. Existing registered domains are migrated as unverified pending and must be reverified.
- DNT and Global Privacy Control suppression; explicit first-party opt-out preference (no stored visitor identifier).
- Daily HMAC visitor identifiers, no IP storage; path-segment masking for likely identities, including selected repeatedly URL-encoded email addresses. Event property values with decoded email-like identifiers are rejected.
- Additional narrow safeguards reject selected formatted Social Security numbers, IPv4/IPv6 addresses and telephone-like identifiers in string event properties; matching path segments are redacted and sensitive UTM values omitted. These are heuristic patterns, **not comprehensive PII detection**. Legitimate non-personal labels resembling those patterns may be filtered.
- Layered anonymous, network-HMAC and registered-site in-memory rate limits, single-node only.
- Prepared SQL parameters; SQL column names selectable only from a hardcoded allowlist.
- Fresh SQLite files are created with owner-only (0600) file permissions and symbolic-link database paths are rejected. Existing database file permissions must be reviewed manually.
- No raw HTML injection from API data in dashboard (rendered through textContent/DOM APIs).
- CSP, nosniff, frame protection, Referrer-Policy, browser-cache disabling.
- CSV spreadsheet formula prefixing.
- Non-root Docker image, dropped container capabilities, read-only root filesystem in Compose.
- Automated request/authorization/privacy regression tests.

- An authenticated per-host manual revocation API can stop new collection and rotate one DNS TXT challenge without deleting historical analytics events. It has no dashboard control and is not automatic ownership-transfer detection.
- Collector event commits repeat the ownership check under SQLite's writer lock; a revocation committed before that transaction blocks ingestion. An event committed before a concurrent revocation acquires the lock remains historical data.

## Known open risks and release blockers

- Caller can forge `Origin`, URL, user agent, and public site ID. DNS TXT proof confirms control of one DNS record at verification time, not visitor authenticity, legal ownership or durable control. Resolver cache/trust, DNS poisoning, future domain transfers and the absence of periodic proof checks remain open risks. Collection should not be used for security-sensitive billing/audit claims.
- Site-wide single admin token is not suitable for organizations; no per-tenant roles, rotation UX, account lockout, or audit trails.
- In-process layered rate limits are reset by restart, not shared across workers or replicas, and can be bypassed by distributed traffic. They are not edge DDoS protection.
- Anonymous rate-limit tables have a 10,000-key in-memory ceiling per limiter; when saturated, new keys are rejected until expired entries can be evicted. This prevents single-minute key-flood memory growth but can temporarily reject legitimate new visitors and is not a substitute for edge traffic controls.
- Traffic behind a reverse proxy can appear to originate from one proxy IP. Trust proxy forwarded addresses **only** when configured with explicit trusted proxy hosts.
- Event values may still contain personal data despite the property-key denylist and basic value checks. Add stronger consent/data classification, redaction and deletion controls.
- Simple path masking cannot guarantee all PII is removed. Privacy review must inspect real representative URLs, logs and properties before enabling third-party traffic.
- SQLite has manual retention preview/pruning, a required validated pre-prune backup, local integrity-verified backup/restore-to-new-path tests, and an explicit, backup-gated offline schema v0-to-v1 migration for recognized legacy layouts. It lacks a general migration framework, production restore drills, offsite backup management, automated retention, HA and distributed ingestion.
- The current browser UI is not independently accessibility-audited or screenshot-accepted against full GoreeCloud UI requirements.
- Dependency lockfile, SBOM and automated vulnerability scanning remain to be added. GitHub Actions are pinned to verified commit SHAs, with persisted checkout credentials disabled; Dependabot opens reviewed dependency-update proposals without automatic merge.
- Runtime browser-backend integration could not be validated in the current browser sandbox; REST API and mocked UI interactions were tested separately.

## Backup confidentiality and recovery

- The backup CLI uses SQLite online backup API to capture WAL-consistent snapshots from a live database.
- Snapshot filenames are created exclusively with permission mode 0600, verified with SQLite integrity_check, and never overwritten by commands.
- Recovery writes to a new path; it cannot overwrite a live database or auto-switch the running service.
- Backups remain sensitive analytics datasets. Encrypt and protect copies, restrict access and retention, and validate restores in the intended environment.
- Local backup/restore tests do **not** establish an operational disaster-recovery plan.

## Reporting vulnerabilities

Avoid posting credentials, private website data, visitor data or exploit traces in public issues. Use GoreeCloud's designated private security reporting channel when one is established. Until then, privately contact the repository maintainer through an authenticated existing channel.

## Launch gate

Do not expose the service's administrator endpoint to the open internet until authentication, isolation, network controls, TLS, backups, retention/deletion policy, end-to-end E2E tests, and deployment acceptance are verified. Do not claim GDPR/CCPA certification from technical features alone.
