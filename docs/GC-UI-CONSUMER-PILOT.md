# GoreeCloud Analytics — GC UI token migration pilot

**Status:** Review-only development migration. This does not assert full visual/AT/device acceptance, Stable readiness or production deployment.

## Source and permissions

- Authoritative design: [GoreeCloud UI](https://github.com/GoreeCloud/gc-ui), MIT-licensed source at exact commit `1c173d64d966b52122ac02eb0ffbd07d2a5a09e4`.
- Imported asset: `src/tokens.css`, upstream Git blob `dd9a918eb4239cdd47fb13f383ee3496de459489`, copied byte-for-byte to `analytics/static/gc-ui-tokens.css` because this Python FastAPI consumer does not have a Node package/build pipeline for a dynamic shared CSS dependency.
- `tests/test_gc_ui_tokens.py` verifies the exact Git blob hash, CSS semantic roles, lack of external @imports/fonts and load order. Refresh must be a reviewed, pinned update, never a live CDN fetch.
- The app's existing MIT LICENSE applies to the copied same-owner MIT asset; preserve both source attribution and license on redistribution.

## Behavior preserved / intentionally changed

- Preserve the dashboard's existing HTML structure, routes, privacy and authentication flows, input actions and CSS component layouts.
- Keep dark appearance and current Iris alpha fallback as *provisional* design semantics. The prior hardcoded custom `--gc-` palette is removed; the actual colors/contrast now come from the canonical GC UI `--gc-` token file, so some visible color values legitimately differ.
- Load only local `/assets/gc-ui-tokens.css` before local component styling. No new browser network destinations or scripts are introduced; existing `style-src 'self'` CSP remains valid.

## Acceptance and rollback

1. Verify the original application test suite and the new source-integrity tests in CI; check CSS asset status and CSP.
2. Capture same-viewport before/after screenshots on the *actual running* local application at desktop/tablet/mobile widths, dark theme, larger type, forced colors and reduced motion.
3. Carry out keyboard/focus and screen-reader tests on the real dashboard (including the disconnected and denied states). Do **not** enter real credentials or collect analytics events in the visual QA fixture.
4. Reject any contrast or design regression. Preserve the pre-migration main state until evidence supports acceptance. Revert this branch/PR if the pilot is declined; never deploy it merely because automated tests pass.
5. A future build pipeline may replace the pinned snapshot with an equally deterministic same-origin bundled import; do not add CDN dependencies or a second independent theme authority.

This work is one consumer migration **candidate**. The separately maintained GoreeCloud Maps Foundations 1.0.1 consumer remains independent and is **not** silently upgraded to this new alpha contract.
