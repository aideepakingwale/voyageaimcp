"""
VoyageAI Universal Parameter Extractor
=======================================
Runs on EVERY user message to extract any travel parameters present.
Called BEFORE intent classification so all downstream components
(MCP scorer, reasoning engine, template provider) get correct values.

What it extracts from any message:
  destination  → IATA code + city name
  dates        → departure_date (YYYY-MM-DD), nights, return_date
  guests       → total, adults, children
  budget       → GBP value
  preferences  → direct flights, hotel stars, pool, cabin class

Uses:
  1. LLM (Groq/Gemini) — best accuracy, understands "next Christmas", "for 3 of us"
  2. Hybrid fallback — regex + holiday calendar + city lookup
"""
import re
import json
import logging
from datetime import datetime, timedelta

log = logging.getLogger("voyageai.reasoning")

_TODAY = datetime.now()


# ── LLM extraction prompt ──────────────────────────────────────

EXTRACT_SYSTEM = f"""You are a travel parameter extractor. Today is {_TODAY.strftime('%Y-%m-%d')}.

Extract ALL travel parameters from the user message and conversation.
Return ONLY a JSON object — no markdown, no explanation.

Rules:
- Convert relative dates to exact YYYY-MM-DD: "next Christmas" -> "{_TODAY.year if _TODAY.month < 12 else _TODAY.year+1}-12-25"
- "in October" -> "{_TODAY.year if _TODAY.month < 10 else _TODAY.year+1}-10-01"  
- "for X weeks" -> nights: X*7
- Extract ANY destination mentioned, even partial: "India" -> "DEL", "holy places India" -> "DEL" (nearest hub)
- If destination is a region, use the main airport: "India" -> "DEL", "Scottish Highlands" -> "INV"
- budget: extract any number preceded by £ $, or followed by pounds/budget/gbp
- Return null for any field not mentioned

Return this exact structure:
{{
  "destination": "city name or null",
  "destination_iata": "3-letter code or null",
  "destination_country": "country name or null",
  "departure_date": "YYYY-MM-DD or null",
  "nights": number_or_null,
  "return_date": "YYYY-MM-DD or null",
  "guests": number_or_null,
  "adults": number_or_null,
  "children": number_or_null,
  "budget_gbp": number_or_null,
  "min_hotel_stars": number_or_null,
  "direct_flight": true_false_or_null,
  "cabin_class": "ECONOMY/BUSINESS/FIRST or null",
  "pool": true_false_or_null,
  "origin_city": "departure city or null"
}}"""

EXTRACT_USER = """CURRENT PLAN (if any): {current_plan}

CONVERSATION HISTORY:
{history}

USER MESSAGE: "{message}"

Extract all travel parameters. Be thorough — get destination, dates, guests, budget."""


def extract_all_params(
    message: str,
    session_id: str,
    history: list = None,
    last_itinerary: dict = None,
) -> dict:
    """
    Extract all travel parameters from a message.
    Returns dict with any found values (None for missing).
    Also stores non-None values in session entities.
    """
    history = history or []

    # Try LLM first
    params = _llm_extract(message, history, last_itinerary)

    # Merge with regex fallback for anything LLM missed
    regex_params = _regex_extract(message)
    for key, val in regex_params.items():
        if params.get(key) is None and val is not None:
            params[key] = val

    # Resolve destination to IATA if we have a city but no IATA
    if params.get("destination") and not params.get("destination_iata"):
        iata = _resolve_iata(params["destination"])
        if iata:
            params["destination_iata"] = iata

    # Store in session entities
    _store_params(session_id, params)

    log.info("Parameters extracted", extra={
        "session":     session_id,
        "destination": params.get("destination"),
        "iata":        params.get("destination_iata"),
        "dep_date":    params.get("departure_date"),
        "nights":      params.get("nights"),
        "guests":      params.get("guests"),
        "budget":      params.get("budget_gbp"),
    })

    return params


def _llm_extract(message: str, history: list, last_itinerary) -> dict:
    """Use LLM to extract parameters from the message."""
    empty = {k: None for k in [
        "destination", "destination_iata", "destination_country",
        "departure_date", "nights", "return_date", "guests",
        "adults", "children", "budget_gbp", "min_hotel_stars",
        "direct_flight", "cabin_class", "pool", "origin_city",
    ]}

    # Build plan summary
    plan_summary = "(no existing plan)"
    if last_itinerary:
        intent = last_itinerary.get("intent", {})
        dates  = intent.get("dates", {})
        plan_summary = (
            f"Destination: {intent.get('destination')} ({intent.get('city_code')}), "
            f"Dates: {dates.get('departure_date')} to {dates.get('return_date')}, "
            f"Guests: {intent.get('guests')}, Budget: £{intent.get('budget_gbp')}"
        )

    # Format history
    history_str = "\n".join(
        f"[{t.get('role','user').upper()}]: {str(t.get('content',''))[:200]}"
        for t in history[-4:]
    ) if history else "(none)"

    try:
        from llm.waterfall import get_waterfall
        wf   = get_waterfall()
        resp = wf.complete(
            EXTRACT_SYSTEM,
            EXTRACT_USER.format(
                current_plan=plan_summary,
                history=history_str,
                message=message,
            ),
            max_tokens=400,
            temperature=0.05,   # Very low — we want deterministic extraction
        )
        if resp.success and resp.text:
            return _parse_extract_response(resp.text) or empty
    except Exception as e:
        log.debug("LLM extract error: %s", e)

    return empty


def _parse_extract_response(text: str) -> dict | None:
    """Parse LLM extraction response into a clean dict."""
    try:
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            text = parts[1] if len(parts) >= 3 else text
            if text.startswith("json"):
                text = text[4:]
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end+1]
        data = json.loads(text)

        # Normalise nulls
        for k, v in list(data.items()):
            if v in ("null", "none", "", "N/A", "n/a"):
                data[k] = None

        # Validate IATA
        if data.get("destination_iata"):
            iata = str(data["destination_iata"]).upper().strip()
            data["destination_iata"] = iata if re.match(r"^[A-Z]{3}$", iata) else None

        # Validate date
        if data.get("departure_date"):
            try:
                datetime.strptime(str(data["departure_date"]), "%Y-%m-%d")
            except ValueError:
                data["departure_date"] = None

        # Compute return_date if missing
        if data.get("departure_date") and data.get("nights") and not data.get("return_date"):
            try:
                dep = datetime.strptime(data["departure_date"], "%Y-%m-%d")
                data["return_date"] = (dep + timedelta(days=int(data["nights"]))).strftime("%Y-%m-%d")
            except Exception:
                pass

        return data
    except Exception as e:
        log.debug("Extract parse error: %s | text=%s", e, text[:80])
        return None


def _regex_extract(message: str) -> dict:
    """
    Regex-based extraction fallback.
    Handles the most common patterns reliably.
    """
    params = {}
    text   = message.lower()

    # ── Destination ───────────────────────────────────────────
    from reasoning.destination_resolver import resolve_destination

    # Try full text first
    dest_result = resolve_destination(message, {})
    if dest_result.get("iata") and dest_result.get("confidence", 0) >= 0.75:
        params["destination_iata"]     = dest_result["iata"]
        params["destination"]          = dest_result.get("city", "")
        params["destination_country"]  = dest_result.get("country", "")
    else:
        # Try each word/phrase in the message
        words = message.lower().split()
        for n in range(4, 0, -1):
            for i in range(len(words)-n+1):
                phrase = " ".join(words[i:i+n])
                r = resolve_destination(phrase, {})
                if r.get("iata") and r.get("confidence", 0) >= 0.80:
                    params["destination_iata"]    = r["iata"]
                    params["destination"]         = r.get("city", phrase.title())
                    params["destination_country"] = r.get("country", "")
                    break
            if params.get("destination_iata"):
                break

    # Country→destination mapping for "Spain", "India", "Japan" style
    COUNTRY_TO_HUB = {
        "spain":"MAD","france":"CDG","italy":"FCO","germany":"FRA","greece":"ATH",
        "portugal":"LIS","turkey":"IST","egypt":"CAI","thailand":"BKK","japan":"NRT",
        "china":"PEK","india":"DEL","indonesia":"CGK","malaysia":"KUL","singapore":"SIN",
        "australia":"SYD","new zealand":"AKL","canada":"YYZ","mexico":"MEX",
        "brazil":"GRU","argentina":"EZE","peru":"LIM","colombia":"BOG","chile":"SCL",
        "south africa":"JNB","kenya":"NBO","morocco":"CMN","nigeria":"LOS","ghana":"ACC",
        "uae":"DXB","saudi arabia":"RUH","qatar":"DOH","israel":"TLV","jordan":"AMM",
        "vietnam":"SGN","cambodia":"PNH","myanmar":"RGN","laos":"VTE","nepal":"KTM",
        "sri lanka":"CMB","maldives":"MLE","pakistan":"KHI","bangladesh":"DAC",
        "ireland":"DUB","netherlands":"AMS","belgium":"BRU","switzerland":"ZRH",
        "austria":"VIE","sweden":"ARN","norway":"OSL","denmark":"CPH","finland":"HEL",
        "iceland":"KEF","poland":"WAW","czech republic":"PRG","hungary":"BUD",
        "croatia":"ZAG","serbia":"BEG","romania":"OTP","bulgaria":"SOF",
    }
    if not params.get("destination_iata"):
        msg_l = message.lower()
        for country, iata in sorted(COUNTRY_TO_HUB.items(), key=lambda x: len(x[0]), reverse=True):
            if re.search(r'\b' + re.escape(country) + r'\b', msg_l):
                params["destination_iata"]    = iata
                params["destination"]         = country.title()
                params["destination_country"] = country.title()
                break

    # ── Dates ─────────────────────────────────────────────────
    from reasoning.llm_intent_extractor import resolve_natural_date, HOLIDAY_DATES
    date_result = resolve_natural_date(message)
    if date_result:
        if date_result.get("departure_date"):
            params["departure_date"] = date_result["departure_date"]
        if date_result.get("nights") and not params.get("nights"):
            params["nights"] = date_result["nights"]

    # ISO date
    iso_m = re.search(r"20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])", message)
    if iso_m and not params.get("departure_date"):
        params["departure_date"] = iso_m.group(0)

    # Month names
    MONTHS = {
        "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
        "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
        "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
        "sep":9,"oct":10,"nov":11,"dec":12,
    }
    if not params.get("departure_date"):
        # "in October", "next October", "for October"
        for name, num in sorted(MONTHS.items(), key=lambda x: len(x[0]), reverse=True):
            if name in text:
                year = _TODAY.year
                candidate = datetime(year, num, 1)
                if candidate < _TODAY:
                    candidate = datetime(year + 1, num, 1)
                # Try "15th October" style
                day_m = re.search(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+{name}|{name}\s+(\d{{1,2}})", text)
                if day_m:
                    day = int(day_m.group(1) or day_m.group(2))
                    try:
                        candidate = datetime(candidate.year, num, day)
                        if candidate < _TODAY:
                            candidate = datetime(candidate.year + 1, num, day)
                    except ValueError:
                        pass
                params["departure_date"] = candidate.strftime("%Y-%m-%d")
                break

    # Duration
    if not params.get("nights"):
        # "for X nights/days/weeks"
        n_m = re.search(r"for\s+(\d+)\s*(night|day|week)s?", text)
        if not n_m:
            n_m = re.search(r"(\d+)\s*(night|week)s?", text)
        if n_m:
            n = int(n_m.group(1))
            params["nights"] = n * 7 if "week" in n_m.group(2) else n

    # Compute return_date
    if params.get("departure_date") and params.get("nights") and not params.get("return_date"):
        try:
            dep = datetime.strptime(params["departure_date"], "%Y-%m-%d")
            params["return_date"] = (dep + timedelta(days=params["nights"])).strftime("%Y-%m-%d")
        except Exception:
            pass

    # ── Guests ────────────────────────────────────────────────
    adults_m   = re.search(r"(\d+)\s*adults?", text)
    children_m = re.search(r"(\d+)\s*(?:children|child|kids?)", text)
    people_m   = re.search(r"(\d+)\s*(?:people|guests|passengers|of us|in total)", text)
    family_m   = re.search(r"family of (\d+)", text)

    if adults_m:
        params["adults"]  = int(adults_m.group(1))
    if children_m:
        params["children"] = int(children_m.group(1))
    if adults_m and children_m:
        params["guests"] = params["adults"] + params["children"]
    elif people_m:
        params["guests"] = int(people_m.group(1))
    elif family_m:
        params["guests"] = int(family_m.group(1))

    # Solo
    if any(p in text for p in ["just me", "solo", "by myself", "on my own", "alone"]):
        params["guests"] = params.get("guests", 1)
        params["adults"] = 1
        params["children"] = 0

    # Couples
    if any(p in text for p in ["just the two of us", "couple", "two of us", "just us two"]):
        params.setdefault("guests",  2)
        params.setdefault("adults",  2)
        params.setdefault("children", 0)

    # ── Budget ────────────────────────────────────────────────
    budget_m = re.search(r"[£$](\d[\d,]*)", message)
    if not budget_m:
        budget_m = re.search(r"(\d[\d,]+)\s*(?:pounds?|gbp|budget)", text)
    if budget_m:
        params["budget_gbp"] = int(budget_m.group(1).replace(",", ""))

    # ── Preferences ───────────────────────────────────────────
    if re.search(r"(\d)\s*[\-\s]?star", text):
        m = re.search(r"(\d)\s*[\-\s]?star", text)
        params["min_hotel_stars"] = int(m.group(1))
    elif "luxury" in text or "5 star" in text or "five star" in text:
        params["min_hotel_stars"] = 5
    elif "budget" in text and "hotel" in text:
        params["min_hotel_stars"] = 2

    if re.search(r"direct\s+flight|non.?stop", text):
        params["direct_flight"] = True
    if re.search(r"business\s+class", text):
        params["cabin_class"] = "BUSINESS"
    elif re.search(r"first\s+class", text):
        params["cabin_class"] = "FIRST"
    if "pool" in text:
        params["pool"] = True

    # Origin city
    origin_m = re.search(
        r"(?:flying|fly|depart(?:ing)?|from)\s+from\s+([a-z][a-z\s]{2,20}?)(?:\s+to\b|\s+airport|,|\.|\Z)",
        text,
    )
    if origin_m:
        params["origin_city"] = origin_m.group(1).strip()

    return {k: v for k, v in params.items() if v is not None}


def _resolve_iata(city: str) -> str | None:
    """Resolve city name to IATA."""
    try:
        from core.reference_cache import ref
        return ref.city_to_iata(city.lower())
    except Exception:
        pass
    try:
        from reasoning.mcp_scorer import DEST_MAP
        city_l = city.lower()
        for name, code in sorted(DEST_MAP.items(), key=lambda x: len(x[0]), reverse=True):
            if name in city_l or city_l in name:
                return code
    except Exception:
        pass
    return None


def _store_params(session_id: str, params: dict):
    """Store extracted params in session entities for downstream use."""
    try:
        from rag.memory_store import memory_store
        ENTITY_MAP = {
            "destination_iata":    "city_code",
            "destination_country": "country_code",
            "departure_date":      "departure_date",
            "return_date":         "return_date",
            "nights":              "nights",
            "guests":              "guests",
            "adults":              "adults",
            "children":            "children",
            "budget_gbp":          "budget_gbp",
            "min_hotel_stars":     "min_hotel_stars",
            "direct_flight":       "direct_flight",
            "cabin_class":         "cabin_class",
            "pool":                "pool",
        }
        for param_key, entity_key in ENTITY_MAP.items():
            val = params.get(param_key)
            if val is not None:
                memory_store.store_entity(session_id, entity_key, val, confidence=0.90)

        # Also store destination as city_code for display
        if params.get("destination"):
            memory_store.store_entity(session_id, "destination", params["destination"], 0.90)
    except Exception as e:
        log.debug("Entity storage error: %s", e)
