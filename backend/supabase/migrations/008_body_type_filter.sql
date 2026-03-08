-- ==========================================================================
-- Body type support for listing search
-- ==========================================================================
-- 1. Ensure body_type column exists
-- 2. Backfill body_type from make/model for rows where it's NULL
-- 3. Add p_body_types param to search_listings_filtered RPC
-- ==========================================================================

-- Ensure body_type exists (001 created it; some deployments may differ)
ALTER TABLE listings ADD COLUMN IF NOT EXISTS body_type TEXT;

-- Infer body type from model for common trucks (when body_type is NULL)
-- Handles "F150", "F-150 XLT", "Silverado 1500", "Ram 1500", etc.
UPDATE listings
SET body_type = 'Truck'
WHERE (body_type IS NULL OR body_type = '')
  AND (
    lower(COALESCE(model, '')) ~ 'f-?150|f-?250|f-?350|super\s*duty'
    OR lower(COALESCE(model, '')) ~ 'silverado|sierra\s*(1500|2500)?'
    OR lower(COALESCE(model, '')) ~ 'ram\s*(1500|2500|3500)'
    OR lower(COALESCE(model, '')) ~ '\m(tacoma|tundra|colorado|canyon|ranger|frontier|titan|ridgeline|maverick|gladiator|santa\s*cruz)\M'
  );

-- Function to infer body type from model (for runtime filtering when body_type is NULL)
CREATE OR REPLACE FUNCTION infer_body_type_from_model(model_name text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN COALESCE(model_name, '') = '' THEN NULL
    WHEN lower(model_name) ~ 'f-?150|f-?250|f-?350|super\s*duty' THEN 'Truck'
    WHEN lower(model_name) ~ 'silverado|sierra\s*(1500|2500)?' THEN 'Truck'
    WHEN lower(model_name) ~ 'ram\s*(1500|2500|3500)' THEN 'Truck'
    WHEN lower(model_name) ~ '\m(tacoma|tundra|colorado|canyon|ranger|frontier|titan|ridgeline|maverick|gladiator|santa\s*cruz)\M' THEN 'Truck'
    ELSE NULL
  END
$$;

-- Update search_listings_filtered: add p_body_types, filter by body_type or inferred
DROP FUNCTION IF EXISTS search_listings_filtered(text[], text[], double precision, double precision, integer, integer, text, integer);

CREATE OR REPLACE FUNCTION search_listings_filtered(
    p_makes text[] DEFAULT NULL,
    p_models text[] DEFAULT NULL,
    p_budget_min float DEFAULT NULL,
    p_budget_max float DEFAULT NULL,
    p_min_year int DEFAULT NULL,
    p_max_mileage int DEFAULT NULL,
    p_location text DEFAULT NULL,
    p_body_types text[] DEFAULT NULL,
    p_limit int DEFAULT 100
)
RETURNS TABLE (
    id text,
    vin text,
    year int,
    make text,
    model text,
    "trim" text,
    title text,
    price float,
    mileage int,
    location text,
    source_url text,
    source_name text,
    image_urls text[],
    exterior_color text,
    interior_color text,
    fuel_type text,
    motor_type text,
    transmission text,
    drivetrain text,
    safety_score float,
    reliability_score float,
    value_score float,
    efficiency_score float,
    recall_penalty float,
    composite_score float,
    breakdown jsonb
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  normalized_body_types text[];
BEGIN
  -- Normalize body types: "truck", "pickup" -> "Truck", etc.
  IF p_body_types IS NOT NULL AND cardinality(p_body_types) > 0 THEN
    normalized_body_types := ARRAY(
      SELECT initcap(
        CASE lower(trim(bt))
          WHEN 'pickup' THEN 'Truck'
          WHEN 'suv' THEN 'SUV'
          WHEN 'crossover' THEN 'Crossover'
          ELSE initcap(trim(bt))
        END
      )
      FROM unnest(p_body_types) AS bt
      WHERE bt IS NOT NULL AND trim(bt) != ''
    );
  END IF;

  RETURN QUERY
  SELECT
      l.id::text,
      l.vin,
      l.year,
      l.make,
      l.model,
      NULL::text AS "trim",
      l.title,
      (NULLIF(regexp_replace(COALESCE(l.price::text, ''), '[^0-9.]', '', 'g'), '')::float),
      parse_mileage_to_int(l.mileage::text),
      l.location,
      l.detail_url AS source_url,
      'database'::text AS source_name,
      CASE WHEN l.image_url IS NOT NULL AND l.image_url != '' THEN ARRAY[l.image_url] ELSE ARRAY[]::text[] END,
      NULL::text AS exterior_color,
      NULL::text AS interior_color,
      l.motor_type AS fuel_type,
      l.motor_type,
      l.transmission,
      l.drivetrain,
      (ls.safety_score::float),
      (ls.reliability_score::float),
      (ls.value_score::float),
      (ls.efficiency_score::float),
      (ls.recall_penalty::float),
      (ls.composite_score::float),
      ls.breakdown
  FROM listings l
  LEFT JOIN listing_scores ls ON ls.listing_id::text = l.id::text
  WHERE
      (p_makes IS NULL OR l.make = ANY(p_makes))
      AND (p_models IS NULL OR l.model = ANY(p_models))
      AND (p_min_year IS NULL OR l.year >= p_min_year)
      AND (p_budget_max IS NULL OR (NULLIF(regexp_replace(COALESCE(l.price::text, ''), '[^0-9.]', '', 'g'), '')::float) <= p_budget_max)
      AND (p_budget_min IS NULL OR (NULLIF(regexp_replace(COALESCE(l.price::text, ''), '[^0-9.]', '', 'g'), '')::float) >= p_budget_min)
      AND (p_max_mileage IS NULL OR parse_mileage_to_int(l.mileage::text) <= p_max_mileage)
      AND (p_location IS NULL OR p_location = '' OR l.location ILIKE '%' || p_location || '%')
      AND (
        normalized_body_types IS NULL
        OR cardinality(normalized_body_types) = 0
        OR COALESCE(NULLIF(trim(l.body_type), ''), infer_body_type_from_model(l.model)) = ANY(normalized_body_types)
      )
  ORDER BY ls.composite_score DESC NULLS LAST,
      (NULLIF(regexp_replace(COALESCE(l.price::text, ''), '[^0-9.]', '', 'g'), '')::float) ASC NULLS LAST
  LIMIT p_limit;
END;
$$;
