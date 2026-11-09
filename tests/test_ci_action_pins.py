"""Guard the only CI workflow against moving or unreviewed action revisions.

The official actions/checkout, setup-python and setup-node tag commits were
verified against GitHub's Git REST API on November 8, 2026. Changes to
this allowlist require an explicit engineering/CI review.
"""
from pathlib import Path
import re

CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
ALLOWED = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "6d4fd22b20465ccc0f7354476588e8df7c9ca0e0",
    "actions/setup-node": "949feb2413d6458794dcd2491c4babbbce0c15c1",
}


def test_workflow_uses_only_exact_sha_pinned_allowlisted_actions():
    source = CI.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", source, flags=re.M)
    assert len(uses) == len(ALLOWED), "Unexpected action use added, removed or duplicated"
    actual = {}
    for item in uses:
        assert "@" in item and item.count("@") == 1
        name, sha = item.split("@")
        assert re.fullmatch(r"[a-f0-9]{40}", sha), f"Action must use full SHA: {name}"
        assert name not in actual, f"Duplicate action: {name}"
        actual[name] = sha
    assert actual == ALLOWED
