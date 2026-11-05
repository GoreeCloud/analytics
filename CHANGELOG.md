# Changelog

## 0.1.2 — November 5, 2026 (unpublished development snapshot)

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

**Limitations:** Source remains a local development snapshot. Neither GitHub publication nor live deployment occurred. Real browser end-to-end, Docker runtime, offsite recovery testing, independent GC UI visual acceptance, distributed ingestion and production security review remain pending.

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
