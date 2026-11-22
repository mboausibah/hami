import os
import re

import pytest
from fastapi.testclient import TestClient

from tests.helpers import REPO, serve_dir

TOKEN = os.environ["HAMI_REVIEWER_TOKEN"]


@pytest.fixture(scope="module")
def ui():
    from app import db as dbmod
    from app.main import create_app

    dbmod.reset_init_cache()
    c = TestClient(create_app())
    r = c.post("/review/login", data={"token": TOKEN}, follow_redirects=False)
    assert r.status_code == 303 and "hami_reviewer" in r.headers.get("set-cookie", "")
    return c


@pytest.fixture(scope="module")
def site():
    base, srv = serve_dir(REPO / "testsites" / "corpus")
    port = base.rsplit(":", 1)[1]
    yield lambda name, path: f"http://{name}.localhost:{port}/{path}"
    srv.shutdown()


def csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


def test_requires_login():
    from app.main import create_app

    c = TestClient(create_app())
    r = c.get("/review", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/review/login"
    assert c.post("/review/login", data={"token": "wrong"}, follow_redirects=False).headers["location"].endswith("error=1")


def test_pages_render_in_both_languages(ui):
    for path in ("/review", "/review/discovery", "/review/links", "/review/alerts", "/review/clusters",
                 "/review/static", "/review/train"):
        en = ui.get(path + "?lang=en")
        ar = ui.get(path + "?lang=ar")
        assert en.status_code == 200 and ar.status_code == 200, path
        assert 'dir="rtl"' in ar.text and 'dir="ltr"' in en.text


def test_case_page_label_and_history(ui, site):
    from app.pipeline import submit_scan

    p = submit_scan(site("consolecase", "syn_task02/01.html"), "manual", force=True)
    page = ui.get(f"/review/scans/{p['scan_id']}")
    assert page.status_code == 200 and "sha256" in page.text.lower() or "SHA-256" in page.text
    token = csrf(page.text)
    assert ui.post(f"/review/scans/{p['scan_id']}/review", data={"label": "legitimate", "csrf": "bad"}).status_code == 403
    ui.post(f"/review/scans/{p['scan_id']}/review", data={"label": "legitimate", "csrf": token})
    ui.post(f"/review/scans/{p['scan_id']}/review",
            data={"label": "fraudulent", "behavior_tags": ["deposit_to_unlock", "off_platform_contact"],
                  "scam_type": "task_scam", "training_eligible": "on", "csrf": token})
    page = ui.get(f"/review/scans/{p['scan_id']}?lang=en").text
    assert "superseded" in page and "supersedes" in page
    # Captured HTML is never served as HTML to the reviewer.
    from app.db import db
    with db() as conn:
        html_art = conn.execute("SELECT artifact_id FROM artifacts WHERE scan_id=? AND kind='html'", (p["scan_id"],)).fetchone()
    r = ui.get(f"/review/artifacts/{html_art[0]}")
    assert r.headers["content-type"].startswith("text/plain") and "attachment" in r.headers["content-disposition"]


def test_static_check_never_stores_values(ui):
    page = ui.get("/review/static").text
    ui.post("/review/static/run", data={"csrf": csrf(page)})
    page = ui.get("/review/static").text
    assert "aws_access_key" in page and "private_key" in page
    for secret in ("AKIAIOSFODNN7EXAMPLE", "fake-Passw0rd-for-tests", "orbita-fake-db-pass", "FAKE-KEY-MATERIAL"):
        assert secret not in page
    from app.db import db
    with db() as conn:
        dump = "\n".join(str(tuple(r)) for r in conn.execute("SELECT * FROM static_findings"))
    assert "AKIAIOSFODNN7EXAMPLE" not in dump and "fake-Passw0rd" not in dump
