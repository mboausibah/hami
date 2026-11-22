"""Regression tests on the team's private sessions (skipped automatically when data/private is missing).

- cs.aed99.com (aed99's support subdomain, a sign-in/chat page) returns High risk through registrable-domain
  inheritance once aed99.com is reviewer-confirmed.
- betnala.com (deliberately unlabeled) returns High risk or Caution through the kit match and appears in the
  review queue linked to kit02_aed99.
Nothing is fetched from the internet: the sessions are imported offline into this test's database.
"""
import csv
from pathlib import Path

import pytest

from app.config import settings

SESSIONS = Path(settings.private_dir) / "sessions"
pytestmark = pytest.mark.skipif(not SESSIONS.is_dir() or not any(SESSIONS.glob("*.har*")),
                                reason="data/private/sessions not present (private data is never committed)")


@pytest.fixture(scope="module")
def imported(tmp_path_factory):
    import os

    from app import db as dbmod
    from ml.import_sessions import main as import_sessions

    previous = os.environ.get("HAMI_DB_PATH")
    os.environ["HAMI_DB_PATH"] = str(tmp_path_factory.mktemp("priv") / "priv.sqlite3")
    dbmod.reset_init_cache()
    assert import_sessions([]) == 0
    yield
    if previous is None:
        os.environ.pop("HAMI_DB_PATH", None)
    else:
        os.environ["HAMI_DB_PATH"] = previous
    dbmod.reset_init_cache()


def _latest(conn, host):
    return conn.execute("SELECT MAX(scan_id) FROM scans WHERE host=? AND batch='sessions'", (host,)).fetchone()[0]


def test_support_subdomain_inherits_and_kit_rebrand(imported):
    from app import services
    from app.db import db
    from app.pipeline import reanalyze_stored

    with db() as conn:
        aed = _latest(conn, "aed99.com")
        assert aed, "aed99.com session kit missing"
        services.create_review(conn, aed, "fraudulent", "regression-test", ["gambling_deposit"], "gambling_deposit")
        cs, bn = _latest(conn, "cs.aed99.com"), _latest(conn, "betnala.com")
    p = reanalyze_stored(cs)
    assert p["tier"] == "high_risk" and "reviewed_registrable_domain" in p["rules_fired"], (p["tier"], p["rules_fired"])
    q = reanalyze_stored(bn)
    assert q["tier"] in ("high_risk", "caution"), (q["tier"], q["rules_fired"])
    km = q["evidence"]["kit_match"]
    assert km and km["host"].endswith("aed99.com") and km["n_files"] >= 3
    with db() as conn:
        link = conn.execute("SELECT * FROM links WHERE relation_type='same_kit' AND "
                            "((host_a='aed99.com' AND host_b='betnala.com') OR (host_a='betnala.com' AND host_b='aed99.com'))").fetchone()
    assert link is not None and link["review_status"] == "pending"
    with (Path(settings.private_dir) / "datasets" / "labels.csv").open(encoding="utf-8-sig", newline="") as f:
        kit = next(r["kit_id"] for r in csv.DictReader(f) if "aed99.com" in r["file_or_url"])
    assert kit == "kit02_aed99"
