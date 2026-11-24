-- Domain age from certificate transparency (cached per registrable domain) and scans that carry page structure
-- from the user's own browser (never reused as the server-side cache for other users' checks).
CREATE TABLE IF NOT EXISTS domain_age (
    domain          TEXT PRIMARY KEY,
    first_cert_at   TEXT,
    source          TEXT,
    error           TEXT,
    checked_at      TEXT NOT NULL
);
ALTER TABLE scans ADD COLUMN client_signals INTEGER NOT NULL DEFAULT 0;
