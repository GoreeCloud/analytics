"""HTTP authorization contract for a separately authenticated GoreeCloud subject.

This module does not decode JWTs, fetch signing keys, or establish a session.
ONLY a host-configured cryptographic Identity verifier can produce a trusted
principal. Never derive principal fields from HTTP headers or unsigned claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VerifiedPrincipal:
    tenant_id: str
    subject_id: str

    def __post_init__(self) -> None:
        for key, value, limit in (("tenant_id", self.tenant_id, 128),
                                  ("subject_id", self.subject_id, 255)):
            if type(value) is not str or not value or len(value) > limit or any(
                ord(c) < 33 or ord(c) == 127 for c in value
            ):
                raise ValueError(f"Invalid trusted {key}")


class IdentityVerifier(Protocol):
    """Host-side signed access token verification; no unverified claims."""

    def __call__(self, access_token: str) -> VerifiedPrincipal: ...
