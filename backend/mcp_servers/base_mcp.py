"""Base MCP Server — all domain servers inherit from this."""
import time
from abc import ABC, abstractmethod
from typing import Any
from cachetools import TTLCache
from config import Config


class BaseMCP(ABC):
    """Standardised MCP tool interface with integrated logging."""

    def __init__(self, ttl: int = 300):
        self.name    = self.__class__.__name__
        self._cache  = TTLCache(maxsize=256, ttl=ttl)
        self.latency = 0.0

        # Each MCP gets its own named logger
        from core.logging_config import get_logger
        # e.g. FlightMCP → voyageai.mcp.FlightMCP
        self._log = get_logger(f"mcp.{self.name}")

    def call(self, params: dict) -> dict:
        """Public call — adds caching, latency tracking, logging, confidence."""
        key    = str(sorted(params.items()))
        cached = key in self._cache
        t0     = time.perf_counter()

        if cached:
            result = {**self._cache[key], "cached": True}
            self._log.debug("Cache hit", extra={
                "server": self.name, "params_key": key[:60]
            })
            return result

        try:
            result = self._fetch(params)
            blocked = self._strict_live_check(result)
            if blocked:
                result = blocked
            else:
                result["confidence"] = self._score_confidence(result)
                result["source"]     = result.get("source", self.name)
                result["cached"]     = False
                self._cache[key]     = result
        except Exception as e:
            self.latency = round((time.perf_counter() - t0) * 1000, 1)
            self._log.error("MCP fetch failed: %s", e, exc_info=True, extra={
                "server": self.name, "params": str(params)[:200]
            })
            result = self._fallback(params, str(e))

        self.latency = round((time.perf_counter() - t0) * 1000, 1)

        src  = result.get("data", {})
        source_label = (
            src.get("source")
            if isinstance(src, dict) and src.get("source")
            else result.get("source", "?")
        )
        conf = result.get("confidence", 0)

        self._log.info("MCP call", extra={
            "server":     self.name,
            "source":     source_label,
            "confidence": round(conf, 2),
            "latency_ms": self.latency,
            "cached":     False,
            "params":     {k: v for k, v in params.items()
                           if k not in ("profile","preferences")},
        })
        self._log.info("MCP response", extra={
            "server":      self.name,
            "status":      result.get("status", "ok" if not result.get("error") else "error"),
            "source":      source_label,
            "confidence":  round(conf, 2),
            "error":       result.get("error", ""),
            "fallback":    bool(result.get("fallback", False)),
            "cached":      bool(result.get("cached", False)),
            "response":    result,
        })

        return result

    @abstractmethod
    def _fetch(self, params: dict) -> dict: ...

    def _fallback(self, params: dict, error: str) -> dict:
        return {"error": error, "confidence": 0.0,
                "source": self.name, "fallback": True, "data": {}}

    def _strict_live_check(self, result: dict) -> dict | None:
        if not Config.REQUIRE_LIVE_TRAVEL_DATA:
            return None
        server_key = self.name.replace("MCP", "").lower()
        aliases = {
            "flight": "flights",
            "hotel": "hotels",
            "experience": "experiences",
            "ancillary": "ancillaries",
        }
        required_key = aliases.get(server_key, server_key)
        if required_key not in Config.REQUIRED_LIVE_MCP_SERVERS:
            return None
        data = result.get("data", {}) if isinstance(result, dict) else {}
        source = str(data.get("source") or result.get("source") or "").lower()
        if any(marker in source for marker in Config.LIVE_SOURCE_MARKERS):
            return None
        provider_diagnostics = result.get("provider_diagnostics", {})
        return {
            "error": (
                f"{required_key} requires live provider data, but received "
                f"{source or 'no source'} data."
            ),
            "status": "data_unavailable",
            "confidence": 0.0,
            "source": self.name,
            "fallback": False,
            "data": {},
            "required_provider": required_key,
            "provider_diagnostics": provider_diagnostics,
        }

    def _score_confidence(self, result: dict) -> float:
        if result.get("error"): return 0.0
        if result.get("data"):  return 0.85
        return 0.5

    def _jitter(self, base: float, pct: float = 0.10) -> float:
        import random
        return round(base * (1 + random.uniform(-pct, pct)), 2)
