"""Strict Origin header syntax for the anonymous browser collector.

This is browser/CORS policy validation, NOT cryptographic visitor
authentication. Non-browser clients can spoof or omit Origin entirely.
"""
from urllib.parse import urlparse


def valid_serialized_origin(value: str, registered_hostname: str) -> bool:
    """Only accept a canonical HTTP(S) serialized origin of the exact host."""
    if (type(value) is not str or not value or len(value) > 1024 or
            type(registered_hostname) is not str or not registered_hostname):
        return False
    if any(ord(c) < 33 or ord(c) > 126 for c in value):
        return False
    try:
        parsed = urlparse(value)
        port = parsed.port  # Raises on invalid/non-decimal/out-of-range ports.
        if parsed.scheme not in ("http", "https") or parsed.hostname != registered_hostname:
            return False
        if (parsed.username is not None or parsed.password is not None or
            parsed.path or parsed.params or parsed.query or parsed.fragment or
            port == 0):
            return False
        expected = f"{parsed.scheme}://{registered_hostname}"
        if port is not None:
            expected += f":{port}"
        # Compare raw bytes, not urlparse's normalized output. Reject smuggled
        # path/query/fragment/control characters and ambiguous port notation.
        return value == expected
    except ValueError:
        return False
