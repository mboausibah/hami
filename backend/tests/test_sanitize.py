from app.sanitize import redact_text, sanitize_har, sanitize_html, sanitize_url


def test_redacts_email_and_phones():
    t = redact_text("Contact hr.team@example-mail.com or +971 50 123 4567 or 050-123-4567 now")
    assert "@" not in t and "4567" not in t
    assert t.count("[phone]") == 2 and "[email]" in t


def test_redacts_arabic_indic_phone():
    t = redact_text("اتصل على ٠٥٠١٢٣٤٥٦٧")
    assert "٠٥٠١٢٣٤٥٦٧" not in t and "[phone]" in t


def test_keeps_amounts_and_whatsapp_indicator():
    t = redact_text("Recharge AED 500 to unlock VIP 2. Chat: https://wa.me/971501234567")
    assert "AED 500" in t and "VIP 2" in t
    assert "wa.me/[phone]" in t


def test_strips_token_params():
    u = sanitize_url("https://x.test/p?id=5&token=abc123&session_id=zz&email=a@b.co&lang=ar")
    assert "token" not in u and "session" not in u and "email" not in u
    assert "id=5" in u and "lang=ar" in u


def test_sanitize_har_removes_secrets():
    har = {"log": {"entries": [{
        "request": {"method": "POST", "url": "https://x.test/api/login?auth=SECRET",
                    "headers": [{"name": "Cookie", "value": "sid=1"}, {"name": "Authorization", "value": "Bearer t"},
                                {"name": "User-Agent", "value": "UA"}],
                    "cookies": [{"name": "sid", "value": "1"}],
                    "queryString": [{"name": "auth", "value": "SECRET"}],
                    "postData": {"mimeType": "application/json", "text": "{\"password\":\"hunter2\"}"}},
        "response": {"status": 200, "headers": [{"name": "Set-Cookie", "value": "sid=2"}],
                     "cookies": [{"name": "sid", "value": "2"}],
                     "content": {"mimeType": "application/json", "text": "{\"mail\":\"v@x.test\",\"cs\":\"+971501112233\"}"}}},
        {"request": {"method": "GET", "url": "https://x.test/logo.png", "headers": []},
         "response": {"status": 200, "headers": [], "content": {"mimeType": "image/png", "text": "iVBOR", "encoding": "base64"}}},
    ]}}
    out = sanitize_har(har)
    s = str(out)
    for secret in ("SECRET", "sid=1", "sid=2", "Bearer t", "hunter2", "v@x.test", "501112233"):
        assert secret not in s, secret
    e0 = out["log"]["entries"][0]
    assert e0["request"]["postData"]["text"] == "[removed by sanitizer]"
    assert {h["name"] for h in e0["request"]["headers"]} == {"User-Agent"}
    assert out["log"]["entries"][1]["response"]["content"]["text"] is None
    # original untouched
    assert har["log"]["entries"][0]["request"]["cookies"]


def test_sanitize_html_drops_input_values():
    h = sanitize_html('<input name="user" value="victim@mail.com"><p>call 0501234567</p>')
    assert "victim" not in h and "0501234567" not in h
