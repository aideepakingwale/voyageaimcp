"""
VoyageAI Guardrail Config Cache
=================================
Singleton built once at application startup from the guardrail_* DB tables.
Provides fast typed access to every guardrail setting.

All guardrail code reads from this cache — nothing is hardcoded in guard files.

Usage:
    from core.guardrail_config_cache import gcfg

    gcfg.threshold("CONFIDENCE_THRESHOLD")   → 0.72
    gcfg.threshold("FACTUAL_ACCURACY_MIN")   → 0.80
    gcfg.limit("MAX_INPUT_TOKENS")           → 512
    gcfg.is_skip_code("TAP")                 → True  (airline code)
    gcfg.is_skip_code("LHR")                 → False (valid airport — don't skip)
    gcfg.skip_codes()                        → frozenset of all skip codes
    gcfg.injection_patterns()                → list of compiled regex patterns
    gcfg.travel_signals()                    → list of signal strings by category
    gcfg.schema_rules()                      → list of field rule dicts
    gcfg.string("LLM_WATERFALL")             → '["groq","gemini","anthropic","template"]'
    gcfg.stats()                             → dict with counts and build time
"""
import logging
import re
import time
import json
from typing import Optional

log = logging.getLogger("voyageai.app")


class GuardrailConfigCache:
    """
    Startup singleton for all guardrail configuration.
    Primary source: guardrail_* SQLite tables.
    Fallback: hardcoded defaults (so the app works even before first DB load).
    """

    # ── Safe defaults (used when DB tables not yet populated) ────────────────
    _DEFAULTS = {
        "CONFIDENCE_THRESHOLD":    0.72,
        "FACTUAL_ACCURACY_MIN":    0.80,
        "PRICE_DRIFT_LIMIT":       1.50,
        "MAX_BUDGET_OVERSHOOT":    0.50,
        "MAX_INPUT_TOKENS":        512,
        "MAX_RETRY_ITERATIONS":    3,
        "HIGH_VALUE_THRESHOLD":    1000.0,
        "MIN_CONNECTION_MINUTES":  45,
        "SESSION_TTL_SECONDS":     1800,
        "GDS_SESSION_TIMEOUT":     600,
        "LLM_MAX_TOKENS":          2048,
        "LLM_TEMPERATURE":         0.1,
        "LLM_TIMEOUT_S":           20,
        "RAG_SIMILARITY_THRESHOLD":0.75,
    }

    _DEFAULT_SKIP_CODES = frozenset([
        # Minimal set — DB will have the full list
        "THE","AND","FOR","NOT","LLM","MCP","RAG","API","URL","PDF","VAT","TAX",
        "TAP","BAW","EZY","KLM","QTR","UAE","ETD","ITC","TAJ","OBR","STD","DBL",
        "UAE","KSA","USA","GBR","CHN","JPN","IND","PAK","THA","IDN","MYS","ZAF",
    ])

    _DEFAULT_INJECTION = [
        re.compile(r"ignore\s+(?:previous|all)\s+instructions?", re.I),
        re.compile(r"you\s+are\s+now",                           re.I),
        re.compile(r"pretend\s+you\s+are",                       re.I),
        re.compile(r"jailbreak",                                 re.I),
        re.compile(r"override\s+safety",                         re.I),
    ]

    _DEFAULT_TRAVEL_SIGNALS = [
        "flight","hotel","trip","travel","holiday","vacation","book","journey",
        "destination","airport","visa","passport","accommodation","budget",
        "change","update","modify","instead","different","dates","guests",
    ]

    def __init__(self):
        self._built      = False
        self._build_ms   = 0.0
        self._source     = "defaults"

        # Config values
        self._config: dict[str, any] = dict(self._DEFAULTS)

        # Skip codes (all codes that should NOT be validated as IATA airports)
        self._skip_codes: frozenset = self._DEFAULT_SKIP_CODES

        # Injection patterns (compiled regex)
        self._injection_patterns: list = list(self._DEFAULT_INJECTION)

        # Travel signals (strings)
        self._travel_signals: dict[str, list] = {
            "ALL": list(self._DEFAULT_TRAVEL_SIGNALS)
        }

        # Schema rules
        self._schema_rules: list[dict] = []

    def build(self) -> "GuardrailConfigCache":
        """Load from DB. Safe to call multiple times — subsequent calls are no-ops."""
        if self._built:
            return self
        t0 = time.perf_counter()
        try:
            if self._load_from_db():
                self._source = "database"
            else:
                self._source = "defaults"
        except Exception as e:
            log.warning("GuardrailConfigCache DB load failed, using defaults: %s", e)
            self._source = "defaults"
        finally:
            self._build_ms = round((time.perf_counter() - t0) * 1000, 1)
            self._built    = True

        log.info(
            "GuardrailConfigCache ready in %sms from %s — %d config, %d skip_codes, "
            "%d injection patterns, %d travel signals, %d schema rules",
            self._build_ms, self._source,
            len(self._config), len(self._skip_codes),
            len(self._injection_patterns),
            sum(len(v) for v in self._travel_signals.values()),
            len(self._schema_rules),
        )
        return self

    # ── DB load ───────────────────────────────────────────────────────────────

    def _load_from_db(self) -> bool:
        try:
            from pathlib import Path
            import sqlite3
            db_path = Path(__file__).parent.parent / "data" / "voyageai.db"
            if not db_path.exists():
                return False
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            # Check tables exist
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'guardrail_%'"
            )]
            if "guardrail_config" not in tables:
                conn.close()
                return False

            n_config = conn.execute("SELECT COUNT(*) FROM guardrail_config").fetchone()[0]
            if n_config == 0:
                conn.close()
                return False

            # Load config values
            self._config = dict(self._DEFAULTS)  # start with defaults
            for row in conn.execute("SELECT key,value,dtype FROM guardrail_config"):
                try:
                    if row["dtype"] == "float":
                        self._config[row["key"]] = float(row["value"])
                    elif row["dtype"] == "int":
                        self._config[row["key"]] = int(row["value"])
                    elif row["dtype"] == "bool":
                        self._config[row["key"]] = row["value"].lower() in ("1","true","yes")
                    else:
                        self._config[row["key"]] = row["value"]
                except (ValueError, TypeError):
                    pass  # keep default

            # Load skip codes
            skip = set()
            for row in conn.execute("SELECT code FROM guardrail_skip_codes"):
                skip.add(row["code"].upper())
            if skip:
                self._skip_codes = frozenset(skip)

            # Load injection patterns
            patterns = []
            for row in conn.execute(
                "SELECT pattern FROM guardrail_injection_patterns WHERE enabled=1"
            ):
                try:
                    patterns.append(re.compile(row["pattern"], re.IGNORECASE))
                except re.error:
                    pass
            if patterns:
                self._injection_patterns = patterns

            # Load travel signals by category
            signals: dict[str, list] = {}
            for row in conn.execute("SELECT signal, category FROM guardrail_travel_signals"):
                signals.setdefault(row["category"], []).append(row["signal"])
            signals["ALL"] = [s for lst in signals.values() for s in lst]
            if signals:
                self._travel_signals = signals

            # Load schema rules
            rules = []
            for row in conn.execute("SELECT * FROM guardrail_schema_rules"):
                rules.append(dict(row))
            if rules:
                self._schema_rules = rules

            conn.close()
            return True

        except Exception as e:
            log.debug("GuardrailConfigCache._load_from_db error: %s", e)
            return False

    # ── Public API ────────────────────────────────────────────────────────────

    def threshold(self, key: str, default: float = 0.8) -> float:
        """Get a float threshold/ratio config value."""
        v = self._config.get(key, default)
        return float(v) if v is not None else default

    def limit(self, key: str, default: int = 100) -> int:
        """Get an integer limit config value."""
        v = self._config.get(key, default)
        return int(v) if v is not None else default

    def string(self, key: str, default: str = "") -> str:
        """Get a string config value."""
        return str(self._config.get(key, default))

    def value(self, key: str, default=None):
        """Get any config value in its native type."""
        return self._config.get(key, default)

    def is_skip_code(self, code: str) -> bool:
        """
        True if this 3-letter code should NOT be validated as an IATA airport.
        Covers: English words, tech abbreviations, airline codes, hotel brands,
                room type codes, country abbreviations.
        """
        return code.upper() in self._skip_codes

    def skip_codes(self) -> frozenset:
        """Return the full set of codes to skip in IATA validation."""
        return self._skip_codes

    def injection_patterns(self) -> list:
        """Return compiled regex patterns for prompt injection detection."""
        return self._injection_patterns

    def travel_signals(self, category: str = "ALL") -> list:
        """Return travel domain signal strings for a given category."""
        return self._travel_signals.get(category,
               self._travel_signals.get("ALL", self._DEFAULT_TRAVEL_SIGNALS))

    def schema_rules(self) -> list[dict]:
        """Return all schema validation rules."""
        return self._schema_rules

    def reload(self) -> "GuardrailConfigCache":
        """Force a reload from DB (call after updating guardrail config tables)."""
        self._built = False
        return self.build()

    def stats(self) -> dict:
        return {
            "built":              self._built,
            "source":             self._source,
            "build_ms":           self._build_ms,
            "config_keys":        len(self._config),
            "skip_codes":         len(self._skip_codes),
            "injection_patterns": len(self._injection_patterns),
            "travel_signals":     sum(len(v) for v in self._travel_signals.values()),
            "schema_rules":       len(self._schema_rules),
        }


# ── Module-level singleton ────────────────────────────────────────────────────
gcfg = GuardrailConfigCache()
