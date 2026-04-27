"""Layer 1 — Input Guardrail: sanitise before LLM sees it."""
import re
from config import Config
from .types import GuardrailResult


class InputGuardrail:
    """
    Protects against:
    - Prompt injection / jailbreaking attempts
    - Context flooding (oversized inputs)
    - Out-of-scope (non-travel) queries
    """

    INJECTION_PATTERNS = [
        r"ignore\s+(?:previous|all)\s+instructions?",
        r"you\s+are\s+now",
        r"pretend\s+you\s+are",
        r"disregard\s+your",
        r"new\s+system\s+prompt",
        r"act\s+as\s+if",
        r"forget\s+everything",
        r"jailbreak",
        r"DAN\s+mode",
        r"override\s+safety",
    ]

    TRAVEL_SIGNALS = [
        "flight", "hotel", "trip", "travel", "holiday", "vacation",
        "book", "journey", "destination", "airport", "visa", "passport",
        "accommodation", "transfer", "car", "experience", "tour", "plan",
        "weather", "currency", "budget", "night", "check.?in", "check.?out",
        "family", "adult", "child", "passenger", "ticket", "itinerary",
        "resort", "cruise", "ski", "beach", "city", "abroad", "overseas",
    ]

    def validate(self, text: str) -> GuardrailResult:
        words = text.split()

        # Check 1: length limit
        if len(words) > Config.MAX_INPUT_TOKENS:
            return GuardrailResult(
                passed=False, layer="L1_INPUT",
                reason=f"Input too long ({len(words)} words, max {Config.MAX_INPUT_TOKENS})",
                action="reject",
            )

        # Check 2: injection detection
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return GuardrailResult(
                    passed=False, layer="L1_INPUT",
                    reason="Potential prompt injection detected",
                    action="reject",
                )

        # Check 3: travel domain relevance (only for longer inputs)
        if len(words) > 3:
            text_lower = text.lower()
            has_signal = any(re.search(p, text_lower) for p in self.TRAVEL_SIGNALS)
            if not has_signal:
                return GuardrailResult(
                    passed=False, layer="L1_INPUT",
                    reason="Query appears to be outside the travel domain",
                    action="redirect",
                    data="I'm VoyageAI, your travel assistant. I can help with flights, hotels, transfers, and experiences. Where would you like to go?",
                )

        return GuardrailResult(passed=True, layer="L1_INPUT", action="proceed")
