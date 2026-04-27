"""
VoyageAI LLM Waterfall
Tries providers in order: Groq → Gemini → Anthropic → Template
Each provider is tried once. On failure, moves to next.
Tracks provider health, latency, and cost per session.
"""
import time, json, re
from typing import Optional
from config import Config
from .base_provider      import LLMResponse
from .groq_provider      import GroqProvider
from .gemini_provider    import GeminiProvider
from .anthropic_provider import AnthropicProvider
from .template_provider  import TemplateProvider


class LLMWaterfall:
    """
    Zero-cost LLM routing strategy:
    1. Groq       — FREE, fastest (~500 tok/s)
    2. Gemini     — FREE, 15 req/min
    3. Anthropic  — PAID fallback (Haiku, ~$0.001/call)
    4. Template   — FREE, deterministic, always works
    """

    def __init__(self):
        self.providers = {
            "groq": GroqProvider(
                api_key        = Config.GROQ_API_KEY,
                model          = Config.GROQ_MODEL,
                fallback_model = Config.GROQ_FALLBACK,
            ),
            "gemini": GeminiProvider(
                api_key   = Config.GEMINI_API_KEY,
                model     = Config.GEMINI_MODEL,
                pro_model = Config.GEMINI_PRO,
            ),
            "anthropic": AnthropicProvider(
                api_key = Config.ANTHROPIC_API_KEY,
                model   = Config.ANTHROPIC_MODEL,
            ),
            "template": TemplateProvider(),
        }

        self.waterfall_order = Config.LLM_WATERFALL
        self.stats = {
            name: {
                "calls": 0, "successes": 0, "failures": 0,
                "total_cost": 0.0, "total_latency_ms": 0.0,
            }
            for name in self.providers
        }
        self._log_status()

        from core.logging_config import get_logger
        self._log = get_logger("llm.waterfall")

    # ── Main entry point ──────────────────────────────────
    def complete(self, system: str, user: str,
                 max_tokens: int = None,
                 temperature: float = None) -> LLMResponse:
        """Try each provider in order. Return first success."""
        max_tokens  = max_tokens  or Config.LLM_MAX_TOKENS
        temperature = temperature or Config.LLM_TEMPERATURE
        attempts    = []

        for pname in self.waterfall_order:
            provider = self.providers.get(pname)
            if not provider:
                continue

            t0 = time.time()
            try:
                resp = provider.complete(system, user, max_tokens, temperature)
            except Exception as e:
                resp = LLMResponse(success=False, provider=pname, error=str(e))

            resp.latency_ms = round((time.time() - t0) * 1000, 1)

            st = self.stats[pname]
            st["calls"]            += 1
            st["total_latency_ms"] += resp.latency_ms

            if resp.success:
                st["successes"]  += 1
                st["total_cost"] += resp.cost_usd
                attempts.append({"provider": pname, "ok": True,
                                  "ms": resp.latency_ms})
                resp.text     = self._clean_json(resp.text)
                resp.attempts = attempts
                if _HAS_LOGGER:
                    _log.info("LLM SUCCESS",
                              extra={
                                  "request_id":  get_request_id(),
                                  "provider":    pname,
                                  "model":       resp.model,
                                  "elapsed_ms":  resp.latency_ms,
                                  "input_tokens":resp.input_tokens,
                                  "output_tokens":resp.output_tokens,
                                  "cost_usd":    resp.cost_usd,
                                  "attempts":    len(attempts),
                              })
                return resp
            else:
                st["failures"] += 1
                attempts.append({"provider": pname, "ok": False,
                                  "error": resp.error[:80]})
                self._log.warning("LLM provider failed, trying next", extra={
                    "provider":   pname,
                    "error":      resp.error[:120],
                    "latency_ms": resp.latency_ms,
                })
                if _HAS_LOGGER:
                    _log.warning("LLM PROVIDER FAILED",
                                 extra={
                                     "request_id": get_request_id(),
                                     "provider":   pname,
                                     "elapsed_ms": resp.latency_ms,
                                     "error":      resp.error[:120],
                                 })

        # Should never reach here (template always works)
        return LLMResponse(
            success=False, provider="waterfall",
            error=f"All providers failed: {attempts}"
        )

    # ── Health / stats ────────────────────────────────────
    def get_status(self) -> dict:
        result = {}
        for name, prov in self.providers.items():
            st = self.stats[name]
            calls = max(st["calls"], 1)
            result[name] = {
                "available":      prov.is_available(),
                "free":           prov.free,
                "calls":          st["calls"],
                "success_rate":   round(st["successes"] / calls * 100, 1),
                "avg_latency_ms": round(st["total_latency_ms"] / calls),
                "total_cost_usd": round(st["total_cost"], 6),
            }
        return result

    # ── Internals ─────────────────────────────────────────
    def _log_status(self):
        print("\n╔══════════════════════════════════╗")
        print("║   VoyageAI  LLM Waterfall        ║")
        print("╠══════════════════════════════════╣")
        for name in self.waterfall_order:
            p     = self.providers[name]
            avail = p.is_available()
            cost  = "FREE" if p.free else "PAID"
            icon  = "✓" if avail else "✗"
            print(f"║  {icon} {name:<12} [{cost:<4}]        ║")
        print("╚══════════════════════════════════╝\n")

    def _clean_json(self, text: str) -> str:
        text = text.strip()
        # Strip markdown fences
        if "```" in text:
            parts = text.split("```")
            if len(parts) >= 3:
                text = parts[1]
                if text.startswith("json"):
                    text = text[4:]
        # Strip any leading/trailing non-JSON chars
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end+1]
        return text.strip()


# ── Singleton ─────────────────────────────────────────────
_waterfall: Optional[LLMWaterfall] = None

def get_waterfall() -> LLMWaterfall:
    global _waterfall
    if _waterfall is None:
        _waterfall = LLMWaterfall()
    return _waterfall
