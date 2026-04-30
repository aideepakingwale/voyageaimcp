"""Layer 3 — Action Guardrail: final gate before GDS transaction."""
import re, json
from config import Config
from .types import GuardrailResult


class ActionGuardrail:
    """
    Final gate before any booking system is touched:
    - Hard block if PCI card data in LLM context
    - Confidence threshold gate (85%)
    - Human confirmation for high-value bookings (>£1,000)
    """

    def gate(self, llm_output: dict, confidence: float, session: dict) -> GuardrailResult:
        # Hard block — cannot be overridden
        if not self._no_pci_data(llm_output):
            return GuardrailResult(
                passed=False, layer="L3_ACTION",
                reason="PCI payment data detected in LLM context — hard block",
                action="hard_block",
            )

        # Confidence threshold
        from core.guardrail_config_cache import gcfg
        if not gcfg._built: gcfg.build()
        confidence_threshold = gcfg.threshold("CONFIDENCE_THRESHOLD", 0.72)
        high_value_threshold = gcfg.threshold("HIGH_VALUE_THRESHOLD", 1000.0)
        if confidence < confidence_threshold:
            return GuardrailResult(
                passed=False, layer="L3_ACTION",
                reason=f"Confidence {confidence:.0%} below {Config.CONFIDENCE_THRESHOLD:.0%} threshold",
                action="retry",
            )

        # High-value human confirmation
        total = float(llm_output.get("total_cost_gbp", 0))
        if total > high_value_threshold:
            return GuardrailResult(
                passed=False, layer="L3_ACTION",
                reason=f"Booking value £{total:.0f} requires human confirmation",
                action="human_confirm",
                data={"amount": total, "summary": llm_output.get("summary", "")},
            )

        return GuardrailResult(passed=True, layer="L3_ACTION", action="proceed")

    def _no_pci_data(self, data: dict) -> bool:
        """Returns True if no payment card data detected."""
        text = json.dumps(data).lower()
        patterns = [
            r"\b4[0-9]{12}(?:[0-9]{3})?\b",  # Visa
            r"\b5[1-5][0-9]{14}\b",            # Mastercard
            r"\bcvv\b", r"\bcvc\b",
            r"\bcard\s+number\b",
        ]
        return not any(re.search(p, text) for p in patterns)
