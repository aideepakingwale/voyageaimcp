"""Layer 2b — Factual Claim Verification."""
from config import Config
from .types  import GuardrailResult


def _build_valid_iata() -> set:
    """
    Build the full valid IATA set from the MCP scorer's DEST_MAP
    plus known departure airports. Single source of truth.
    """
    try:
        from reasoning.mcp_scorer import DEST_MAP, CODE_TO_COUNTRY
        codes = set(DEST_MAP.values()) | set(CODE_TO_COUNTRY.keys())
    except Exception:
        codes = set()

    # Add departure airports not in DEST_MAP
    codes.update({
        # UK & Ireland
        "LHR","LGW","STN","LTN","LCY","MAN","BHX","EDI","GLA","BRS",
        "NCL","LBA","LPL","BFS","CWL","SOU","EMA","BOH","EXT","NWI",
        "ABZ","INV","JER","GCI","DUB","ORK","SNN",
        # Europe departures
        "AMS","CDG","ORY","FRA","MUC","BER","MAD","BCN","SVQ","AGP",
        "VLC","BIO","ALC","PMI","IBZ","TFS","LPA","ACE","FUE","LPA",
        "FCO","MXP","VCE","PSA","NAP","PMO","CTA","BRI","LIS","OPO",
        "FAO","FNC","ATH","SKG","HER","CFU","RHO","JTR","JMK","ZTH",
        "KGS","DBV","SPU","ZRH","GVA","VIE","BRU","LUX","CPH","ARN",
        "OSL","HEL","KEF","PRG","WAW","BUD","OTP","SOF","ZAG",
        # Middle East
        "DXB","AUH","SHJ","DOH","RUH","JED","KWI","MCT","AMM","BEY",
        "TLV","CAI","IST","ESB",
        # Asia Pacific
        "SIN","NRT","KIX","ITM","HKG","ICN","PEK","PVG","CAN","CTU",
        "BKK","HKT","CNX","USM","DPS","CGK","KUL","PEN","MNL","HAN",
        "SGN","PNH","RGN","CMB","MLE","KTM","DAC","KHI","LHE","ISB",
        "BOM","DEL","BLR","HYD","MAA","GOI","CCU","AMD","PNQ",
        "SYD","MEL","BNE","PER","ADL","AKL","WLG","CHC",
        # Africa
        "JNB","CPT","DUR","NBO","MBA","ZNZ","DAR","ADD","ACC","LOS",
        "ABV","CMN","RAK","TUN","ALG","KGL","MRU","SEZ","RUN",
        # Americas
        "JFK","LAX","ORD","MIA","SFO","BOS","IAD","DFW","ATL","IAH",
        "SEA","DEN","LAS","MCO","PHX","MSP","YYZ","YVR","YUL","YYC",
        "MEX","CUN","HAV","BOG","MDE","LIM","SCL","EZE","GIG","GRU",
        "BSB","CCS","UIO","LPB","ASU","MVD","PTY","SJO","GUA",
        # Caribbean / Pacific
        "BGI","KIN","POS","ANU","UVF","GND","NAS","GCM","PLS",
        "HNL","NAN","BOB","PPT","NOU",
    })
    return codes


# Build once at import time
VALID_IATA: set = _build_valid_iata()


class FactualGuardrail:
    """
    Cross-checks LLM claims against MCP-verified data:
      - IATA airport codes exist in our full validated set
      - Prices within ±30% of MCP quotes (when MCP data available)
    """

    def verify(self, llm_output: dict, mcp_data: dict) -> GuardrailResult:
        failures    = []
        checks_done = 0

        # ── Check 1: IATA codes ─────────────────────────────────
        iata_codes = self._extract_iata_codes(llm_output)
        for code in iata_codes:
            checks_done += 1
            if code.upper() not in VALID_IATA:
                failures.append(f"Unknown IATA code: {code}")

        # ── Check 2: Price drift vs MCP data ────────────────────
        if mcp_data:
            flight_check = self._check_flight_price(llm_output, mcp_data)
            if flight_check:
                checks_done += 1
                failures.append(flight_check)

        if checks_done == 0:
            return GuardrailResult(
                layer="L2b_FACTUAL", passed=True,
                reason="ok", action="proceed",
                failed_fields=[], data={"accuracy": 1.0},
            )

        accuracy = max(0.0, 1.0 - (len(failures) / checks_done))
        passed   = accuracy >= Config.FACTUAL_ACCURACY_MIN

        return GuardrailResult(
            layer="L2b_FACTUAL",
            passed=passed,
            reason=(f"Factual accuracy {accuracy:.0%} below "
                    f"{Config.FACTUAL_ACCURACY_MIN:.0%}. "
                    f"Issues: {failures}") if not passed else "ok",
            action="proceed" if passed else "retry",
            failed_fields=failures,
            data={"accuracy": round(accuracy, 2)},
        )

    def _extract_iata_codes(self, output: dict) -> list[str]:
        """Pull all 3-letter uppercase codes from the output."""
        import re, json
        text   = json.dumps(output, default=str)
        raw    = re.findall(r'\b([A-Z]{3})\b', text)
        # Filter to plausible airport codes (exclude common English words)
        SKIP   = {"THE","AND","FOR","NOT","BUT","YOU","HIS","HER","CAN",
                  "ALL","ARE","WAS","HAS","HAD","ITS","ONE","OUT","WHO",
                  "GET","GOT","SET","YES","NOW","OLD","NEW","OWN","USE",
                  "DAY","WAY","MAY","SAY","SEE","HOW","OUR","ANY","FAR",
                  "FEW","BIG","DID","CAR","END","JOB","LET","PUT","RUN",
                  "USD","GBP","EUR","GDP","API","URL","PDF","CSS","LLM",
                  "MCP","RAG","GDS","ETA","ATA","ETE","VIP","TBC","TBD",
                  "PRO","ADV","SUV","MPV","OPO","AGP"}
        return [c for c in raw if c not in SKIP]

    def _check_flight_price(self, output: dict, mcp_data: dict) -> str | None:
        """Return an issue string if flight price drifts >30% from MCP."""
        try:
            llm_flights = (output.get("recommendations", {})
                               .get("flights", []))
            mcp_flights = (mcp_data.get("flights", {})
                               .get("data", {})
                               .get("flights", []))
            if not llm_flights or not mcp_flights:
                return None

            mcp_min = min(f.get("price_gbp", 99999) for f in mcp_flights)
            mcp_max = max(f.get("price_gbp", 0)     for f in mcp_flights)

            for flight in llm_flights[:2]:
                llm_price = (flight.get("price_gbp")
                             or flight.get("price", 0))
                if not llm_price:
                    continue
                low  = mcp_min * (1 - Config.PRICE_DRIFT_LIMIT)
                high = mcp_max * (1 + Config.PRICE_DRIFT_LIMIT)
                if not (low <= float(llm_price) <= high):
                    return (f"Flight price £{llm_price} outside "
                            f"MCP range £{mcp_min:.0f}–£{mcp_max:.0f}")
        except Exception:
            pass
        return None
