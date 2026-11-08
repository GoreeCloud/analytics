# GoreeCloud Identity integration contract — partial API gate, full Identity NOT implemented

**Status:** source-backed architecture and a development-only API gate with test-only synthetic identities. Real signed-token verification, SSO/browser login and live Keycloak integration are still unimplemented; no production approval is asserted. Verified dependency baseline: [GoreeCloud/identity](https://github.com/GoreeCloud/identity) `main` at `75b2957cf793343da4e8b119e70f673a973546f1` (November 7, 2026).

## Existing trust boundaries

- Analytics currently uses **one shared environment-supplied admin Bearer token** for the dashboard and every administrative/reporting route. Multiple sites are partitioned by site IDs. SQLite v2 introduces empty operator-owned site/tenant and site/subject permission tables; it still has no working user authentication, tenant enforcement or Identity connection. A site ID alone does not establish ownership.
- GoreeCloud Identity offers development-only Python `ResourceIdentityConfig`, `PinnedIssuerKeys`, `ResourceAuthorizer`, and `AccessRequest` components. They verify Keycloak-style RS256 bearer access tokens with an **operator-pinned issuer**, expected audience and OAuth client, token lifetime/class/scopes, a matching **signed** `goreecloud_tenant` claim, and explicit policy rules. Their source is not currently distributed to Analytics as a reviewed/installed package, and their existence does **not** imply a deployed login system.
- The Identity authorization adapter permits only explicitly allowed actions. A valid signature alone never grants resource access; tenant claim equality alone is not site ownership. Client IP in any Identity policy must be the directly authenticated peer (or supplied through independently verified trusted proxy configuration), **never raw X-Forwarded-For headers**.

## Required implementation order

1. **Define a deployable dependency contract.** Review and package the existing GoreeCloud Identity resource-server library with a controlled version, license, provenance, dependency pinning and tested upgrade path. Reuse it rather than writing a second JWT signature validator inside Analytics. No unpinned network fetches, token-provided JWK URLs, or arbitrary issuer discovery.
2. **Bind sites to a trusted tenant in the database.** Use the explicit, backup-gated v2 tenant/site-owner table and subject-permission model, and implement reviewed operator assignment and Identity enforcement, with an operator-reviewed mapping for legacy sites. **Never silently assign legacy sites to the first successfully signed-in user or to a token-provided tenant.** All site-specific APIs must independently resolve the site-to-tenant binding before evaluating access.
3. **Protect every administrative route.** An optional [Identity API gate](IDENTITY-API-GATE.md) now guards site-specific HTTP routes with exact stored tenant/subject/action membership *after* a trusted host-injected verifier returns a principal; no actual signed-token verifier is included. Integrate Identity's pinned issuer, audience, authorized party, mandatory scopes and signed tenant claim, then authorize exact site/action pairs. Site listing must filter by authorized memberships; wrong/unknown sites must not leak tenant data. Add strict privilege boundaries for domain verification/revocation, event reports and exports, goal editing, site deletion and operations.
4. **Disable unsafe fallback.** When Identity enforcement is enabled, do not accept the old shared admin token as an alternate way around tenant/role checks. The local development legacy mode may remain available only when explicitly configured and not exposed on a public listener. Missing Identity configuration, issuer outages, invalid tokens and absent policies fail **closed**.
5. **Handle web sign-in separately.** Use an OIDC Authorization Code + PKCE relying party and a server-side session/BFF with Secure, HttpOnly, SameSite cookies and CSRF protection. Do not write OAuth access/refresh tokens to browser localStorage, analytics events, URL query strings, or diagnostic logs. Identity's current browser-session examples are development scaffolding, not accepted Analytics web login.
6. **Define revocation and operational controls.** Enforce short token lifetimes, trusted signing-key rotation and appropriate online revocation/introspection. Add audited principal/resource/action outcomes without logging raw tokens or visitor information. Validate HTTPS/proxy boundaries and restore/migration procedures before any deployment.

## Proposed route-to-permission boundary

| Operation | Minimum explicit site permission | Additional condition |
| --- | --- | --- |
| List sites or read dashboards, summaries, funnels and goals | `analytics:read` | Only site IDs owned by the verified tenant and explicitly visible to the principal |
| Export event-level CSV | `analytics:export` | Site membership + separate privacy/export authorization |
| Create or change goals | `analytics:manage` | Site membership with write privileges |
| DNS ownership verification, revocation or site registration | `analytics:admin` | Verified tenant authority and separately audited operations |
| Delete an entire site and its records | `analytics:delete` | High-risk offline recovery/backup and confirmation controls, no browser delete route until reviewed |

These strings are **proposed** permission names, not existing GoreeCloud Identity scopes or shipped Analytics policies. Policies must distinguish action-specific permission from authentication and signed tenant affiliation. A global role should not automatically grant access to all sites in a shared database.

## Negative acceptance tests before enabling Identity mode

- Refuse unsigned, bad-signature, wrong-`kid`, expired, overlong-lived, ID-class, wrong issuer, audience or OAuth-client tokens; reject missing scope, malformed/absent/mismatched signed tenant and missing role/group policy.
- Refuse access to a site with no independently verified owner mapping, to another tenant's site, to unknown or deleted sites, or to a site outside the subject's membership; reject read-only users' export/delete/edit attempts.
- Refuse all operations during pinned-key-fetch failures or revoked/expired sessions according to an explicit policy; never fall back to an unverified bearer token or the legacy shared admin secret.
- Preserve normal DNS-gated public collection as a **separate anonymous trust boundary**; authenticated control-plane permissions do not prove visitor events legitimate.
- Exercise a real disposable Keycloak OIDC flow, API JWT verification, browser BFF/CSRF/Logout, per-site ownership migration, and CI before security acceptance. Test production certificate/proxy and key-rotation behavior separately.

## Product boundaries

GoreeShield owns data minimization, permissions transparency and consent/retention expectations. Wardveil owns threat monitoring, token/key abuse controls and incident response. GoreeCloud Mesh owns API interoperability. GoreeCloud UI owns the sign-in/admin experience. **GoreeCloud Identity owns principal authentication**, while Analytics must enforce its own resource ownership and least-privilege API decisions.

The separate v2 schema foundation and offline, manually confirmed first-owner binding are described in [Site Ownership](SITE-OWNERSHIP.md) and [Owner Assignment](OWNER-ASSIGNMENT.md); this integration design does not authenticate users, deploy a service, or change credentials.
