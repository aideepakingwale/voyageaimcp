"""
VoyageAI Conversational LLM Engine
=====================================
Sends the FULL conversation to the LLM as a proper chat.
The LLM understands context, sentiment, and generates both:
  1. A structured action (what to do with the plan)
  2. A human response (what to say to the user)

This replaces the fragmented intent+extraction+modification pipeline
with a single intelligent LLM call that sees everything.
"""
import json
import logging
from datetime import datetime

log = logging.getLogger("voyageai.reasoning")

_TODAY = datetime.now().strftime("%Y-%m-%d")

SYSTEM = f"""You are VoyageAI, an expert autonomous travel planning assistant.
Today is {_TODAY}.

You have access to a user's current travel plan and conversation history.
Your job: understand EXACTLY what the user wants and respond appropriately.

RESPONSE RULES:
1. If user mentions a vague place ("North India", "holy places", "somewhere warm")
   → Pick a specific IATA city code — never return the same destination as before
2. "North India" → DEL (Delhi) or AMD (Amritsar) or JAI (Jaipur) or VNS (Varanasi)
3. "South India" → MAA (Chennai) or COK (Kochi) or BLR (Bangalore)
4. Never ask for information already in the conversation
5. If changing destination → set new IATA code immediately, don't ask
6. Understand sentiment: "something more peaceful" = quieter destination
7. Match user's EXACT request — if they say "North India" don't suggest Goa

Return ONLY this JSON:
{{
  "action": "plan|modify|clarify|confirm|cancel|suggest",
  "modification_type": "destination|dates|guests|hotel|flight|budget|null",
  "destination": "City name or null",
  "destination_iata": "IATA code or null",
  "departure_date": "YYYY-MM-DD or null",
  "nights": number_or_null,
  "guests": number_or_null,
  "adults": number_or_null,
  "children": number_or_null,
  "budget_gbp": number_or_null,
  "min_hotel_stars": number_or_null,
  "direct_flight": true_false_or_null,
  "response": "Your conversational reply to the user (1-2 sentences max)",
  "reasoning": "What you understood the user wants"
}}"""

USER_TEMPLATE = """CURRENT PLAN:
{plan}

CONVERSATION HISTORY:
{history}

USER SAYS: "{message}"

Understand what the user wants and respond accordingly."""


def process_with_llm(
    message: str,
    session_id: str,
    history: list,
    last_itinerary: dict | None,
    customer_ctx: dict = None,
) -> dict | None:
    """
    Send the full conversation to the LLM and get a structured action + response.
    Returns None if LLM unavailable.
    """
    plan_summary = _plan_summary(last_itinerary)
    history_str  = _format_history(history[-8:])

    try:
        from llm.waterfall import get_waterfall
        wf = get_waterfall()
        # Don't use template provider for this — it needs real LLM reasoning
        # Temporarily skip template to force real LLM
        resp = _call_real_llm(wf, plan_summary, history_str, message)
        if resp:
            parsed = _parse(resp)
            if parsed:
                log.info("Conversational LLM response", extra={
                    "session":   session_id,
                    "action":    parsed.get("action"),
                    "dest":      parsed.get("destination_iata"),
                    "mod_type":  parsed.get("modification_type"),
                    "reasoning": parsed.get("reasoning","")[:80],
                })
                return parsed
    except Exception as e:
        log.debug("Conversational LLM error: %s", e)
    return None


def _call_real_llm(wf, plan: str, history: str, message: str) -> str | None:
    """Call Groq or Gemini specifically — skip template provider."""
    from llm.waterfall import get_waterfall
    from config import Config

    system = SYSTEM
    user   = USER_TEMPLATE.format(plan=plan, history=history, message=message)

    # Try providers in order, skip template
    for pname in Config.LLM_WATERFALL:
        if pname == "template":
            continue
        provider = wf.providers.get(pname)
        if not provider or not provider.is_available():
            continue
        try:
            import time
            t0   = time.time()
            resp = provider.complete(system, user, max_tokens=400, temperature=0.2)
            if resp.success:
                log.info("Conversational LLM success", extra={
                    "provider":  pname,
                    "latency_ms":round((time.time()-t0)*1000,1),
                })
                return resp.text
        except Exception as e:
            log.debug("Provider %s failed: %s", pname, e)
    return None


def _parse(text: str) -> dict | None:
    try:
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            text = parts[1] if len(parts) >= 3 else text
            if text.startswith("json"):
                text = text[4:]
        start = text.find("{"); end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end+1]
        data = json.loads(text)
        # Clean nulls
        for k, v in list(data.items()):
            if v in ("null", "none", "", "N/A"):
                data[k] = None
        # Validate IATA
        if data.get("destination_iata"):
            iata = str(data["destination_iata"]).upper().strip()
            import re
            if not re.match(r"^[A-Z]{3}$", iata):
                data["destination_iata"] = None
        return data
    except Exception as e:
        log.debug("Conversational LLM parse error: %s", e)
        return None


def _plan_summary(itinerary: dict | None) -> str:
    if not itinerary:
        return "(no current plan)"
    intent = itinerary.get("intent", {})
    dates  = intent.get("dates", {})
    return (
        f"Destination: {intent.get('destination')} ({intent.get('city_code')})\n"
        f"Dates: {dates.get('departure_date')} → {dates.get('return_date')} ({dates.get('nights')} nights)\n"
        f"Guests: {intent.get('guests')} ({intent.get('adults')} adults, {intent.get('children')} children)\n"
        f"Budget: £{intent.get('budget_gbp')}\n"
        f"Hotel: {intent.get('preferences',{}).get('min_hotel_stars','?')}★\n"
        f"Total: £{itinerary.get('total_cost_gbp','?')}"
    )


def _format_history(history: list) -> str:
    if not history:
        return "(no prior conversation)"
    return "\n".join(
        f"[{t.get('role','user').upper()}]: {str(t.get('content',''))[:300]}"
        for t in history
    )
