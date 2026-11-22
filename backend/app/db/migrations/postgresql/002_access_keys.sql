-- PostgreSQL translation of ../sqlite/002_access_keys.sql (same schema).
-- Capability key per scan: GET /scans/{id} and screenshot URLs need it (or the reviewer token),
-- so nobody can enumerate which links other people checked.
ALTER TABLE scans ADD COLUMN IF NOT EXISTS access_key TEXT;
CREATE INDEX IF NOT EXISTS idx_scans_status ON scans(status, submitted_at);
