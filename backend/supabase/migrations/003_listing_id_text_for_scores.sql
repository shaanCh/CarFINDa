-- ==========================================================================
-- Fix: listing_scores.listing_id type mismatch
-- ==========================================================================
-- Your listings table uses non-UUID ids (e.g. "22643787" from CarMax/scrapers).
-- listing_scores.listing_id was UUID, causing: invalid input syntax for type uuid.
--
-- This migration changes listings.id and all listing_id columns to TEXT so
-- numeric/scraper ids work.
-- ==========================================================================

-- 1. Drop foreign keys that reference listings(id)
ALTER TABLE listing_scores   DROP CONSTRAINT IF EXISTS listing_scores_listing_id_fkey;
ALTER TABLE search_listings  DROP CONSTRAINT IF EXISTS search_listings_listing_id_fkey;
ALTER TABLE price_history    DROP CONSTRAINT IF EXISTS price_history_listing_id_fkey;
ALTER TABLE outreach_messages DROP CONSTRAINT IF EXISTS outreach_messages_listing_id_fkey;

-- 2. Alter child columns to TEXT
ALTER TABLE listing_scores   ALTER COLUMN listing_id TYPE TEXT USING listing_id::text;
ALTER TABLE search_listings  ALTER COLUMN listing_id TYPE TEXT USING listing_id::text;
ALTER TABLE price_history    ALTER COLUMN listing_id TYPE TEXT USING listing_id::text;
ALTER TABLE outreach_messages ALTER COLUMN listing_id TYPE TEXT USING listing_id::text;

-- 3. Alter listings.id to TEXT (primary key)
ALTER TABLE listings ALTER COLUMN id TYPE TEXT USING id::text;

-- 4. Re-add foreign keys
ALTER TABLE listing_scores   ADD CONSTRAINT listing_scores_listing_id_fkey
    FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE CASCADE;
ALTER TABLE search_listings  ADD CONSTRAINT search_listings_listing_id_fkey
    FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE CASCADE;
ALTER TABLE price_history    ADD CONSTRAINT price_history_listing_id_fkey
    FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE CASCADE;
ALTER TABLE outreach_messages ADD CONSTRAINT outreach_messages_listing_id_fkey
    FOREIGN KEY (listing_id) REFERENCES listings(id);
