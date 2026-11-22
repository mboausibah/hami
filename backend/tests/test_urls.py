import pytest

from app.urls import UnsafeTarget, check_target, defang, normalize_url, registrable_domain, request_allowed


def test_normalize():
    assert normalize_url("HTTPS://WWW.Example.com:443/a/?b=2&a=1#frag") == "https://example.com/a?a=1&b=2"
    assert normalize_url("example.com") == "https://example.com/"
    assert "token" not in normalize_url("https://x.test/?token=abc")


def test_registrable_domain():
    assert registrable_domain("uae2.ap1.shop") == "ap1.shop"
    assert registrable_domain("www.mohre.gov.ae") == "mohre.gov.ae"
    assert registrable_domain("a.b.example.co.uk") == "example.co.uk"
    assert registrable_domain("site-a.localhost") == "site-a.localhost"


def test_defang():
    assert defang("https://ma.example-vip.shop/x") == "hxxps://ma[.]example-vip[.]shop/x"


def test_ssrf_guard():
    for bad in ("http://127.0.0.1/", "http://10.0.0.5/", "http://169.254.169.254/latest", "file:///etc/passwd",
                "http://user:pw@example.com/", "http://intranet.local/"):
        with pytest.raises(UnsafeTarget):
            check_target(bad, allow_hosts=[], allow_private=False, resolve=False)
    check_target("http://site-a.localhost:8100/", allow_hosts=["*.localhost"], allow_private=False, resolve=False)
    assert not request_allowed("http://192.168.1.1/admin", [], False)
    assert request_allowed("https://example.com/x.js", [], False)
