"""
VoyageAI Conversational Modification Engine
============================================
Handles multi-turn conversation AFTER an initial itinerary is generated.

States:
  PLANNING      — fresh trip request, call full ReasoningEngine
  MODIFYING     — user is changing something specific in the current plan
  CLARIFYING    — system is asking a follow-up question before modifying
  CONFIRMING    — user is confirming/cancelling the plan

Flow:
  User: "Plan Seychelles 4 people July £4000"
    → ReasoningEngine → store itinerary → state=CONFIRMING

  User: "I want to change the dates"
    → CLARIFYING → ask "What dates would you like instead?"

  User: "September 15 for 10 nights"
    → MODIFYING → patch dates → re-run MCP for new flights/hotels

  User: "Can we upgrade to 5 star?"
    → MODIFYING → patch hotel preference → re-run hotel MCP only
"""
import re
import json
import logging
from datetime import datetime, timedelta
from rag.memory_store import memory_store

log = logging.getLogger("voyageai.reasoning")


# ── Modification type classifiers ──────────────────────────────

DATE_PATTERNS = [
    r"change.*date", r"different date", r"reschedule", r"postpone",
    r"move.*to", r"in (january|february|march|april|may|june|july|august|"
    r"september|october|november|december)", r"next (month|year|week)",
    r"earlier", r"later", r"delay", r"(jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b",
    r"\d{1,2}(st|nd|rd|th)?\s+(january|february|march|april|may|june|july|"
    r"august|september|october|november|december)",
    r"(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+\d{1,2}",
]

GUEST_PATTERNS = [
    r"add (a|another|one more|an extra) person", r"one more (person|adult|child|guest|people)",
    r"(fewer|less) people", r"(\d+) (people|guests|adults|passengers|of us)",
    r"just (the )?two|just (us )?two|just (one|1)|solo|alone",
    r"family of (\d+)", r"add (a )?child", r"without the kids",
]

HOTEL_PATTERNS = [
    r"(cheaper|budget|less expensive) hotel", r"(better|nicer|luxury|5.star|five.star) hotel",
    r"upgrade (the )?hotel", r"different hotel", r"(\d).star hotel",
    r"(beach|sea.view|city.centre|central) hotel", r"with (pool|spa|gym|breakfast)",
    r"all.inclusive", r"boutique hotel",
]

FLIGHT_PATTERNS = [
    r"direct flight", r"non.stop", r"(earlier|later|morning|evening|overnight) flight",
    r"different airline", r"(business|first) class", r"upgrade.*flight",
    r"cheaper flight", r"(faster|quicker) route",
]

BUDGET_PATTERNS = [
    r"(increase|raise|higher) (the )?budget", r"(reduce|lower|decrease|cut) (the )?budget",
    r"cheaper", r"more expensive", r"£\d+", r"\$\d+", r"spend (more|less)",
    r"budget of £?\d+",
]

DESTINATION_PATTERNS = [
    r"(go|travel|fly) (to|somewhere)",r"different (destination|place|country|city)",
    r"what about .+instead", r"how about .+ instead",
]

CANCEL_PATTERNS = [
    r"cancel", r"start (over|again|fresh)", r"forget (it|this|everything)",
    r"never mind", r"don't (want|like) (this|it)", r"scrap (this|it|the plan)",
    r"start from scratch",
]

CONFIRM_PATTERNS = [
    r"(yes|yep|yeah|ok|okay|sure|confirm|book|proceed|go ahead|looks good|perfect|great)",
    r"that (works|looks|sounds) (good|great|perfect|fine)",
    r"i('ll| will) take (it|that|this)",
    r"let's (book|go|do (it|this))",
]


def classify_intent(message: str, has_itinerary: bool) -> dict:
    """
    Classify what the user wants to do with the current message.
    Returns: { type, subtype, extracted_values, needs_clarification, clarify_question }
    """
    msg_l = message.lower().strip()

    # Cancel?
    if has_itinerary and any(re.search(p, msg_l) for p in CANCEL_PATTERNS):
        return {"type": "cancel", "subtype": None, "extracted": {},
                "needs_clarification": False}

    # Confirm?
    if has_itinerary and len(msg_l.split()) <= 6:
        if any(re.search(p, msg_l) for p in CONFIRM_PATTERNS):
            return {"type": "confirm", "subtype": None, "extracted": {},
                    "needs_clarification": False}

    # Modification types (only relevant when an itinerary exists)
    if has_itinerary:
        # Date change
        if any(re.search(p, msg_l) for p in DATE_PATTERNS):
            dates = _extract_dates(message)
            nights = _extract_nights(message)
            if dates or nights:
                return {"type": "modify", "subtype": "dates",
                        "extracted": {**dates, **({"nights": nights} if nights else {})},
                        "needs_clarification": False}
            else:
                return {"type": "modify", "subtype": "dates", "extracted": {},
                        "needs_clarification": True,
                        "clarify_question": "What dates would you like? For example: 'September 15 for 12 nights' or 'October 1st to October 14th'"}

        # Guest change
        if any(re.search(p, msg_l) for p in GUEST_PATTERNS):
            guests = _extract_guest_count(message)
            if guests:
                return {"type": "modify", "subtype": "guests", "extracted": guests,
                        "needs_clarification": False}
            else:
                return {"type": "modify", "subtype": "guests", "extracted": {},
                        "needs_clarification": True,
                        "clarify_question": "How many people will be travelling? And how many are children?"}

        # Hotel change
        if any(re.search(p, msg_l) for p in HOTEL_PATTERNS):
            prefs = _extract_hotel_prefs(message)
            return {"type": "modify", "subtype": "hotel", "extracted": prefs,
                    "needs_clarification": False}

        # Flight change
        if any(re.search(p, msg_l) for p in FLIGHT_PATTERNS):
            prefs = _extract_flight_prefs(message)
            return {"type": "modify", "subtype": "flight", "extracted": prefs,
                    "needs_clarification": False}

        # Budget change
        if any(re.search(p, msg_l) for p in BUDGET_PATTERNS):
            budget = _extract_budget(message)
            if budget:
                return {"type": "modify", "subtype": "budget",
                        "extracted": {"budget_gbp": budget},
                        "needs_clarification": False}
            else:
                return {"type": "modify", "subtype": "budget", "extracted": {},
                        "needs_clarification": True,
                        "clarify_question": "What budget would you like? E.g. '£5,000' or 'under £3,000'"}

        # Destination change
        if any(re.search(p, msg_l) for p in DESTINATION_PATTERNS):
            return {"type": "modify", "subtype": "destination", "extracted": {},
                    "needs_clarification": False}

    # Default: fresh planning request
    return {"type": "plan", "subtype": None, "extracted": {},
            "needs_clarification": False}


def apply_modification(session_id: str, intent: dict) -> dict | None:
    """
    Apply a modification to the stored itinerary.
    Returns the patched itinerary dict, or None if no itinerary to patch.
    """
    last = memory_store.get_last_itinerary(session_id)
    if not last:
        return None

    # Deep copy
    itinerary = json.loads(json.dumps(last))
    intent_block = itinerary.setdefault("intent", {})
    dates_block  = intent_block.setdefault("dates", {})
    prefs_block  = intent_block.setdefault("preferences", {})
    extracted    = intent.get("extracted", {})
    subtype      = intent.get("subtype")

    if subtype == "dates":
        if "departure_date" in extracted:
            dates_block["departure_date"] = extracted["departure_date"]
        if "return_date" in extracted:
            dates_block["return_date"] = extracted["return_date"]
        if "nights" in extracted:
            dates_block["nights"] = extracted["nights"]
            # Recalculate return date if departure known
            if "departure_date" in dates_block and dates_block["departure_date"]:
                try:
                    dep = datetime.strptime(dates_block["departure_date"], "%Y-%m-%d")
                    ret = dep + timedelta(days=extracted["nights"])
                    dates_block["return_date"] = ret.strftime("%Y-%m-%d")
                except Exception:
                    pass

    elif subtype == "guests":
        if "guests" in extracted:
            intent_block["guests"]   = extracted["guests"]
        if "adults" in extracted:
            intent_block["adults"]   = extracted["adults"]
        if "children" in extracted:
            intent_block["children"] = extracted["children"]

    elif subtype == "hotel":
        if "min_stars" in extracted:
            prefs_block["min_hotel_stars"] = extracted["min_stars"]
        if "pool" in extracted:
            prefs_block["pool"] = extracted["pool"]
        if "all_inclusive" in extracted:
            prefs_block["all_inclusive"] = extracted["all_inclusive"]
        if "budget_tier" in extracted:
            # budget tier affects hotel price range
            intent_block["hotel_preference"] = extracted["budget_tier"]

    elif subtype == "flight":
        if "direct" in extracted:
            prefs_block["direct_flight"] = extracted["direct"]
        if "cabin" in extracted:
            prefs_block["cabin_class"] = extracted["cabin"]

    elif subtype == "budget":
        if "budget_gbp" in extracted:
            intent_block["budget_gbp"] = extracted["budget_gbp"]

    return itinerary


# ── Extraction helpers ─────────────────────────────────────────

def _extract_dates(text: str) -> dict:
    result = {}
    text_l = text.lower()

    MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
              "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
              "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
              "sep":9,"oct":10,"nov":11,"dec":12}

    # "September 15" or "15 September" or "15th September"
    for month_name, month_num in MONTHS.items():
        if month_name not in text_l:
            continue
        # Day before month: "15th September", "15 Sep"
        m = re.search(rf"(\d{{1,2}})(st|nd|rd|th)?\s+{month_name}", text_l)
        if m:
            day = int(m.group(1))
            year = datetime.now().year
            try_date = datetime(year, month_num, day)
            if try_date < datetime.now():
                try_date = datetime(year+1, month_num, day)
            result["departure_date"] = try_date.strftime("%Y-%m-%d")
            break
        # Month before day: "September 15"
        m2 = re.search(rf"{month_name}\s+(\d{{1,2}})(st|nd|rd|th)?", text_l)
        if m2:
            day = int(m2.group(1))
            year = datetime.now().year
            try_date = datetime(year, month_num, day)
            if try_date < datetime.now():
                try_date = datetime(year+1, month_num, day)
            result["departure_date"] = try_date.strftime("%Y-%m-%d")
            break
        # Just the month: "in September" → first of that month
        m3 = re.search(rf"in\s+{month_name}|next\s+{month_name}|for\s+{month_name}", text_l)
        if m3:
            year = datetime.now().year
            try_date = datetime(year, month_num, 1)
            if try_date < datetime.now():
                try_date = datetime(year+1, month_num, 1)
            result["departure_date"] = try_date.strftime("%Y-%m-%d")
            break

    # ISO date: 2026-09-15
    iso = re.search(r"20\d\d-\d\d-\d\d", text)
    if iso and "departure_date" not in result:
        result["departure_date"] = iso.group(0)

    return result


def _extract_nights(text: str) -> int | None:
    m = re.search(r"(\d+)\s*nights?", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d+)\s*weeks?", text, re.IGNORECASE)
    if m2:
        return int(m2.group(1)) * 7
    return None


def _extract_guest_count(text: str) -> dict:
    result = {}
    text_l = text.lower()

    # "family of 5", "5 people", "5 of us"
    m = re.search(r"(\d+)\s*(?:people|guests|passengers|of us|in total|travelling)", text_l)
    if m:
        result["guests"] = int(m.group(1))

    # "2 adults and 2 children"
    a = re.search(r"(\d+)\s*adults?", text_l)
    c = re.search(r"(\d+)\s*(?:child(?:ren)?|kids?)", text_l)
    if a:
        result["adults"] = int(a.group(1))
    if c:
        result["children"] = int(c.group(1))
    if "adults" in result and "children" in result:
        result["guests"] = result["adults"] + result["children"]

    # Solo patterns
    if any(p in text_l for p in ["just me", "solo", "just myself", "alone", "on my own"]):
        result = {"guests": 1, "adults": 1, "children": 0}

    # "just the two of us"
    if any(p in text_l for p in ["two of us", "just us two", "just two", "couple"]):
        result = {"guests": 2, "adults": 2, "children": 0}

    return result


def _extract_hotel_prefs(text: str) -> dict:
    text_l = text.lower()
    prefs = {}

    # Star rating
    m = re.search(r"(\d)\s*[\-\s]*star", text_l)
    if m:
        prefs["min_stars"] = int(m.group(1))
    elif "luxury" in text_l or "5 star" in text_l or "five star" in text_l:
        prefs["min_stars"] = 5
    elif "budget" in text_l or "cheap" in text_l or "basic" in text_l:
        prefs["min_stars"] = 2
        prefs["budget_tier"] = "budget"
    elif "mid-range" in text_l or "moderate" in text_l:
        prefs["min_stars"] = 3
        prefs["budget_tier"] = "mid"

    if "pool" in text_l: prefs["pool"] = True
    if "all.inclusive" in text_l or "all inclusive" in text_l: prefs["all_inclusive"] = True

    return prefs


def _extract_flight_prefs(text: str) -> dict:
    text_l = text.lower()
    prefs = {}
    if "direct" in text_l or "non-stop" in text_l or "nonstop" in text_l:
        prefs["direct"] = True
    if "business" in text_l:
        prefs["cabin"] = "BUSINESS"
    elif "first" in text_l and "class" in text_l:
        prefs["cabin"] = "FIRST"
    elif "economy" in text_l:
        prefs["cabin"] = "ECONOMY"
    return prefs


def _extract_budget(text: str) -> int | None:
    m = re.search(r"[£$](\d[\d,]*)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    m2 = re.search(r"(\d[\d,]+)\s*(?:pounds?|gbp|dollars?)", text, re.IGNORECASE)
    if m2:
        return int(m2.group(1).replace(",", ""))
    return None


# ── Exported convenience wrappers ─────────────────────────────

def _extract_dates_from_text(message: str) -> dict:
    """Alias for external import."""
    result = _extract_dates(message)
    nights = _extract_nights(message)
    if nights:
        result["nights"] = nights
    return result
