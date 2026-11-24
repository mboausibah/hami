import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Isolated storage for every test session; never touches the real DB or artifacts.
_TMP = Path(tempfile.mkdtemp(prefix="hami-test-"))
os.environ["HAMI_DATA_DIR"] = str(_TMP / "storage")
os.environ["HAMI_DB_PATH"] = str(_TMP / "storage" / "test.sqlite3")
os.environ.setdefault("HAMI_REVIEWER_TOKEN", "test-reviewer-token")
os.environ.setdefault("RATE_SCANS_PER_MIN", "1000")
os.environ.setdefault("RATE_DEFAULT_PER_MIN", "1000")
os.environ.setdefault("RATE_LOOKUP_PER_MIN", "1000")
os.environ["DOMAIN_AGE_ENABLED"] = "false"  # tests never query certificate-transparency services


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """A brand-new database file for one test."""
    from app import db as dbmod
    from app.config import settings

    path = tmp_path / "t.sqlite3"
    monkeypatch.setenv("HAMI_DB_PATH", str(path))
    dbmod.reset_init_cache()
    settings.data_dir = tmp_path / "storage"
    settings.ensure_dirs()
    yield path
    dbmod.reset_init_cache()
