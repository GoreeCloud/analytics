# Client-side minimization of Analytics events

**Status:** tested early-development tracker behavior. This is defense in depth, not a complete PII filter or legal consent program.

## Outbound payload

The cookie-free browser tracker now sends a stripped page URL rather than `location.href` as-is. It removes fragments, all query keys other than `utm_source`, `utm_medium` and `utm_campaign`, and suppresses suspiciously formatted values from those three permitted keys. The path sanitizer replaces selected identity-like path segments with `:redacted` before transmission. It sends only the **origin** of the referring web page, never its path, query string or fragment.

The SPA navigation deduplicator uses the minimized page URL; changing only a discarded query parameter no longer creates a synthetic new pageview. DNT, Global Privacy Control and manual opt-out behavior are unchanged. HTTP(S)-only URL validation prevents the tracker from emitting `file:` or other non-web URL values.

## Boundaries and verification

- Event names and caller-provided `properties` are still application-controlled; applications must not submit secrets, personal information, identifiers or sensitive event properties. Server-side validation remains necessary.
- Heuristic path masking cannot cover arbitrary free-text names or every identifier. Generated server logs, intermediaries, and upstream first-party website logs must be reviewed separately.
- UTM source/medium/campaign continue to be supported but may be omitted when malformed or potentially sensitive. Referrer **host attribution** is preserved; detailed paths are intentionally not transmitted.
- Six local Node tests cover opt-out, DNT/GPC, same-path SPA navigation, sensitive URL/referrer stripping, query-only SPA changes and unsupported schemes. Passing tests do not establish production browser, consent, accessibility or network logging acceptance.
- This minimization applies to the bundled tracker; direct callers of `/api/v1/collect` still require server-side validation. No production deployment is asserted.

See [GoreeCloud Analytics Security Model](SECURITY.md) for release blockers.
