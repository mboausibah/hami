"""API dependencies: reviewer token auth and per-device / per-IP rate limits."""
from __future__ import annotations

import hmac
import re
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request

from app.config import settings

DEVICE_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def valid_device_id(device_id: str | None) -> str | None:
    if device_id is None:
        return None
    if not DEVICE_RE.match(device_id):
        raise HTTPException(400, "device_id must be a random UUID")
    return device_id


def token_ok(token: str | None) -> bool:
    expected = settings.reviewer_token
    return bool(expected) and bool(token) and hmac.compare_digest(token.encode(), expected.encode())


def require_reviewer(authorization: str | None = Header(default=None),
                     x_reviewer_token: str | None = Header(default=None)) -> str:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or x_reviewer_token
    if not settings.reviewer_token:
        raise HTTPException(503, "reviewer token not configured (set HAMI_REVIEWER_TOKEN in .env)")
    if not token_ok(token):
        raise HTTPException(401, "reviewer token required")
    return "reviewer"


class RateLimiter:
    """Sliding-window limiter, in memory (one API process)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, key: str, limit: int, window: float = 60.0) -> tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[(bucket, key)]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False, window - (now - q[0])
            q.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    # Behind a tunnel/reverse proxy the first X-Forwarded-For hop is the client.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str):  # noqa: ANN201
    per_min = {"scans": lambda: settings.rate_scans_per_min, "lookup": lambda: settings.rate_lookup_per_min,
               "snapshots": lambda: settings.rate_snapshots_per_min}.get(bucket, lambda: settings.rate_default_per_min)

    def dep(request: Request, x_device_id: str | None = Header(default=None)) -> None:
        limit = per_min()
        ip = client_ip(request)
        device = x_device_id or request.query_params.get("device_id")
        if device:
            ok, retry = limiter.check(bucket + ":dev", device, limit)
            if not ok:
                raise HTTPException(429, "rate limit exceeded for this device", headers={"Retry-After": str(int(retry) + 1)})
        ok, retry = limiter.check(bucket + ":ip", ip, limit * max(1, settings.rate_ip_multiplier))
        if not ok:
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(int(retry) + 1)})

    return dep
