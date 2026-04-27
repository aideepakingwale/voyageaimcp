"""VoyageAI Configuration"""
import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    # ── LLM Waterfall ─────────────────────────────────────
    GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL     = "llama-3.1-70b-versatile"
    GROQ_FALLBACK  = "mixtral-8x7b-32768"

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL   = "gemini-1.5-flash"
    GEMINI_PRO     = "gemini-1.5-pro"

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL   = "claude-haiku-4-5-20251001"

    LLM_WATERFALL  = ["groq", "gemini", "anthropic", "template"]
    LLM_MAX_TOKENS = 2048
    LLM_TEMPERATURE= 0.1
    LLM_TIMEOUT_S  = 20

    # ── Real-time data APIs ───────────────────────────────
    AMADEUS_CLIENT_ID  = os.getenv("AMADEUS_CLIENT_ID",  "")
    AMADEUS_CLIENT_SEC = os.getenv("AMADEUS_CLIENT_SECRET","")
    OPENWEATHER_API_KEY= os.getenv("OPENWEATHER_API_KEY", "")
    EXCHANGERATE_API_KEY=os.getenv("EXCHANGERATE_API_KEY","")
    ORS_API_KEY        = os.getenv("OPENROUTESERVICE_API_KEY","")

    # ── Guardrails ────────────────────────────────────────
    CONFIDENCE_THRESHOLD    = 0.85
    MAX_RETRY_ITERATIONS    = 3
    HIGH_VALUE_THRESHOLD    = 1000
    MAX_INPUT_TOKENS        = 512
    MIN_CONNECTION_MINUTES  = 45
    MAX_BUDGET_OVERSHOOT    = 0.10
    PRICE_DRIFT_LIMIT       = 0.05
    FACTUAL_ACCURACY_MIN    = 0.80

    # ── Session / RAG ─────────────────────────────────────
    RAG_SIMILARITY_THRESHOLD = 0.75
    SESSION_TTL_SECONDS      = 1800
    GDS_SESSION_TIMEOUT      = 600

    CORS_ORIGINS = ["*"]
