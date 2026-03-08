# CarFINDa

**Your car agent. Finds it. Scores it. Negotiates it.**

An AI-powered used car intelligence platform that aggregates listings from multiple marketplaces, scores every vehicle against real federal safety and emissions data, and gives you a conversational AI advisor that explains scores, flags bad deals, and generates data-backed negotiation strategies — all from a single natural language search.

---

## The Problem

Used car shopping is broken. Listings are scattered across CarMax, Cars.com, Facebook Marketplace, and dozens of other platforms — each with different pricing, incomplete data, and zero transparency. First-time buyers face:

- **Information asymmetry**: Dealerships know the car's history; you don't
- **No standardized scoring**: Is this $18,000 Civic actually a good deal? How does it compare to the $17,500 one 30 miles away?
- **Hidden risks**: Open recalls, high complaint rates, and known model-year defects buried in government databases no one checks
- **Negotiation disadvantage**: Sellers set the price; buyers guess

CarFINDa solves this by acting as your AI car agent — it scrapes listings in real time, scores them against NHTSA safety data, EPA fuel economy, and market valuations, synthesizes personalized recommendations with plain-English explanations, and generates negotiation scripts backed by the data it found.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                             │
│              Next.js 14 · Tailwind CSS · TypeScript         │
│                                                             │
│   Landing Page ──→ Results Grid ──→ Car Detail Page         │
│   (NL Search)      (Top Picks +     (Scores, Recalls,      │
│                     Synthesis)       Negotiation, Chat)     │
└────────────────────────┬────────────────────────────────────┘
                         │ REST API
┌────────────────────────▼────────────────────────────────────┐
│                     Backend (FastAPI)                        │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌──────────┐  │
│  │ Scraping  │  │ Scoring  │  │    LLM     │  │Marketplace│  │
│  │ Pipeline  │  │ Pipeline │  │   Agents   │  │ Outreach  │  │
│  └────┬─────┘  └────┬─────┘  └─────┬──────┘  └─────┬─────┘  │
│       │              │              │               │        │
│  CarMax API    NHTSA API      Gemini 2.5       Facebook     │
│  Cars.com      EPA API        Flash            Marketplace  │
│  (browser)     VinAudit                        (browser)    │
│                Tavily                                        │
└────────┬────────────────────────────────────────────────────┘
         │ HTTP
┌────────▼────────────────────────────────────────────────────┐
│               Playwright Sidecar (Express.js)               │
│          Chromium · Persistent Profiles · Stealth           │
└─────────────────────────────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────────────────────┐
│                    Supabase (Postgres)                       │
│         Auth · Preferences · Conversations · Outreach       │
└─────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 14, TypeScript, Tailwind CSS |
| **Backend** | FastAPI (Python), Pydantic, httpx |
| **LLM** | Google Gemini 2.5 Flash via `google-genai` SDK |
| **Browser Automation** | Playwright (Chromium) in Express.js sidecar |
| **Database** | Supabase (Postgres + Auth + Row Level Security) |
| **Data APIs** | NHTSA, EPA, VinAudit, Tavily |

---

## Web Scraping Engine

CarFINDa scrapes listings from multiple sources in parallel using `asyncio.gather()`, with each scraper isolated so failures don't cascade.

### Active Scrapers

**CarMax** — Dual-strategy scraper:
1. **Primary**: Direct JSON API (`/cars/api/search/run`) via httpx — fast, no browser needed
2. **Fallback**: Playwright sidecar rendering + BeautifulSoup when API returns 403
- Supports pagination (2 pages × 24 results)
- Three HTML extraction strategies: embedded JSON in `<script>` tags, JSON-LD, and DOM card parsing
- Model slug normalization (e.g., "CR-V" / "CRV" / "cr v" all resolve correctly)

**Cars.com** — Browser-native scraper:
- Always renders through Playwright sidecar (JavaScript-heavy, `<spark-card>` web components)
- Parses custom web component attributes for structured listing data
- Fallback to vehicle detail link extraction

### Scraping Infrastructure

- **User-Agent rotation**: 5 realistic Chrome/Firefox/Safari fingerprints
- **Retry logic**: 3 attempts with exponential backoff (1.5s base) + random jitter
- **Rate limit handling**: Automatic backoff on 429/5xx responses
- **LLM fallback extraction**: When HTML parsing fails, sends page snapshot to Gemini for structured extraction
- **Deduplication**:
  - **VIN-based** (primary): Exact 17-character match with format validation
  - **Fuzzy fallback**: Matches on `(year, make, model, mileage ±1000, price ±$500)` tuple
  - Keeps lowest price across sources, consolidates all source URLs

---

## Playwright Browser Sidecar

A standalone Express.js server wrapping Playwright's Chromium browser, providing HTTP-controlled browser automation for scraping JavaScript-heavy sites and Facebook Marketplace interaction.

### Why a Sidecar?

- **Persistent browser profiles**: Cookies, localStorage, and session data survive across requests — critical for Facebook login persistence
- **Profile isolation**: Each scraper (CarMax, Cars.com, Facebook) gets its own named context, preventing tab/cookie conflicts
- **Resource efficiency**: Lazy initialization on first use, 5-minute idle auto-shutdown
- **Stealth mode**: Custom User-Agent injection, anti-bot flags, and stealth scripts to evade detection
- **Scalability**: Runs independently from the Python backend

### API Surface

| Endpoint | Purpose |
|----------|---------|
| `POST /navigate` | Navigate to URL with configurable `waitUntil` strategy |
| `GET /snapshot` | AI-readable page content via Playwright's `_snapshotForAI()` |
| `GET /content` | Raw HTML string |
| `POST /screenshot` | PNG screenshot with base64 encoding |
| `POST /act` | Interactive actions: click, type, press, hover, scroll, select |
| `POST /evaluate` | Execute arbitrary JavaScript on the page |
| `GET/POST /cookies` | Get/set/clear browser cookies |
| `GET/POST /storage` | Get/set localStorage and sessionStorage |

### Element Reference System

Playwright's `_snapshotForAI()` returns structured HTML with `aria-ref="e3"` attributes. The backend uses these refs in subsequent `/act` calls — enabling semantic element interaction without fragile CSS selectors.

---

## Scoring Engine

Every listing is scored on a **0–100 composite scale** built from 6 weighted components, each derived from real federal data and market analysis.

### Composite Score Formula

```
Composite = (Safety × 0.20) + (Reliability × 0.20) + (Value × 0.25)
          + (Ownership Cost × 0.15) + (Efficiency × 0.10) + (Recall × 0.10)
```

### Score Components

| Component | Weight | Source | Calculation |
|-----------|--------|--------|-------------|
| **Safety** | 20% | NHTSA 5-Star Ratings | `(rating / 5) × 100` |
| **Reliability** | 20% | NHTSA Complaint Database | `100 - (15 × log₁₀(complaints + 1))` |
| **Value** | 25% | VinAudit / Depreciation Model | Price vs. estimated market value ratio |
| **Ownership Cost** | 15% | VinAudit 5-Year Projection | Annual cost mapped to 0–100 scale ($4K=100, $13K+=0) |
| **Efficiency** | 10% | EPA Fuel Economy | `(MPG / 40) × 100`, capped at 50 MPGe for EVs |
| **Recall Penalty** | 10% | NHTSA Recalls | `100 - (open_recalls × 15)`, floor of 40 |

### Two-Tier Scoring

**Fast Mode** (~100ms for 100+ listings, no API calls):
- Used for search results grid
- Market value estimated via depreciation formula: `MSRP × (0.85 ^ age)` with mileage adjustment
- Safety/reliability/efficiency use conservative defaults
- MSRP lookup table for 20+ common models (default: $32,000)

**Full Mode** (~2-3s per listing, live API data):
- Used for detail pages
- Parallel prefetch: NHTSA safety + complaints + EPA fuel economy per unique (make, model, year)
- Per-listing: NHTSA recalls (VIN-preferred) + VinAudit market value + VinAudit ownership cost
- Semaphore-limited to 20 concurrent API calls

### In-Memory Cache

| Data | TTL | Rationale |
|------|-----|-----------|
| Safety ratings | 1 hour | Rarely change |
| Complaints | 1 hour | Batch updates infrequent |
| Recalls | 30 min | Can be issued any time |
| VIN decode | 24 hours | Immutable |
| Fuel economy | 1 hour | Stable EPA data |
| Market value | 1 hour | 90-day rolling average |

---

## Data Sources & APIs

### NHTSA (National Highway Traffic Safety Administration)

Free, public U.S. government API — no key required.

| Endpoint | Data |
|----------|------|
| `SafetyRatings/modelyear/{y}/make/{m}/model/{mo}` | 1-5 star crash test ratings (overall, frontal, side, rollover) |
| `complaints/complaintsByVehicle` | Consumer-reported defects with component breakdowns |
| `recalls/recallsByVehicle` | Open/closed recalls with campaign numbers and affected components |
| `vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}` | VIN decode → make, model, year, trim, engine, transmission |

Rate-limited to 150ms between sequential calls (respecting government API courtesy).

### EPA Fuel Economy (fueleconomy.gov)

Free, public API.

- Fuzzy-matches user model names to EPA's model catalog (handles "F-150" → "F150 Pickup 2WD")
- Discovers up to 5 trim/option variants per model
- Returns combined city/highway MPG for the most common configuration

### VinAudit

Requires API key. Provides two critical datasets:

- **Market Value**: VIN-based or YMMTID-based (`2020_toyota_camry_se`) pricing with confidence bands, sample size, and mileage adjustments
- **Ownership Cost**: 5-year projected breakdown — depreciation, insurance, fuel, maintenance, repairs, and fees

### Tavily Search

Optional fallback for market value estimation. Searches KBB and automotive pricing sites when VinAudit is unavailable.

---

## LLM Agents & Context Engineering

CarFINDa uses Google Gemini 2.5 Flash with structured output enforcement (`response_mime_type="application/json"` + JSON Schema) across 5 specialized agents, each with carefully engineered system prompts and context windows.

### Agent Architecture

| Agent | Purpose | Temperature | Output |
|-------|---------|-------------|--------|
| **Intake Agent** | Parse NL query → structured filters | 0.3 | JSON (12 filter fields) |
| **Snapshot Parser** | Extract listings from browser snapshots | 0.3 | JSON (16 fields per listing) |
| **Synthesizer** | Rank & explain top 5 recommendations | 0.4 | JSON (headlines, explanations, red flags) |
| **Chat Agent** | Multi-turn Q&A about listings/scores | 0.7 | Free-form text |
| **Negotiation Agent** | Generate negotiation strategy + opening DM | 0.4 | JSON (fair price, leverage, scripts) |

### Context Engineering Approach

Each agent receives a structured context window designed for maximum LLM effectiveness:

1. **System Prompt** (50–100 lines): Domain-specific rules, output formatting requirements, edge case handling, and behavioral constraints
2. **Structured Context Block** (Markdown with `##` sections):
   - User intent/query and parsed preferences
   - Listing data: year, make, model, price, mileage, VIN, location, color, fuel, transmission, drivetrain
   - Score breakdowns: composite + all 6 component scores
   - NHTSA data: safety ratings, top complaint categories with counts, open recalls with campaign numbers
   - Market data: estimated value, confidence bands, source
   - Competing listings for comparison context
3. **Schema Enforcement**: All structured agents use Gemini's native JSON Schema validation — the model cannot return malformed output

### Intake Agent

Converts natural language like *"reliable SUV under $25k, low miles, no accidents"* into structured filters:

- 13-point extraction rules covering budget ranges, body types, make/model, mileage, dealbreakers, location, year inference
- Handles colloquial input: "under $25K" → `budget_max: 25000`, "newer" → `min_year: 2021`, "near Boulder" → `"Boulder, CO"`

### Synthesizer

Analyzes up to 30 scored listings and generates:
- **Top 5 recommendations** personalized to the user's stated needs (not just sorted by score)
- **Headlines**: "Best Overall Value", "Safest Pick", "Lowest Ownership Cost"
- **Explanations**: 2–4 sentences citing specific data — "$2,100 below market", "4/5 NHTSA stars", "3 open recalls on drivetrain"
- **Strengths/Concerns**: Tagged pills for quick scanning
- **Red Flags**: Global warnings about model-year issues, recall patterns, or market anomalies

### Chat Agent

Multi-turn conversational AI with full listing and scoring context:
- Explains score breakdowns component by component
- Compares listings side-by-side
- Flags red flags: recalls, complaint patterns, price/odometer anomalies
- Drafts seller messages in multiple styles (friendly, direct, negotiating)
- Suggests related searches based on conversation

### Negotiation Agent

Generates a complete data-backed negotiation strategy:
- **Opening DM**: 4–6 sentence conversational message citing 1–2 data points with a specific offer price
- **Fair price range**: Low/mid/high based on market data
- **Opening offer**: Typically 10–15% below fair value with justification
- **Leverage points**: Market comparisons, recall data, complaint patterns, mileage/condition issues
- **Questions to ask**: Based on known model-year problems
- **Competing listings**: Up to 5 alternatives as negotiation leverage
- **Walk-away price**: Data-derived ceiling

Fallback logic generates basic strategies when the Gemini API key is unavailable.

---

## Facebook Marketplace Integration

Full browser-automated Facebook Marketplace workflow via the Playwright sidecar:

1. **Authentication**: Login with credentials + 2FA via persistent browser profile (cookies survive across sessions)
2. **Search**: Navigate Marketplace with year/price/mileage filters, extract listings from page snapshots
3. **DM Automation**: Send personalized opening messages to sellers with AI-generated offer prices
4. **Reply Monitoring**: Scan Messenger inbox, match conversations back to campaign messages
5. **Follow-ups**: Auto-send follow-up messages to stale (2+ days) unreplied conversations

### Outreach Manager

Supabase-backed campaign tracking system:
- **3 message styles**: Friendly, direct, and negotiating (AI-generated with data-backed offers)
- **Campaign lifecycle**: Create → generate messages → send → monitor replies → follow up
- **Persistence**: Campaign status, message text, sent timestamps, reply text, and conversation URLs stored in Postgres

---

## Frontend

### Pages

**Landing** (`/`): Hero with glass-morphism search bar, NL input ("What kind of car are you looking for?"), expandable filter chips (budget, type, fuel, year), browser geolocation auto-detection

**Results** (`/results`): Two-tier display:
- **Top Picks**: Large cards with LLM-generated headlines, rank badges, score badges, explanation text, and strength/concern tags
- **More Results**: Grid of standard car cards with scores
- **Synthesis Summary**: Search overview with red flags section
- **Loading UX**: Rotating stage indicators ("Parsing preferences..." → "Searching marketplaces..." → "Scoring vehicles..." → "Generating recommendations...")

**Detail** (`/car/[id]`): Full score breakdown, recall/complaint data, negotiation panel, and multi-turn chat

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Chromium (installed via Playwright)

### Environment Variables

Create a `.env` file in the project root:

```env
# Required
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_ROLE_KEY=
DATABASE_URL=

# LLM (required for NL features)
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# Scoring APIs (optional — falls back to depreciation estimates)
VINAUDIT_API_KEY=
TAVILY_API_KEY=

# Browser Sidecar
SIDECAR_URL=http://localhost:3000
SIDECAR_TOKEN=

# Facebook Marketplace (optional)
FB_EMAIL=
FB_PASSWORD=

ENVIRONMENT=development
```

### Setup

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Sidecar (browser automation)
cd sidecar
npm install
npx playwright install chromium
npm run dev

# Frontend
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:3001` with the backend at `:8000` and sidecar at `:3000`.

---

## Project Structure

```
CarFINDa/
├── backend/
│   └── app/
│       ├── main.py                          # FastAPI entry point
│       ├── config.py                        # Pydantic Settings
│       ├── api/routes/                      # REST endpoints
│       │   ├── search.py                    #   Search + scrape + score + synthesize
│       │   ├── chat.py                      #   Multi-turn chat
│       │   ├── negotiate.py                 #   Negotiation strategy generation
│       │   ├── listings.py                  #   Listing CRUD
│       │   ├── preferences.py              #   User preference management
│       │   ├── monitor.py                   #   Price monitoring
│       │   ├── outreach.py                  #   Facebook DM campaigns
│       │   └── credentials.py              #   Facebook auth
│       ├── services/
│       │   ├── llm/                         # LLM agents
│       │   │   ├── gemini_client.py         #   Gemini SDK wrapper
│       │   │   ├── intake_agent.py          #   NL → structured filters
│       │   │   ├── snapshot_parser.py       #   Browser snapshot → listings
│       │   │   ├── synthesizer.py           #   Scored listings → recommendations
│       │   │   ├── chat_agent.py            #   Multi-turn car advisor
│       │   │   └── negotiation_agent.py     #   Negotiation strategy generator
│       │   ├── scoring/                     # Scoring engine
│       │   │   ├── pipeline.py              #   Fast/full scoring orchestration
│       │   │   ├── calculator.py            #   Composite score formula
│       │   │   ├── nhtsa.py                 #   NHTSA safety/complaints/recalls
│       │   │   ├── epa.py                   #   EPA fuel economy
│       │   │   ├── market_value.py          #   VinAudit + Tavily + depreciation
│       │   │   └── ownership_cost.py        #   5-year cost projection
│       │   ├── scraping/                    # Web scraping
│       │   │   ├── pipeline.py              #   Multi-source orchestration
│       │   │   ├── base_scraper.py          #   Shared infra (retry, UA, normalize)
│       │   │   ├── dedup.py                 #   VIN + fuzzy deduplication
│       │   │   └── scrapers/
│       │   │       ├── carmax.py            #   CarMax API + browser fallback
│       │   │       └── carscom.py           #   Cars.com browser scraper
│       │   ├── marketplace/                 # Facebook Marketplace
│       │   │   ├── facebook.py              #   Browser-automated FB scraper
│       │   │   ├── outreach_manager.py      #   DM campaign management
│       │   │   └── negotiation.py           #   Negotiation engine factory
│       │   └── memory/                      # Persistence
│       │       ├── conversation_store.py    #   Chat history (Supabase)
│       │       └── preference_tracker.py    #   User preferences (Supabase)
│       └── models/schemas.py                # Pydantic models
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx                     # Landing page (NL search)
│       │   ├── results/page.tsx             # Results grid + synthesis
│       │   ├── car/[id]/page.tsx            # Detail page + negotiation + chat
│       │   └── api/                         # Next.js API route proxies
│       ├── components/
│       │   ├── chat/                        # ChatPanel, ChatBubble
│       │   ├── layout/                      # TopBar
│       │   └── ui/                          # CarCard, ScoreBadge, SliderInput
│       └── lib/types.ts                     # Shared TypeScript types
├── sidecar/
│   └── src/
│       ├── server.ts                        # Express.js HTTP server
│       ├── actions.ts                       # Browser action handlers
│       └── profiles.ts                      # Persistent browser profile manager
└── .env.example
```

---

## License

MIT
