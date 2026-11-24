-- Redirect/invitation gateways and registration-page template fingerprints.

-- Discovery queue: domains seen as a redirect/invite gateway (or the site it led to) become review candidates.
-- SQLite cannot change a CHECK constraint in place, so the table is rebuilt with the same columns.
CREATE TABLE discovered_domains_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT NOT NULL UNIQUE,
    source          TEXT NOT NULL DEFAULT 'ct' CHECK (source IN ('ct','har_reference','manual','redirect_gateway')),
    cert_seen_at    TEXT,
    first_seen_at   TEXT NOT NULL,
    matched_pattern TEXT,
    evidence        TEXT,
    scan_id         INTEGER REFERENCES scans(scan_id),
    status          TEXT NOT NULL DEFAULT 'queued' CHECK (status IN
                        ('awaiting_approval','queued','scanning','scanned','failed','skipped')),
    status_note     TEXT,
    updated_at      TEXT NOT NULL
);
INSERT INTO discovered_domains_new SELECT id, domain, source, cert_seen_at, first_seen_at, matched_pattern, evidence,
    scan_id, status, status_note, updated_at FROM discovered_domains;
DROP TABLE discovered_domains;
ALTER TABLE discovered_domains_new RENAME TO discovered_domains;

-- Distinctive wording + form structure of a registration / login page (feature hashes, no page text).
CREATE TABLE IF NOT EXISTS page_templates (
    scan_id         INTEGER PRIMARY KEY REFERENCES scans(scan_id),
    host            TEXT NOT NULL,
    site            TEXT NOT NULL,
    features        TEXT NOT NULL,              -- JSON list of integer feature hashes
    n_lines         INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_templates_site ON page_templates(site);
