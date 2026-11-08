# GoreeCloud Analytics — Verified Coverage & Roadmap

**Status at initial repository baseline:** v0.1.2 MVP implementation, local testable source; no production deployment or compliance audit.

The founder's 27 product sections are target requirements. The following matrix prevents roadmap items from being misrepresented as shipped functionality.

| # | Product domain | Current status |
|---|---|---|
| 1 | Web traffic analytics | Partial: pageviews, daily visitors, visits, bounce estimate, paths, referrers, zero-filled time series |
| 2 | Real-time monitoring | Partial: five-minute anonymous activity and visitor counts |
| 3 | Custom events and product analytics | Partial: JS events, named events, constrained properties |
| 4 | Visitor identity and sessions | Partial: rotating daily anonymous HMAC, 30m sessions |
| 5 | Goals and funnels | Partial: ordered two-event funnel plus saved exact-match event/pageview goals; no multi-step saved funnels |
| 6 | User journeys | Planned |
| 7 | Session replay | Planned; consent, masking and retention gates required |
| 8 | Heatmaps | Planned; opt-in and privacy policy required |
| 9 | Audience segmentation and retention | Planned |
| 10 | Marketing attribution | Partial: referrer hostname and basic UTM capture |
| 11 | Trackable links and pixels | Planned |
| 12 | Revenue/ecommerce | Planned |
| 13 | Search and ads integrations | Planned |
| 14 | Core Web Vitals | Planned |
| 15 | Browser error tracking | Planned |
| 16 | Dashboards and BI | Partial: single-site dashboard and traffic chart |
| 17 | Reports and exports | Partial: CSV and JSON endpoints |
| 18 | AI analytics | Planned; read-only permission-aware interface first |
| 19 | APIs, SDKs, webhooks | Partial: local REST API and browser JS tracker |
| 20 | Privacy and security | Partial: DNT/GPC, keyed anonymization, constrained schemas, auth token, bounded request streaming, manual backup-gated retention preview/prune, owner-only database creation, local validated restore-to-new-path and opt-out; no audit completion |
| 21 | Teams and collaboration | Planned; no RBAC yet |
| 22 | Multi-site/multi-app | Partial: multiple registered websites with per-site data isolation; one administrator |
| 23 | Deployment/infrastructure | Partial: Python/SQLite and initial Docker/Compose packaging and SQLite backup/restore CLI; container execution, HA and production readiness unverified |
| 24 | GoreeCloud ecosystem integrations | Planned; documented integration contracts only |
| 25 | GC UI | Partial: original layout mapped to reference design tokens; rendered acceptance unverified |
| 26 | Monitoring and automation | Planned |
| 27 | Enterprise governance | Planned |

## Release gates before public hosting

- [ ] Replace or front the single shared admin token with GoreeCloud Identity + per-org RBAC. See the [Identity integration contract](IDENTITY-INTEGRATION.md) for the verified current boundary, mandatory site-to-tenant mapping and fail-closed release tests.
- [ ] Configure secure HTTPS reverse proxy and trusted forward headers; never trust arbitrary client-supplied IP headers.
- [ ] Validate network-level rate limiting, request body limits, capacity/load testing, storage performance.
- [ ] Extend manual retention preview/prune into governed automated policies; implement audit logging and backup/recovery testing.
- [ ] External security review: origins, CSRF, abuse/spam, sensitive event metadata, visitor hashing and proxy behavior.
- [ ] Database migrations and PostgreSQL; fail-safe upgrades and rollback.
- [ ] Validate browser compatibility, first-run flow, responsive light/dark/high-contrast, screen reader, reduced motion.
- [ ] Build/test/publish CI with pinned dependencies and supply-chain checks.
- [ ] Add optional consent management for features beyond cookie-free aggregate analytics.
- [ ] Verify production deployment and a real end-to-end ingestion/reporting path before asserting release readiness.
