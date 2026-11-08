# Changelog

## Unreleased — DNS ownership proof (source development)

- Added per-host pending DNS TXT challenge verification, bounded resolver calls, per-domain retry limits, and fail-closed collection until proof.
- Existing site registrations and event history are preserved; previously registered hostnames must be reverified before new ingestion. **This intentionally changes earlier behavior.** Back up SQLite before upgrading.
- Added browser setup guidance and automated DNS fake-based verification, migration and authorization checks. No live DNS or production deploy is claimed.
- DNS proof is not authentication of visitor events, permission enforcement across teams, ongoing ownership monitoring, or a production clearance.


## November 5, 2026 — Post-publication maintenance

- Pin official checkout, Python setup, and Node setup GitHub Actions to verified commit SHAs; turn off checkout credential persistence and set a CI timeout.
- Configure Dependabot to propose weekly reviewed updates for GitHub Actions, Python packages, and Docker.
- Move two-step funnel ordering and conversion counts into SQLite so the API does not load the entire matching event history into Python memory. Add cross-session and interleaved-event regression coverage.
- **Status:** Changes are development-source improvements, not a production deployment; external dependency upgrade PRs require separate compatibility review.

## 0.1.2 — November 5, 2026 (published development source; not deployed)

- Implement SQLite online snapshot creation, schema/integrity verification, exclusive target-file creation (0600), and non-overwriting restore-to-new-path workflows.
- Require the offline retention CLI to create a verified pre-prune backup before applying deletions. Existing backups are never replaced.
- Add layered in-memory collector limits: anonymous identity, daily per-site network HMAC, and site-wide event rate.
- Aggregate summary statistics in SQLite instead of loading raw event histories into application memory.
- Fill missing calendar days with zeros in the timeseries API to avoid misleading traffic charts.
- Ensure newly created SQLite database files use owner-only permissions and refuse symbolic-link database paths.
- Add an explicit, first-party browser opt-out preference; honor it across visits without tracking identifiers and never override browser DNT/GPC.
- Avoid repeated same-URL pageviews on single-page application navigation.
- Add integrity, CLI, overwrite-safety, abuse-limit and timeseries regression checks: 28 Python tests plus 3 JavaScript tests.

A running localhost HTTP smoke test verified authentication, registration, event ingestion, reporting and dashboard delivery.

**Limitations:** Source code was published to the public `GoreeCloud/analytics` repository on November 5, 2026. No live deployment occurred. Real browser end-to-end, Docker runtime, offsite recovery testing, independent GC UI visual acceptance, distributed ingestion and production security review remain pending.

## 0.1.1 — November 5, 2026 (unpublished development snapshot)

- Enforce collector request-size limits during streaming rather than after full body buffering.
- Serialize visit selection and creation to avoid duplicate sessions for concurrent events.
- Correct event-only bounce handling and same-name ordered two-step funnels.
- Redact percent-encoded email identifiers from tracked paths and reject selected sensitive property values.
- Handle malformed URLs, origins and referrers without unhandled request errors.
- Reject blank website names and use full calendar-day boundaries in default summary windows.
- Add saved exact-match pageview/event goals, with per-visit conversion rates and dashboard goal creation.
- Add an offline, explicit dry-run-first SQLite retention command; refuse nonexistent database paths.
- Make dashboard navigation behave consistently when disconnected.
- Expand request, privacy, goals, retention and concurrency regression coverage to 19 tests.

## 0.1.0 — November 5, 2026 (initial local MVP)

Initial single-node FastAPI/SQLite source, anonymous browser tracker, event collection, admin API, dashboard, basic reports, CSV export, Compose and CI baseline.
