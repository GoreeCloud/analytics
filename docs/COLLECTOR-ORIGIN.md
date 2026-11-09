# Collector Origin validation (development)

The anonymous collector validates a supplied browser `Origin` as a **canonical
serialized HTTP(S) origin** for the exact DNS-proven site hostname.
Userinfo, paths, queries, fragments, whitespace/control characters, invalid
ports, trailing separators and noncanonical hostname/scheme spelling are
rejected before event ingestion. A valid origin may include a nonzero port;
the server does not reflect malformed `Origin` values in a CORS header.

The tracker uses a normal serialized browser Origin. This guard intentionally
rejects hand-crafted origin-like URLs such as
`https://example.com/path?secret=foo`, which older code accepted solely
because the parsed hostname matched.

**Security boundary:** An anonymous request without `Origin` remains allowed
for compatible clients; attackers can omit or spoof `Origin` and `site_id`.
This change is **not visitor authenticity, CSRF protection for authenticated
routes, origin-based authorization, or distributed abuse prevention**. Exact
DNS TXT verification, ingress quotas and network-edge controls remain separate
requirements. Development clients sending noncanonical values must correct
their headers rather than disable the check.
