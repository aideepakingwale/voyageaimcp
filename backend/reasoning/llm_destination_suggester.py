"""
VoyageAI LLM Destination Suggester
====================================
Uses the LLM to generate destination suggestions from ANY natural language query.
No hardcoded lists. No predefined themes. Pure LLM reasoning.

The LLM:
  - Understands any query: "holy places", "somewhere peaceful", "adventure for solo
    traveller who loves street food", "places like Bali but less crowded", etc.
  - Reads the user's full profile (interests, past trips, loyalty tier, travel style)
  - Generates 3 tailored suggestions with IATA codes, rationale, and practical info
  - Returns structured JSON consumed directly by the suggestion card UI

Flow:
  User: "Holy places from India"
    → LLM prompt: "User wants holy places in India. Their profile: luxury/romance/beach.
                   Suggest 3 destinations they haven't been to."
    → LLM responds: [{destination:"Varanasi",iata:"VNS",why:"...",best_time:"...",budget:1600}]
    → Rendered as suggestion card with LLM-generated descriptions
"""
import json
import logging
import re

log = logging.getLogger("voyageai.reasoning")

SUGGESTION_SYSTEM = """You are VoyageAI's destination expert.
Your job: given what a traveller is asking for, suggest exactly 3 HIGHLY RELEVANT destinations.

CRITICAL SCOPING RULES — read these first:
1. HONOUR THE GEOGRAPHIC SCOPE: If the user asks for "beaches in Kerala India" → ALL 3 must be Kerala beaches (Kovalam, Varkala, Marari). NEVER suggest Maldives or Goa.
   If they ask for "holy places in India" → ALL 3 must be Indian holy cities.
   If they ask for "European cities" → ALL 3 must be European cities.
   NEVER pad with unrelated destinations just to reach 3.

2. STAY ON TOPIC: All 3 suggestions must directly answer what the user asked. No generic fillers.

3. WHEN THE SCOPE IS NARROW: If only 2 perfect answers exist within the scope, name 3 anyway by going deeper — e.g. 3 different Kerala beaches (Kovalam, Varkala, Marari Beach, Cherai, Bekal Fort Beach).

4. Read the user profile for personalisation but NEVER let it override the geographic/thematic scope.

5. Return ONLY valid JSON — no markdown, no explanation.
6. Always include a real IATA airport code for the nearest major airport.
7. Budget = realistic return flight + 7 nights hotel from UK in GBP.

IMPORTANT: Return EXACTLY 3 suggestion objects. All 3 must match the user's specific request.
Never return fewer than 3 objects. Never return a string array like ["City1"].

Return this exact JSON (array of 3 objects):
[
  {
    "destination": "City or place name",
    "country": "Country name",
    "iata": "XXX",
    "tagline": "One vivid sentence — what makes this special for THIS user's request",
    "why_this_fits": "Why this matches what they asked for specifically",
    "highlights": ["top thing 1", "top thing 2", "top thing 3"],
    "best_time": "Month range e.g. Oct–Mar",
    "budget_pp_gbp": 2500,
    "duration_suggestion": "7–10 nights",
    "sentiment_match": "How this addresses the user's emotional ask"
  }
]"""

SUGGESTION_USER = """USER'S REQUEST: "{query}"

USER PROFILE:
  Name: {name}
  Travel style: {travel_style}
  Interests: {interests}
  Loyalty tier: {loyalty_tier}
  Typical budget: £{budget}
  Typical trip: {nights} nights
  Already visited: {visited}
  Past trips context: {past_trips}

CONVERSATION CONTEXT:
{context}

Generate 3 destination suggestions that perfectly match what this user is asking for.
Think about their emotional intent, not just the literal words.
Avoid any destination they have already visited."""



def _pad_to_3(suggestions: list, query: str = "travel") -> list:
    """
    Ensure we always return exactly 3 suggestions.
    Uses a targeted LLM retry WITHIN the same scope, not generic fallbacks.
    This prevents "beaches in Kerala" from being padded with Maldives/Seychelles.
    """
    if len(suggestions) >= 3:
        return suggestions[:3]

    already_suggested = [s.get("destination","") for s in suggestions]
    already_iatas     = {s.get("iata") for s in suggestions}
    needed            = 3 - len(suggestions)

    # Targeted retry — ask LLM for MORE suggestions within the same scope
    try:
        from llm.waterfall import get_waterfall
        wf = get_waterfall()
        system = f"""You are a travel expert. The user asked: "{query}"
Suggest exactly {needed} more destinations that DIRECTLY match this request.
Already suggested: {already_suggested} — do NOT repeat these.
Stay within the SAME geographic/thematic scope as the original query.
Return ONLY a JSON array of {needed} objects with keys: destination, country, iata, tagline, why_this_fits, highlights, best_time, budget_pp_gbp, duration_suggestion"""
        user = f'Give me {needed} more destinations for: "{query}". Not: {already_suggested}.'

        resp = wf.complete(system, user, max_tokens=400, temperature=0.5)
        if resp.success and resp.text:
            extras = _parse_suggestions(resp.text)
            if extras:
                for extra in extras:
                    if extra.get("iata") not in already_iatas and len(suggestions) < 3:
                        suggestions.append(extra)
                        already_iatas.add(extra.get("iata"))
    except Exception:
        pass

    # If still short after LLM retry, use thematically-filtered fallback
    if len(suggestions) < 3:
        q_lower = query.lower()
        extras  = _thematic_fallback(q_lower, already_iatas)
        for extra in extras:
            if extra.get("iata") not in already_iatas and len(suggestions) < 3:
                suggestions.append(extra)
                already_iatas.add(extra.get("iata"))

    return suggestions


def _thematic_fallback(query_lower: str, exclude_iatas: set) -> list:
    """
    Previously: hardcoded lists of Kerala beaches, Goa beaches, Indian holy places, etc.
    Now: delegates to LLM with a focused prompt. Returns empty if LLM unavailable.
    This prevents suggesting Agonda to someone who asked for Italian beaches.
    """
    try:
        from llm.waterfall import get_waterfall
        from config import Config
        wf = get_waterfall()
        system = (
            "You are a travel expert. Return ONLY a JSON array of 3 destination objects. "
            "Stay STRICTLY within the geographic/thematic scope of the query. "
            "Each object: {destination, country, iata, tagline, why_this_fits, "
            "highlights (list), best_time, budget_pp_gbp, duration_suggestion}"
        )
        user = f'Suggest 3 destinations matching: "{query_lower}". Exclude iatas: {list(exclude_iatas)}.'
        for pname in getattr(Config,"LLM_WATERFALL",["groq","gemini","anthropic"]):
            if pname == "template": continue
            provider = getattr(wf,"providers",{}).get(pname)
            if not provider or not provider.is_available(): continue
            resp = provider.complete(system, user, max_tokens=500, temperature=0.4)
            if resp.success and resp.text:
                from reasoning.llm_destination_suggester import _parse_suggestions
                results = _parse_suggestions(resp.text)
                if results:
                    return [r for r in results if r.get("iata") not in exclude_iatas]
            break
    except Exception as e:
        log.debug("Thematic fallback LLM error: %s", e)
    return []


def suggest_destinations_with_llm(
    query: str,
    customer_profile: dict = None,
    conversation_history: list = None,
    last_itinerary: dict = None,
) -> dict:
    """
    Generate destination suggestions using the LLM.

    Returns:
    {
        "is_suggestions": True,
        "suggestions": [...],   ← list of 3 suggestion dicts
        "summary": "...",       ← formatted text for chat display
        "intent": {...},        ← first suggestion as the "primary" destination
        "source": "llm" | "fallback",
    }
    """
    profile  = customer_profile or {}
    history  = conversation_history or []
    visited  = _get_visited(profile, last_itinerary)
    context  = _format_context(history[-4:])

    # Build the prompt
    system = SUGGESTION_SYSTEM
    user   = SUGGESTION_USER.format(
        query          = query,
        name           = profile.get("name", "Guest"),
        travel_style   = profile.get("travel_style", "leisure"),
        interests      = ", ".join(profile.get("interests", ["travel"])),
        loyalty_tier   = profile.get("loyalty_tier", "Blue"),
        budget         = profile.get("typical_budget_gbp", 3000),
        nights         = profile.get("typical_nights", 7),
        visited        = ", ".join(visited) if visited else "None recorded",
        past_trips     = _format_past_trips(profile),
        context        = context,
    )

    # Call LLM
    suggestions = None
    source      = "fallback"
    try:
        from llm.waterfall import get_waterfall
        wf   = get_waterfall()
        resp = wf.complete(system, user, max_tokens=800, temperature=0.7)

        if resp.success and resp.text:
            suggestions = _parse_suggestions(resp.text)
            if suggestions:
                source = resp.provider
                log.info("LLM suggestions generated", extra={
                    "provider":    resp.provider,
                    "query":       query[:80],
                    "destinations": [s.get("destination") for s in suggestions],
                })
    except Exception as e:
        log.debug("Suggestion LLM error: %s", e)

    # Fallback: generic well-chosen suggestions based on query keywords
    if not suggestions:
        suggestions = _fallback_suggestions(query, visited)
        source      = "knowledge_fallback"

    if not suggestions:
        return {}

    # Pad to 3 suggestions if LLM returned fewer
    if len(suggestions) < 3:
        suggestions = _pad_to_3(suggestions, query)

    # Build the formatted summary for the chat UI
    summary = _build_summary(query, suggestions)

    # Use first suggestion as the primary intent (for MCP calls if user picks it)
    first   = suggestions[0]
    intent  = {
        "destination":  first.get("destination", ""),
        "city_code":    first.get("iata", ""),
        "country_code": "",
        "dates":        {"departure_date": None, "return_date": None, "nights": 7},
        "guests":       2, "adults": 2, "children": 0,
        "budget_gbp":   first.get("budget_pp_gbp", 3000),
    }

    return {
        "is_suggestions":  True,
        "suggestions":     suggestions,
        "summary":         summary,
        "intent":          intent,
        "destinations":    [s.get("destination") for s in suggestions],
        "total_cost_gbp":  0,
        "recommendations": {"flights": [], "hotels": [], "experiences": []},
        "confidence_scores": {"overall": 0.85},
        "_source":         source,
    }


def _parse_suggestions(text: str) -> list | None:
    """
    Parse LLM response into list of suggestion dicts.
    Handles: well-formed JSON array, partial JSON, plain string arrays,
    itinerary responses that look like suggestions, and everything in between.
    """
    if not text or not text.strip():
        return None

    # Strip markdown fences
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) >= 3 else text
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()

    # ── Attempt 1: well-formed JSON array of objects ──────────
    try:
        start = text.find("[")
        end   = text.rfind("]")
        if start != -1 and end != -1:
            candidate = text[start:end+1]
            data = json.loads(candidate)
            if isinstance(data, list) and len(data) >= 1:
                # Check if it's an array of objects (proper suggestions)
                if isinstance(data[0], dict) and data[0].get("destination"):
                    return _validate_suggestions(data)
                # Array of strings like ["Dubai","Bali"] — convert to minimal dicts
                if isinstance(data[0], str):
                    return _strings_to_suggestions(data)
    except json.JSONDecodeError:
        pass

    # ── Attempt 2: strip trailing garbage and retry ───────────
    try:
        # The LLM often returns ["Dubai"], "extra text..."
        # Find the FIRST complete JSON object or array
        for pattern in [
            r'\[\s*\{[\s\S]*?\}\s*(?:,\s*\{[\s\S]*?\})*\s*\]',  # [{...},{...}]
            r'\{[\s\S]*?"destination"[\s\S]*?\}',                         # single {...}
        ]:
            m = re.search(pattern, text)
            if m:
                fragment = m.group(0)
                # Wrap single object in array
                if fragment.startswith("{"):
                    fragment = "[" + fragment + "]"
                data = json.loads(fragment)
                if isinstance(data, list) and len(data) >= 1:
                    valid = _validate_suggestions(data)
                    if valid:
                        return valid
    except Exception:
        pass

    # ── Attempt 3: extract destinations from any text ─────────
    # The LLM may have generated an itinerary instead of suggestions
    # Look for destination names we can recognise
    try:
        extracted = _extract_destinations_from_text(text)
        if extracted:
            return extracted
    except Exception:
        pass

    log.debug("Suggestion parse failed entirely | text: %s", text[:120])
    return None


def _validate_suggestions(data: list) -> list:
    """Validate and clean a list of suggestion dicts."""
    valid = []
    for item in data[:3]:
        if not isinstance(item, dict):
            continue
        # Must have destination name
        dest = item.get("destination") or item.get("city") or item.get("name")
        if not dest:
            continue
        item["destination"] = dest
        # Resolve/validate IATA
        iata = str(item.get("iata","")).upper().strip()
        if not re.match(r"^[A-Z]{3}$", iata):
            m    = re.search(r"\b([A-Z]{3})\b", iata)
            iata = m.group(1) if m else _quick_iata(dest)
        item["iata"] = iata
        # Ensure required display fields exist
        item.setdefault("tagline",           f"Explore {dest}")
        item.setdefault("why_this_fits",     "")
        item.setdefault("highlights",        [])
        item.setdefault("best_time",         "Year-round")
        item.setdefault("duration_suggestion","7 nights")
        item.setdefault("country",           "")
        # Sanitise budget — LLM may return string like "2500" or "£2,500"
        raw_budget = item.get("budget_pp_gbp", 2500)
        try:
            item["budget_pp_gbp"] = int(str(raw_budget).replace(",","").replace("£","").replace("$","").strip())
        except (ValueError, TypeError):
            item["budget_pp_gbp"] = 2500
        valid.append(item)
    return valid or None


def _strings_to_suggestions(strings: list) -> list:
    """Convert a plain list of destination name strings to suggestion dicts."""
    result = []
    for name in strings[:3]:
        if not isinstance(name, str) or len(name) < 2:
            continue
        iata = _quick_iata(name)
        result.append({
            "destination":       name.strip().title(),
            "country":           "",
            "iata":              iata or "UNK",
            "tagline":           f"Explore {name.strip().title()}",
            "why_this_fits":     "",
            "highlights":        [],
            "best_time":         "Year-round",
            "budget_pp_gbp":     2500,
            "duration_suggestion":"7 nights",
        })
    return result or None


def _extract_destinations_from_text(text: str) -> list | None:
    """Last resort: find destination names in any free text."""
    from reasoning.context_engine import resolve_destination
    # Look for lines starting with numbers (1. Dubai, 2. Bali etc.)
    numbered = re.findall(r"(?:^|\n)\s*\d+\.\s*[*]*([A-Z][\w\s,]+)", text)
    # Also look for bold **Destination** patterns
    bolded   = re.findall(r"\*\*([A-Z][\w\s]+)\*\*", text)
    candidates = (numbered + bolded)[:6]

    result = []
    seen   = set()
    for name in candidates:
        name = name.strip().split(",")[0].strip()  # "Dubai, UAE" -> "Dubai"
        if not name or name in seen or len(name) < 3:
            continue
        city, iata = resolve_destination(name)
        if iata:
            seen.add(name)
            result.append({
                "destination":       city or name,
                "country":           "",
                "iata":              iata,
                "tagline":           f"Explore {city or name}",
                "why_this_fits":     "",
                "highlights":        [],
                "best_time":         "Year-round",
                "budget_pp_gbp":     2500,
                "duration_suggestion":"7 nights",
            })
        if len(result) >= 3:
            break
    return result or None


def _quick_iata(city: str) -> str:
    """Quick IATA lookup for a city name string."""
    try:
        from reasoning.context_engine import resolve_destination
        _, iata = resolve_destination(city)
        return iata or "UNK"
    except Exception:
        return "UNK"


def _build_summary(query: str, suggestions: list) -> str:
    """Build formatted summary text for the suggestion card."""
    lines = [f"Here are 3 destinations that match your ask:\n"]
    for i, s in enumerate(suggestions, 1):
        dest     = s.get("destination", "")
        country  = s.get("country", "")
        tagline  = s.get("tagline", "")
        best     = s.get("best_time", "")
        budget   = s.get("budget_pp_gbp", 0)
        dur      = s.get("duration_suggestion", "7 nights")
        why      = s.get("why_this_fits", "")
        hlights  = s.get("highlights", [])

        line = f"{i}. **{dest}**, {country}"
        if tagline:
            line += f"\n   _{tagline}_"
        if why:
            line += f"\n   {why}"
        if hlights:
            line += f"\n   ✦ " + "  ✦ ".join(hlights[:3])
        if best:
            line += f"\n   📅 Best time: {best}"
        if budget:
            try:
                budget_int = int(str(budget).replace(",","").replace("£","").replace("$","").strip())
                line += f"  ·  💷 ~£{budget_int:,}/pp for {dur}"
            except (ValueError, TypeError):
                line += f"  ·  💷 ~£{budget}/pp for {dur}"
        lines.append(line)

    lines.append(
        "\nWhich destination interests you? Reply with the number or name "
        "and I'll build a complete personalised itinerary."
    )
    return "\n\n".join(lines)


def _fallback_suggestions(query: str, visited: list) -> list:
    """
    Previously: hardcoded lists of destinations.
    Now: returns empty — we rely on LLM for all suggestions.
    Returning empty is honest; returning hardcoded Maldives for a Kerala query is wrong.
    The caller (_pad_to_3) handles the empty case gracefully.
    """
    return []


def _get_visited(profile: dict, last_itinerary: dict) -> list:
    visited = list(profile.get("visited_destinations", []))
    if last_itinerary:
        dest = last_itinerary.get("intent", {}).get("destination")
        if dest and dest not in visited:
            visited.append(dest)
    return visited


def _format_past_trips(profile: dict) -> str:
    trips = profile.get("past_trips", [])
    if not trips:
        return "No history available"
    return "; ".join(t.get("destination", "") for t in trips[:5] if t.get("destination"))


def _format_context(history: list) -> str:
    if not history:
        return "No prior conversation"
    lines = []
    for turn in history[-4:]:
        role    = turn.get("role", "user").upper()
        content = str(turn.get("content", ""))[:200]
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines)
