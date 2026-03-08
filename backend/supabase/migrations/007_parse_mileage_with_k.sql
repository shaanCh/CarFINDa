-- ==========================================================================
-- Parse mileage with "k" (thousands) suffix
-- ==========================================================================
-- DB stores mileage as text, e.g. "22k miles" or "45,123 mi".
-- Previous logic stripped non-digits, turning "22k miles" into 22.
-- This migration adds parsing: "22k" / "22K" -> 22000.
-- ==========================================================================

CREATE OR REPLACE FUNCTION parse_mileage_to_int(m text)
RETURNS int
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN COALESCE(m, '') ~* '[0-9]+\s*k' THEN
      (regexp_replace(
        COALESCE((regexp_match(lower(COALESCE(m, '')), '([0-9,.]+)\s*k'))[1], '0'),
        '[^0-9.]', '', 'g'
      )::float * 1000)::int
    ELSE
      (NULLIF(regexp_replace(COALESCE(m, ''), '[^0-9]', '', 'g'), '')::int)
  END
$$;

-- Update search_listings_filtered to use the new parser
DROP FUNCTION IF EXISTS search_listings_filtered(text[], text[], double precision, double precision, integer, integer, text, integer);

CREATE OR REPLACE FUNCTION search_listings_filtered(
    p_makes text[] DEFAULT NULL,
    p_models text[] DEFAULT NULL,
    p_budget_min float DEFAULT NULL,
    p_budget_max float DEFAULT NULL,
    p_min_year int DEFAULT NULL,
    p_max_mileage int DEFAULT NULL,
    p_location text DEFAULT NULL,
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
BEGIN
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
    ORDER BY ls.composite_score DESC NULLS LAST,
        (NULLIF(regexp_replace(COALESCE(l.price::text, ''), '[^0-9.]', '', 'g'), '')::float) ASC NULLS LAST
    LIMIT p_limit;
END;
$$;
