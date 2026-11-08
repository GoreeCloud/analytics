# Optional Identity-mode API gate — development integration seam

**Status:** Tested HTTP authorization boundary for a host-injected, separately verified principal. This is NOT a real JWT verifier, deployed Identity login, SSO, OIDC browser session, or authorization to expose Analytics publicly.

## Development behavior

- Default `GC_ANALYTICS_AUTH_MODE=legacy` retains the existing private-development shared admin token. Never expose that endpoint to the internet.
- Explicit `GC_ANALYTICS_AUTH_MODE=identity` requires the application host to call `create_app(settings, identity_verifier=<trusted callable>)` with a **reviewed cryptographic access-token verifier**. No verifier is shipped, and the default factory fails startup in Identity mode. Merely setting the environment variable never enables unsafe sign-in.
- The host verifier must validate pinned issuer/JWKS, token signature, audience, OAuth authorized party, token class/lifetime, required scopes, signed tenant claim and approved policies through GoreeCloud Identity when licensed and packaged. Never trust unverified token claims, `X-Forwarded-*` or caller-selected signing key URLs.
- With a trusted `VerifiedPrincipal(tenant_id, subject_id)`, exact v2 site-owner/subject/action records are checked. A valid signature, signed tenant claim or site ID alone never grants access.
- Site listing filters exact `analytics:read` memberships. Site reports and goal reading require `analytics:read`; CSV export needs `analytics:export`; goal creation needs `analytics:manage`; domain verify/revoke needs `analytics:admin`.
- Unowned, unauthorized and unknown sites are indistinguishable (404). The legacy admin secret cannot bypass Identity mode. Malformed tokens, principal objects or verifier errors return generic 401.
- Creating new sites in Identity mode is deliberately denied until a reviewed onboarding/tenant-binding procedure exists. Site deletion, ownership assignment and [permission revocation](PERMISSION-REVOCATION.md) remain offline/backup-gated; anonymous public collection remains separate and DNS-gated.

## Test and deployment limits

Local regression tests exercise the route permissions against **synthetic in-process test verifier callbacks** only. They do NOT verify any JWT signature, genuine Identity token, OIDC sign-in, revocation, Keycloak, HTTPS, proxy trust or browser BFF. The default dashboard remains a legacy-token interface and is not an Identity login.

Before any deployment, resolve [Identity licensing/packaging issue #17](https://github.com/GoreeCloud/identity/issues/17), import a reviewed pinned-issuer Identity resource adapter, validate real disposable signed-token/OIDC flows, independently verify tenant/site bindings and revocation, implement session/CSRF protection, and pass security/network/recovery/browser acceptance gates. This integration seam cannot be represented as operational SSO.

See [Identity integration requirements](IDENTITY-INTEGRATION.md) and [Security model](SECURITY.md).
