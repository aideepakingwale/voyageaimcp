"""Base MCP Server — all domain servers inherit from this."""
import time
import random
from abc import ABC, abstractmethod
from typing import Any
from cachetools import TTLCache


class BaseMCP(ABC):
    """Standardised MCP tool interface."""

    def __init__(self, ttl: int = 300):
        self.name    = self.__class__.__name__
        self._cache  = TTLCache(maxsize=256, ttl=ttl)
        self.latency = 0.0          # last call latency ms

    def call(self, params: dict) -> dict:
        """Public call — adds caching, latency tracking, confidence."""
        key = str(sorted(params.items()))
        if key in self._cache:
            return {**self._cache[key], "cached": True}

        t0 = time.time()
        try:
            result = self._fetch(params)
            result["confidence"] = self._score_confidence(result)
            result["source"]     = self.name
            result["cached"]     = False
            self._cache[key] = result
        except Exception as e:
            result = self._fallback(params, str(e))

        self.latency = (time.time() - t0) * 1000
        return result

    @abstractmethod
    def _fetch(self, params: dict) -> dict:
        """Live data fetch — implement per domain."""

    def _fallback(self, params: dict, error: str) -> dict:
        """Return structured mock data on API failure."""
        return {"error": error, "confidence": 0.0,
                "source": self.name, "fallback": True, "data": {}}

    def _score_confidence(self, result: dict) -> float:
        """Base confidence — subclasses override with domain logic."""
        if result.get("error"):
            return 0.0
        if result.get("data"):
            return 0.85
        return 0.5

    def _jitter(self, base: float, pct: float = 0.10) -> float:
        """Add ±pct noise to a value (simulates live price drift)."""
        return round(base * (1 + random.uniform(-pct, pct)), 2)
