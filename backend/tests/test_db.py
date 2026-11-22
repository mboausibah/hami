import sqlite3

import pytest

from app import db as dbmod

EXPECTED_TABLES = {
    "scans", "artifacts", "observations", "assessments", "reviews", "dataset_versions", "model_versions",
    "links", "watches", "alerts", "discovered_domains", "static_findings", "schema_migrations",
}


def test_migrations_create_all_tables(fresh_db):
    applied = dbmod.migrate(fresh_db)
    assert applied == ["001_init"]
    assert dbmod.migrate(fresh_db) == []  # idempotent
    conn = sqlite3.connect(fresh_db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= tables


def test_static_findings_has_no_value_column(fresh_db):
    dbmod.migrate(fresh_db)
    conn = sqlite3.connect(fresh_db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(static_findings)")}
    assert not cols & {"value", "secret", "secret_value", "match", "snippet"}
    assert {"category", "file_path", "line", "col", "detected_at", "review_status"} <= cols


def _scan(conn):
    return conn.execute(
        "INSERT INTO scans (submitted_url, normalized_url, host, source_type, submitted_at) VALUES (?,?,?,?,?)",
        ("https://a.test/", "https://a.test/", "a.test", "manual", dbmod.utcnow()),
    ).lastrowid


def test_reviews_are_append_only_with_supersedes(fresh_db):
    with dbmod.db() as conn:
        sid = _scan(conn)
        r1 = conn.execute(
            "INSERT INTO reviews (scan_id, label, reviewer, created_at) VALUES (?,?,?,?)",
            (sid, "legitimate", "rev", dbmod.utcnow())).lastrowid
        r2 = conn.execute(
            "INSERT INTO reviews (scan_id, label, reviewer, supersedes, created_at) VALUES (?,?,?,?,?)",
            (sid, "fraudulent", "rev", r1, dbmod.utcnow())).lastrowid
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE reviews SET label='inconclusive' WHERE review_id=?", (r1,))
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM reviews WHERE review_id=?", (r1,))
        rows = conn.execute("SELECT review_id, label, supersedes FROM reviews ORDER BY review_id").fetchall()
        assert [tuple(r) for r in rows] == [(r1, "legitimate", None), (r2, "fraudulent", r1)]


def test_observations_immutable(fresh_db):
    with dbmod.db() as conn:
        sid = _scan(conn)
        oid = conn.execute(
            "INSERT INTO observations (scan_id, indicator_type, created_at) VALUES (?,?,?)",
            (sid, "deposit_to_unlock", dbmod.utcnow())).lastrowid
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE observations SET indicator_type='x' WHERE obs_id=?", (oid,))


def test_check_constraints(fresh_db):
    with dbmod.db() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scans (submitted_url, normalized_url, host, source_type, submitted_at) VALUES (?,?,?,?,?)",
                ("u", "u", "h", "carrier-pigeon", dbmod.utcnow()))
        sid = _scan(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO assessments (scan_id, risk_tier, rules_fired, clues_json, created_at)"
                         " VALUES (?,?,?,?,?)", (sid, "very_bad", "[]", "[]", dbmod.utcnow()))
