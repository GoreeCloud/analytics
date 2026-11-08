"""Selected high-risk identifier regression coverage (not comprehensive PII detection)."""
import pytest
from fastapi import HTTPException
from analytics.privacy import contains_high_risk_identifier, normalized_event, safe_path


@pytest.mark.parametrize("value", [
    "123-45-6789", "123%2D45%2D6789", "123%252D45%252D6789",
    "192.168.10.42", "192%2E168%2E10%2E42", "2001:db8::1",
    "(555) 123-4567", "+1 555 123 4567",
])
def test_high_risk_identifiers_rejected_as_properties(value):
    assert contains_high_risk_identifier(value)
    with pytest.raises(HTTPException) as error:
        normalized_event({
            "type": "event", "url": "https://example.com/checkout",
            "name": "purchase", "properties": {"label": value}
        }, ["example.com"])
    assert error.value.status_code == 400


@pytest.mark.parametrize("path", [
    "/customers/123-45-6789", "/customers/123%2D45%2D6789",
    "/host/192.168.1.42", "/host/2001%3Adb8%3A%3A1",
    "/contact/555-123-4567",
])
def test_high_risk_path_segments_redacted(path):
    assert safe_path(path).split("/")[-1] == ":redacted"


def test_sensitive_utm_values_are_dropped_without_recording():
    output = normalized_event({
        "type": "pageview", "url": "https://example.com/?utm_source=192.168.1.10"
    }, ["example.com"])
    assert output["utm_source"] == ""


@pytest.mark.parametrize("value", ["spring-sale", "v1.2.3.4", "purchase_123", "free", "direct"])
def test_harmless_event_labels_remain_allowed(value):
    assert not contains_high_risk_identifier(value)
    normalized_event({
        "type": "event", "url": "https://example.com/home",
        "name": "purchase", "properties": {"label": value}
    }, ["example.com"])
