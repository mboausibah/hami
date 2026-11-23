from app.capture import _http_url


def test_final_url_keeps_last_web_page():
    assert _http_url("https://a.example/x", "https://b.example/") == "https://a.example/x"
    for odd in ("about:blank", "data:text/html,hi", "chrome-error://chromewebdata/", ""):
        assert _http_url(odd, "https://cs.example.com/") == "https://cs.example.com/"
