-- ==========================================================================
-- CarFINDa — Initial Database Schema
-- ==========================================================================
-- This migration creates all core tables for the CarFINDa platform:
--   - User preferences and preference evolution history
--   - Search sessions and results
--   - Listings with VIN-based deduplication
--   - Listing scores (safety, reliability, value, efficiency)
--   - Persistent conversation memory for the AI agent
--   - Monitored searches (background deal watching)
--   - Price history tracking
--   - Outreach campaigns and messages (seller DM automation)
--
-- All tables have Row Level Security (RLS) enabled so users can only
-- access their own data via Supabase Auth.
-- ==========================================================================


-- --------------------------------------------------------------------------
-- User preferences
-- --------------------------------------------------------------------------
CREATE TABLE user_preferences (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    budget_min INTEGER DEFAULT 0,
    budget_max INTEGER,
    vehicle_types TEXT[] DEFAULT '{}',
    max_mileage INTEGER,
    location TEXT,
    radius_miles INTEGER DEFAULT 50,
    dealbreakers TEXT[] DEFAULT '{}',
    preferred_makes TEXT[] DEFAULT '{}',
    min_year INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);


-- --------------------------------------------------------------------------
-- Search sessions
-- --------------------------------------------------------------------------
CREATE TABLE search_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    query_text TEXT,
    parsed_filters JSONB,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'scraping', 'scoring', 'complete', 'failed')),
    results_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);


-- --------------------------------------------------------------------------
-- Listings (VIN-deduplicated)
-- --------------------------------------------------------------------------
CREATE TABLE listings (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    vin TEXT,
    year INTEGER NOT NULL,
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    trim TEXT,
    price NUMERIC(10,2),
    mileage INTEGER,
    location TEXT,
    exterior_color TEXT,
    interior_color TEXT,
    fuel_type TEXT,
    transmission TEXT,
    drivetrain TEXT,
    body_type TEXT,
    image_urls TEXT[] DEFAULT '{}',
    sources JSONB DEFAULT '[]',  -- [{source_name, source_url, price, scraped_at}]
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(vin)  -- deduplicate by VIN
);


-- --------------------------------------------------------------------------
-- Listing scores
-- --------------------------------------------------------------------------
CREATE TABLE listing_scores (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    listing_id UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    safety_score NUMERIC(5,2),
    reliability_score NUMERIC(5,2),
    value_score NUMERIC(5,2),
    efficiency_score NUMERIC(5,2),
    recall_penalty NUMERIC(5,2),
    composite_score NUMERIC(5,2),
    breakdown JSONB,  -- human-readable explanation of each component
    scored_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(listing_id)
);


-- --------------------------------------------------------------------------
-- Search-listing junction (which listings belong to which search)
-- --------------------------------------------------------------------------
CREATE TABLE search_listings (
    search_id UUID NOT NULL REFERENCES search_sessions(id) ON DELETE CASCADE,
    listing_id UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    rank INTEGER,
    PRIMARY KEY (search_id, listing_id)
);


-- --------------------------------------------------------------------------
-- Conversations (persistent agent memory)
-- --------------------------------------------------------------------------
CREATE TABLE conversations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id UUID,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_conversations_user ON conversations(user_id, created_at DESC);
CREATE INDEX idx_conversations_session ON conversations(session_id, created_at);


-- --------------------------------------------------------------------------
-- Preference history (track evolution over time)
-- --------------------------------------------------------------------------
CREATE TABLE preference_history (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    preferences JSONB NOT NULL,
    source TEXT DEFAULT 'explicit' CHECK (source IN ('explicit', 'inferred')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_pref_history_user ON preference_history(user_id, created_at DESC);


-- --------------------------------------------------------------------------
-- Monitored searches (background deal watching)
-- --------------------------------------------------------------------------
CREATE TABLE monitored_searches (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    preferences_snapshot JSONB NOT NULL,
    frequency TEXT DEFAULT 'daily' CHECK (frequency IN ('hourly', 'daily', 'weekly')),
    is_active BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);


-- --------------------------------------------------------------------------
-- Price history (track listing price changes over time)
-- --------------------------------------------------------------------------
CREATE TABLE price_history (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    listing_id UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    price NUMERIC(10,2) NOT NULL,
    source_name TEXT,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_price_history_listing ON price_history(listing_id, recorded_at DESC);


-- --------------------------------------------------------------------------
-- Outreach campaigns
-- --------------------------------------------------------------------------
CREATE TABLE outreach_campaigns (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    message_style TEXT DEFAULT 'friendly',
    max_messages INTEGER DEFAULT 10,
    auto_followup BOOLEAN DEFAULT TRUE,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);


-- --------------------------------------------------------------------------
-- Outreach messages
-- --------------------------------------------------------------------------
CREATE TABLE outreach_messages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    campaign_id UUID NOT NULL REFERENCES outreach_campaigns(id) ON DELETE CASCADE,
    listing_id UUID REFERENCES listings(id),
    seller_name TEXT,
    platform TEXT DEFAULT 'facebook',
    message_text TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'replied', 'failed')),
    sent_at TIMESTAMPTZ,
    reply_text TEXT,
    replied_at TIMESTAMPTZ,
    conversation_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_outreach_campaign ON outreach_messages(campaign_id, status);


-- ==========================================================================
-- Row Level Security (RLS)
-- ==========================================================================
-- Enable RLS on all tables so Supabase Auth policies control access.

ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE listing_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE preference_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE monitored_searches ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_messages ENABLE ROW LEVEL SECURITY;


-- ==========================================================================
-- RLS Policies — users can only access their own data
-- ==========================================================================

-- User preferences: full CRUD on own rows
CREATE POLICY "Users can manage own preferences"
    ON user_preferences FOR ALL
    USING (auth.uid() = user_id);

-- Search sessions: full CRUD on own rows
CREATE POLICY "Users can manage own searches"
    ON search_sessions FOR ALL
    USING (auth.uid() = user_id);

-- Listings: anyone can read (public marketplace data)
CREATE POLICY "Anyone can read listings"
    ON listings FOR SELECT
    USING (true);

-- Listing scores: anyone can read (public scoring data)
CREATE POLICY "Anyone can read scores"
    ON listing_scores FOR SELECT
    USING (true);

-- Search-listing junction: users can see listings from their own searches
CREATE POLICY "Users can see own search listings"
    ON search_listings FOR SELECT
    USING (
        search_id IN (SELECT id FROM search_sessions WHERE user_id = auth.uid())
    );

-- Conversations: full CRUD on own rows
CREATE POLICY "Users can manage own conversations"
    ON conversations FOR ALL
    USING (auth.uid() = user_id);

-- Preference history: full CRUD on own rows
CREATE POLICY "Users can see own preference history"
    ON preference_history FOR ALL
    USING (auth.uid() = user_id);

-- Monitored searches: full CRUD on own rows
CREATE POLICY "Users can manage own monitors"
    ON monitored_searches FOR ALL
    USING (auth.uid() = user_id);

-- Price history: anyone can read (public pricing data)
CREATE POLICY "Anyone can read price history"
    ON price_history FOR SELECT
    USING (true);

-- Outreach campaigns: full CRUD on own rows
CREATE POLICY "Users can manage own campaigns"
    ON outreach_campaigns FOR ALL
    USING (auth.uid() = user_id);

-- Outreach messages: users can manage messages in their own campaigns
CREATE POLICY "Users can manage own outreach messages"
    ON outreach_messages FOR ALL
    USING (
        campaign_id IN (SELECT id FROM outreach_campaigns WHERE user_id = auth.uid())
    );
