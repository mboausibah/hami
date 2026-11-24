-- PostgreSQL translation of ../sqlite/005_gateways_templates.sql (same schema).
ALTER TABLE discovered_domains DROP CONSTRAINT IF EXISTS discovered_domains_source_check;
ALTER TABLE discovered_domains ADD CONSTRAINT discovered_domains_source_check
    CHECK (source IN ('ct','har_reference','manual','redirect_gateway'));

CREATE TABLE IF NOT EXISTS page_templates (
    scan_id         BIGINT PRIMARY KEY REFERENCES scans(scan_id),
    host            TEXT NOT NULL,
    site            TEXT NOT NULL,
    features        TEXT NOT NULL,
    n_lines         INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_templates_site ON page_templates(site);
