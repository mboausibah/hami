"""URL helpers: normalization, token stripping, registrable domains, defanging, target safety."""
from __future__ import annotations

import fnmatch
import ipaddress
import re
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

# Query parameter names that look like credentials, session handles or personal data.
TOKEN_PARAM_RE = re.compile(
    r"(token|auth|key|session|sess|sid|sig|signature|password|passwd|pwd|secret|jwt|access|refresh|"
    r"otp|code|email|mail|phone|mobile|tel|ticket|nonce|state|credential|login|user|uid|account|invite)",
    re.I,
)
# Public Suffix List (bundled snapshot, private section included so *.github.io / *.vercel.app sites are
# separate registrable domains). No network access: suffix_list_urls=() uses the snapshot in the package.
_PSL = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)
# Storage-bucket hosts that the PSL does not list: each bucket is its own "site".
_BUCKET_RE = re.compile(r"^([a-z0-9-]+\.oss-[a-z0-9-]+\.aliyuncs\.com|[a-z0-9.-]+\.s3[.-][a-z0-9.-]*amazonaws\.com)$")

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
    """eTLD+1 via the Public Suffix List; IPs, localhost names and unknown suffixes return the host."""
    host = (host or "").lower().rstrip(".")
    if not host or _is_ip(host) or host == "localhost" or host.endswith(".localhost"):
        return host  # test sites: each *.localhost name is its own site
    m = _BUCKET_RE.match(host)
    if m:
        return m.group(1)
    r = _PSL(host)
    reg = getattr(r, "top_domain_under_public_suffix", None) or r.registered_domain
    return reg or host


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
