# VoyageAI — Autonomous Travel Agent

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Frontend Widget (HTML/JS)  — Zero UI Travel Assistant  │
│  • Conversational interface  • GDS session timer        │
│  • Itinerary card renderer   • Micro-confirmation flow  │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP POST /api/chat
┌──────────────────────▼──────────────────────────────────┐
│  Flask RAG Server (Python)  — Orchestration Layer       │
│  • Session management (30-min TTL)                      │
│  • RAG memory store (entity extraction + retrieval)     │
│  • Reasoning engine with retry loops                    │
└──┬────────────┬───────────────────────────────────┬─────┘
   │            │                                   │
   ▼            ▼                                   ▼
┌──────┐  ┌───────────┐  ┌──────────────────────────────┐
│Guard-│  │ MCP Server│  │  Anthropic Claude API         │
│rails │  │ Registry  │  │  • Intent inference           │
│L1+L2 │  │           │  │  • Itinerary reasoning        │
│+L3   │  │ Flights   │  │  • Confidence self-scoring    │
└──────┘  │ Hotels    │  └──────────────────────────────┘
          │ Cars      │
          │ Weather   │
          │ Maps      │
          │ Currency  │
          │ Visa      │
          │ Experien. │
          └───────────┘
```

## Quick Start

### Option A — Run locally (recommended for demo)

```bash
# 1. Clone and setup
cd voyageai/backend
pip install -r requirements.txt

# 2. Set API key (minimum required)
export ANTHROPIC_API_KEY=your_key_here

# 3. Start backend
python app.py

# 4. Open frontend
open ../frontend/index.html
```

### Option B — Docker Compose

```bash
# 1. Copy and fill environment file
cp .env.example .env
nano .env   # add your ANTHROPIC_API_KEY

# 2. Start all services
docker-compose up --build

# 3. Open browser
open http://localhost:8080
```

## Demo Mode (No API Key)

The app works without an Anthropic API key using the `/api/demo` endpoint.
Set `USE_DEMO = true` in `frontend/index.html` (already the default).

This uses live MCP server data (flights/hotels/weather etc.) but returns
a pre-structured itinerary instead of calling the LLM.

## API Endpoints

| Method | Endpoint              | Description                    |
|--------|-----------------------|--------------------------------|
| POST   | /api/chat             | Main reasoning endpoint        |
| POST   | /api/demo             | Demo mode (no LLM key needed)  |
| POST   | /api/session          | Create new session             |
| GET    | /api/session/<id>     | Get session state              |
| POST   | /api/confirm          | Confirm booking element        |
| GET    | /api/health           | Health check                   |
| GET    | /api/mcp              | List MCP servers               |
| POST   | /api/mcp/<server>     | Call specific MCP server       |

## Three-Layer Guardrails

**Layer 1 — Input:** Injection detection, length limit, domain relevance check  
**Layer 2a — Schema:** JSON schema validation against typed itinerary schema  
**Layer 2b — Factual:** IATA code verification, price drift check vs MCP data  
**Layer 2c — Business:** Budget cap, date integrity, minimum connection times  
**Layer 3 — Action:** PCI hard block, 85% confidence gate, £1k human confirm  

## Confidence Scoring

```
final_score = (intent × 0.25) + (rag × 0.20) + (gds × 0.35) + (guard × 0.20)
Threshold: 0.85 → PROCEED | < 0.85 → RETRY (max 3×) → Human handoff
```

## MCP Servers

| Server       | Data Source                    | TTL    | Fallback |
|--------------|--------------------------------|--------|----------|
| Flights      | Amadeus API / mock             | 3 min  | ✓ Mock   |
| Hotels       | Internal / mock                | 5 min  | ✓ Mock   |
| Cars         | Hertz/Avis / mock              | 10 min | ✓ Mock   |
| Weather      | OpenWeatherMap / mock          | 1 hour | ✓ Mock   |
| Maps         | Google Maps / mock             | 24 hr  | ✓ Mock   |
| Currency     | ExchangeRate-API / mock        | 1 hour | ✓ Mock   |
| Visa         | IATA Timatic / mock            | 7 days | ✓ Mock   |
| Experiences  | Viator / mock                  | 1 hour | ✓ Mock   |

## Free API Keys (for live data)

- **OpenWeatherMap:** openweathermap.org/api (free tier)
- **ExchangeRate-API:** exchangerate-api.com (free tier)  
- **Amadeus:** developers.amadeus.com (free sandbox)
- **Google Maps:** console.cloud.google.com (free tier with billing)
