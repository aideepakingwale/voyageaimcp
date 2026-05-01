"""
MCP Relevance Scorer
Scores each MCP server's relevance to the current query (0.0-1.0)
and builds the parameter payload for each server call.

Key fix: destination is extracted from the MESSAGE TEXT first,
falling back to session entities. This prevents always defaulting to LIS.
"""
import re
import json
import logging
from datetime import datetime, timedelta
from rag.memory_store import memory_store

log = logging.getLogger("voyageai.mcp")

# ── Destination extraction ────────────────────────────────────
# Maps destination name/alias → IATA city code
DEST_MAP = {
    # Iberian Peninsula
    "lisbon":"LIS","portugal":"LIS","porto":"OPO","algarve":"FAO","faro":"FAO",
    # Spain
    "barcelona":"BCN","madrid":"MAD","malaga":"AGP","tenerife":"TFS",
    "ibiza":"IBZ","mallorca":"PMI","majorca":"PMI","seville":"SVQ",
    "gran canaria":"LPA","lanzarote":"ACE","fuerteventura":"FUE",
    # France
    "paris":"CDG","nice":"NCE","lyon":"LYS","marseille":"MRS",
    # Italy
    "rome":"FCO","milan":"MXP","venice":"VCE","florence":"PSA",
    "naples":"NAP","sicily":"CTA","sardinia":"CAG","amalfi":"NAP",
    # Greece
    "athens":"ATH","santorini":"JTR","mykonos":"JMK","corfu":"CFU",
    "crete":"HER","rhodes":"RHO","thessaloniki":"SKG","zakynthos":"ZTH",
    # Eastern Europe
    "amsterdam":"AMS","brussels":"BRU","vienna":"VIE","zurich":"ZRH",
    "geneva":"GVA","prague":"PRG","budapest":"BUD","warsaw":"WAW",
    "munich":"MUC","berlin":"BER","frankfurt":"FRA","hamburg":"HAM",
    "dublin":"DUB","edinburgh":"EDI","stockholm":"ARN","oslo":"OSL",
    "copenhagen":"CPH","helsinki":"HEL","reykjavik":"KEF","iceland":"KEF",
    # Middle East & Africa
    "dubai":"DXB","abu dhabi":"AUH","doha":"DOH","riyadh":"RUH",
    "marrakech":"RAK","morocco":"CMN","casablanca":"CMN","cairo":"CAI",
    "cape town":"CPT","johannesburg":"JNB","nairobi":"NBO",
    "zanzibar":"ZNZ","mauritius":"MRU","seychelles":"SEZ","reunion":"RUN",
    # Asia
    "singapore":"SIN","tokyo":"NRT","osaka":"KIX","kyoto":"ITM",
    "bangkok":"BKK","phuket":"HKT","chiang mai":"CNX","koh samui":"USM",
    "bali":"DPS","jakarta":"CGK","kuala lumpur":"KUL","hong kong":"HKG",
    "seoul":"ICN","beijing":"PEK","shanghai":"PVG",
    "colombo":"CMB","sri lanka":"CMB","maldives":"MLE","male":"MLE",
    "delhi":"DEL","mumbai":"BOM","goa":"GOI","india":"DEL",
    # Americas
    "new york":"JFK","los angeles":"LAX","miami":"MIA","chicago":"ORD",
    "san francisco":"SFO","toronto":"YYZ","vancouver":"YVR",
    "cancun":"CUN","mexico city":"MEX","havana":"HAV",
    "rio de janeiro":"GIG","sao paulo":"GRU","buenos aires":"EZE",
    "bogota":"BOG","lima":"LIM","santiago":"SCL",
    # Pacific
    "sydney":"SYD","melbourne":"MEL","brisbane":"BNE","auckland":"AKL",
    "hawaii":"HNL","honolulu":"HNL","fiji":"NAN","bora bora":"BOB",
}

# City code → ISO country code
CODE_TO_COUNTRY = {
    "LIS":"PT","OPO":"PT","FAO":"PT","BCN":"ES","MAD":"ES","PMI":"ES",
    "TFS":"ES","AGP":"ES","IBZ":"ES","LPA":"ES","ACE":"ES","FCO":"IT",
    "MXP":"IT","VCE":"IT","PSA":"IT","NAP":"IT","CDG":"FR","NCE":"FR",
    "ATH":"GR","JTR":"GR","JMK":"GR","HER":"GR","CFU":"GR",
    "AMS":"NL","VIE":"AT","ZRH":"CH","GVA":"CH","DXB":"AE","AUH":"AE",
    "DOH":"QA","CMN":"MA","RAK":"MA","CAI":"EG","CPT":"ZA","JNB":"ZA",
    "NBO":"KE","MRU":"MU","SEZ":"SC","SIN":"SG","NRT":"JP","KIX":"JP",
    "BKK":"TH","HKT":"TH","DPS":"ID","CGK":"ID","KUL":"MY","HKG":"HK",
    "ICN":"KR","PEK":"CN","PVG":"CN","CMB":"LK","MLE":"MV","DEL":"IN",
    "BOM":"IN","GOI":"IN","JFK":"US","LAX":"US","MIA":"US","SFO":"US",
    "ORD":"US","YYZ":"CA","YVR":"CA","CUN":"MX","GIG":"BR","GRU":"BR",
    "SYD":"AU","MEL":"AU","AKL":"NZ","KEF":"IS","PRG":"CZ","BUD":"HU",
    "ARN":"SE","OSL":"NO","CPH":"DK","HEL":"FI","EDI":"GB","DUB":"IE",
}


def extract_destination(text: str, entities: dict) -> tuple[str, str]:
    """
    Extract (city_code, country_code) from message text.
    Priority:
      1. Destination after "to X" / "in X" / "trip to X" patterns
      2. Longest match scan of full text
      3. Session entities
      4. Default LIS
    """
    import re
    text_lower = text.lower()

    # Priority 1: Explicit destination patterns — "to X", "trip to X", "holiday in X"
    dest_patterns = [
        r"(?:trip|holiday|travel|fly|flight|going|visit|heading)\s+to\s+([a-z][a-z ]+?)(?:\s+for|\s+in\s+\d|\s+\d|,|\.|$)",
        r"to\s+([a-z][a-z ]+?)(?:\s+for|\s+in\s+\d|\s+\d|,|\.|$)",
        r"(?:in|visit(?:ing)?)\s+([a-z][a-z ]+?)(?:\s+for|\s+in\s+\d|\s+\d|,|\.|$)",
    ]
    for pattern in dest_patterns:
        m = re.search(pattern, text_lower)
        if m:
            candidate = m.group(1).strip()
            # Match against DEST_MAP (longest match)
            for name in sorted(DEST_MAP.keys(), key=len, reverse=True):
                if name in candidate or candidate in name:
                    code    = DEST_MAP[name]
                    country = CODE_TO_COUNTRY.get(code, code[:2])
                    return code, country

    # Priority 2: Scan full text (longest match first)
    for name in sorted(DEST_MAP.keys(), key=len, reverse=True):
        if name in text_lower:
            code    = DEST_MAP[name]
            country = CODE_TO_COUNTRY.get(code, code[:2])
            return code, country

    # Priority 3: Session entities
    city_code = entities.get("city_code", "LIS")
    country   = entities.get("country_code",
                  CODE_TO_COUNTRY.get(city_code, "PT"))
    return city_code, country


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
        "customer":    [],
        "loyalty":     [],
        "ancillaries": [],
    }

    ALWAYS_INCLUDE = {"flights", "hotels"}

    def score_all(self, text: str, threshold: float = 0.65) -> dict[str, float]:
        text_lower = text.lower()
        scores = {}
        for server, keywords in self.KEYWORD_MAP.items():
            if server in self.ALWAYS_INCLUDE:
                scores[server] = 0.80
                continue
            if not keywords:
                continue
            hits = sum(1 for kw in keywords if re.search(kw, text_lower))
            raw  = min(1.0, (hits / len(keywords)) * 3.5)
            if raw >= threshold:
                scores[server] = round(raw, 2)
        return scores

    def build_params(self, text: str, session_id: str,
                    origin_iata: str = None) -> dict[str, dict]:
        """
        Build MCP call parameters.
        - origin_iata: detected from user IP or entered by user (overrides default)
        - destination: extracted from message text using destination map
        """

        entities = memory_store.retrieve_all_entities(session_id)

        # ── Destination: entities WIN (pre-extracted by universal_extractor) ─
        # Priority: session entity → text extraction → resolver → fallback
        dest    = (entities.get("city_code")
                   or entities.get("destination_iata"))
        country = entities.get("country_code", "")

        if not dest or dest == "LIS":
            # Try text extraction as fallback
            text_dest, text_country = extract_destination(text, {})
            if text_dest and text_dest != "LIS":
                dest, country = text_dest, text_country
            else:
                try:
                    from reasoning.destination_resolver import resolve_destination
                    resolved = resolve_destination(text, entities)
                    if resolved.get("iata") and resolved.get("confidence", 0) >= 0.75:
                        dest    = resolved["iata"]
                        country = resolved.get("country_code", "")
                except Exception:
                    pass

        if not dest:
            # Try reference cache with any word in the text
            try:
                from core.reference_cache import ref as _r2
                if not _r2._built: _r2.build()
                for word in text.split():
                    w = word.strip(".,()").lower()
                    if len(w) >= 4:
                        _iata = _r2.city_to_iata(w)
                        if _iata:
                            dest    = _iata
                            country = (_r2.airport(_iata) or {}).get("country_code","")
                            break
            except Exception:
                pass
        if not dest:
            dest    = "LHR"  # absolute last resort
            country = "GB" 

        # ── Extract other params from text ─────────────────────
        # Guests/budget: entities first (from universal_extractor), then text
        guests   = (int(entities.get("guests", 0)) or
                    self._extract_int(text, r"(\d+)\s*(?:people|guests|adults|passengers|of\s+us)", 2))
        children = (int(entities.get("children", 0)) or
                    self._extract_int(text, r"(\d+)\s*(?:child(?:ren)?|kids?)", 0))
        adults   = (int(entities.get("adults", 0)) or max(1, guests - children))
        budget   = (int(entities.get("budget_gbp", 0)) or
                    self._extract_int(text, r"[£$€](\d[\d,]*)", 3000, strip_commas=True))
        nights   = (int(entities.get("nights", 0)) or
                    self._extract_int(text, r"(\d+)\s*nights?", 7))

        # Month from departure date or "in October" etc.
        month    = self._extract_month(text) or int(
            (entities.get("departure_date", f"{datetime.now().year}-08-01") or "").split("-")[1]
            if entities.get("departure_date") else "8"
        )
        # Dates: read from session entities (set by universal_extractor)
        _entity_date = entities.get("departure_date")
        _entity_nights = entities.get("nights")
        if _entity_nights:
            nights = int(_entity_nights)

        # Also check prompt text for "Departure: YYYY-MM-DD" (modification prompts)
        _dep_kw  = re.search(r"Departure:\s*(20\d\d-\d{2}-\d{2})", text, re.IGNORECASE)
        _iso_all = re.findall(r"20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])", text)
        _dur_kw  = re.search(r"Duration:\s*(\d+)\s*nights?", text, re.IGNORECASE)
        if _dur_kw: nights = int(_dur_kw.group(1))

        _prompt_date = (_dep_kw.group(1) if _dep_kw
                        else _iso_all[0] if _iso_all else None)

        # Entity date is already extracted and validated — use it
        check_in  = (_entity_date or _prompt_date or
                     (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d"))
        # Validate return_date entity — must be ISO format, not a month name like "August"
        _raw_return = entities.get("return_date","")
        _return_ok  = bool(_raw_return) and bool(re.match(r"20\d\d-\d{2}-\d{2}", str(_raw_return)))
        check_out   = (
            _raw_return if _return_ok else
            (datetime.strptime(check_in, "%Y-%m-%d") + timedelta(days=nights)).strftime("%Y-%m-%d")
        )

        passport  = entities.get("passport_country", "GB")

        # Use detected/user-provided origin, fallback to LHR
        # Origin: user-provided → session entity → extracted from text → default LHR
        origin = (
            (origin_iata or "").upper().strip()
            or (entities.get("origin_iata") or "")
            or _extract_origin_from_text(text)
            or "LHR"
        ).upper().strip()

        log.debug("MCP params built", extra={
            "origin": origin, "dest": dest, "country": country,
            "guests": guests, "nights": nights, "budget": budget, "month": month,
        })

        return {
            "flights": {
                "origin": origin, "destination": dest,
                "date": check_in, "adults": guests,
                "direct_only": "direct" in text.lower(),
            },
            "hotels": {
                "city": dest, "check_in": check_in, "check_out": check_out,
                "guests": guests, "rooms": max(1, guests // 2),
                "pool": any(w in text.lower() for w in ["pool","swimming","spa"]),
                "family_rooms": children > 0,
            },
            "cars":      {"airport": dest, "guests": guests, "days": nights},
            "weather":   {"city": dest, "departure_date": check_in, "month": month},
            "maps":      {"origin": f"{dest}_AIRPORT", "destination": "CITY_CENTRE"},
            "currency":  {"base": "GBP", "target": "EUR", "amount": budget},
            "visa": {
                "passport_country":    passport,
                "destination_country": country,
                "duration_days":       nights,
                "purpose":             entities.get("travel_style", "leisure"),
                "profile": {
                    "travel_style":       entities.get("travel_style", "leisure"),
                    "adults_in_family":   adults,
                    "children_in_family": children,
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
    def _extract_int(self, text, pattern, default, strip_commas=False):
        m = re.search(pattern, text, re.IGNORECASE)
        if not m: return default
        val = m.group(1).replace(",", "") if strip_commas else m.group(1)
        try: return int(val)
        except ValueError: return default

    def _extract_month(self, text):
        months = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
                  "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
                  "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
                  "sep":9,"oct":10,"nov":11,"dec":12}
        text_l = text.lower()
        for name, num in months.items():
            if name in text_l:
                return num
        return None

    def _extract_interests(self, text, entities):
        kws   = ["beach","culture","food","adventure","family","romance",
                 "ski","diving","hiking","wine","history","art","shopping"]
        found = [kw for kw in kws if kw in text.lower()]
        saved = entities.get("interests", [])
        return list(set(list(saved) + found))[:5]


def _extract_origin_from_text(text: str) -> str | None:
    """
    Extract departure/origin airport from natural language.
    Handles:
      "flying from Manchester to Seychelles"
      "departing BHX"
      "from London Heathrow"
      "MAN to DPS"  (direct IATA pair)
    """
    import re
    text_l = text.lower().strip()

    # Pattern 1: "X to Y" where X is a 3-letter IATA code
    m = re.search(r'\b([A-Z]{3})\s+to\s+[A-Z]{3}\b', text.upper())
    if m:
        return m.group(1)

    # Pattern 2: "flying/departing from X"
    m = re.search(
        r'(?:fly(?:ing)?|depart(?:ing)?|travel(?:l?ing)?|leaving?)\s+from\s+([a-z][a-z ]{1,25}?)(?:\s+to\b|,|\.|$)',
        text_l)
    if m:
        candidate = m.group(1).strip()
        iata = _lookup_origin(candidate)
        if iata:
            return iata

    # Pattern 3: "from X to Y"
    m = re.search(r'\bfrom\s+([a-z][a-z ]{1,25}?)\s+to\b', text_l)
    if m:
        candidate = m.group(1).strip()
        iata = _lookup_origin(candidate)
        if iata:
            return iata

    # Pattern 4: "departing X" (no "from")
    m = re.search(r'\bdepart(?:ing)?\s+([a-z][a-z ]{1,20}?)(?:\s|,|\.|$)', text_l)
    if m:
        candidate = m.group(1).strip()
        iata = _lookup_origin(candidate)
        if iata:
            return iata

    return None


def _lookup_origin(candidate: str) -> str | None:
    """Look up IATA from candidate string — direct or partial match."""
    if len(candidate) == 3 and candidate.isalpha():
        return candidate.upper()
    from core.geo_location import city_to_iata
    return city_to_iata(candidate)

