"""
MCP Relevance Scorer
Scores each MCP server's relevance to the current query (0.0–1.0)
and builds the parameter payload for each server call.
"""
import re
import json
from datetime import datetime, timedelta
from rag.memory_store import memory_store


class MCPRelevanceScorer:
    """
    Keyword-based relevance scoring for MCP tool selection.
    Servers scoring above threshold (default 0.65) are invoked.
    """

    KEYWORD_MAP = {
        "flights":     ["flight","fly","depart","arrive","airline","airport","seat","ticket","direct"],
        "hotels":      ["hotel","stay","room","night","check.in","resort","accommodation","pool","property"],
        "cars":        ["car","drive","transfer","taxi","rental","pickup","vehicle","shuttle"],
        "weather":     ["weather","temperature","rain","climate","forecast","pack","sunny","cold","warm"],
        "maps":        ["distance","far","route","walk","how long","near","map","km","drive time"],
        "currency":    ["currency","exchange","rate","euro","dollar","convert","money","budget","cost"],
        "visa":        ["visa","passport","entry","permit","document","customs","requirement"],
        "experiences": ["tour","activity","visit","attraction","show","food","sightseeing","experience","things to do"],
        "customer":    [],   # invoked directly when customer_id known
        "loyalty":     [],   # invoked after customer is resolved
        "ancillaries": [],   # invoked after flight+hotel selected
    }

    # These are always included for travel queries
    ALWAYS_INCLUDE = {"flights", "hotels"}

    def score_all(self, text: str, threshold: float = 0.65) -> dict[str, float]:
        """Return relevance score per server, filtered by threshold."""
        text_lower = text.lower()
        scores = {}
        for server, keywords in self.KEYWORD_MAP.items():
            if server in self.ALWAYS_INCLUDE:
                scores[server] = 0.80   # baseline
                continue
            if not keywords:
                continue    # customer/loyalty/ancillaries handled separately
            hits = sum(1 for kw in keywords if re.search(kw, text_lower))
            raw  = min(1.0, (hits / len(keywords)) * 3.5)
            if raw >= threshold:
                scores[server] = round(raw, 2)

        return scores

    def build_params(self, text: str, session_id: str) -> dict[str, dict]:
        """Build MCP call parameters from query text and session entities."""
        entities = memory_store.retrieve_all_entities(session_id)

        guests   = self._extract_int(text, r"(\d+)\s*(?:people|guests|adults|passengers|of\s+us)", 2)
        budget   = self._extract_int(text, r"[£$€](\d[\d,]*)", 3000, strip_commas=True)
        nights   = self._extract_int(text, r"(\d+)\s*nights?", 7)
        children = self._extract_int(text, r"(\d+)\s*(?:child(?:ren)?|kids?)", 0)
        adults   = max(1, guests - children)

        dest     = entities.get("city_code", "LIS")
        check_in = entities.get("departure_date",
                               (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d"))
        check_out= entities.get("return_date",
                               (datetime.now() + timedelta(days=60 + nights)).strftime("%Y-%m-%d"))
        month    = int(check_in.split("-")[1])

        return {
            "flights": {
                "origin": "LHR", "destination": dest,
                "date": check_in, "adults": guests,
                "direct_only": "direct" in text.lower(),
            },
            "hotels": {
                "city": dest, "check_in": check_in, "check_out": check_out,
                "guests": guests, "rooms": max(1, guests // 2),
                "pool": "pool" in text.lower() or month in (6,7,8),
                "family_rooms": children > 0,
            },
            "cars":      {"airport": dest, "guests": guests, "days": nights},
            "weather":   {"city": dest, "month": month},
            "maps":      {"origin": f"{dest}_AIRPORT", "destination": "CITY_CENTRE"},
            "currency":  {"base": "GBP", "target": "EUR", "amount": budget},
            "visa":      {
                "passport_country":   entities.get("passport_country", "GB"),
                "destination_country":entities.get("country_code", "PT"),
                "duration_days":      nights,
                "purpose":            entities.get("travel_style", "leisure"),
                "profile": {
                    "travel_style":       entities.get("travel_style", "leisure"),
                    "adults_in_family":   entities.get("adults", 2),
                    "children_in_family": entities.get("children", 0),
                },
            },
            "experiences": {
                "city": dest, "guests": guests,
                "interests": self._extract_interests(text, entities),
            },
        }

    def summarise_mcp(self, mcp_data: dict) -> str:
        """Compact MCP data to fit in LLM context window."""
        lines = []
        for name, data in mcp_data.items():
            conf  = data.get("confidence", 0)
            inner = data.get("data", {})
            lines.append(f"\n--- {name.upper()} MCP (confidence:{conf:.0%}) ---")
            if isinstance(inner, dict):
                for k, v in list(inner.items())[:6]:
                    if isinstance(v, list):
                        lines.append(f"  {k}: {json.dumps(v[:3])}")
                    elif v is not None:
                        lines.append(f"  {k}: {json.dumps(v)}")
        return "\n".join(lines)

    # ── helpers ──────────────────────────────────────────────
    def _extract_int(self, text: str, pattern: str,
                     default: int, strip_commas: bool = False) -> int:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return default
        val = m.group(1).replace(",", "") if strip_commas else m.group(1)
        try:
            return int(val)
        except ValueError:
            return default

    def _extract_interests(self, text: str, entities: dict) -> list:
        tags  = entities.get("interests", [])
        kws   = ["beach", "culture", "food", "adventure", "family",
                 "romance", "ski", "diving", "hiking", "wine"]
        found = [kw for kw in kws if kw in text.lower()]
        return list(set(list(tags) + found))[:5]
