"""URL helpers: normalization, token stripping, registrable domains, defanging, target safety."""
from __future__ import annotations

import fnmatch
import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameter names that look like credentials, session handles or personal data.
TOKEN_PARAM_RE = re.compile(
    r"(token|auth|key|session|sess|sid|sig|signature|password|passwd|pwd|secret|jwt|access|refresh|"
    r"otp|code|email|mail|phone|mobile|tel|ticket|nonce|state|credential|login|user|uid|account|invite)",
    re.I,
)
# Multi-label public suffixes we care about (UAE + common). A full PSL is out of scope for the MVP.
MULTI_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.in", "co.jp", "com.br",
    "com.cn", "com.hk", "com.sg", "com.tr", "com.sa", "net.sa", "gov.sa", "com.eg", "com.kw", "com.qa",
    "com.bh", "com.om", "com.jo", "com.lb", "com.pk", "com.my", "co.za", "com.mx", "com.ar",
    "ae", "co.ae", "com.ae", "net.ae", "org.ae", "gov.ae", "ac.ae", "sch.ae", "mil.ae",
    "oss-ap-southeast-1.aliyuncs.com", "github.io", "vercel.app", "netlify.app", "pages.dev",
    "web.app", "firebaseapp.com", "herokuapp.com", "blogspot.com", "wixsite.com",
}


class UnsafeTarget(ValueError):
    """The URL points at something the capture browser must not visit."""


def ensure_scheme(url: str) -> str:
    url = url.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "https://" + url.lstrip("/")
    return url


def strip_token_params(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TOKEN_PARAM_RE.search(k)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def hostname(url: str) -> str:
    try:
        return (urlsplit(ensure_scheme(url)).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def normalize_url(url: str) -> str:
    """Canonical form used for caching and case grouping: scheme+host lowercase, no default port,
    no fragment (except SPA hash routes are dropped too), token-like params stripped, sorted query."""
    url = strip_token_params(ensure_scheme(url))
    p = urlsplit(url)
    scheme = p.scheme.lower()
    host = (p.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    port = p.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query = urlencode(sorted(parse_qsl(p.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def registrable_domain(host: str) -> str:
    host = (host or "").lower().rstrip(".")
    if not host or _is_ip(host):
        return host
    labels = host.split(".")
    if host.endswith(".localhost") or host == "localhost":
        return host  # test sites: each *.localhost name is its own site
    for n in (3, 2):
        if len(labels) > n and ".".join(labels[-n:]) in MULTI_SUFFIXES:
            return ".".join(labels[-(n + 1):])
    if len(labels) >= 2 and ".".join(labels[-2:]) in MULTI_SUFFIXES:
        return ".".join(labels[-3:]) if len(labels) >= 3 else host
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def same_site(host_a: str, host_b: str) -> bool:
    return registrable_domain(host_a) == registrable_domain(host_b)


def defang(url_or_host: str) -> str:
    s = re.sub(r"^http", "hxxp", url_or_host, flags=re.I)
    return s.replace(".", "[.]")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _private_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.strip("[]"))
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
        or addr.is_reserved or addr.is_unspecified
    )


def host_allowlisted(host: str, allow: list[str]) -> bool:
    return any(fnmatch.fnmatch(host, pat) for pat in allow)


def check_target(url: str, allow_hosts: list[str], allow_private: bool, resolve: bool = True) -> None:
    """Refuse non-http(s) schemes, credentials in URLs, and private-network targets (SSRF guard)."""
    p = urlsplit(url)
    if p.scheme not in ("http", "https"):
        raise UnsafeTarget(f"scheme not allowed: {p.scheme}")
    if p.username or p.password:
        raise UnsafeTarget("credentials in URL are not allowed")
    host = (p.hostname or "").lower()
    if not host:
        raise UnsafeTarget("missing host")
    if host_allowlisted(host, allow_hosts) or allow_private:
        return
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal") or host.endswith(".local"):
        raise UnsafeTarget("local hostnames are not allowed")
    if _is_ip(host):
        if _private_ip(host):
            raise UnsafeTarget("private network address")
        return
    if resolve:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return  # unresolvable: the capture will simply fail to load (insufficient evidence)
        for info in infos:
            if _private_ip(info[4][0]):
                raise UnsafeTarget("host resolves to a private network address")


def request_allowed(url: str, allow_hosts: list[str], allow_private: bool) -> bool:
    """Cheap per-request guard used inside the capture browser (no DNS lookups)."""
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    if p.scheme in ("data", "blob", "about"):
        return True
    if p.scheme not in ("http", "https", "ws", "wss"):
        return False
    host = (p.hostname or "").lower()
    if host_allowlisted(host, allow_hosts) or allow_private:
        return True
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        return False
    if _is_ip(host) and _private_ip(host):
        return False
    return True
