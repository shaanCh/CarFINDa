-- ==========================================================================
-- Fix search_listings_filtered RPC — use columns that exist in listings table
-- ==========================================================================
-- The RPC referenced l.title, l.detail_url, l.image_url which don't exist.
-- Schema has: image_urls (array), sources (JSONB with url/source_url).
-- ==========================================================================

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
        l.trim,
        (l.year::text || ' ' || l.make || ' ' || l.model)::text AS title,
        (NULLIF(regexp_replace(COALESCE(l.price::text, ''), '[^0-9.]', '', 'g'), '')::float),
        (NULLIF(regexp_replace(COALESCE(l.mileage::text, ''), '[^0-9]', '', 'g'), '')::int),
        l.location,
        COALESCE(
            (l.sources->0->>'url'),
            (l.sources->0->>'source_url')
        )::text AS source_url,
        COALESCE((l.sources->0->>'name'), 'database')::text AS source_name,
        COALESCE(l.image_urls, ARRAY[]::text[]),
        l.exterior_color,
        l.interior_color,
        l.fuel_type,
        l.fuel_type AS motor_type,
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
        AND (p_max_mileage IS NULL OR (NULLIF(regexp_replace(COALESCE(l.mileage::text, ''), '[^0-9]', '', 'g'), '')::int) <= p_max_mileage)
        AND (p_location IS NULL OR p_location = '' OR l.location ILIKE '%' || p_location || '%')
    ORDER BY ls.composite_score DESC NULLS LAST,
        (NULLIF(regexp_replace(COALESCE(l.price::text, ''), '[^0-9.]', '', 'g'), '')::float) ASC NULLS LAST
    LIMIT p_limit;
END;
$$;
