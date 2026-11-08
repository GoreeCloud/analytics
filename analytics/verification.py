"""Per-host DNS ownership proof with bounded resolver behavior.

This confirms DNS write control at one point in time, not legal ownership,
DNSSEC validation, durable ownership, or authenticity of collected events.
"""
import dns.exception
import dns.resolver

LABEL = "_goreecloud-analytics"
PREFIX = "goreecloud-analytics-verification="


class DNSLookupUnavailable(Exception):
    """The configured resolver could not provide a usable DNS answer."""


def txt_record_name(domain: str) -> str:
    return f"{LABEL}.{domain}"


def txt_record_value(challenge: str) -> str:
    return f"{PREFIX}{challenge}"


def read_txt_records(record_name: str) -> list[str]:
    """Use only the host-configured recursive TXT resolver; never fetch URLs."""
    resolver = dns.resolver.Resolver(configure=True)
    resolver.timeout = 1.0
    resolver.lifetime = 3.0
    try:
        answers = resolver.resolve(record_name + ".", "TXT", search=False)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException as exc:
        raise DNSLookupUnavailable("DNS verification lookup failed") from exc
    result = []
    for item in answers:
        raw = b"".join(item.strings)
        if len(raw) > 512:
            continue
        try:
            result.append(raw.decode("ascii"))
        except UnicodeDecodeError:
            continue
    return result
