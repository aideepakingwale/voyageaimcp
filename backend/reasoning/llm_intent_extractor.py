"""
VoyageAI LLM Intent Extractor
==============================
Uses the LLM waterfall to understand EVERY chat message in context.

Instead of regex pattern matching, every user message + full conversation
history is sent to the LLM with a structured extraction prompt.

The LLM extracts:
  - intent type (plan / modify / clarify / confirm / cancel / question)
  - what specifically changed (if modification)
  - all concrete values (dates in YYYY-MM-DD, guests as integers, budget as GBP)
  - natural language dates → exact ISO dates
    "coming Christmas" → 2026-12-25
    "New Year week"    → 2026-12-29 for 7 nights
    "next summer"      → 2026-07-01
    "Easter"           → 2027-04-05
    "half term"        → nearest school half term

Returns structured JSON the rest of the system can use directly.
"""
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger("voyageai.reasoning")

# ── Holiday / season date resolver (pre-LLM quick lookup) ─────
# These are resolved before the LLM call to give the LLM grounding
_TODAY = datetime.now()
_YEAR  = _TODAY.year


def _next_date(month: int, day: int) -> str:
    """Return YYYY-MM-DD for the next occurrence of this month/day."""
    candidate = datetime(_YEAR, month, day)
    if candidate < _TODAY:
        candidate = datetime(_YEAR + 1, month, day)
    return candidate.strftime("%Y-%m-%d")


def _easter(year: int) -> datetime:
    """Compute Easter Sunday for a given year (Anonymous Gregorian)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day   = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(year, month, day)


def _uk_half_term(reference: datetime) -> str:
    """Return start of nearest UK school half-term break."""
    half_terms = [
        datetime(_YEAR, 2, 17), datetime(_YEAR, 5, 26), datetime(_YEAR, 10, 27),
        datetime(_YEAR + 1, 2, 16), datetime(_YEAR + 1, 5, 25), datetime(_YEAR + 1, 10, 26),
    ]
    future = [d for d in half_terms if d >= reference]
    return (future[0] if future else half_terms[-1]).strftime("%Y-%m-%d")


HOLIDAY_DATES: dict[str, dict] = {
    # Christmas & New Year
    "christmas":           {"departure_date": _next_date(12, 25), "nights": 7},
    "christmas day":       {"departure_date": _next_date(12, 25), "nights": 7},
    "coming christmas":    {"departure_date": _next_date(12, 25), "nights": 7},
    "christmas week":      {"departure_date": _next_date(12, 23), "nights": 7},
    "christmas holidays":  {"departure_date": _next_date(12, 23), "nights": 14},
    "xmas":                {"departure_date": _next_date(12, 25), "nights": 7},
    "new year":            {"departure_date": _next_date(12, 29), "nights": 7},
    "new year's eve":      {"departure_date": _next_date(12, 28), "nights": 5},
    "new year week":       {"departure_date": _next_date(12, 29), "nights": 7},
    "festive":             {"departure_date": _next_date(12, 23), "nights": 14},
    "festive period":      {"departure_date": _next_date(12, 23), "nights": 14},
    "festive season":      {"departure_date": _next_date(12, 23), "nights": 14},
    # Easter
    "easter":              {"departure_date": (_easter(_YEAR) if _easter(_YEAR) > _TODAY else _easter(_YEAR + 1)).strftime("%Y-%m-%d"), "nights": 10},
    "easter holidays":     {"departure_date": (_easter(_YEAR) - timedelta(days=2) if _easter(_YEAR) > _TODAY else _easter(_YEAR + 1) - timedelta(days=2)).strftime("%Y-%m-%d"), "nights": 14},
    "easter break":        {"departure_date": (_easter(_YEAR) - timedelta(days=2) if _easter(_YEAR) > _TODAY else _easter(_YEAR + 1) - timedelta(days=2)).strftime("%Y-%m-%d"), "nights": 10},
    "good friday":         {"departure_date": (_easter(_YEAR) - timedelta(days=2) if _easter(_YEAR) > _TODAY else _easter(_YEAR + 1) - timedelta(days=2)).strftime("%Y-%m-%d"), "nights": 4},
    # School holidays
    "half term":           {"departure_date": _uk_half_term(_TODAY), "nights": 7},
    "half-term":           {"departure_date": _uk_half_term(_TODAY), "nights": 7},
    "half term break":     {"departure_date": _uk_half_term(_TODAY), "nights": 7},
    "school holidays":     {"departure_date": _uk_half_term(_TODAY), "nights": 14},
    "summer holidays":     {"departure_date": _next_date(7, 22), "nights": 14},
    "school summer":       {"departure_date": _next_date(7, 22), "nights": 14},
    # Seasons
    "next summer":         {"departure_date": _next_date(7, 1),  "nights": 14},
    "this summer":         {"departure_date": _next_date(7, 1),  "nights": 14},
    "summer":              {"departure_date": _next_date(7, 1),  "nights": 7},
    "next winter":         {"departure_date": _next_date(12, 20), "nights": 10},
    "this winter":         {"departure_date": _next_date(12, 20), "nights": 10},
    "winter sun":          {"departure_date": _next_date(12, 20), "nights": 10},
    "next spring":         {"departure_date": _next_date(3, 20), "nights": 7},
    "this spring":         {"departure_date": _next_date(3, 20), "nights": 7},
    "next autumn":         {"departure_date": _next_date(9, 1),  "nights": 7},
    "this autumn":         {"departure_date": _next_date(9, 1),  "nights": 7},
    "next fall":           {"departure_date": _next_date(9, 1),  "nights": 7},
    # Bank holidays / long weekends
    "may bank holiday":    {"departure_date": _next_date(5, 24), "nights": 4},
    "august bank holiday": {"departure_date": _next_date(8, 23), "nights": 4},
    "bank holiday":        {"departure_date": _next_date(5, 24), "nights": 4},
    # Months (first of month)
    "january":  {"departure_date": _next_date(1, 1)},
    "february": {"departure_date": _next_date(2, 1)},
    "march":    {"departure_date": _next_date(3, 1)},
    "april":    {"departure_date": _next_date(4, 1)},
    "may":      {"departure_date": _next_date(5, 1)},
    "june":     {"departure_date": _next_date(6, 1)},
    "july":     {"departure_date": _next_date(7, 1)},
    "august":   {"departure_date": _next_date(8, 1)},
    "september":{"departure_date": _next_date(9, 1)},
    "october":  {"departure_date": _next_date(10, 1)},
    "november": {"departure_date": _next_date(11, 1)},
    "december": {"departure_date": _next_date(12, 1)},
    # Relative
    "next month":    {"departure_date": (datetime(_TODAY.year, _TODAY.month % 12 + 1, 1)).strftime("%Y-%m-%d")},
    "next week":     {"departure_date": (_TODAY + timedelta(weeks=1)).strftime("%Y-%m-%d"), "nights": 7},
    "this weekend":  {"departure_date": (_TODAY + timedelta(days=(5-_TODAY.weekday()) % 7)).strftime("%Y-%m-%d"), "nights": 3},
}


def resolve_natural_date(text: str) -> Optional[dict]:
    """
    Try to resolve a natural language date reference to ISO dates.
    Returns {"departure_date": "YYYY-MM-DD", "nights": N} or just departure_date.
    """
    text_l = text.lower().strip()

    # Try known holiday/season strings (longest match first)
    for key in sorted(HOLIDAY_DATES.keys(), key=len, reverse=True):
        if key in text_l:
            return HOLIDAY_DATES[key]

    # Try "for N weeks/nights" + holiday
    nights_m = re.search(r"(\d+)\s*(?:nights?|weeks?)", text_l)
    for key in sorted(HOLIDAY_DATES.keys(), key=len, reverse=True):
        if key in text_l and nights_m:
            result = dict(HOLIDAY_DATES[key])
            n = int(nights_m.group(1))
            result["nights"] = n * 7 if "week" in nights_m.group(0) else n
            return result

    return None


# ── Extraction prompt ─────────────────────────────────────────

EXTRACTION_SYSTEM = """You are VoyageAI's intent extraction engine.
Your ONLY job is to extract structured travel intent from a conversation.
You MUST return valid JSON — nothing else, no markdown, no explanation.

Today's date: {today}

CRITICAL RULES:
1. Convert ALL natural language dates to ISO format YYYY-MM-DD:
   - "coming Christmas" → departure_date: "{christmas}"
   - "New Year week" → departure_date: "{new_year}", nights: 7
   - "Easter" → departure_date: "{easter}"
   - "next summer" → departure_date: "{summer}"
   - "half term" → departure_date: "{half_term}"
   - "in July" → departure_date: "{july}"
   - "September 15" → departure_date: "{year}-09-15"
   - "next month" → departure_date: "{next_month}"

2. Duration:
   - "1 week" → nights: 7
   - "2 weeks" → nights: 14
   - "10 days" → nights: 10
   - "long weekend" → nights: 3

3. Intent types:
   - "plan": fresh trip request (no prior plan exists, or destination change)
   - "modify": changing something in the existing plan
   - "confirm": user accepts the plan (yes/ok/book/looks good)
   - "cancel": user wants to start over (cancel/forget/start again)
   - "question": asking about the plan (not changing it)

4. What changed (for modify):
   - dates: changed departure or return date or duration
   - guests: number of people changed
   - hotel: star rating, type or preference changed
   - flight: airline, class, direct/indirect changed
   - budget: spending limit changed
   - destination: travel to somewhere different

5. For "modify", ALWAYS extract concrete values from the message.
   Never leave extracted values empty if the user specified them.

Return this exact JSON structure:
{{
  "intent": "plan|modify|confirm|cancel|question",
  "modification_type": "dates|guests|hotel|flight|budget|destination|null",
  "needs_clarification": false,
  "clarification_question": null,
  "extracted": {{
    "departure_date": "YYYY-MM-DD or null",
    "return_date": "YYYY-MM-DD or null",
    "nights": integer_or_null,
    "guests": integer_or_null,
    "adults": integer_or_null,
    "children": integer_or_null,
    "budget_gbp": integer_or_null,
    "min_stars": integer_or_null,
    "direct_flight": boolean_or_null,
    "cabin_class": "ECONOMY|BUSINESS|FIRST|null",
    "destination": "city name or null",
    "destination_iata": "IATA code or null",
    "pool": boolean_or_null,
    "all_inclusive": boolean_or_null
  }},
  "confidence": 0.0_to_1.0,
  "reasoning": "one sentence: what I understood the user wants"
}}"""

EXTRACTION_USER = """CURRENT PLAN (if any):
{current_plan}

CONVERSATION HISTORY:
{history}

LATEST USER MESSAGE:
{message}

Extract the intent and all concrete values. Pay special attention to dates — resolve them precisely."""


def extract_intent_with_llm(
    message: str,
    history: list[dict],
    last_itinerary: dict | None,
    session_id: str = "",
) -> dict:
    """
    Use the LLM waterfall to extract structured intent from the conversation.

    Returns:
    {
      "intent": "plan|modify|confirm|cancel|question",
      "modification_type": "dates|guests|hotel|...",
      "needs_clarification": bool,
      "clarification_question": str | None,
      "extracted": { departure_date, nights, guests, ... },
      "confidence": float,
      "reasoning": str,
      "_source": "llm|fallback"
    }
    """
    # Build date context for the prompt
    today     = _TODAY.strftime("%Y-%m-%d")
    ctx_dates = {
        "today":      today,
        "christmas":  HOLIDAY_DATES["christmas"]["departure_date"],
        "new_year":   HOLIDAY_DATES["new year"]["departure_date"],
        "easter":     HOLIDAY_DATES["easter"]["departure_date"],
        "summer":     HOLIDAY_DATES["next summer"]["departure_date"],
        "half_term":  HOLIDAY_DATES["half term"]["departure_date"],
        "july":       HOLIDAY_DATES["july"]["departure_date"],
        "year":       str(_TODAY.year + (1 if _TODAY.month >= 6 else 0)),
        "next_month": HOLIDAY_DATES["next month"]["departure_date"],
    }

    # Build current plan summary
    plan_summary = _summarise_plan(last_itinerary)

    # Build history string (last 8 turns)
    history_str = _format_history(history[-8:]) if history else "(no prior conversation)"

    # System prompt with date context injected
    system = EXTRACTION_SYSTEM.format(**ctx_dates)
    user   = EXTRACTION_USER.format(
        current_plan=plan_summary,
        history=history_str,
        message=message,
    )

    # Try LLM
    try:
        from llm.waterfall import get_waterfall
        wf   = get_waterfall()
        resp = wf.complete(system, user, max_tokens=400, temperature=0.1)

        if resp.success and resp.text:
            parsed = _parse_llm_response(resp.text)
            if parsed:
                parsed["_source"] = "llm"
                parsed["_provider"] = resp.provider
                log.info("LLM intent extracted", extra={
                    "session":   session_id,
                    "intent":    parsed.get("intent"),
                    "mod_type":  parsed.get("modification_type"),
                    "extracted": parsed.get("extracted"),
                    "reasoning": parsed.get("reasoning",""),
                    "provider":  resp.provider,
                })
                return parsed
    except Exception as e:
        log.debug("LLM intent extraction error: %s", e)

    # Fallback to quick resolver for dates
    fallback = _quick_fallback(message, bool(last_itinerary))
    fallback["_source"] = "fallback"
    return fallback


def _summarise_plan(itinerary: dict | None) -> str:
    if not itinerary:
        return "(no existing plan)"
    intent = itinerary.get("intent", {})
    dates  = intent.get("dates", {})
    return (
        f"Destination: {intent.get('destination','?')} ({intent.get('city_code','?')})\n"
        f"Dates: {dates.get('departure_date','?')} → {dates.get('return_date','?')} "
        f"({dates.get('nights','?')} nights)\n"
        f"Guests: {intent.get('guests','?')} "
        f"({intent.get('adults','?')} adults, {intent.get('children','?')} children)\n"
        f"Budget: £{intent.get('budget_gbp','?')}\n"
        f"Hotel: {intent.get('preferences',{}).get('min_hotel_stars','?')}★\n"
        f"Total cost: £{itinerary.get('total_cost_gbp','?')}"
    )


def _format_history(history: list[dict]) -> str:
    lines = []
    for turn in history:
        role    = turn.get("role", "user").upper()
        content = str(turn.get("content", ""))[:300]
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines) if lines else "(no history)"


def _parse_llm_response(text: str) -> dict | None:
    """Parse and validate LLM JSON response."""
    try:
        # Strip markdown fences
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            text = parts[1] if len(parts) >= 3 else text
            if text.startswith("json"):
                text = text[4:]

        # Extract JSON object
        start = text.find("{")
        end   = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end+1]

        data = json.loads(text)

        # Validate required fields
        if "intent" not in data:
            return None

        # Normalise intent
        intent = data.get("intent","plan").lower()
        if intent not in ("plan","modify","confirm","cancel","question"):
            intent = "plan"
        data["intent"] = intent

        # Normalise extracted values — ensure None not string "null"
        extracted = data.get("extracted", {})
        for k, v in list(extracted.items()):
            if v == "null" or v == "":
                extracted[k] = None
        data["extracted"] = extracted

        # Convert nights from float to int
        if extracted.get("nights"):
            try:
                extracted["nights"] = int(extracted["nights"])
            except Exception:
                pass

        # Compute return_date if we have departure + nights
        dep    = extracted.get("departure_date")
        nights = extracted.get("nights")
        if dep and nights and not extracted.get("return_date"):
            try:
                ret = datetime.strptime(dep, "%Y-%m-%d") + timedelta(days=nights)
                extracted["return_date"] = ret.strftime("%Y-%m-%d")
            except Exception:
                pass

        return data

    except Exception as e:
        log.debug("LLM response parse error: %s | text: %s", e, text[:100])
        return None


def _quick_fallback(message: str, has_itinerary: bool) -> dict:
    """
    Fast regex fallback when LLM is unavailable.
    Still handles holidays/seasons via HOLIDAY_DATES.
    """
    msg_l = message.lower().strip()

    # Cancel
    if any(p in msg_l for p in ["cancel","start over","start again","forget it","scrap"]):
        return {"intent":"cancel","modification_type":None,"needs_clarification":False,
                "clarification_question":None,"extracted":{},"confidence":0.9}

    # Confirm
    if (has_itinerary and len(msg_l.split()) <= 8 and
            any(p in msg_l for p in ["yes","ok","okay","confirm","book","looks good","great","perfect"])):
        return {"intent":"confirm","modification_type":None,"needs_clarification":False,
                "clarification_question":None,"extracted":{},"confidence":0.9}

    # Date modification
    date_signals = ["date","christmas","new year","easter","half term","summer","winter",
                    "spring","autumn","january","february","march","april","may","june",
                    "july","august","september","october","november","december",
                    "week","night","change","reschedule","postpone","earlier","later"]

    # Check guests BEFORE dates to avoid misclassification
    guest_signals = ["people","guests","adults","children","kids","person","persons",
                     "of us","travelling","family of","solo","couple","just us","just two"]
    is_guest_msg = any(s in msg_l for s in guest_signals) and re.search(r'\d', msg_l)

    if has_itinerary and any(s in msg_l for s in date_signals) and not is_guest_msg:
        resolved = resolve_natural_date(message)
        extracted = resolved if resolved else {}
        # Explicit "N nights/weeks" ALWAYS overrides the holiday default
        nm = re.search(r"for\s+(\d+)\s*(nights?|weeks?)|"
                        r"(\d+)\s*(nights?|weeks?)", msg_l)
        if nm:
            # Use first non-None group
            n_str    = nm.group(1) or nm.group(3)
            unit_str = nm.group(2) or nm.group(4)
            if n_str:
                n = int(n_str)
                extracted["nights"] = n * 7 if "week" in unit_str else n
        # Recalculate return date if we have dep + nights
        if extracted.get("departure_date") and extracted.get("nights"):
            try:
                from datetime import datetime as _dt, timedelta as _td
                dep = _dt.strptime(extracted["departure_date"], "%Y-%m-%d")
                extracted["return_date"] = (dep + _td(days=extracted["nights"])).strftime("%Y-%m-%d")
            except Exception:
                pass
        needs_clarification = not bool(extracted.get("departure_date"))
        return {
            "intent": "modify",
            "modification_type": "dates",
            "needs_clarification": needs_clarification,
            "clarification_question": "What exact dates would you like? For example: 'December 25 for 1 week' or 'Christmas Day, 7 nights'" if needs_clarification else None,
            "extracted": extracted,
            "confidence": 0.75 if extracted else 0.5,
        }

    # Guest modification — also catches "N adults and M children"
    if has_itinerary and is_guest_msg:
        from reasoning.conversation_engine import _extract_guest_count
        extracted = _extract_guest_count(message)
        return {"intent":"modify","modification_type":"guests","needs_clarification":not bool(extracted),
                "clarification_question":"How many people will be travelling?" if not extracted else None,
                "extracted":extracted,"confidence":0.7}

    # Hotel
    if has_itinerary and any(s in msg_l for s in ["hotel","star","pool","resort","upgrade","cheaper"]):
        from reasoning.conversation_engine import _extract_hotel_prefs
        return {"intent":"modify","modification_type":"hotel","needs_clarification":False,
                "clarification_question":None,"extracted":_extract_hotel_prefs(message),"confidence":0.7}

    # Budget
    if has_itinerary and any(s in msg_l for s in ["budget","£","spend","afford","cheaper","expensive"]):
        from reasoning.conversation_engine import _extract_budget
        b = _extract_budget(message)
        return {"intent":"modify","modification_type":"budget","needs_clarification":not bool(b),
                "clarification_question":"What's your new budget?" if not b else None,
                "extracted":{"budget_gbp":b} if b else {},"confidence":0.7}

    # Default: fresh plan
    return {"intent":"plan","modification_type":None,"needs_clarification":False,
            "clarification_question":None,"extracted":{},"confidence":0.6}
