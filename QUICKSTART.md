# VoyageAI — Zero Cost Quick Start

## Step 1: Get Free API Keys (5 minutes)

### Groq (PRIMARY — fastest, completely free)
1. Go to https://console.groq.com
2. Sign up with email (no credit card)
3. Go to API Keys → Create API Key
4. Copy key → paste as GROQ_API_KEY

### Gemini (SECONDARY — free tier)
1. Go to https://aistudio.google.com
2. Sign in with Google account
3. Click "Get API Key" → Create API key
4. Copy key → paste as GEMINI_API_KEY

## Step 2: Configure

```bash
cp .env.example .env
# Edit .env — add at minimum GROQ_API_KEY or GEMINI_API_KEY
nano .env
```

## Step 3: Run

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Open `frontend/index.html` in your browser.

## How the Waterfall Works

```
Your request
    │
    ▼
┌─────────────┐   ✓ success    ┌──────────────┐
│ Groq (FREE) │──────────────► │  Response    │
│ llama-3.1   │                └──────────────┘
└──────┬──────┘
       │ ✗ rate limit / no key
       ▼
┌─────────────┐   ✓ success    ┌──────────────┐
│Gemini (FREE)│──────────────► │  Response    │
│ 1.5-flash   │                └──────────────┘
└──────┬──────┘
       │ ✗ quota / no key
       ▼
┌─────────────┐   ✓ success    ┌──────────────┐
│  Anthropic  │──────────────► │  Response    │
│  (PAID)     │                └──────────────┘
└──────┬──────┘
       │ ✗ no key / error
       ▼
┌─────────────┐   always       ┌──────────────┐
│  Template   │──────────────► │  Response    │
│  (FREE,     │                │  (from MCP   │
│   built-in) │                │   data only) │
└─────────────┘                └──────────────┘
```

## Free Tier Limits

| Provider | Requests/day | Tokens/day | Cost    |
|----------|-------------|------------|---------|
| Groq     | 14,400      | 500,000    | FREE    |
| Gemini   | Unlimited*  | 1,000,000  | FREE    |
| Template | Unlimited   | Unlimited  | FREE    |
| Anthropic| Unlimited   | Unlimited  | ~$0.001 |

*Gemini: 15 req/min rate limit on free tier

## Test Without Any API Keys

The app works in demo mode with zero API keys:
- Open `frontend/index.html`
- The `USE_DEMO = true` flag in index.html uses `/api/demo`
- Full MCP data (flights, hotels, weather etc) is live
- Itinerary is built from template provider (deterministic)
