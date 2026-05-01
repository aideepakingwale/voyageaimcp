"""
VoyageAI Intelligent Recovery Engine
======================================
When a travel plan fails for ANY reason, this module:

  1. Analyses the failure using the LLM
  2. Understands what went wrong (no seats, dates, budget, route, visa, etc.)
  3. Generates contextually intelligent recovery options:
       - Alternative dates on the same route
       - Alternative destinations matching the same theme
       - Alternative routing (hub connections)
       - Budget adjustments
       - Group-splitting suggestions
  4. Returns a structured response the frontend renders as a helpful card
     — never a broken itinerary with 0 seats and £0 costs

Example failure scenarios handled:
  - "No seats: EK716 only 3 seats for 4 guests"
      → Try EK718 (tomorrow), or split group, or fly via DXB
  - "Budget exceeded: £6800 vs £2000 limit"
      → 3-star hotel options, cheaper airlines, shoulder-season dates
  - "Invalid route: no direct flights LHR→KEF in January"
      → Via LGW or via CPH connecting
  - "Date in past: departure 2025-03-01 already passed"
      → Ask for corrected date
  - "Unknown destination: XYZQ"
      → Nearest real airport lookup
  - Confidence too low on hallucinated itinerary
      → Simplify request or use template provider
"""
import json
import logging
from typing import Optional

log = logging.getLogger("voyageai.reasoning")

# ── LLM prompt ────────────────────────────────────────────────────────────────

RECOVERY_SYSTEM = """You are VoyageAI's intelligent recovery assistant.
A travel plan has failed. Analyse WHY it failed and provide practical recovery options.

FAILURE CATEGORIES and recovery strategies:
- NO_SEATS / FULL_FLIGHT    → suggest alternative dates ±7 days, alternate airlines, hub routing
- BUDGET_EXCEEDED           → suggest 3★ hotels, budget airlines, shoulder-season, shorter trip
- INVALID_ROUTE             → suggest connecting airports, alternative nearby airports
- INVALID_DATE / PAST_DATE  → ask for corrected date, suggest next available season
- CONFIDENCE_LOW            → simplify request, break into smaller steps
- UNKNOWN_DESTINATION       → suggest nearest known airport, check spelling
- VISA_RESTRICTION          → flag visa requirement, suggest visa-free alternatives

Return ONLY valid JSON with this structure:
{
  "failure_category": "NO_SEATS|BUDGET_EXCEEDED|INVALID_ROUTE|INVALID_DATE|CONFIDENCE_LOW|UNKNOWN_DESTINATION|VISA_RESTRICTION|OTHER",
  "plain_english": "What went wrong in 1 simple sentence",
  "recovery_type": "SUGGEST_ALTERNATIVES|SUGGEST_DATES|SUGGEST_ROUTING|ADJUST_BUDGET|ASK_USER",
  "recovery_message": "Friendly, helpful 2-3 sentence explanation with clear next steps",
  "alternatives": [
    {"type": "destination|date|route|budget", "label": "Short label", "value": "Actionable value e.g. '2026-08-01' or 'Alappuzha'", "reason": "Why this helps"}
  ],
  "quick_replies": ["Try different dates", "Show alternative destinations", "Adjust budget"]
}"""

RECOVERY_USER = """ORIGINAL REQUEST: "{original_request}"

PLAN DETAILS:
  Destination: {destination} ({iata})
  Dates: {departure_date} → {return_date} ({nights} nights)
  Guests: {guests} ({adults} adults, {children} children)
  Budget: £{budget}

FAILURE REASON: "{failure_reason}"
FAILED LAYER: {failed_layer}

What went wrong and how should we recover? Provide practical alternatives."""


def analyse_failure(
    failure_reason: str,
    failed_layer: str,
    original_message: str,
    plan_context: dict,
    session_id: str = "",
) -> dict:
    """
    Analyse any planning failure and return intelligent recovery options.

    Args:
        failure_reason:   The guardrail failure reason string
        failed_layer:     Which guardrail layer failed (L1_INPUT, L2b_FACTUAL, etc.)
        original_message: The user's original message
        plan_context:     Dict with destination, dates, guests, budget
        session_id:       For logging

    Returns:
        {
          "failure_category": str,
          "plain_english": str,
          "recovery_type": str,
          "recovery_message": str,
          "alternatives": list[dict],
          "quick_replies": list[str],
          "source": "llm" | "rule_based",
        }
    """
    # Try LLM analysis first
    result = _llm_analyse(failure_reason, failed_layer, original_message, plan_context)
    if result:
        result["source"] = "llm"
        log.info("Intelligent recovery via LLM: %s → %s",
                 result.get("failure_category"), result.get("recovery_type"))
        return result

    # Deterministic fallback — rule-based category detection
    result = _rule_based_recovery(failure_reason, failed_layer, original_message, plan_context)
    result["source"] = "rule_based"
    log.info("Intelligent recovery via rules: %s → %s",
             result.get("failure_category"), result.get("recovery_type"))
    return result


def build_recovery_response(
    recovery: dict,
    session_id: str,
    original_message: str,
    plan_context: dict,
) -> dict:
    """
    Build the full API response for a failed plan.
    Includes the recovery message, alternatives, and optionally destination suggestions.
    """
    dest          = plan_context.get("destination", "your destination")
    failure_cat   = recovery.get("failure_category", "OTHER")
    recovery_type = recovery.get("recovery_type", "ASK_USER")
    message       = recovery.get("recovery_message", "Something went wrong. Please try again.")
    alternatives  = recovery.get("alternatives", [])
    quick_replies = recovery.get("quick_replies", ["Try again", "Different destination"])

    # If recovery involves alternative destinations, fetch LLM suggestions
    destination_suggestions = []
    if recovery_type in ("SUGGEST_ALTERNATIVES",) or failure_cat == "NO_SEATS":
        destination_suggestions = _get_alternative_suggestions(
            original_message, dest, failure_cat, plan_context
        )

    # Build structured date alternatives for seat/route failures
    date_alternatives = []
    if failure_cat in ("NO_SEATS", "INVALID_ROUTE") and plan_context.get("departure_date"):
        date_alternatives = _suggest_date_alternatives(plan_context["departure_date"])

    return {
        "status":               "plan_failed",
        "failure_category":     failure_cat,
        "plain_english":        recovery.get("plain_english", ""),
        "recovery_type":        recovery_type,
        "message":              message,
        "alternatives":         alternatives,
        "date_alternatives":    date_alternatives,
        "quick_replies":        quick_replies,
        "suggestions":          destination_suggestions,
        "is_suggestions":       bool(destination_suggestions),
        "summary":              message,
        "conversation_state":   "recovery",
        "recovery_source":      recovery.get("source", "unknown"),
    }


# ── LLM Analysis ─────────────────────────────────────────────────────────────

def _llm_analyse(
    failure_reason: str, failed_layer: str,
    original_message: str, plan_context: dict,
) -> Optional[dict]:
    try:
        from llm.waterfall import get_waterfall
        from config import Config
        wf = get_waterfall()
        intent  = plan_context.get("intent", {})
        dates   = intent.get("dates", {}) or plan_context.get("dates", {})

        user = RECOVERY_USER.format(
            original_request = original_message[:200],
            destination      = intent.get("destination") or plan_context.get("destination", "Unknown"),
            iata             = intent.get("city_code")   or plan_context.get("iata", "?"),
            departure_date   = dates.get("departure_date", "?"),
            return_date      = dates.get("return_date", "?"),
            nights           = dates.get("nights", "?"),
            guests           = intent.get("guests")  or plan_context.get("guests", 2),
            adults           = intent.get("adults")  or plan_context.get("adults", 2),
            children         = intent.get("children")or plan_context.get("children", 0),
            budget           = intent.get("budget_gbp") or plan_context.get("budget_gbp", 3000),
            failure_reason   = failure_reason[:300],
            failed_layer     = failed_layer,
        )

        # Only use real LLM providers — template can't reason about failures
        for pname in getattr(Config, "LLM_WATERFALL", ["groq", "gemini", "anthropic"]):
            if pname == "template":
                continue
            provider = getattr(wf, "providers", {}).get(pname)
            if not provider or not provider.is_available():
                continue
            try:
                resp = provider.complete(RECOVERY_SYSTEM, user, max_tokens=500, temperature=0.3)
                if resp.success and resp.text:
                    parsed = _parse_recovery(resp.text)
                    if parsed:
                        return parsed
            except Exception as e:
                log.debug("Recovery LLM %s error: %s", pname, e)
            break  # Only try one LLM
    except Exception as e:
        log.debug("LLM recovery error: %s", e)
    return None


def _parse_recovery(text: str) -> Optional[dict]:
    try:
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            text  = parts[1] if len(parts) >= 3 else text
            if text.lower().startswith("json"):
                text = text[4:]
        s = text.find("{"); e = text.rfind("}")
        if s != -1 and e != -1:
            data = json.loads(text[s:e+1])
            # Validate required fields
            if data.get("recovery_message") and data.get("failure_category"):
                data.setdefault("alternatives",  [])
                data.setdefault("quick_replies", ["Try different dates", "Show alternatives"])
                return data
    except Exception as ex:
        log.debug("Recovery parse error: %s", ex)
    return None


# ── Rule-based fallback ───────────────────────────────────────────────────────

def _rule_based_recovery(
    reason: str, layer: str,
    original_message: str, plan_context: dict,
) -> dict:
    """
    Deterministic failure categorisation when LLM is unavailable.
    Covers the most common failure patterns.
    """
    r = reason.lower()
    intent = plan_context.get("intent", {})
    dest   = intent.get("destination") or plan_context.get("destination", "your destination")
    guests = intent.get("guests") or plan_context.get("guests", 2)
    budget = intent.get("budget_gbp") or plan_context.get("budget_gbp", 3000)
    dates  = (intent.get("dates") or plan_context.get("dates") or {})
    dep    = dates.get("departure_date", "")

    # ── No seats ──────────────────────────────────────────────────────────────
    if "no_seats" in r or "seat" in r or "seats" in r or "only" in r and "guests" in r:
        return {
            "failure_category": "NO_SEATS",
            "plain_english":    f"The selected flights are fully booked for {guests} passengers.",
            "recovery_type":    "SUGGEST_ALTERNATIVES",
            "recovery_message": (
                f"Unfortunately the flights to {dest} are fully booked for {guests} guests on these dates. "
                f"Here are some options to try:\n\n"
                f"• **Different dates** — shifting by 1–2 weeks often opens availability\n"
                f"• **Alternative destinations** — similar places with better availability\n"
                f"• **Split booking** — two separate bookings if your group can travel independently"
            ),
            "alternatives": [
                {"type":"date",        "label":"1 week earlier",  "value":_offset_date(dep,-7),  "reason":"More availability"},
                {"type":"date",        "label":"1 week later",    "value":_offset_date(dep,+7),  "reason":"More availability"},
                {"type":"date",        "label":"2 weeks later",   "value":_offset_date(dep,+14), "reason":"More options"},
                {"type":"destination", "label":"Similar destination","value":"",                  "reason":"More flights available"},
            ],
            "quick_replies": ["Try 1 week earlier", "Try 1 week later", "Show similar destinations"],
        }

    # ── Budget exceeded ───────────────────────────────────────────────────────
    if "budget" in r or "cost" in r or "exceed" in r or "over" in r:
        return {
            "failure_category": "BUDGET_EXCEEDED",
            "plain_english":    f"The trip cost exceeds the £{budget} budget.",
            "recovery_type":    "ADJUST_BUDGET",
            "recovery_message": (
                f"The itinerary to {dest} costs more than £{budget}. "
                f"Here are ways to bring it within budget:\n\n"
                f"• **Shorter trip** — fewer nights reduces hotel costs significantly\n"
                f"• **3-star hotel** — same destination, comfortable but less expensive\n"
                f"• **Shoulder season** — travel just outside peak season for much lower fares\n"
                f"• **Increase budget** — tell me your maximum and I'll find the best option"
            ),
            "alternatives": [
                {"type":"budget",  "label":"Increase to £" + str(int(budget*1.3)), "value":str(int(budget*1.3)), "reason":"30% more budget"},
                {"type":"budget",  "label":"5 nights instead", "value":"5", "reason":"Shorter stay reduces cost"},
                {"type":"budget",  "label":"3-star hotel",      "value":"3",    "reason":"Lower hotel grade"},
            ],
            "quick_replies": ["Increase my budget", "Shorter trip", "3-star hotel", "Different dates"],
        }

    # ── Route / no flights ────────────────────────────────────────────────────
    if "route" in r or "no flight" in r or "invalid" in r and "iata" not in r:
        return {
            "failure_category": "INVALID_ROUTE",
            "plain_english":    f"No direct flights found for this route to {dest}.",
            "recovery_type":    "SUGGEST_ROUTING",
            "recovery_message": (
                f"We couldn't find flights to {dest} that match your criteria. "
                f"Options:\n\n"
                f"• **Connecting flights** — via a hub airport (Dubai, Delhi, Doha)\n"
                f"• **Nearest airport** — we can check nearby airports for better connectivity\n"
                f"• **Alternative destination** — similar places with good flight connections"
            ),
            "alternatives": [
                {"type":"route",       "label":"Via Dubai (DXB)",  "value":"DXB", "reason":"Good connectivity to Asia/India"},
                {"type":"route",       "label":"Via Delhi (DEL)",   "value":"DEL", "reason":"Good for Indian destinations"},
                {"type":"destination", "label":"Alternative",       "value":"",    "reason":"Better flight options"},
            ],
            "quick_replies": ["Try connecting via Dubai", "Show similar destinations"],
        }

    # ── Date issues ───────────────────────────────────────────────────────────
    if "date" in r or "past" in r or "future" in r or "departure" in r:
        return {
            "failure_category": "INVALID_DATE",
            "plain_english":    "The travel date needs to be corrected.",
            "recovery_type":    "ASK_USER",
            "recovery_message": (
                "The departure date doesn't look right. "
                "Could you confirm when you'd like to travel? "
                "For example: 'October next year' or 'Christmas for 1 week'."
            ),
            "alternatives": [],
            "quick_replies": ["October", "Christmas", "Next summer", "Specify a date"],
        }

    # ── Confidence / accuracy ─────────────────────────────────────────────────
    if "accuracy" in r or "confidence" in r or "unknown" in r or "iata" in r:
        return {
            "failure_category": "CONFIDENCE_LOW",
            "plain_english":    "The AI wasn't confident enough about the destination details.",
            "recovery_type":    "ASK_USER",
            "recovery_message": (
                f"I couldn't build a confident itinerary for {dest}. "
                f"Could you help me with a bit more detail? For example:\n\n"
                f"• Which airport would you fly from?\n"
                f"• Any specific area of {dest} you want to visit?\n"
                f"• Or shall I suggest similar destinations with better flight options?"
            ),
            "alternatives": [],
            "quick_replies": ["Suggest alternatives", "Try again with more details"],
        }

    # ── Generic fallback ──────────────────────────────────────────────────────
    return {
        "failure_category": "OTHER",
        "plain_english":    "The trip plan couldn't be completed.",
        "recovery_type":    "SUGGEST_ALTERNATIVES",
        "recovery_message": (
            f"I wasn't able to complete the itinerary to {dest}. "
            f"Would you like me to:\n\n"
            f"• Suggest similar destinations that might work better?\n"
            f"• Try different dates or travel options?\n"
            f"• Simplify the request (e.g. fewer guests, wider date range)?"
        ),
        "alternatives": [],
        "quick_replies": ["Show similar destinations", "Try different dates", "Simplify request"],
    }


# ── Alternative suggestions ───────────────────────────────────────────────────

def _get_alternative_suggestions(
    original_message: str, failed_dest: str,
    failure_category: str, plan_context: dict,
) -> list:
    """Get destination suggestions relevant to what the user originally wanted."""
    try:
        from reasoning.llm_destination_suggester import suggest_destinations_with_llm
        # Build a query that captures the intent but not the failed destination
        query = (
            f"{original_message} "
            f"— but NOT {failed_dest} which has no availability"
            if failure_category == "NO_SEATS"
            else f"alternatives to {failed_dest}: {original_message}"
        )
        result = suggest_destinations_with_llm(
            query=query,
            customer_profile=plan_context.get("customer_profile"),
        )
        if result and result.get("suggestions"):
            # Filter out the failed destination
            return [
                s for s in result["suggestions"]
                if s.get("destination","").lower() != failed_dest.lower()
            ]
    except Exception as e:
        log.debug("Alternative suggestions error: %s", e)
    return []


def _suggest_date_alternatives(departure_date: str) -> list:
    """Generate ±1 and ±2 week date alternatives."""
    offsets = [(-7,"1 week earlier"), (7,"1 week later"),
               (-14,"2 weeks earlier"), (14,"2 weeks later")]
    result  = []
    for days, label in offsets:
        new_date = _offset_date(departure_date, days)
        if new_date:
            result.append({"label": label, "date": new_date, "days_offset": days})
    return result


def _offset_date(date_str: str, days: int) -> str:
    """Offset a YYYY-MM-DD date string by N days."""
    try:
        from datetime import datetime, timedelta
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (d + timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        return ""
