# VoyageAI — Windows Local Setup Guide

**Autonomous AI Travel Assistant · Zero-Cost LLM Waterfall**

> Run the full VoyageAI stack on your Windows machine in under 10 minutes.  
> No Docker required. Works on Windows 10 / 11.

---

## What You Are Running

```
Browser (index.html)
       │
       ▼  HTTP
Flask Server (app.py) — Python 3.11+
       │
       ├── LLM Waterfall:  Groq → Gemini → Anthropic → Template
       │
       ├── 8 MCP Servers:  Flights · Hotels · Cars · Weather
       │                   Maps · Currency · Visa · Experiences
       │
       ├── Guardrail Engine: Input → Schema → Factual → Business → Action
       │
       └── RAG Memory Store: Session context · Entity extraction
```

---

## Prerequisites

### 1 · Python 3.11 or 3.12

Check if already installed:

```cmd
python --version
```

If not installed:

1. Go to **https://www.python.org/downloads/**
2. Download **Python 3.11.x** or **3.12.x** (Windows installer, 64-bit)
3. Run the installer — **tick "Add Python to PATH"** before clicking Install
4. Verify:

```cmd
python --version
pip --version
```

---

### 2 · Get at Least ONE Free API Key

You need at minimum one LLM key. Both are completely free — no credit card.

#### Option A — Groq (Recommended — Fastest)

| | |
|---|---|
| **URL** | https://console.groq.com |
| **Signup** | Email address — no credit card |
| **Free tier** | 14,400 requests/day · 500,000 tokens/day |
| **Speed** | ~500 tokens/second (fastest available) |
| **Model used** | llama-3.1-70b-versatile |

Steps:
1. Go to https://console.groq.com
2. Sign Up → verify email
3. Left sidebar → **API Keys**
4. Click **Create API Key**
5. Copy the key (starts with `gsk_...`)

---

#### Option B — Google Gemini (Also Free)

| | |
|---|---|
| **URL** | https://aistudio.google.com |
| **Signup** | Google account — no credit card |
| **Free tier** | 15 req/min · 1,000,000 tokens/day |
| **Model used** | gemini-1.5-flash |

Steps:
1. Go to https://aistudio.google.com
2. Sign in with your Google account
3. Click **Get API Key** (top left)
4. Click **Create API key in new project**
5. Copy the key (starts with `AIza...`)

---

> **No keys at all?** The app still works using the **Template provider** — a built-in Python fallback that builds itineraries from live MCP data with zero API calls.

---

## Installation

### Step 1 — Unzip the Project

Unzip `VoyageAI_Codebase_v2.zip` to a folder, for example:

```
C:\Projects\voyageai\
```

Your folder structure should look like:

```
C:\Projects\voyageai\
├── frontend\
│   └── index.html
├── backend\
│   ├── app.py
│   ├── config.py
│   ├── requirements.txt
│   ├── llm\
│   │   ├── waterfall.py
│   │   ├── groq_provider.py
│   │   ├── gemini_provider.py
│   │   ├── anthropic_provider.py
│   │   └── template_provider.py
│   ├── mcp_servers\
│   │   ├── flight_mcp.py
│   │   ├── hotel_mcp.py
│   │   ├── car_mcp.py
│   │   ├── weather_mcp.py
│   │   ├── maps_mcp.py
│   │   ├── currency_mcp.py
│   │   ├── visa_mcp.py
│   │   └── experience_mcp.py
│   ├── guardrails\
│   │   └── __init__.py
│   ├── reasoning\
│   │   └── __init__.py
│   └── rag\
│       └── __init__.py
├── .env.example
├── README.md
└── QUICKSTART.md
```

---

### Step 2 — Open Command Prompt in the Backend Folder

**Option A — File Explorer:**
1. Open `C:\Projects\voyageai\backend\` in File Explorer
2. Click the address bar at the top
3. Type `cmd` and press **Enter**

**Option B — Start Menu:**
1. Press `Win + R`
2. Type `cmd` → Enter
3. Then type:

```cmd
cd C:\Projects\voyageai\backend
```

---

### Step 3 — Create a Virtual Environment (Recommended)

This keeps VoyageAI's packages separate from your other Python projects:

```cmd
python -m venv venv
```

Activate it:

```cmd
venv\Scripts\activate
```

You should see `(venv)` appear at the start of your command prompt line:

```cmd
(venv) C:\Projects\voyageai\backend>
```

> **Note:** You must run this activate command every time you open a new Command Prompt window.

---

### Step 4 — Install Dependencies

```cmd
pip install -r requirements.txt
```

This installs all required packages. First time takes 2–3 minutes.

Expected output ends with something like:
```
Successfully installed flask-3.0.0 groq-0.9.0 google-generativeai-0.7.2 ...
```

---

### Step 5 — Configure Your API Keys

Copy the example environment file:

```cmd
copy .env.example .env
```

Open `.env` in Notepad:

```cmd
notepad .env
```

The file looks like this:

```
GROQ_API_KEY=your_groq_key_here
GEMINI_API_KEY=your_gemini_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
OPENWEATHER_API_KEY=your_openweather_key_here
EXCHANGERATE_API_KEY=your_exchangerate_key_here
GOOGLE_MAPS_API_KEY=your_googlemaps_key_here
AMADEUS_CLIENT_ID=your_amadeus_client_id
AMADEUS_CLIENT_SECRET=your_amadeus_client_secret
```

Replace the values with your actual keys. **You only need one LLM key to start.**

Example with just Groq:

```
GROQ_API_KEY=gsk_abc123yourkeyhere
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
OPENWEATHER_API_KEY=
EXCHANGERATE_API_KEY=
GOOGLE_MAPS_API_KEY=
AMADEUS_CLIENT_ID=
AMADEUS_CLIENT_SECRET=
```

Save and close Notepad.

---

### Step 6 — Start the Flask Server

```cmd
python app.py
```

Expected startup output:

```
╔══════════════════════════════════╗
║   VoyageAI  LLM Waterfall        ║
╠══════════════════════════════════╣
║  ✓ groq         [FREE]           ║
║  ✗ gemini       [FREE]  (not configured)  ║
║  ✗ anthropic    [PAID]  (not configured)  ║
║  ✓ template     [FREE]           ║
╚══════════════════════════════════╝

 * Running on http://127.0.0.1:5000
 * Debug mode: on
```

The server is now running. **Leave this window open.**

---

### Step 7 — Open the Frontend

Open a new **File Explorer** window and navigate to:

```
C:\Projects\voyageai\frontend\
```

Double-click **index.html** — it opens in your default browser.

> **Alternatively,** right-click `index.html` → Open with → Chrome / Edge / Firefox

You should see the VoyageAI chat interface with the LLM waterfall chips in the top-right corner.

---

### Step 8 — Test It

Type in the chat box:

```
Family holiday to Lisbon in October, 4 of us, pool hotel, budget £3,000
```

Press **Enter** or click the send button.

Watch the **MCP server chips** light up amber as data is fetched, then the **Groq chip** turn green when the LLM responds.

You should receive a full itinerary card with flights, hotel, cost breakdown, confidence scores, and booking confirmation buttons.

---

## Troubleshooting

### ❌ `python` is not recognised

Python is not on your PATH. Fix it:

1. Search Windows for **"Edit the system environment variables"**
2. Click **Environment Variables**
3. Under **System Variables**, find **Path** → Edit
4. Add the path to your Python installation, typically:
   - `C:\Users\YourName\AppData\Local\Programs\Python\Python311\`
   - `C:\Users\YourName\AppData\Local\Programs\Python\Python311\Scripts\`
5. Restart Command Prompt

Alternatively, reinstall Python and tick **"Add Python to PATH"**.

---

### ❌ `pip install` fails with SSL error

Run this in Command Prompt:

```cmd
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

---

### ❌ `ModuleNotFoundError: No module named 'flask'`

Your virtual environment is not activated. Run:

```cmd
venv\Scripts\activate
```

Then retry `python app.py`.

---

### ❌ `Address already in use` / Port 5000 busy

Something else is using port 5000. Run the server on a different port:

```cmd
python app.py --port 5001
```

Then update `index.html` — find this line near the bottom:

```javascript
const API = window.VOYAGE_API || 'http://localhost:5000/api';
```

Change `5000` to `5001`.

---

### ❌ `groq.AuthenticationError` or `Invalid API Key`

Your Groq key is wrong or not saved correctly. Check:

1. Open `.env` in Notepad
2. Make sure the key has no extra spaces, quotes, or line breaks
3. Save and restart the Flask server

---

### ❌ The browser shows a blank page or CORS error

The browser cannot reach the Flask server. Check:

1. The Flask server is running (you see `* Running on http://127.0.0.1:5000`)
2. You opened `index.html` from a local file path (not uploaded somewhere)
3. No firewall or antivirus is blocking `localhost:5000`

If Windows Defender Firewall shows a popup asking about network access, click **Allow**.

---

### ❌ `google.api_core.exceptions.InvalidArgument` from Gemini

The Gemini API key is wrong or the project has billing disabled. Go to https://aistudio.google.com and generate a fresh key.

---

### ❌ Response says "human_handoff"

The AI tried 3 times and confidence stayed below 85%. Usually means:

- No LLM keys configured → only Template provider running, confidence naturally lower
- Very complex or ambiguous query — try simplifying: `"Lisbon 7 nights 4 people £3000"`

---

## Stopping the Server

Press `Ctrl + C` in the Command Prompt window running Flask.

---

## Restarting After Closing

Every time you want to run VoyageAI again:

```cmd
cd C:\Projects\voyageai\backend
venv\Scripts\activate
python app.py
```

Then open `frontend\index.html` in your browser.

---

## Optional: Free External API Keys

These enable live data for Weather and Currency. All have free tiers — no credit card.

| Service | URL | Free Tier | Key name in .env |
|---|---|---|---|
| OpenWeather | openweathermap.org/api | 1,000 calls/day | `OPENWEATHER_API_KEY` |
| ExchangeRate | exchangerate-api.com | 1,500 calls/month | `EXCHANGERATE_API_KEY` |
| Amadeus (flights) | developers.amadeus.com | Sandbox access | `AMADEUS_CLIENT_ID` / `_SECRET` |

Without these keys, the app uses built-in mock data that is realistic but not live.

---

## Project Structure Reference

```
backend\
│
├── app.py                  Flask server — all API endpoints
├── config.py               All configuration and thresholds
├── requirements.txt        Python dependencies
│
├── llm\                    LLM Waterfall
│   ├── waterfall.py        Orchestrator — tries providers in order
│   ├── groq_provider.py    Groq (FREE) — llama-3.1-70b
│   ├── gemini_provider.py  Gemini (FREE) — 1.5-flash
│   ├── anthropic_provider.py  Claude Haiku (PAID fallback)
│   └── template_provider.py   Pure Python (always works)
│
├── mcp_servers\            8 Real-Time Data Tools
│   ├── flight_mcp.py       Flights — Amadeus + mock
│   ├── hotel_mcp.py        Hotels — realistic mock
│   ├── car_mcp.py          Cars & transfers
│   ├── weather_mcp.py      Weather — OpenWeatherMap + mock
│   ├── maps_mcp.py         Distances — Google Maps + mock
│   ├── currency_mcp.py     FX Rates — ExchangeRate-API + mock
│   ├── visa_mcp.py         Visa rules — IATA mock
│   └── experience_mcp.py   Tours & activities
│
├── guardrails\             3-Layer Safety System
│   └── __init__.py         L1 Input · L2a Schema · L2b Factual
│                           L2c Business Rules · L3 Action Gate
│
├── reasoning\              AI Reasoning Engine
│   └── __init__.py         Intent → MCP calls → LLM → Retry loop
│                           Confidence scoring · Human handoff
│
└── rag\                    Session Memory
    └── __init__.py         Entity store · Context builder · History

frontend\
└── index.html              Zero-UI chat widget — complete app in one file
```

---

## API Endpoints (for developers)

Once the server is running, these endpoints are available at `http://localhost:5000`:

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/chat` | Main — send message, get itinerary |
| `POST` | `/api/demo` | Demo mode — no LLM key needed |
| `POST` | `/api/session` | Create a new session |
| `GET` | `/api/session/<id>` | View session state |
| `POST` | `/api/confirm` | Confirm a booking element |
| `GET` | `/api/health` | Server health + waterfall status |
| `GET` | `/api/waterfall` | LLM provider status and stats |
| `GET` | `/api/mcp` | List all MCP servers |
| `POST` | `/api/mcp/<name>` | Call a specific MCP server directly |

Test the server is running:

```cmd
curl http://localhost:5000/api/health
```

Or open in browser: `http://localhost:5000/api/health`

---

## LLM Waterfall Explained

```
Your message
     │
     ▼
┌────────────────────────────────────────────────────────────┐
│  WATERFALL — tries each provider in order                  │
│                                                            │
│  1.  ⚡ Groq        FREE   llama-3.1-70b   ~500 tok/s     │
│          │  ✗ rate limit or no key                         │
│          ▼                                                  │
│  2.  🔷 Gemini      FREE   gemini-1.5-flash ~150 tok/s    │
│          │  ✗ quota or no key                              │
│          ▼                                                  │
│  3.  🟣 Anthropic  PAID   claude-haiku     ~80 tok/s      │
│          │  ✗ no key                                       │
│          ▼                                                  │
│  4.  🔧 Template   FREE   pure Python      instant        │
│         (always works — builds from MCP data)              │
└────────────────────────────────────────────────────────────┘
```

The waterfall status is shown live in the top-right of the UI. Green = success. Red = failed/not configured. The first provider that succeeds is used — the rest are not called.

---

## Confidence Scoring

Every response includes a confidence score built from four signals:

| Signal | Weight | Measures |
|---|---|---|
| Intent | 25% | Did the AI understand the request correctly? |
| Memory (RAG) | 20% | How well were session preferences recalled? |
| Booking (GDS) | 35% | Is the itinerary actually bookable? |
| Accuracy | 20% | Did the AI invent any facts? |

**Threshold: 85%** — below this, the engine retries up to 3 times. After 3 failed attempts, it hands off to a human specialist.

---

## Built by

**Deepak Ingwale & Mahima Verma**  
TCS Travel, Transport & Hospitality Practice  
VoyageAI PoC · 2024

---

*For issues, check the Troubleshooting section above or raise with the team.*
