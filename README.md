# GoreeCloud Analytics

**Privacy-first, self-hosted web and product analytics — early MVP (v0.1.2).**

GoreeCloud Analytics is an original, small analytics service for the GoreeCloud ecosystem. The founder's full 27-domain product specification is a **target architecture**, not an implementation claim. This repository implements the initial verified vertical slice: registered-site management, cookie-free pageviews, custom events, basic anonymous visits, real-time activity counts, traffic summaries, UTM extraction, page and event breakdowns, a basic two-step funnel, saved exact-match conversion goals, CSV export, exclusive verified SQLite backup/restore and backup-gated retention, and a GC UI-aligned responsive dashboard with goal creation.

> **Maturity:** early development. Not production-ready or deployed. Session replay, heatmaps, ecommerce integrations, federated SSO, advanced funnels/cohorts, MCP, AI, multi-tenancy, distributed ingestion, and PostgreSQL are **not yet implemented**.

## Quick start (local development)

Requires **Python 3.11+**. Use a dedicated virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
export GC_ANALYTICS_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export GC_ANALYTICS_HASH_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export GC_ANALYTICS_DATABASE=./analytics.sqlite3
uvicorn analytics.app:build --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Open http://127.0.0.1:8000 and supply the admin token that was generated in your terminal. **Persist the tokens in a secure secret store if you want data access across restarts.** Restarting with a new hash secret resets anonymous identity continuity; keep secrets private and outside Git.

### Docker Compose (local-only by default)

Set the two environment variables using **independent random values** (the `.env.example` intentionally contains empty fields, not usable secrets), then run:

```bash
docker compose up --build -d
```

The Compose configuration binds only `127.0.0.1:8000`, uses a persistent data volume and a non-root container, and is still **not approved for public exposure**. If your container engine does not propagate a writable owned volume, adjust its volume ownership before starting rather than running the service as root. Do not publish the administrator endpoint until the release gates are satisfied.

### Register and verify a website

Register a website using **Add website** and its FQDN (for example `example.com`). New registrations remain **pending**, and public collection is rejected until the administrator proves DNS control for each hostname. In your DNS provider, publish the TXT record shown in the dashboard:

```text
Name:  _goreecloud-analytics.example.com
Type:  TXT
Value: goreecloud-analytics-verification=<unique challenge from the dashboard>
```

After DNS propagation, select **Check DNS TXT record**. The server performs a bounded TXT lookup through its configured recursive resolver. Verification is per exact hostname; verifying the apex does not verify subdomains. The dashboard reveals the tracker snippet only after a matching domain has been verified. Install it immediately before the closing `</head>` element of each verified site.

Administrators may also use authenticated `GET /api/v1/sites` for pending TXT records and `POST /api/v1/sites/{site_id}/domains/verify` with JSON body `{"domain":"example.com"}`. DNS checks are limited to six attempts per minute per domain on this node. DNS proof is **not** authentication of individual tracking requests.

**Important existing-database upgrade:** Create and verify a consistent SQLite backup before deploying this schema. Historical site records and event rows remain intact, but existing registered domains start **unverified**, so new collection will pause until TXT verification is completed. Plan that interruption explicitly. Schema migrations and rollback are not yet fully versioned, and no production migration has been tested.

These checks do not replace GoreeCloud Identity access policies, privacy consent, IP/network controls, periodic proof revalidation, or external DNS trust analysis. The tracker uses no cookies, honors DNT/GPC, sends sanitized pageview and custom event data, and exposes:

```js
window.goreecloudAnalytics.track('signup', {plan: 'free'});
```

An element with `data-gc-event="signup"` also produces a custom event when clicked. Do not send names, email addresses, access tokens, or sensitive information as event properties.

### Revoke a hostname's verification (administrative recovery)

An authenticated administrator can disable a registered hostname's ingestion using `POST /api/v1/sites/{site_id}/domains/revoke` with JSON `{"domain":"example.com"}`. This rotates that hostname's DNS challenge and clears its verified status without deleting historical data. Collection returns HTTP 403 until the **new** challenge is published and verified.

**This intentionally interrupts collection.** Use it only for a known DNS ownership or trust concern; the dashboard does not expose a revoke button. Automatic periodic re-verification, ownership-transfer detection, and tenant-scoped credentials remain outstanding.

### Saved conversion goals

After registering a site, use the dashboard's **Conversion goals** form to create an exact-match pageview goal such as `/pricing` or event goal such as `signup`. The goal report counts each converting visit at most once in the selected date window. Administrator-authenticated API endpoints are `POST /api/v1/sites/{site_id}/goals` and `GET /api/v1/sites/{site_id}/goals`. Goal rates use visits with any tracked activity as the denominator; they are **not** user-level conversion rates or revenue attribution.

### API example

```bash
curl -H "Authorization: Bearer $GC_ANALYTICS_ADMIN_TOKEN" http://127.0.0.1:8000/api/v1/sites
```

`GET /healthz` is unauthenticated. Administrative APIs require an exact Bearer token. Anonymous collection is via `POST /api/v1/collect` and registered domains. The raw IP is used only in memory to derive a daily HMAC identifier; IP is not saved. Registered and DNS-verified domains are exact-match. The cross-site origin must match the event URL host when present; this origin signal does not prevent forged non-browser events.

## Architecture and privacy boundaries

- **Backend:** FastAPI with SQLite using atomic transactions and restricted permissions on newly created database files, suited only to a single-node early release. Docker/Compose packaging is included but a container runtime build has not been verified. No production migrations, queue, or distributed rate limiter.
- **Frontend:** original vanilla HTML/CSS/JS dashboard, aligned to verified GoreeCloud UI (`GoreeCloud/gc-ui`) semantic tokens, spacing, accessibility patterns, and visual hierarchy. It is not a packaged upstream GC UI component release.
- **Tracking:** first-party-installable cookie-free JS tracker, request-size limit, event-property allowlist, exact-match host check, browser-origin check, DNT/GPC handling, optional persistent local opt-out preference, daily anonymized visitor HMAC, 30-minute inactivity sessions, layered in-memory rate limiting.
- **Administration:** single environment-supplied administrator token; no authentication UX, organizational RBAC, or SSO yet. Use a VPN or trusted reverse proxy for any non-local admin access and HTTPS for tracker delivery. Do **not** expose this MVP admin UI publicly without completing the security roadmap.
- **Limitations:** anonymous visitors are based on IP + user agent and rotate daily. Shared IPs can cause collisions; a changed IP or user agent can split identities. Live visits and bounce rates are approximate. Event submission is publicly instrumented and cannot be guaranteed fraud-free. Browser geography and session replay are not implemented. Layered limiters are only local-memory and are not a replacement for edge DDoS protection. Event properties must not contain PII; simple value checks catch some sensitive values but cannot guarantee safe classification.

## Quality checks

```bash
python -m pytest -q
node --test tests/tracker.test.mjs
python -m compileall -q analytics
```

A local HTTP smoke test has exercised a running localhost server, administrator authorization, registration, collection and summaries. A real graphical browser end-to-end test is still pending.

## Data retention (offline maintenance)

The initial service has a **manual, dry-run-first** retention utility. It does not silently delete historical data or schedule recurring cleanup. The CLI **requires** an exclusive, integrity-verified backup before it will prune records:

```bash
python -m analytics.maintenance --database ./analytics.sqlite3 --days 90
# Review the JSON counts, then use an exclusive automatic backup before deleting.
mkdir -m 700 -p ./private-backups
python -m analytics.maintenance --database ./analytics.sqlite3 --days 90 --apply \
  --backup-to ./private-backups/pre-prune.sqlite3
```

Expired events are removed and expired sessions without retained events are pruned. The command rejects missing database paths and existing backup destinations instead of overwriting data. Backups should be encrypted and retained outside the application host according to a documented private retention policy. Manual restore-to-new-path functionality and local snapshot integrity tests are implemented, but production recovery, off-host backup rotation and scheduled retention remain release blockers.

## Local backup, verification and recovery

Back up a running SQLite service with the consistent SQLite backup API (no direct copying of a live WAL database). Destination directories must already exist and existing backups are never overwritten:

```bash
mkdir -m 700 -p ./private-backups
python -m analytics.backup --database ./analytics.sqlite3 --output ./private-backups/snapshot.sqlite3
python -m analytics.backup --verify-only ./private-backups/snapshot.sqlite3
# Recovery creates a NEW file; it never replaces an existing live database.
python -m analytics.backup --restore-from ./private-backups/snapshot.sqlite3 --output ./restored.sqlite3
```

Before promoting a restored database, **stop the service**, verify its contents, take a separate backup of the live database, and explicitly change the configured database path. The recovery command does not deploy or automatically switch the service. Backups contain analytics data and must not be committed to Git or stored in public locations.

## Opt out of browser tracking

The browser honors Do Not Track and Global Privacy Control. A website can also expose a voluntary, persistent opt-out toggle without creating a tracking cookie:

```js
window.goreecloudAnalytics.optOut(); // stops events and stores a first-party privacy preference
window.goreecloudAnalytics.isOptedOut();
window.goreecloudAnalytics.optIn(); // never overrides browser DNT/GPC
```

The only localStorage entry created by the tracker is an explicit privacy preference; it stores no visitor identifier. Without storage permission, opt-out remains effective for the current page only. Site administrators remain responsible for lawful consent and privacy notices.

## Planned delivery phases

1. **Harden the foundation:** threat modeling, reverse proxy trusted-host configuration, authentication and granular permissions, deletion/retention, migrations, and Postgres support.
2. **Product analytics:** saved goals, richer funnels, journey maps, cohorts, retention, custom segmentation, better UTM attribution and reporting.
3. **Experience monitoring:** explicit consent controls, replay masking and opt-in recording, aggregate heatmaps, Core Web Vitals, client errors, policy-tested retention.
4. **Ecosystem and intelligence:** GC UI package adoption, GoreeCloud Identity/Workspace Teams roles, Notify integrations, read-only MCP, AI analysis, payment-provider connectors, scheduled reports, auditable automation.

See [docs/ROADMAP.md](docs/ROADMAP.md) for the 27-domain coverage matrix and [docs/SECURITY.md](docs/SECURITY.md) for the documented threat model and launch blockers.

## Licensing and provenance

The original GoreeCloud-authored source in this repository is licensed under **MIT**; see [`LICENSE`](LICENSE). MIT was selected for this initial permissive original-source service and tracker so other GoreeCloud apps can integrate with it. Dependencies remain governed by their own upstream licenses; no Umami source code, artwork, icons, or copyrighted interface assets were imported. Upstream Umami was referenced as a product research baseline only, not represented as GoreeCloud-authored code.
