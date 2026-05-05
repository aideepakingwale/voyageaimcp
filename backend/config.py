"""VoyageAI Configuration"""
import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    # ── LLM Waterfall ─────────────────────────────────────
    GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL     = "llama-3.3-70b-versatile"
    GROQ_FALLBACK  = "llama-3.1-8b-instant"

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL   = "gemini-2.0-flash"
    GEMINI_PRO     = "gemini-1.5-flash"

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL   = "claude-haiku-4-5-20251001"

    ALLOW_TEMPLATE_PROVIDER = os.getenv("ALLOW_TEMPLATE_PROVIDER", "false").lower() == "true"
    LLM_WATERFALL  = [
        p.strip() for p in os.getenv("LLM_WATERFALL", "groq,gemini,anthropic").split(",")
        if p.strip()
    ]
    if ALLOW_TEMPLATE_PROVIDER and "template" not in LLM_WATERFALL:
        LLM_WATERFALL.append("template")
    LLM_MAX_TOKENS = 2048
    LLM_TEMPERATURE= 0.1
    LLM_TIMEOUT_S  = 20

    # ── Real-time data APIs ───────────────────────────────
    AMADEUS_CLIENT_ID  = os.getenv("AMADEUS_CLIENT_ID",  "")
    AMADEUS_CLIENT_SEC = os.getenv("AMADEUS_CLIENT_SECRET","")
    FLIGHT_DATA_PROVIDER = os.getenv("FLIGHT_DATA_PROVIDER", "duffel").strip().lower()
    HOTEL_DATA_PROVIDER = os.getenv("HOTEL_DATA_PROVIDER", "liteapi").strip().lower()
    DUFFEL_API_TOKEN = os.getenv("DUFFEL_API_TOKEN", "")
    DUFFEL_API_BASE = os.getenv("DUFFEL_API_BASE", "https://api.duffel.com")
    DUFFEL_API_VERSION = os.getenv("DUFFEL_API_VERSION", "v2")
    LITEAPI_API_KEY = os.getenv("LITEAPI_API_KEY", "")
    LITEAPI_API_BASE = os.getenv("LITEAPI_API_BASE", "https://api.liteapi.travel/v3.0")
    LITEAPI_GUEST_NATIONALITY = os.getenv("LITEAPI_GUEST_NATIONALITY", "GB")
    BOOKING_API_TOKEN = os.getenv("BOOKING_API_TOKEN", "")
    BOOKING_AFFILIATE_ID = os.getenv("BOOKING_AFFILIATE_ID", "")
    BOOKING_API_BASE = os.getenv("BOOKING_API_BASE", "https://demandapi-sandbox.booking.com/3.1")
    BOOKING_BOOKER_COUNTRY = os.getenv("BOOKING_BOOKER_COUNTRY", "gb")
    BOOKING_BOOKER_PLATFORM = os.getenv("BOOKING_BOOKER_PLATFORM", "desktop")
    OPENWEATHER_API_KEY= os.getenv("OPENWEATHER_API_KEY", "")
    EXCHANGERATE_API_KEY=os.getenv("EXCHANGERATE_API_KEY","")
    ORS_API_KEY        = os.getenv("OPENROUTESERVICE_API_KEY","")

    # ── Guardrails ────────────────────────────────────────
    CONFIDENCE_THRESHOLD    = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
    MAX_RETRY_ITERATIONS    = 3
    HIGH_VALUE_THRESHOLD    = 1000
    MAX_INPUT_TOKENS        = 512
    MIN_CONNECTION_MINUTES  = 45
    MAX_BUDGET_OVERSHOOT    = 0.10
    PRICE_DRIFT_LIMIT       = 0.05
    FACTUAL_ACCURACY_MIN    = 0.80

    # -- Data integrity -----------------------------------------------
    REQUIRE_LIVE_TRAVEL_DATA = os.getenv("REQUIRE_LIVE_TRAVEL_DATA", "true").lower() != "false"
    REQUIRED_LIVE_MCP_SERVERS = {
        s.strip() for s in os.getenv(
            "REQUIRED_LIVE_MCP_SERVERS", "flights,hotels,currency,weather"
        ).split(",") if s.strip()
    }
    LIVE_SOURCE_MARKERS = ("live", "api")

    # -- Session / RAG -------------------------------------
    RAG_SIMILARITY_THRESHOLD = 0.75
    SESSION_TTL_SECONDS      = 1800
    GDS_SESSION_TIMEOUT      = 600

    CORS_ORIGINS = ["*"]

    # ── Logging ──────────────────────────────────────────
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')  # INFO | DEBUG
