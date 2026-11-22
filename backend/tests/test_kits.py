"""Kit fingerprinting: identical app bundles link sites; common libraries never do."""
import json

from app.analyze.assets import code_strings, extract_assets, name_words, sketch, sketch_similarity, split_name
from app.db import db, utcnow
from app.linking.kit import kit_matches, store_assets


def har(entries):
    return {"log": {"entries": [{"request": {"url": u}, "response": {"status": 200, "content": {
        "mimeType": m, "text": t, "_hami_sha256": h, "_hami_size": len(t or "x" * 2000)}}} for u, m, t, h in entries]}}


def test_build_names_and_words():
    assert split_name("en-US-Qm7xTz2K.js") == ("en-US", True)
    assert split_name("main.a1b2c3d4.chunk.js") == ("main", True)
    assert split_name("index-template.js") == (None, False)
    assert name_words("views-levelsNew") == "views levels new"
    assert name_words("homeDepositTab-bXc-GGAZ") .startswith("home deposit tab")


def test_near_identical_sketch():
    a = " ".join(f"function f{i}(x){{return x*{i}+'Deposit {i} to unlock level {i % 7}'}}" for i in range(1500))
    b = a.replace("level 3", "tier 3", 5).replace("f42(", "g42(")  # a rebuilt bundle with small edits
    assert sketch_similarity(sketch(a), sketch(b)) > 0.8
    assert sketch_similarity(sketch(a), sketch("completely different code " * 300)) < 0.2


def test_code_strings_skip_vendor_and_libraries():
    assets = extract_assets(har([
        ("https://x.test/assets/en-US-Qm7xTz2K.js", "application/javascript",
         'export default {a:"Deposit",b:"Withdraw now",c:"VIP level 2",d:"function(){}"}', "1" * 64),
        ("https://x.test/assets/vendor-media-Zx5cVb7n.js", "application/javascript", 'var x="Library text here"', "2" * 64),
        ("https://code.jquery.com/jquery-3.7.1.min.js", "application/javascript", 'var y="jQuery says hi there"', "3" * 64),
    ]))
    lines, names = code_strings(assets)
    assert "Withdraw now" in lines and "Library text here" not in lines and "jQuery says hi there" not in lines


def _scan(conn, host, batch=None):
    return conn.execute("INSERT INTO scans (submitted_url, normalized_url, host, source_type, submitted_at, status, "
                        "capture_status, batch) VALUES (?,?,?,?,?,?,?,?)",
                        (f"https://{host}/", f"https://{host}/", host, "manual", utcnow(), "done", "ok", batch)).lastrowid


def test_kit_match_and_common_libraries(fresh_db):
    app_files = [("views-levels-Hn4pRw8e.css", "css", "a" * 64), ("en-US-Qm7xTz2K.js", "js", "b" * 64),
                 ("rewardBox-Ty6uWq1z.css", "css", "c" * 64), ("prizeWheel-Lp0oKi9u.css", "css", "d" * 64)]
    lib = [("jquery-3.7.1.min.js", "js", "e" * 64), ("analytics.js", "js", "f" * 64), ("shared-ui-Abc12345.js", "js", "9" * 64)]
    rows = lambda files: [{"host": "cdn.example-kit.test", "file_name": n, "chunk_name": split_name(n)[0],
                           "name_hashed": int(split_name(n)[1]), "kind": k, "sha256": h, "size_bytes": 5000,
                           "sketch": None} for n, k, h in files]
    with db() as conn:
        a = _scan(conn, "confirmed-scam.test")
        b = _scan(conn, "rebrand.test")
        legit = _scan(conn, "legit-shop.test", batch="legit_urls")
        store_assets(conn, a, "confirmed-scam.test", rows(app_files + lib))
        store_assets(conn, b, "rebrand.test", rows(app_files[:3] + lib))
        store_assets(conn, legit, "legit-shop.test", rows(lib))
        m = kit_matches(conn, b)
        assert m and m[0].site == "confirmed-scam.test" and m[0].strength == "strong"
        assert len(m[0].files) == 3 and not any("jquery" in f or "shared-ui" in f for f in m[0].files)
        # A legitimate site that only shares common libraries (and a file also seen on a legit capture) never matches.
        assert kit_matches(conn, legit) == []
