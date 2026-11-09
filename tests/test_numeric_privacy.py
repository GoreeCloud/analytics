"""Prevent numeric identifiers in privacy-sensitive event fields.

These tests cover a class of identifiers omitted by the former string-only
property-value check. The rules are conservative and may reject long innocent
numbers until an explicit, privacy-reviewed field taxonomy is introduced.
"""
import pytest
from fastapi import HTTPException

from analytics.privacy import normalized_event, safe_path, contains_high_risk_identifier


@pytest.mark.parametrize("value", [
    "123456789", "123%32%33%34%35%36%37%38%39",
    "4111111111111111", "4111111111111111.0", 
    "0000000000000000", "purchase_4111111111111111",
])
def test_high_risk_unformatted_numeric_identifiers_are_detected(value):
    assert contains_high_risk_identifier(value)


@pytest.mark.parametrize("value", [
    123456789, 4111111111111111, 1234567890123, 4111111111111111.0,
    "4111111111111111", "purchase_4111111111111111"
])
def test_numeric_identity_in_json_properties_is_rejected(value):
    with pytest.raises(HTTPException) as exc:
        normalized_event({"type": "event", "url": "https://example.com/page",
                          "name": "purchase", "properties": {"metric": value}},
                         ["example.com"])
    assert exc.value.status_code == 400


@pytest.mark.parametrize("name", [
    "purchase_4111111111111111", "event_123456789",
])
def test_identifier_bearing_event_name_is_rejected(name):
    with pytest.raises(HTTPException) as exc:
        normalized_event({"type": "event", "url": "https://example.com/page",
                          "name": name}, ["example.com"])
    assert exc.value.status_code == 400


@pytest.mark.parametrize("value", [
    "123456789", "4111111111111111", "123%34%35%36%37%38%39",
])
def test_identifier_bearing_url_segments_are_masked(value):
    assert safe_path("/order/" + value) == "/order/:redacted"


@pytest.mark.parametrize("value", ["123456789", "4111111111111111"])
def test_numeric_utm_values_are_discarded(value):
    event = normalized_event({"type": "pageview", "url":
                              "https://example.com/?utm_source=" + value +
                              "&utm_medium=email&utm_campaign=launch"},
                             ["example.com"])
    assert event["utm_source"] == ""
    assert event["utm_medium"] == "email"
    assert event["utm_campaign"] == "launch"


def test_safe_analytics_values_continue_to_work():
    event = normalized_event({"type": "event",
        "url": "https://example.com/pricing?utm_source=summer",
        "name": "signup", "properties": {
            "amount": 120.25, "quantity": 103, "active": True,
            "category": "menswear-v2",
        }}, ["example.com"])
    assert event["utm_source"] == "summer"
    assert event["name"] == "signup"
    assert event["path"] == "/pricing"
