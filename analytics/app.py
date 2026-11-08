"""GoreeCloud Analytics MVP API and browser dashboard.

Explicitly single-node. External collection is anonymous and public by design;
administrative reads/writes always require a separate server secret.
"""
from __future__ import annotations

import csv
import hmac
import io
import json
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Callable
from threading import Lock
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import Settings
from .auth import IdentityVerifier, VerifiedPrincipal
from .ownership import has_site_permission
from .privacy import EVENT_RE, anonymize, normalize_domain, normalized_event, safe_path
from .storage import Storage
from .verification import DNSLookupUnavailable, read_txt_records, txt_record_name, txt_record_value

STATIC = Path(__file__).parent / "static"


def browser_family(user_agent: str) -> str:
    """Store only a coarse browser family, not the raw user-agent fingerprint."""
    ua = user_agent.lower()
    for signature, family in (("edg/", "Edge"), ("firefox/", "Firefox"),
                              ("chrome/", "Chrome"), ("safari/", "Safari")):
        if signature in ua:
            return family
    return "Other"


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    domains: list[str] = Field(min_length=1, max_length=20)


class DomainVerify(BaseModel):
    domain: str = Field(min_length=3, max_length=253)


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["event", "pageview"]
    target: str = Field(min_length=1, max_length=512)


class SingleNodeLimiter:
    """Basic anonymous ingestion limiter; use network edge limits for deployments."""
    def __init__(self, limit: int = 120):
        self.limit = limit
        self._data: dict[str, tuple[int, int]] = {}
        self._lock = Lock()

    def check(self, key: str) -> bool:
        window = int(time.monotonic() // 60)
        with self._lock:
            # Keep a hard memory ceiling even when a flood introduces new
            # identifiers within a single minute. Previous cleanup kept all
            # current-window keys, allowing unbounded memory growth.
            if key not in self._data and len(self._data) >= 10000:
                self._data = {k: v for k, v in self._data.items() if v[0] == window}
                if len(self._data) >= 10000:
                    return False  # Fail closed for new keys until next window.
            old_window, count = self._data.get(key, (window, 0))
            count = count + 1 if old_window == window else 1
            self._data[key] = (window, count)
            return count <= self.limit


def create_app(settings: Settings | None = None, txt_lookup: Callable[[str], list[str]] | None = None,
               identity_verifier: IdentityVerifier | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.auth_mode not in ("legacy", "identity"):
        raise RuntimeError("Unknown authorization mode")
    if settings.auth_mode == "identity" and not callable(identity_verifier):
        raise RuntimeError("Identity mode requires a trusted signed-token verifier")
    if settings.auth_mode == "legacy" and identity_verifier is not None:
        raise RuntimeError("Do not attach an Identity verifier in legacy mode")
    storage = Storage(settings.database)
    limiter = SingleNodeLimiter()
    ip_limiter = SingleNodeLimiter(limit=600)
    site_limiter = SingleNodeLimiter(limit=10000)
    ingress_limiter = SingleNodeLimiter(limit=1800)
    dns_limiter = SingleNodeLimiter(limit=6)
    app = FastAPI(title="GoreeCloud Analytics", version="0.1.2", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.storage = storage
    # In-memory safeguards only: dedicated network-edge protection is required
    # before public hosting. Keeping separate buckets limits UA-rotation spam.
    app.state.ip_limiter = ip_limiter
    app.state.site_limiter = site_limiter
    app.state.ingress_limiter = ingress_limiter
    app.state.dns_limiter = dns_limiter
    app.state.txt_lookup = txt_lookup or read_txt_records

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        result = await call_next(request)
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Referrer-Policy"] = "no-referrer"
        result.headers["X-Frame-Options"] = "DENY"
        result.headers["Cache-Control"] = "no-store"
        result.headers["Content-Security-Policy"] = (
            "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            "script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; form-action 'self'"
        )
        return result

    def admin(authorization: str | None, *, site_id: str | None = None,
              permission: str = "analytics:read") -> VerifiedPrincipal | None:
        prefix = "Bearer "
        candidate = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else ""
        if (not candidate or len(candidate) > 16384 or
                any(ord(char) < 33 or ord(char) > 126 for char in candidate)):
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})
        if settings.auth_mode == "legacy":
            if not hmac.compare_digest(candidate, settings.admin_token):
                raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})
            return None
        # Identity mode never accepts the legacy admin token as a bypass.
        # The host adapter, once approved, MUST verify signature, pinned
        # issuer, audience, client, scopes, token lifetime/class and tenant.
        if hmac.compare_digest(candidate, settings.admin_token):
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})
        try:
            principal = identity_verifier(candidate)
        except Exception:
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"}) from None
        if type(principal) is not VerifiedPrincipal:
            raise HTTPException(401, "Unauthorized", headers={"WWW-Authenticate": "Bearer"})
        if site_id is not None:
            with storage.connect() as db:
                if not has_site_permission(db, site_id=site_id,
                                           trusted_tenant_id=principal.tenant_id,
                                           trusted_subject_id=principal.subject_id,
                                           permission=permission):
                    raise HTTPException(404, "Unknown site")
        return principal

    def get_site(db, site_id: str):
        site = db.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        if site is None:
            raise HTTPException(404, "Unknown site")
        return site

    @app.get("/healthz")
    def health():
        return {"status": "ok", "service": "goreecloud-analytics"}

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/assets/{name}", include_in_schema=False)
    def assets(name: str):
        if name not in ("dashboard.js", "style.css", "tracker.js"):
            raise HTTPException(404)
        media = "text/javascript" if name.endswith(".js") else "text/css"
        return FileResponse(STATIC / name, media_type=media)

    def domain_status(db, site_id: str):
        return [{"domain": item["domain"], "verified": item["verified_at"] is not None,
                 "verified_at": item["verified_at"],
                 "record_name": txt_record_name(item["domain"]),
                 "record_value": txt_record_value(item["challenge"]) if item["verified_at"] is None else None}
                for item in db.execute("SELECT domain, challenge, verified_at FROM site_domains "
                                       "WHERE site_id=? ORDER BY domain", (site_id,))]

    @app.get("/api/v1/sites")
    def sites(authorization: str | None = Header(default=None)):
        principal = admin(authorization)
        with storage.connect() as db:
            if principal is None:
                rows = db.execute("SELECT * FROM sites ORDER BY name")
            else:
                # Site and TXT challenge metadata must never leak across tenants.
                rows = db.execute(
                    "SELECT s.* FROM sites s JOIN site_owners o ON o.site_id=s.id "
                    "JOIN site_permissions p ON p.site_id=s.id "
                    "WHERE o.tenant_id=? AND p.subject_id=? "
                    "AND p.permission='analytics:read' ORDER BY s.name",
                    (principal.tenant_id, principal.subject_id))
            return [{"id": s["id"], "name": s["name"], "domains": json.loads(s["domains"]),
                     "created_at": s["created_at"], "verification": domain_status(db, s["id"])}
                    for s in rows]

    @app.post("/api/v1/sites", status_code=201)
    def new_site(payload: SiteCreate, authorization: str | None = Header(default=None)):
        admin(authorization)
        if settings.auth_mode == "identity":
            # There is not yet an independently approved ownership-onboarding
            # workflow. Never auto-claim a newly created site from token claims.
            raise HTTPException(403, "Identity site onboarding is not yet implemented")
        try:
            domains = sorted({normalize_domain(x) for x in payload.domains})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if any(len(domain) + len(txt_record_name("")) > 253 for domain in domains):
            raise HTTPException(422, "Domain too long for DNS ownership challenge")
        normalized_name = payload.name.strip()
        if not normalized_name:
            raise HTTPException(422, "Website name cannot be blank")
        site_id = secrets.token_urlsafe(16)
        with storage.connect() as db:
            db.execute("INSERT INTO sites(id,name,domains,created_at) VALUES(?,?,?,?)",
                       (site_id, normalized_name, json.dumps(domains), iso(datetime.now(timezone.utc))))
            for domain in domains:
                db.execute("INSERT INTO site_domains(site_id,domain,challenge,verified_at) VALUES(?,?,?,NULL)",
                           (site_id, domain, secrets.token_urlsafe(32)))
            verification = domain_status(db, site_id)
        return {"id": site_id, "name": normalized_name, "domains": domains,
                "verification": verification}

    @app.post("/api/v1/sites/{site_id}/domains/verify")
    def verify_domain(site_id: str, payload: DomainVerify,
                      authorization: str | None = Header(default=None)):
        """Require owner-controlled DNS TXT proof; never trust event Origin as proof."""
        admin(authorization, site_id=site_id, permission="analytics:admin")
        try:
            domain = normalize_domain(payload.domain)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with storage.connect() as db:
            get_site(db, site_id)
            item = db.execute("SELECT challenge, verified_at FROM site_domains "
                              "WHERE site_id=? AND domain=?", (site_id, domain)).fetchone()
            if item is None:
                raise HTTPException(404, "Unknown registered domain")
            if item["verified_at"] is not None:
                return {"domain": domain, "verified": True}
            expected = txt_record_value(item["challenge"])
        if not dns_limiter.check(f"{site_id}|{domain}"):
            raise HTTPException(429, "Retry DNS verification after one minute")
        try:
            values = app.state.txt_lookup(txt_record_name(domain))
        except DNSLookupUnavailable as exc:
            raise HTTPException(503, "DNS resolver unavailable; retry later") from exc
        if not any(isinstance(x, str) and hmac.compare_digest(x, expected) for x in values):
            raise HTTPException(409, "DNS TXT challenge not found")
        with storage.connect() as db:
            updated = db.execute("UPDATE site_domains SET verified_at=?, challenge='' "
                                 "WHERE site_id=? AND domain=? AND challenge=? AND verified_at IS NULL",
                                 (iso(datetime.now(timezone.utc)), site_id, domain,
                                  item["challenge"]))
            if updated.rowcount == 0:
                raise HTTPException(409, "Verification challenge changed; reload and retry")
        return {"domain": domain, "verified": True}

    @app.post("/api/v1/sites/{site_id}/domains/revoke")
    def revoke_domain(site_id: str, payload: DomainVerify,
                      authorization: str | None = Header(default=None)):
        """Stop intake for one hostname and rotate its DNS ownership challenge."""
        admin(authorization, site_id=site_id, permission="analytics:admin")
        try:
            domain = normalize_domain(payload.domain)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with storage.connect() as db:
            get_site(db, site_id)
            exists = db.execute("SELECT 1 FROM site_domains WHERE site_id=? AND domain=?",
                                (site_id, domain)).fetchone()
            if exists is None:
                raise HTTPException(404, "Unknown registered domain")
            challenge = secrets.token_urlsafe(32)
            db.execute("UPDATE site_domains SET verified_at=NULL, challenge=? WHERE site_id=? AND domain=?",
                       (challenge, site_id, domain))
        return {"domain": domain, "verified": False,
                "record_name": txt_record_name(domain),
                "record_value": txt_record_value(challenge)}

    @app.options("/api/v1/collect")
    def collect_preflight(request: Request):
        # Collection uses text/plain to avoid preflights. Do not reflect arbitrary CORS origins.
        return Response(status_code=204)

    @app.post("/api/v1/collect", status_code=202)
    async def collect(request: Request):
        # Do not record DNT/GPC visitors.
        if request.headers.get("dnt") == "1" or request.headers.get("sec-gpc") == "1":
            return Response(status_code=204)
        # Apply the anonymous ingress budget before parsing or database work.
        # Invalid requests count too; upstream edge filtering is still required.
        ingress_now = datetime.now(timezone.utc)
        ingress_host = request.client.host if request.client else "unknown"
        ingress_key = anonymize(settings.hash_secret, "__ingress__", ingress_host, "", ingress_now)
        if not ingress_limiter.check(ingress_key):
            raise HTTPException(429, "Rate limit exceeded")
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                raise HTTPException(400, "Invalid Content-Length")
            if length < 0:
                raise HTTPException(400, "Invalid Content-Length")
            if length > 4096:
                raise HTTPException(413, "Payload exceeds 4KB")
        # A missing or forged Content-Length must never permit unbounded buffering.
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 4096:
                raise HTTPException(413, "Payload exceeds 4KB")
            data.extend(chunk)
        raw = bytes(data)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Invalid JSON")
        if not isinstance(payload, dict) or not isinstance(payload.get("site_id"), str):
            raise HTTPException(400, "site_id required")
        site_id = payload["site_id"]
        if len(site_id) > 100:
            raise HTTPException(400, "Invalid site_id")
        now = datetime.now(timezone.utc)
        ip = request.client.host if request.client else "unknown"
        ua = request.headers.get("user-agent", "")[:250]
        anonymous = anonymize(settings.hash_secret, site_id, ip, ua, now)
        with storage.connect() as db:
            site = get_site(db, site_id)
            normalized = normalized_event(payload, json.loads(site["domains"]))
            proved = db.execute("SELECT 1 FROM site_domains WHERE site_id=? AND domain=? "
                                "AND verified_at IS NOT NULL",
                                (site_id, normalized["hostname"])).fetchone()
            if proved is None:
                raise HTTPException(403, "Domain ownership is not verified")
            origin = request.headers.get("origin")
            if origin:
                try:
                    parsed_origin = urlparse(origin)
                    valid_origin = (parsed_origin.scheme in ("http", "https") and
                                    parsed_origin.hostname == normalized["hostname"] and
                                    not parsed_origin.username and not parsed_origin.password)
                except ValueError:
                    valid_origin = False
                if not valid_origin:
                    raise HTTPException(403, "Origin mismatch")
            # Rate-limit valid intake by anonymous session, client network and
            # registered website. All client-IP-derived keys are HMACs in memory
            # only; no IP address is stored in the database or log.
            network_key = anonymize(settings.hash_secret, site_id, ip, "", now)
            if (not limiter.check(anonymous) or not ip_limiter.check(network_key)
                    or not site_limiter.check(site_id)):
                raise HTTPException(429, "Rate limit exceeded")
            # Serialize read/insert/update so simultaneous events cannot create
            # competing visits for the same anonymous visitor on this node.
            db.execute("BEGIN IMMEDIATE")
            # Recheck hostname proof under the SQLite writer lock. A completed
            # revocation between optimistic precheck and event commit must win.
            current_proof = db.execute(
                "SELECT 1 FROM site_domains WHERE site_id=? AND domain=? "
                "AND verified_at IS NOT NULL",
                (site_id, normalized["hostname"])
            ).fetchone()
            if current_proof is None:
                raise HTTPException(403, "Domain ownership is not verified")
            last = db.execute(
                "SELECT id FROM sessions WHERE site_id=? AND visitor_hash=? AND last_seen>=? "
                "ORDER BY last_seen DESC LIMIT 1",
                (site_id, anonymous, iso(now - timedelta(minutes=30)))
            ).fetchone()
            session = last["id"] if last else secrets.token_urlsafe(16)
            if not last:
                db.execute("INSERT INTO sessions(id,site_id,visitor_hash,first_seen,last_seen,event_count) "
                           "VALUES(?,?,?,?,?,0)", (session, site_id, anonymous, iso(now), iso(now)))
            db.execute("UPDATE sessions SET last_seen=?, event_count=event_count+1 WHERE id=?", (iso(now), session))
            db.execute(
                "INSERT INTO events(id,site_id,session_id,visitor_hash,ts,kind,path,hostname,referrer,name,"
                "properties,ua_family,utm_source,utm_medium,utm_campaign) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (secrets.token_urlsafe(16), site_id, session, anonymous, iso(now),
                 normalized["kind"], normalized["path"], normalized["hostname"],
                 normalized["referrer"], normalized["name"], normalized["properties"],
                 browser_family(ua), normalized["utm_source"], normalized["utm_medium"],
                 normalized["utm_campaign"])
            )
        # No CORS allow-any-site: return only for a matched/registered browser origin.
        response = Response(status_code=202)
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    def window(start: str | None, end: str | None):
        def parse(s: str | None, default: datetime):
            if not s:
                return default
            try:
                value = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return value
            except ValueError:
                raise HTTPException(422, "Dates must use YYYY-MM-DD")
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        first = parse(start, today - timedelta(days=6))
        last = parse(end, today) + timedelta(days=1)
        if last <= first or last - first > timedelta(days=366):
            raise HTTPException(422, "Date window must be between 1 and 366 days")
        return iso(first), iso(last)

    @app.get("/api/v1/sites/{site_id}/summary")
    def summary(site_id: str, start: str | None = None, end: str | None = None,
                authorization: str | None = Header(default=None)):
        admin(authorization, site_id=site_id, permission="analytics:read")
        low, high = window(start, end)
        with storage.connect() as db:
            get_site(db, site_id)
            # Aggregate in SQLite instead of transferring every raw event into
            # Python memory. This bounds application memory for a large date window.
            totals = db.execute("""
                SELECT COUNT(*) AS visits, COALESCE(SUM(pv),0) AS pageviews,
                       COALESCE(SUM(custom),0) AS events,
                       COALESCE(SUM(CASE WHEN pv=1 THEN 1 ELSE 0 END),0) AS bounced,
                       COALESCE(SUM(CASE WHEN pv>0 THEN 1 ELSE 0 END),0) AS pageview_visits,
                       COALESCE(AVG((julianday(last_ts)-julianday(first_ts))*86400),0) AS duration
                FROM (
                    SELECT session_id, MIN(ts) AS first_ts, MAX(ts) AS last_ts,
                           SUM(CASE WHEN kind='pageview' THEN 1 ELSE 0 END) AS pv,
                           SUM(CASE WHEN kind='event' THEN 1 ELSE 0 END) AS custom
                    FROM events WHERE site_id=? AND ts>=? AND ts<?
                    GROUP BY session_id
                )
            """, (site_id, low, high)).fetchone()
            visitors = db.execute(
                "SELECT COUNT(DISTINCT visitor_hash) FROM events WHERE site_id=? AND ts>=? AND ts<?",
                (site_id, low, high)).fetchone()[0]
            pv_sessions = totals["pageview_visits"]
            return {
                "pageviews": totals["pageviews"],
                "visitors": visitors,
                "visits": totals["visits"],
                "events": totals["events"],
                "bounce_rate": round(100 * totals["bounced"] / pv_sessions, 1) if pv_sessions else 0,
                "avg_duration_seconds": round(totals["duration"]),
            }

    @app.get("/api/v1/sites/{site_id}/timeseries")
    def timeseries(site_id: str, start: str | None = None, end: str | None = None,
                   authorization: str | None = Header(default=None)):
        admin(authorization, site_id=site_id, permission="analytics:read")
        low, high = window(start, end)
        with storage.connect() as db:
            get_site(db, site_id)
            data = db.execute("SELECT substr(ts,1,10) AS day, COUNT(*) AS pageviews, "
                              "COUNT(DISTINCT visitor_hash) AS visitors FROM events "
                              "WHERE site_id=? AND kind='pageview' AND ts>=? AND ts<? "
                              "GROUP BY day ORDER BY day", (site_id, low, high)).fetchall()
            by_day = {r["day"]: {"day": r["day"], "pageviews": r["pageviews"],
                                 "visitors": r["visitors"]} for r in data}
            # Even zero-traffic days matter: omitting them makes charts falsely
            # collapse time and overstate continuity of traffic.
            first = datetime.fromisoformat(low).date()
            last_exclusive = datetime.fromisoformat(high).date()
            return [by_day.get(day.isoformat(), {"day": day.isoformat(),
                      "pageviews": 0, "visitors": 0})
                    for day in (first + timedelta(days=n)
                                for n in range((last_exclusive - first).days))]

    @app.get("/api/v1/sites/{site_id}/breakdown")
    def breakdown(site_id: str, dimension: str = "path", start: str | None = None,
                  end: str | None = None, authorization: str | None = Header(default=None)):
        admin(authorization, site_id=site_id, permission="analytics:read")
        if dimension not in ("path", "referrer", "name", "utm_source", "utm_medium", "utm_campaign"):
            raise HTTPException(422, "Unsupported dimension")
        low, high = window(start, end)
        with storage.connect() as db:
            get_site(db, site_id)
            sql = f"SELECT {dimension} AS label, COUNT(*) AS count FROM events WHERE site_id=? AND ts>=? AND ts<?"
            if dimension == "name":
                sql += " AND kind='event'"
            elif dimension == "path":
                sql += " AND kind='pageview'"
            sql += f" GROUP BY {dimension} ORDER BY count DESC LIMIT 20"
            return [dict(r) for r in db.execute(sql, (site_id, low, high))]

    @app.post("/api/v1/sites/{site_id}/goals", status_code=201)
    def create_goal(site_id: str, payload: GoalCreate,
                    authorization: str | None = Header(default=None)):
        """Register an exact-match event or sanitized page path as a goal."""
        admin(authorization, site_id=site_id, permission="analytics:manage")
        name = payload.name.strip()
        target = payload.target.strip()
        if not name:
            raise HTTPException(422, "Goal name cannot be blank")
        if payload.kind == "event" and not EVENT_RE.fullmatch(target):
            raise HTTPException(422, "Invalid event goal target")
        if payload.kind == "pageview" and (not target.startswith("/") or
                                           safe_path(target) != target or
                                           "?" in target or "#" in target):
            raise HTTPException(422, "Invalid page goal target")
        goal_id = secrets.token_urlsafe(16)
        with storage.connect() as db:
            get_site(db, site_id)
            try:
                db.execute("INSERT INTO goals(id,site_id,name,kind,target,created_at) VALUES(?,?,?,?,?,?)",
                           (goal_id, site_id, name, payload.kind, target,
                            iso(datetime.now(timezone.utc))))
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "A goal with that name already exists") from exc
        return {"id": goal_id, "name": name, "kind": payload.kind, "target": target}

    @app.get("/api/v1/sites/{site_id}/goals")
    def goals(site_id: str, start: str | None = None, end: str | None = None,
              authorization: str | None = Header(default=None)):
        """Count sessions meeting each goal once within the selected date range."""
        admin(authorization, site_id=site_id, permission="analytics:read")
        low, high = window(start, end)
        with storage.connect() as db:
            get_site(db, site_id)
            visits = db.execute("SELECT COUNT(DISTINCT session_id) FROM events "
                                "WHERE site_id=? AND ts>=? AND ts<?", (site_id, low, high)).fetchone()[0]
            result = []
            for g in db.execute("SELECT * FROM goals WHERE site_id=? ORDER BY name", (site_id,)):
                match_col = "name" if g["kind"] == "event" else "path"
                converted = db.execute(
                    f"SELECT COUNT(DISTINCT session_id) FROM events WHERE site_id=? "
                    f"AND kind=? AND {match_col}=? AND ts>=? AND ts<?",
                    (site_id, g["kind"], g["target"], low, high)).fetchone()[0]
                result.append({"id": g["id"], "name": g["name"], "kind": g["kind"],
                               "target": g["target"], "converting_visits": converted,
                               "total_visits": visits,
                               "visit_conversion_rate": round(100 * converted / visits, 1) if visits else 0})
            return result

    @app.get("/api/v1/sites/{site_id}/realtime")
    def realtime(site_id: str, authorization: str | None = Header(default=None)):
        admin(authorization, site_id=site_id, permission="analytics:read")
        with storage.connect() as db:
            get_site(db, site_id)
            rows = db.execute("SELECT COUNT(*) AS events, COUNT(DISTINCT visitor_hash) AS visitors "
                              "FROM events WHERE site_id=? AND ts>=?",
                              (site_id, iso(datetime.now(timezone.utc) - timedelta(minutes=5)))).fetchone()
            return dict(rows)

    @app.get("/api/v1/sites/{site_id}/funnel")
    def two_step_funnel(site_id: str, first: str, second: str,
                        start: str | None = None, end: str | None = None,
                        authorization: str | None = Header(default=None)):
        """Initial ordered two-event funnel within one visit (no attribution inferred)."""
        admin(authorization, site_id=site_id, permission="analytics:read")
        if not first or not second or len(first) > 80 or len(second) > 80:
            raise HTTPException(422, "Provide two valid event names")
        low, high = window(start, end)
        # Rank events within each session in SQLite instead of materializing
        # every matching event in Python. rowid breaks ties when events share
        # the same millisecond timestamp, preserving ingestion order.
        with storage.connect() as db:
            get_site(db, site_id)
            counts = db.execute("""
                WITH relevant AS (
                    SELECT session_id, name, ts, rowid AS insertion_order
                    FROM events
                    WHERE site_id=? AND kind='event' AND name IN (?,?)
                      AND ts>=? AND ts<?
                ),
                ordered AS (
                    SELECT session_id, name,
                           ROW_NUMBER() OVER (
                               PARTITION BY session_id ORDER BY ts, insertion_order
                           ) AS position
                    FROM relevant
                ),
                first_steps AS (
                    SELECT session_id, MIN(position) AS position
                    FROM ordered WHERE name=? GROUP BY session_id
                )
                SELECT COUNT(*) AS started,
                       COALESCE(SUM(CASE WHEN EXISTS (
                           SELECT 1 FROM ordered later
                           WHERE later.session_id=first_steps.session_id
                             AND later.name=?
                             AND later.position>first_steps.position
                       ) THEN 1 ELSE 0 END), 0) AS completed
                FROM first_steps
            """, (site_id, first, second, low, high, first, second)).fetchone()
        started, completed = counts["started"], counts["completed"]
        return {"first": first, "second": second, "started": started, "completed": completed,
                "conversion_rate": round(100 * completed / started, 1) if started else 0}

    @app.get("/api/v1/sites/{site_id}/export.csv")
    def export(site_id: str, start: str | None = None, end: str | None = None,
               authorization: str | None = Header(default=None)):
        admin(authorization, site_id=site_id, permission="analytics:export")
        low, high = window(start, end)
        with storage.connect() as db:
            get_site(db, site_id)
            rows = db.execute("SELECT ts,kind,path,hostname,referrer,name,properties,utm_source,utm_medium,utm_campaign "
                              "FROM events WHERE site_id=? AND ts>=? AND ts<? ORDER BY ts LIMIT 100001",
                              (site_id, low, high)).fetchall()
        if len(rows) > 100000:
            raise HTTPException(422, "Export exceeds 100,000 rows; choose a smaller date range")
        output = io.StringIO()
        writer = csv.writer(output)
        fields = ("ts", "kind", "path", "hostname", "referrer", "name", "properties", "utm_source", "utm_medium", "utm_campaign")
        writer.writerow(fields)
        # Prefix formula-like spreadsheet values to prevent CSV formula injection.
        for row in rows:
            writer.writerow(["'" + str(row[f]) if str(row[f]).lstrip().startswith(("=", "+", "-", "@")) else row[f] for f in fields])
        return Response(content=output.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="goreecloud-analytics-{site_id[:12]}.csv"'
        })

    return app


app = None  # Uvicorn entrypoint below uses an app factory to enforce configuration.


def build():
    return create_app()
