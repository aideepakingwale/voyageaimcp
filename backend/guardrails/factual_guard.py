"""
Layer 2b — Factual Claim Verification
All validation data loaded from DB via GuardrailConfigCache.
No hardcoded skip lists — manage everything via data/load_guardrail_config.py.
"""
import json
import re
import logging
from config import Config
from .types import GuardrailResult

log = logging.getLogger("voyageai.guardrails")


def _get_ref():
    from core.reference_cache import ref
    if not ref._built: ref.build()
    return ref

def _get_gcfg():
    from core.guardrail_config_cache import gcfg
    if not gcfg._built: gcfg.build()
    return gcfg


class FactualGuardrail:
    """
    Cross-checks LLM output against reference data:
      - IATA codes validated against ReferenceCache (DB-backed, 504 airports)
      - Skip codes loaded from guardrail_skip_codes DB table
      - Price drift threshold from guardrail_config DB table
    """

    def verify(self, llm_output: dict, mcp_data: dict) -> GuardrailResult:
        ref      = _get_ref()
        gcfg     = _get_gcfg()
        failures = []
        checks   = 0

        # ── IATA code validation ──────────────────────────────────────────────
        for code in self._extract_candidate_codes(llm_output, gcfg):
            if not ref.should_validate_as_iata(code):
                continue
            checks += 1
            if not ref.is_airport(code):
                failures.append(f"Unknown IATA code: {code}")
                log.debug("Unknown IATA: %s", code)

        # ── Price drift vs MCP ────────────────────────────────────────────────
        if mcp_data:
            issue = self._check_flight_price(llm_output, mcp_data, gcfg)
            if issue:
                checks += 1
                failures.append(issue)

        if checks == 0:
            return GuardrailResult(
                layer="L2b_FACTUAL", passed=True, reason="ok",
                action="proceed", failed_fields=[], data={"accuracy": 1.0}
            )

        accuracy_min = gcfg.threshold("FACTUAL_ACCURACY_MIN", 0.80)
        accuracy     = max(0.0, 1.0 - len(failures) / checks)
        passed       = accuracy >= accuracy_min

        return GuardrailResult(
            layer         = "L2b_FACTUAL",
            passed        = passed,
            reason        = (f"Factual accuracy {accuracy:.0%} below "
                             f"{accuracy_min:.0%}. Issues: {failures}") if not passed else "ok",
            action        = "proceed" if passed else "retry",
            failed_fields = failures,
            data          = {"accuracy": round(accuracy, 2)},
        )

    def _extract_candidate_codes(self, output: dict, gcfg) -> list[str]:
        """
        Extract 3-letter uppercase tokens from airport-context fields only.
        Filters against the DB-managed skip code list.
        """
        text = json.dumps(output, default=str)

        # Only check codes in airport-relevant JSON fields
        airport_context = re.findall(
            r'"(?:origin|destination|iata|city_code|airport|from|to)"\s*:\s*"([A-Z]{3})"',
            text
        )
        if airport_context:
            candidates = list(set(airport_context))
        else:
            candidates = re.findall(r'\b([A-Z]{3})\b', text)

        # Filter: remove DB-managed skip codes + reference cache non-airports
        skip_codes = gcfg.skip_codes()
        ref        = _get_ref()
        return [
            c for c in candidates
            if c not in skip_codes and ref.should_validate_as_iata(c)
        ]

    def _check_flight_price(self, output: dict, mcp_data: dict, gcfg) -> str | None:
        try:
            llm_flights = output.get("recommendations", {}).get("flights", [])
            mcp_flights = (mcp_data.get("flights", {})
                               .get("data", {}).get("flights", []))
            if not llm_flights or not mcp_flights:
                return None

            mcp_min = min(f.get("price_gbp", 99999) for f in mcp_flights)
            mcp_max = max(f.get("price_gbp", 0)     for f in mcp_flights)

            # Drift limit from DB config (default 1.5 = ±150%)
            drift = gcfg.threshold("PRICE_DRIFT_LIMIT", 1.5)

            for flight in llm_flights[:2]:
                price = flight.get("price_gbp") or flight.get("price", 0)
                if not price:
                    continue
                if not (mcp_min * (1 - drift) <= float(price) <= mcp_max * (1 + drift)):
                    return (f"Flight price £{price} outside "
                            f"MCP range £{mcp_min:.0f}–£{mcp_max:.0f}")
        except Exception:
            pass
        return None
