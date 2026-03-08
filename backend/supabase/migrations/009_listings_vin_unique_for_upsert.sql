-- ==========================================================================
-- Ensure listings has UNIQUE(vin) for PostgREST upsert (ON CONFLICT)
-- ==========================================================================
-- Error 42P10: "no unique or exclusion constraint matching the ON CONFLICT"
-- occurs when upserting on vin without this constraint.
-- The listings table may have been created without it (e.g. via Supabase UI).
-- ==========================================================================

-- Standard UNIQUE allows multiple NULLs; enforces uniqueness for non-null vin
CREATE UNIQUE INDEX IF NOT EXISTS listings_vin_key ON listings(vin);
