-- ==========================================================================
-- Restore DEFAULT on listings.id for upsert (23502 fix)
-- ==========================================================================
-- Migration 003 changed id to TEXT; ALTER COLUMN TYPE can drop the default.
-- When we omit id for VIN upserts (to avoid PK conflicts), new rows need
-- a generated id. This restores the default so INSERT works.
-- ==========================================================================

ALTER TABLE listings
  ALTER COLUMN id SET DEFAULT gen_random_uuid()::text;
