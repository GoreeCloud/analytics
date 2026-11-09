"""Reject ambiguous JSON object keys before validating anonymous events.

RFC 8259 allows recipients to disagree about object member duplication.
Failing closed eliminates interpretation differences at the application
boundary, including duplicate nested event properties.
"""
from __future__ import annotations


def unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Use with json.loads(object_pairs_hook=...) for every nested JSON object."""
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Duplicate JSON object member")
        values[key] = value
    return values
