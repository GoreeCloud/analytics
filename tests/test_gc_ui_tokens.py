"""Fail-closed checks for the pinned, offline GoreeCloud UI token pilot."""
import hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "analytics" / "static"
UPSTREAM_BLOB_SHA = "dd9a918eb4239cdd47fb13f383ee3496de459489"
UPSTREAM_COMMIT = "1c173d64d966b52122ac02eb0ffbd07d2a5a09e4"
def test_immutable_gc_ui_token_snapshot_and_safe_css():
    body = (STATIC / "gc-ui-tokens.css").read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(body)).encode("ascii") + b"\0" + body).hexdigest()
    assert actual == UPSTREAM_BLOB_SHA, "GC UI snapshot changed without a reviewed upstream pin"
    content = body.decode("utf-8")
    for role in ("--gc-canvas:", "--gc-surface:", "--gc-text:", "--gc-brand:",
                 "--gc-on-brand:", "--gc-focus-ring:", "--gc-radius-md:"):
        assert role in content
    assert "@import" not in content and "@font-face" not in content
    assert "url(http" not in content.lower()
def test_dashboard_consumes_shared_tokens_before_local_components():
    html = (STATIC / "index.html").read_text()
    first = html.index('href="/assets/gc-ui-tokens.css"')
    second = html.index('href="/assets/style.css"')
    assert first < second
    assert 'data-gc-theme="dark"' in html and 'data-gc-accent="iris"' in html
    css = (STATIC / "style.css").read_text()
    assert "var(--gc-canvas)" in css and "var(--gc-text)" in css
    assert "--gc-canvas:#" not in css and "--gc-brand:#" not in css
    assert "font-family:var(--gc-font-ui," in css
