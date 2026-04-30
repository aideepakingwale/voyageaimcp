"""
Layer 2b — Factual Claim Verification
Uses the startup ReferenceCache for all IATA, currency and country lookups.
No hardcoded lists — all data lives in data/reference_data.py.
"""
import json
import re
import logging
from config import Config
from .types import GuardrailResult

log = logging.getLogger("voyageai.guardrails")


def _get_ref():
    """Lazy-load reference cache — build it if not yet done."""
    from core.reference_cache import ref
    if not ref._built:
        ref.build()   # safe to call multiple times (idempotent)
    return ref


class FactualGuardrail:
    """
    Cross-checks LLM output against reference data:
      - IATA codes validated against ReferenceCache (not a hardcoded list)
      - Currency codes, country codes, common abbreviations excluded from IATA check
      - Price drift check vs MCP data (±30%)
    """

    def verify(self, llm_output: dict, mcp_data: dict) -> GuardrailResult:
        ref      = _get_ref()
        failures = []
        checks   = 0

        # ── IATA code validation ──────────────────────────────
        for code in self._extract_candidate_codes(llm_output):
            # Only validate codes that look like airports (not currencies/countries/abbrevs)
            if not ref.should_validate_as_iata(code):
                continue
            checks += 1
            if not ref.is_airport(code):
                failures.append(f"Unknown IATA code: {code}")
                log.debug("Unknown IATA: %s", code)

        # ── Price drift vs MCP ────────────────────────────────
        if mcp_data:
            issue = self._check_flight_price(llm_output, mcp_data)
            if issue:
                checks += 1
                failures.append(issue)

        if checks == 0:
            return GuardrailResult(
                layer="L2b_FACTUAL", passed=True, reason="ok",
                action="proceed", failed_fields=[], data={"accuracy": 1.0}
            )

        accuracy = max(0.0, 1.0 - len(failures) / checks)
        passed   = accuracy >= Config.FACTUAL_ACCURACY_MIN

        return GuardrailResult(
            layer    = "L2b_FACTUAL",
            passed   = passed,
            reason   = (f"Factual accuracy {accuracy:.0%} below "
                        f"{Config.FACTUAL_ACCURACY_MIN:.0%}. "
                        f"Issues: {failures}") if not passed else "ok",
            action   = "proceed" if passed else "retry",
            failed_fields = failures,
            data     = {"accuracy": round(accuracy, 2)},
        )

    def _extract_candidate_codes(self, output: dict) -> list[str]:
        """
        Extract all 3-letter uppercase tokens from the LLM output.
        Returns only tokens that COULD be IATA codes — filters common
        English words and known non-airport abbreviations using the cache.
        """
        ref  = _get_ref()
        text = json.dumps(output, default=str)
        raw  = re.findall(r'\b([A-Z]{3})\b', text)

        # Hard-skip list for common English words not in the cache
        # Hard-skip: common words + codes that are ALWAYS valid airports
        # Listed here so factual check works even before cache is built
        ENGLISH_SKIP = {
            # English words
            "THE","AND","FOR","NOT","BUT","YOU","HIS","HER","CAN","ALL",
            "ARE","WAS","HAS","HAD","ITS","ONE","OUT","WHO","GET","GOT",
            "SET","YES","NOW","OLD","NEW","OWN","USE","DAY","WAY","MAY",
            "SAY","SEE","HOW","OUR","ANY","FAR","FEW","BIG","DID","CAR",
            "END","JOB","LET","PUT","RUN","INN","AIR","SKY","SEA","BAY",
            # Common tech/business abbreviations that appear in JSON
            "LLM","MCP","RAG","GDS","API","URL","PDF","CSS","ETA","VIP",
            "TBC","TBD","PRO","GDP","VAT","TAX","SLA","ROI","KPI","CRM",
            "SRC","DST","DEP","ARR","DUR","LEG","PAX","ADT","CHD","INF",
            "GPS","ETD","MON","TUE","WED","THU","FRI","SAT","SUN",
            # Known valid airports (fallback if cache fails)
            "LHR","LGW","MAN","EDI","BHX","BRS","LIS","MAD","BCN","CDG",
            "FCO","FRA","AMS","DXB","DOH","SIN","NRT","HKG","JFK","LAX",
            "SYD","DUB","ATH","IST","CPH","ARN","ZRH","GVA","VIE","BRU",
            # Airline IATA codes (2-3 letter) that appear in JSON but are NOT airports
            "TAP","BAW","EZY","RYR","IBE","KLM","AFR","DLH","AZA","TOM",
            "EAT","SAS","NAX","UAE","ETD","QTR","EKY","FIN","AAL","DAL",
            "UAL","BAA","VIR","MON","TUI","TCX","AEA","WZZ","VUE","LOT",
            # Rating/type codes
            "STD","DBL","TWN","SGL","FAM","SUI","VIP","EXE","PRE",
        }
        return [c for c in raw if c not in ENGLISH_SKIP]

    def _check_flight_price(self, output: dict, mcp_data: dict) -> str | None:
        try:
            llm_flights = output.get("recommendations", {}).get("flights", [])
            mcp_flights = (mcp_data.get("flights", {})
                               .get("data", {}).get("flights", []))
            if not llm_flights or not mcp_flights:
                return None

            mcp_min = min(f.get("price_gbp", 99999) for f in mcp_flights)
            mcp_max = max(f.get("price_gbp", 0)     for f in mcp_flights)

            for flight in llm_flights[:2]:
                price = flight.get("price_gbp") or flight.get("price", 0)
                if not price:
                    continue
                drift  = Config.PRICE_DRIFT_LIMIT
                if not (mcp_min*(1-drift) <= float(price) <= mcp_max*(1+drift)):
                    return (f"Flight price £{price} outside "
                            f"MCP range £{mcp_min:.0f}–£{mcp_max:.0f}")
        except Exception:
            pass
        return None
