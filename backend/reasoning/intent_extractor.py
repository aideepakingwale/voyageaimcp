"""
VoyageAI LLM Intent Extractor
===============================
Routes every user message through an LLM to extract structured intent.
Replaces all regex-based pattern matching for dates, guests, budget etc.

The LLM understands natural language like:
  "coming Christmas for a week"    → departure_date: 2026-12-25, nights: 7
  "next Easter"                    → departure_date: 2027-04-05
  "fly from Manchester"            → origin_iata: MAN
  "me and my wife"                 → guests: 2, adults: 2
  "under 3 grand"                  → budget_gbp: 3000
  "5 star with a pool"             → min_hotel_stars: 5, pool: true
  "change the dates"               → intent: modify, subtype: dates, needs_clarification: true
  "yes that looks great"           → intent: confirm
  "cancel that"                    → intent: cancel

Returns a structured JSON dict that the chat API uses directly.
"""
import json
import logging
import re
from datetime import datetime

log = logging.getLogger("voyageai.reasoning")

# ── System prompt for intent extraction ──────────────────────
INTENT_SYSTEM_PROMPT = """You are a travel intent parser for VoyageAI. Your ONLY job is to parse user messages and return structured JSON.

Today's date is {today}. Current year is {year}.

RULES:
1. Return ONLY valid JSON — no markdown, no explanation, no preamble
2. Resolve ALL relative dates to actual YYYY-MM-DD dates:
   - "Christmas" / "Christmas Day" → {year}-12-25 (or {next_year}-12-25 if already past)
   - "Christmas week" / "over Christmas" → departure {year}-12-22, nights: 9
   - "New Year" / "New Year's" → {year}-12-29 (to cover both NYE and NY)
   - "Easter" → calculate actual Easter Sunday for {year} or {next_year}
   - "summer" → {year}-07-15 if not yet, else {next_year}-07-15
   - "next month" → first of next month
   - "in 2 weeks" → today + 14 days
   - "half term" → UK October half term: {year}-10-26
   - "bank holiday weekend" → next UK bank holiday Monday - 3 days
   - "next weekend" → next Saturday
   - "a week from now" → today + 7 days
3. Resolve duration naturally:
   - "a week" / "one week" / "7 nights" → nights: 7
   - "two weeks" / "fortnight" → nights: 14
   - "10 days" → nights: 10
   - "long weekend" → nights: 3
4. For MODIFICATIONS to an existing plan, only fill in the fields being changed
5. For FRESH requests, fill in everything extractable from the message

INTENT TYPES:
- "plan"    → new trip request (no existing itinerary, or user wants completely new destination)
- "modify"  → changing something about the current plan
- "confirm" → user accepts the plan ("yes", "book it", "looks good", "perfect", "go ahead")
- "cancel"  → user wants to start over ("cancel", "forget it", "start again", "scrap this")
- "clarify" → user's message needs a follow-up question before you can act

MODIFICATION SUBTYPES:
- "dates"       → changing departure date, duration, or return date
- "guests"      → changing number of travellers
- "hotel"       → changing hotel preference (stars, type, amenities)
- "flight"      → changing flight preference (direct, airline, cabin class)
- "budget"      → changing budget
- "destination" → going somewhere different
- "general"     → multiple things changing, or unclear which

RETURN THIS EXACT JSON STRUCTURE:
{
  "intent": "plan|modify|confirm|cancel|clarify",
  "modification_subtype": "dates|guests|hotel|flight|budget|destination|general|null",
  "needs_clarification": false,
  "clarify_question": null,
  "extracted": {
    "destination": null,
    "city_code": null,
    "departure_date": null,
    "return_date": null,
    "nights": null,
    "guests": null,
    "adults": null,
    "children": null,
    "budget_gbp": null,
    "origin_city": null,
    "origin_iata": null,
    "min_hotel_stars": null,
    "pool": null,
    "all_inclusive": null,
    "direct_flight": null,
    "cabin_class": null,
    "travel_style": null,
    "interests": null
  },
  "confidence": 0.0,
  "reasoning": "brief explanation of what you understood"
}

EXAMPLES:
User: "I want to change my travel dates to coming Christmas for 1 week"
→ {
  "intent": "modify",
  "modification_subtype": "dates",
  "needs_clarification": false,
  "extracted": {
    "departure_date": "2026-12-25",
    "return_date": "2027-01-01",
    "nights": 7
  },
  "confidence": 0.97,
  "reasoning": "Christmas = Dec 25 {year}, 1 week = 7 nights"
}

User: "Can we go in February half term instead, just the two of us"
→ {
  "intent": "modify",
  "modification_subtype": "dates",
  "needs_clarification": false,
  "extracted": {
    "departure_date": "{year}-02-16",
    "nights": 7,
    "guests": 2,
    "adults": 2,
    "children": 0
  },
  "confidence": 0.92,
  "reasoning": "UK Feb half term approx Feb 16, couple = 2 adults"
}

User: "Fly from Manchester"
→ {
  "intent": "modify",
  "modification_subtype": "general",
  "extracted": {
    "origin_city": "Manchester",
    "origin_iata": "MAN"
  },
  "confidence": 0.99,
  "reasoning": "Manchester airport IATA = MAN"
}

User: "Yes, book it"
→ {"intent": "confirm", "confidence": 0.99, "reasoning": "clear confirmation"}

User: "Actually can we go to Maldives instead of Seychelles"
→ {
  "intent": "modify",
  "modification_subtype": "destination",
  "extracted": {
    "destination": "Maldives",
    "city_code": "MLE"
  },
  "confidence": 0.98,
  "reasoning": "destination change to Maldives MLE"
}"""


def extract_intent(message: str, session_context: str = "",
                   last_itinerary: dict = None) -> dict:
    """
    Use the LLM to extract structured intent from a user message.
    
    Returns a dict with:
      intent, modification_subtype, needs_clarification,
      clarify_question, extracted, confidence, reasoning
    """
    today     = datetime.now()
    year      = today.year
    next_year = year + 1

    # Build system prompt with current date context
    system = (INTENT_SYSTEM_PROMPT
              .replace("{today}",     today.strftime("%Y-%m-%d"))
              .replace("{year}",      str(year))
              .replace("{next_year}", str(next_year)))

    # Build user context block
    context_parts = []

    if session_context and session_context.strip():
        context_parts.append(f"CURRENT SESSION CONTEXT:\n{session_context}")

    if last_itinerary:
        intent_block = last_itinerary.get("intent", {})
        dates_block  = intent_block.get("dates", {})
        context_parts.append(
            f"CURRENT ITINERARY:\n"
            f"  Destination: {intent_block.get('destination','?')} ({intent_block.get('city_code','?')})\n"
            f"  Dates: {dates_block.get('departure_date','?')} → {dates_block.get('return_date','?')} ({dates_block.get('nights','?')} nights)\n"
            f"  Guests: {intent_block.get('guests','?')} people\n"
            f"  Budget: £{intent_block.get('budget_gbp','?')}\n"
            f"  Total cost: £{last_itinerary.get('total_cost_gbp','?')}"
        )

    context_block = "\n\n".join(context_parts)
    user_prompt   = (f"{context_block}\n\nUSER MESSAGE: {message}"
                     if context_block else f"USER MESSAGE: {message}")

    # Call LLM via the waterfall
    try:
        from llm.waterfall import get_waterfall
        wf   = get_waterfall()
        resp = wf.complete(system, user_prompt, max_tokens=600, temperature=0.1)

        if not resp.success:
            log.warning("Intent extractor LLM failed: %s", resp.error[:100])
            return _regex_fallback(message, last_itinerary)

        # Parse the JSON response
        raw = resp.text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()
        # Find JSON object
        start = raw.find("{"); end = raw.rfind("}")
        if start != -1 and end != -1:
            raw = raw[start:end+1]

        result = json.loads(raw)

        # Detect if template provider returned an itinerary instead of intent
        # (happens when template is the only provider available)
        if "recommendations" in result or "intent" in result and isinstance(result.get("intent"), dict) and "dates" in result.get("intent", {}):
            log.debug("Template returned itinerary not intent — using regex fallback")
            return _regex_fallback(message, last_itinerary)

        # Normalise the result
        extracted = result.get("extracted") or {}
        extracted = {k: v for k, v in extracted.items() if v is not None}

        return {
            "type":                result.get("intent", "plan"),
            "subtype":             result.get("modification_subtype"),
            "needs_clarification": result.get("needs_clarification", False),
            "clarify_question":    result.get("clarify_question"),
            "extracted":           extracted,
            "confidence":          float(result.get("confidence", 0.85)),
            "reasoning":           result.get("reasoning", ""),
            "source":              "llm",
        }

    except json.JSONDecodeError as e:
        log.warning("Intent extractor JSON parse failed: %s | raw: %s", e, raw[:100])
        return _regex_fallback(message, last_itinerary)
    except Exception as e:
        log.warning("Intent extractor error: %s", e)
        return _regex_fallback(message, last_itinerary)


def _regex_fallback(message: str, last_itinerary: dict = None) -> dict:
    """
    Enhanced regex fallback — handles holidays, relative dates, and common phrases.
    Used when LLM unavailable or returns wrong format.
    """
    msg_l  = message.lower().strip()
    has_it = bool(last_itinerary)

    # ── Confirm ───────────────────────────────────────────────
    if has_it and re.search(r"\b(yes|yep|yeah|ok|okay|sure|confirm|book|"
                             r"proceed|go ahead|perfect|great|looks good|"
                             r"lets go|let\'s go|sounds good|deal)\b", msg_l):
        return {"type":"confirm","subtype":None,"extracted":{},
                "needs_clarification":False,"source":"regex_fallback"}

    # ── Cancel ────────────────────────────────────────────────
    if re.search(r"\b(cancel|start over|start again|forget it|scrap|"
                 r"never mind|restart|from scratch)\b", msg_l):
        return {"type":"cancel","subtype":None,"extracted":{},
                "needs_clarification":False,"source":"regex_fallback"}

    # ── Implicit modification signals when itinerary exists ───────────────
    # These phrases imply modification even without "change" / "update"
    IMPLICIT_MOD_SIGNALS = [
        r"\bjust (the |us )?(two|three|four|five|six|one)\b",
        r"\bjust me\b|\bjust myself\b|\bgoing solo\b",
        r"\bonly (the )?(\d+) of us\b",
        r"\bthe (\d+) of us\b",
        r"\bno kids\b|\bwithout (the )?kids\b|\bwithout children\b",
        r"\bjust (us |the )?(couple|two adults|2 adults)\b",
        r"\badd (my |our )?(wife|husband|partner|mother|father|friend|colleague)\b",
        r"\bone more person\b|\bone extra person\b",
        r"\bchristmas week\b|\bover christmas\b|\bfor christmas\b",
        r"\bnew year\b|\bnew year\'s\b|\bnew years\b",
        r"\beaster week\b|\bover easter\b",
        r"\bsummer holiday\b|\bsummer break\b",
        r"\bfly from\b|\bflying from\b|\bdepart from\b",
        r"\bwant (a |to )?(5|four|five)-?star\b",
        r"\bmake it direct\b|\bdirect flight\b|\bnon-stop\b",
    ]

    implicit_mod = has_it and any(re.search(p, msg_l) for p in IMPLICIT_MOD_SIGNALS)

    # ── Holiday date patterns ──────────────────────────────────
    extracted = {}
    if has_it or implicit_mod:
        yr = datetime.now().year
        nxt = yr + 1

        # Christmas
        if re.search(r"\bchristmas\b", msg_l):
            christmas = f"{yr}-12-25"
            if datetime.now() > datetime(yr, 12, 10):
                christmas = f"{nxt}-12-25"
            extracted["departure_date"] = christmas
            nights = _extract_nights_regex(msg_l)
            if nights: extracted["nights"] = nights

        # New Year
        elif re.search(r"\bnew year\b|\bnew year\'s\b", msg_l):
            extracted["departure_date"] = f"{yr}-12-29"
            if datetime.now().month == 12 and datetime.now().day > 20:
                extracted["departure_date"] = f"{nxt}-12-29"

        # Easter
        elif re.search(r"\beaster\b", msg_l):
            extracted["departure_date"] = _calc_easter(yr)

        # Half term
        elif re.search(r"\bhalf term\b|\bhalf-term\b", msg_l):
            if re.search(r"\bfeb|\bfebruary\b", msg_l):
                extracted["departure_date"] = f"{yr}-02-16"
            elif re.search(r"\boct|\boctober\b", msg_l):
                extracted["departure_date"] = f"{yr}-10-26"
            else:
                extracted["departure_date"] = f"{yr}-10-26"

        # Summer
        elif re.search(r"\bsummer\b", msg_l):
            extracted["departure_date"] = f"{yr}-07-15"
            if datetime.now().month >= 8:
                extracted["departure_date"] = f"{nxt}-07-15"

        # Generic nights extraction
        nights = _extract_nights_regex(msg_l)
        if nights and "nights" not in extracted:
            extracted["nights"] = nights

    if extracted and has_it:
        return {"type":"modify","subtype":"dates","extracted":extracted,
                "needs_clarification":False,"source":"regex_fallback_holiday"}

    # ── Modification hints ────────────────────────────────────
    if (has_it or implicit_mod) and re.search(r"\b(change|update|modify|different|instead|"
                             r"cheaper|upgrade|earlier|later|more|fewer|add|"
                             r"switch|swap|replace|prefer|want)\b", msg_l):
        subtype = "general"
        if re.search(r"\b(date|when|month|week|night|depart|arrive|"
                     r"christmas|easter|summer|winter|january|february|"
                     r"march|april|may|june|july|august|september|"
                     r"october|november|december)\b", msg_l):
            subtype = "dates"
        elif re.search(r"\b(people|guest|adult|child|person|family|couple|"
                       r"solo|passenger|traveller|of us|of us|no kids|"
                       r"just (the |us )?(two|three|four|one)|just me|"
                       r"just (us|ourselves)|wife|husband|partner)\b", msg_l):
            subtype = "guests"
        elif re.search(r"\b(hotel|star|pool|spa|resort|accommodation|"
                       r"room|suite|villa|lodge)\b", msg_l):
            subtype = "hotel"
        elif re.search(r"\b(flight|fly|direct|airline|class|business|"
                       r"economy|first.class|nonstop|stopover)\b", msg_l):
            subtype = "flight"
        elif re.search(r"\b(budget|pound|gbp|cost|price|cheap|afford|"
                       r"expensive|money|spend)\b", msg_l):
            subtype = "budget"
        elif re.search(r"\b(destination|go to|visit|travel to|instead of|"
                       r"somewhere else|different country|different city)\b", msg_l):
            subtype = "destination"

        needs_clarify = not bool(extracted)
        return {"type":"modify","subtype":subtype,"extracted":extracted,
                "needs_clarification":needs_clarify,
                "clarify_question":(f"What specific {subtype} change would you like?"
                                    if needs_clarify else None),
                "source":"regex_fallback"}

    return {"type":"plan","subtype":None,"extracted":{},
            "needs_clarification":False,"source":"regex_fallback"}


def _extract_nights_regex(msg_l: str) -> int | None:
    m = re.search(r"(\d+)\s*nights?", msg_l)
    if m: return int(m.group(1))
    m = re.search(r"(\d+)\s*weeks?", msg_l)
    if m: return int(m.group(1)) * 7
    if re.search(r"\bone week\b|\ba week\b", msg_l): return 7
    if re.search(r"\btwo weeks?\b|\ba fortnight\b", msg_l): return 14
    if re.search(r"\blong weekend\b", msg_l): return 3
    return None


def _calc_easter(year: int) -> str:
    """Compute Easter Sunday for a given year (Anonymous Gregorian algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19*a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2*e + 2*i - h - k) % 7
    m = (a + 11*h + 22*l) // 451
    month = (h + l - 7*m + 114) // 31
    day   = ((h + l - 7*m + 114) % 31) + 1
    # If date is past, return next year's Easter
    if datetime(year, month, day) < datetime.now():
        return _calc_easter(year + 1)
    return f"{year}-{month:02d}-{day:02d}"
