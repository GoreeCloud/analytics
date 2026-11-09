"""Privacy-constrained request normalization and anonymous identification."""
import math
import hashlib
import hmac
import ipaddress
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, unquote

from fastapi import HTTPException

DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)
EVENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
PROP_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")

# Block selected high-risk personal identifiers in event values and paths.
# These narrow rules reduce accidental collection; they are not a general PII audit.
SSN_RE = re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)")
IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\w)")
# Conservative, form-independent protection for unformatted identifiers.
# Tradeoff: this can also omit legitimate 9- and 13+-digit metric labels.
BARE_SSN_RE = re.compile(r"(?<!\d)\d{9}(?!\d)")
LONG_NUMERIC_ID_RE = re.compile(r"(?<!\d)\d{13,}(?!\d)")


def contains_high_risk_identifier(value: str) -> bool:
    """Recognize selected formatted identifiers after bounded URL decoding."""
    decoded = decode_for_privacy(value)
    if (SSN_RE.search(decoded) or PHONE_RE.search(decoded)
            or BARE_SSN_RE.search(decoded) or LONG_NUMERIC_ID_RE.search(decoded)):
        return True
    if IPV4_RE.search(decoded):
        for candidate in IPV4_RE.findall(decoded):
            try:
                if isinstance(ipaddress.ip_address(candidate), ipaddress.IPv4Address):
                    return True
            except ValueError:
                continue
    try:
        return isinstance(ipaddress.ip_address(decoded), ipaddress.IPv6Address)
    except ValueError:
        return False



def normalize_domain(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if len(value) > 253 or not DOMAIN_RE.fullmatch(value) or "." not in value:
        raise ValueError("Expected a fully qualified domain, e.g. example.com")
    return value


def allowed_host(host: str, domains: list[str]) -> bool:
    return host.lower() in domains


def decode_for_privacy(value: str) -> str:
    """Unwrap nested URL encoding for PII checks without storing decoded values."""
    for _ in range(6):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value


def safe_path(path: str) -> str:
    """Mask likely identity-bearing path segments before storing analytics."""
    result = []
    for segment in (path or "/").split("/"):
        # Decode only to classify sensitive values: %40 must not bypass email
        # masking. Never store an undecoded sensitive identifier as a path.
        decoded = decode_for_privacy(segment)
        lower = decoded.lower()
        if ("@" in decoded or len(decoded) > 32 or
            re.search(r"[0-9]{5,}", lower) or
            re.search(r"(?:bearer|secret|token|apikey|accesskey|password)[_=-]", lower) or
            re.fullmatch(r"[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}", lower) or
            contains_high_risk_identifier(decoded)):
            result.append(":redacted")
        else:
            result.append(segment)
    return ("/".join(result) or "/")[:512]


def normalized_event(payload: dict, allowed_domains: list[str]) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(400, "Expected a JSON object")
    kind = payload.get("type", "")
    if kind not in ("pageview", "event"):
        raise HTTPException(400, "type must be pageview or event")
    url = payload.get("url", "")
    if not isinstance(url, str) or len(url) > 2048:
        raise HTTPException(400, "Invalid URL")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise HTTPException(400, "Invalid URL") from exc
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or not parsed.hostname:
        raise HTTPException(400, "Invalid URL")
    try:
        hostname = parsed.hostname.lower().rstrip(".")
    except ValueError:
        raise HTTPException(400, "Invalid hostname")
    if not allowed_host(hostname, allowed_domains):
        raise HTTPException(403, "Domain is not registered for this site")
    name = payload.get("name", "")
    if not isinstance(name, str) or (kind == "event" and not EVENT_RE.fullmatch(name)):
        raise HTTPException(400, "Invalid event name")
    if kind == "pageview":
        name = ""
    elif contains_high_risk_identifier(name):
        raise HTTPException(400, "Sensitive event name")
    props = payload.get("properties", {})
    if not isinstance(props, dict) or len(props) > 20:
        raise HTTPException(400, "properties must be an object with 20 or fewer entries")
    safe_props = {}
    for key, val in props.items():
        if not isinstance(key, str) or not PROP_RE.fullmatch(key) or any(s in key.lower() for s in ("password", "token", "secret", "email", "phone", "address", "credit", "card", "ssn")):
            raise HTTPException(400, "Disallowed event property key")
        if type(val) not in (str, bool, int, float) or (type(val) is float and not math.isfinite(val)) or len(str(val)) > 160:
            raise HTTPException(400, "Disallowed event property value")
        if type(val) in (str, int, float):
            privacy_scan = decode_for_privacy(str(val))
            if ("@" in privacy_scan or
                re.search(r"\b(?:bearer\s|sk-[A-Za-z0-9]|[0-9]{13,19}\b)",
                          privacy_scan, re.I) or
                contains_high_risk_identifier(privacy_scan)):
                raise HTTPException(400, "Sensitive event property value")
        safe_props[key] = val
    if len(json.dumps(safe_props)) > 2048:
        raise HTTPException(400, "Event properties too large")
    qs = parse_qs(parsed.query)
    def utm(key):
        s = qs.get(key, [""])[0]
        if (not isinstance(s, str) or
                not re.fullmatch(r"[A-Za-z0-9_.~-]{1,100}", s) or
                contains_high_risk_identifier(s)):
            return ""
        return s
    referrer = payload.get("referrer", "")
    if isinstance(referrer, str) and len(referrer) <= 2048:
        try:
            r = urlparse(referrer)
            referrer = (r.hostname or "").lower() if r.scheme in ("http", "https") else ""
        except ValueError:
            referrer = ""
    else:
        referrer = ""
    return {
        "kind": kind, "hostname": hostname, "path": safe_path(parsed.path or "/"),
        "name": name, "properties": json.dumps(safe_props, separators=(",", ":")),
        "referrer": referrer[:253],
        "utm_source": utm("utm_source"), "utm_medium": utm("utm_medium"),
        "utm_campaign": utm("utm_campaign"),
    }


def anonymize(secret: str, site_id: str, ip: str, user_agent: str, now: datetime) -> str:
    # Daily keyed hash. Raw IP and UA are never persisted; hash rotates every UTC day.
    day = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    msg = f"{day}|{site_id}|{ip}|{user_agent[:250]}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:32]
