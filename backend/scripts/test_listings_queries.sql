-- ==========================================================================
-- Manual test queries for search_listings_filtered
-- Run these in Supabase SQL Editor to verify the RPC works.
-- ==========================================================================

-- 1. No filters (limit 5)
SELECT * FROM search_listings_filtered(p_limit := 5);

-- 2. Budget max $30k
SELECT * FROM search_listings_filtered(p_budget_max := 30000, p_limit := 5);

-- 3. Min year 2020
SELECT * FROM search_listings_filtered(p_min_year := 2020, p_limit := 5);

-- 4. Make Toyota
SELECT * FROM search_listings_filtered(p_makes := ARRAY['Toyota'], p_limit := 5);

-- 5. Make Honda, model Civic
SELECT * FROM search_listings_filtered(
  p_makes := ARRAY['Honda'],
  p_models := ARRAY['Civic'],
  p_limit := 5
);

-- 6. Budget $20k + year 2018+
SELECT * FROM search_listings_filtered(
  p_budget_max := 20000,
  p_min_year := 2018,
  p_limit := 5
);

-- 7. Max mileage 50k
SELECT * FROM search_listings_filtered(p_max_mileage := 50000, p_limit := 5);

-- 8. Location contains "Denver"
SELECT * FROM search_listings_filtered(p_location := 'Denver', p_limit := 5);
