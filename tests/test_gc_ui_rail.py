"""Fail-closed source integrity and privacy regression for Analytics GC UI rail pilot."""
import hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "analytics" / "static"
UPSTREAM_GC_UI_COMMIT = "2eba99e5844fa5c403dc006e63bfd60b1752043b"
ASSETS = {
    "gc-ui-components.css": "64b25a85ca155aaebb0cf40db5388bcb587527b9",
    "gc-ui-navigation-rail.mjs": "7dbade32fc3446be1245fcb62bf4253a180fb77e",
}
def git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()

def test_shared_goreecloud_ui_rail_is_pinned_exact_source():
    for name, expected in ASSETS.items():
        body = (STATIC / name).read_bytes()
        assert git_blob_sha(body) == expected, f"{name} drifted from approved upstream source"
        text = body.decode("utf-8")
        assert "@import" not in text and "@font-face" not in text
        assert "url(https:" not in text and "url(http:" not in text
    module = (STATIC / "gc-ui-navigation-rail.mjs").read_text()
    assert "export function initNavigationRail" in module
    assert "localStorage." not in module and "sessionStorage." not in module
    assert "fetch(" not in module and "XMLHttpRequest" not in module

def test_dashboard_rail_contract_and_mobile_nav_are_explicit():
    html = (STATIC / "index.html").read_text()
    assert html.index('href="/assets/gc-ui-tokens.css"') < html.index('href="/assets/gc-ui-components.css"')
    assert html.index('href="/assets/gc-ui-components.css"') < html.index('href="/assets/style.css"')
    assert '<script type="module" src="/assets/gc-ui-rail-init.mjs">' in html
    assert 'aria-controls="analytics-primary-nav"' in html
    assert 'class="shell gc-navigation-shell"' in html
    assert html.count('class="gc-navigation-rail__label"') == 4
    css = (STATIC / "style.css").read_text()
    assert "@media (min-width:601px) and (max-width:820px)" in css
    assert "@media(max-width:600px)" in css
    assert '.sidebar .gc-navigation-rail__toggle { display:none; }' in css
    assert "flex-direction:row; align-items:stretch; justify-content:space-between" in css
    assert "height:calc(88px + env(safe-area-inset-bottom,0px))" in css
    assert ".main { padding-bottom:calc(100px + env(safe-area-inset-bottom,0px)); }" in css
    assert 'data-gc-collapsed="true"' in css
