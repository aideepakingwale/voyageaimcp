"""Layer 1 — Input Guardrail: sanitise before LLM sees it."""
import re
from config import Config
from .types import GuardrailResult


def _get_gcfg():
    from core.guardrail_config_cache import gcfg
    if not gcfg._built: gcfg.build()
    return gcfg


class InputGuardrail:
    """
    Protects against:
    - Prompt injection / jailbreaking attempts  (patterns from guardrail_injection_patterns DB table)
    - Context flooding / oversized inputs       (MAX_INPUT_TOKENS from guardrail_config DB table)
    - Out-of-scope non-travel queries           (signals from guardrail_travel_signals DB table)
    All validation data managed via data/load_guardrail_config.py.
    """

    def validate(self, text: str) -> GuardrailResult:
        gcfg  = _get_gcfg()
        words = text.split()

        # Check 1: length limit (from DB)
        max_tokens = gcfg.limit("MAX_INPUT_TOKENS", 512)
        if len(words) > max_tokens:
            return GuardrailResult(
                passed=False, layer="L1_INPUT",
                reason=f"Input too long ({len(words)} words, max {max_tokens})",
                action="reject",
            )

        # Check 2: injection detection (patterns from DB)
        for pattern in gcfg.injection_patterns():
            if pattern.search(text):
                return GuardrailResult(
                    passed=False, layer="L1_INPUT",
                    reason="Potential prompt injection detected",
                    action="reject",
                )

        # Check 3: travel domain relevance — only for medium-length inputs
        if len(words) > 3:
            text_lower = text.lower()
            signals    = gcfg.travel_signals("ALL")  # all categories from DB
            has_signal = any(re.search(sig, text_lower) for sig in signals)
            if not has_signal:
                return GuardrailResult(
                    passed=False, layer="L1_INPUT",
                    reason="Query appears to be outside the travel domain",
                    action="redirect",
                    data="I'm VoyageAI, your travel assistant. I can help with flights, hotels, transfers, and experiences. Where would you like to go?",
                )

        return GuardrailResult(passed=True, layer="L1_INPUT", action="proceed")
