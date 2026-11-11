# Analytics — Collapsible GC UI navigation rail pilot

**Status:** Stacked draft consumer migration. Not production deployed, not a stable release and not human/physical-device accepted.

## Source and authority

This pilot builds on the separately staged [GC UI token migration](https://github.com/GoreeCloud/analytics/pull/36). The shared controller and component stylesheet are **byte-for-byte source snapshots** from the MIT-licensed [GoreeCloud UI main commit `2eba99e5844fa5c403dc006e63bfd60b1752043b`](https://github.com/GoreeCloud/gc-ui/commit/2eba99e5844fa5c403dc006e63bfd60b1752043b). Source blobs: `src/navigation-rail.js` = `7dbade32fc3446be1245fcb62bf4253a180fb77e` and `src/components.css` = `64b25a85ca155aaebb0cf40db5388bcb587527b9`. `tests/test_gc_ui_rail.py` verifies exact source, and updates must be reviewed and re-pinned. No npm build or external CDN is required for this Python consumer; all CSS and JavaScript run from the existing same-origin FastAPI asset allowlist.

## Responsive behavior

- At desktop widths of 1024+ CSS px, the sidebar starts expanded with labeled navigation. The button collapses it to icon-only.
- At tablet widths of 601–1023 CSS px, it starts compact and can expand. Native links remain accessible; title hints appear when compact, and text labels stay in the accessibility tree.
- At phone widths of 600 CSS px and below, the existing mobile bottom-navigation layout remains. The toggle is hidden and all destination labels are restored to visible text even if the user previously collapsed on a larger screen.
- The shell's main content occupies the remaining available width, preserving the existing dashboard cards, forms, session-only authentication and private reporting API. Existing unauthorized navigation still fails closed in `dashboard.js`.
- No new telemetry, location, remote scripts or preference persistence. The feature changes only navigation presentation and local hash selection; it does not grant data access or bypass server authorization.

## Verification and release gate

Run the full Analytics Python and Node tests and inspect local HTTP response headers for the bundled styles/modules. Compare before/after actual desktop 1440×900, tablet 820×1180 and phone 390×844 screens in dark/forced-color/reduced-motion and long-label states, including zoom and horizontal overflow. Verify keyboard toggle/focus, hash history, login-blocked destination clicks and VoiceOver/NVDA/Orca/TalkBack announcements on real hardware. A CI pass or a synthetic screenshot is **not** human visual approval. Manual AT and physical-device acceptance stay open and this stacked PR must not deploy by default.

**Rollback:** Revert this PR or restore the previous Analytics branch state; the token pilot remains independently reviewable. Do not change the server's authentication or database during visual acceptance.
