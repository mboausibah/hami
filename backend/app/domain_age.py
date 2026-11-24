"""Domain age at scan time from certificate transparency (same public sources as the discovery worker).

Returns the age in days of the FIRST certificate ever logged for a registrable domain (Cert Spotter first, crt.sh as
fallback). That is a lower bound on how long the site has existed with HTTPS, not the registration date, and the
clue says so. Results are cached in the database (positive 7 days, failures 1 day); outgoing queries are spaced at
least DOMAIN_AGE_MIN_GAP_S apart and time-limited. Local, private and test hosts are never looked up.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.db import db, utcnow
from app.urls import registrable_domain

USER_AGENT = "Hami-domain-age/1.0 (hackathon research prototype; cached, rate-limited)"
POSITIVE_TTL = timedelta(days=7)
NEGATIVE_TTL = timedelta(days=1)
_lock = threading.Lock()
_last_query = 0.0


def _skip(domain: str) -> bool:
    if not domain or "." not in domain or domain.endswith((".localhost", ".local", ".test", ".example", ".invalid")):
        return True
    try:
        ipaddress.ip_address(domain)
        return True
    except ValueError:
        return False


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _certspotter(client: httpx.Client, domain: str) -> datetime | None:
    r = client.get("https://api.certspotter.com/v1/issuances",
                   params={"domain": domain, "include_subdomains": "true"}, timeout=settings.domain_age_timeout_s)
    r.raise_for_status()
    dates = [d for d in (_parse(e.get("not_before")) for e in r.json()) if d]
    return min(dates) if dates else None


def _crtsh(client: httpx.Client, domain: str) -> datetime | None:
    r = client.get("https://crt.sh/", params={"q": domain, "output": "json"}, timeout=settings.domain_age_timeout_s)
    r.raise_for_status()
    dates = [d for d in (_parse(e.get("not_before")) for e in r.json()) if d]
    return min(dates) if dates else None


def first_certificate(domain: str) -> tuple[datetime | None, str, str | None]:
    """(first certificate time, source, error). Network call; respects the global spacing."""
    global _last_query
    with _lock:
        wait = settings.domain_age_min_gap_s - (time.monotonic() - _last_query)
        if wait > 0:
            time.sleep(wait)
        _last_query = time.monotonic()
    errors = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for name, fn in (("certspotter", _certspotter), ("crt.sh", _crtsh)):
            try:
                first = fn(client, domain)
                if first is not None:
                    return first, name, None
                errors.append(f"{name}: no certificates")
            except (httpx.HTTPError, ValueError) as e:
                errors.append(f"{name}: {type(e).__name__}")
    return None, "", "; ".join(errors)[:300]


def cert_age_days(host: str) -> int | None:
    """Days since the first logged certificate of the host's registrable domain, or None if unknown."""
    if not settings.domain_age_enabled:
        return None
    domain = registrable_domain(host)
    if _skip(domain):
        return None
    now = datetime.now(timezone.utc)
    with db() as conn:
        row = conn.execute("SELECT * FROM domain_age WHERE domain=?", (domain,)).fetchone()
    if row is not None:
        checked = _parse(row["checked_at"])
        first = _parse(row["first_cert_at"])
        ttl = POSITIVE_TTL if first else NEGATIVE_TTL
        if checked and now - checked < ttl:
            return max(0, (now - first).days) if first else None
    first, source, error = first_certificate(domain)
    with db() as conn:
        if conn.execute("SELECT 1 FROM domain_age WHERE domain=?", (domain,)).fetchone():
            conn.execute("UPDATE domain_age SET first_cert_at=?, source=?, error=?, checked_at=? WHERE domain=?",
                         (first.strftime("%Y-%m-%dT%H:%M:%SZ") if first else None, source or None, error, utcnow(), domain))
        else:
            conn.execute("INSERT INTO domain_age (domain, first_cert_at, source, error, checked_at) VALUES (?,?,?,?,?)",
                         (domain, first.strftime("%Y-%m-%dT%H:%M:%SZ") if first else None, source or None, error, utcnow()))
    return max(0, (now - first).days) if first else None
