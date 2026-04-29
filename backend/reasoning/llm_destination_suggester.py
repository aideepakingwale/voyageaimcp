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
Your job: given what a traveller is asking for, suggest exactly 3 perfect destinations.

RULES:
1. Suggest ANY destination in the world — not from a fixed list
2. Read the user profile carefully and personalise suggestions
3. Avoid destinations already in their travel history
4. Return ONLY valid JSON — no markdown, no explanation
5. Always include a real IATA airport code for the nearest major airport
6. Keep descriptions specific and evocative — tell them WHY this destination fits THEIR ask
7. Budget should be realistic return flight + 7 nights hotel from UK in GBP

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
    """Parse LLM response into list of suggestion dicts."""
    try:
        # Strip markdown fences
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            text = parts[1] if len(parts) >= 3 else text
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        # Find JSON array
        start = text.find("[")
        end   = text.rfind("]")
        if start != -1 and end != -1:
            text = text[start:end+1]

        data = json.loads(text)
        if isinstance(data, list) and len(data) >= 1:
            # Validate each suggestion has minimum fields
            valid = []
            for item in data[:3]:
                if item.get("destination") and item.get("iata"):
                    # Ensure IATA is uppercase and exactly 3 letters
                    iata = str(item["iata"]).upper().strip()
                    if not re.match(r"^[A-Z]{3}$", iata):
                        # Try to extract 3-letter code from the field
                        match = re.search(r"\b([A-Z]{3})\b", iata)
                        iata  = match.group(1) if match else "UNK"
                    item["iata"] = iata
                    valid.append(item)
            return valid if valid else None
    except Exception as e:
        log.debug("Suggestion parse error: %s | text: %s", e, text[:100])
    return None


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
            line += f"  ·  💷 ~£{budget:,}/pp for {dur}"
        lines.append(line)

    lines.append(
        "\nWhich destination interests you? Reply with the number or name "
        "and I'll build a complete personalised itinerary."
    )
    return "\n\n".join(lines)


def _fallback_suggestions(query: str, visited: list) -> list:
    """
    Simple knowledge-based fallback when LLM is unavailable.
    Returns generic suggestions for common query types.
    """
    q = query.lower()

    # Broad sentiment/theme matching
    QUICK_MAP = {
        ("holy", "sacred", "spiritual", "pilgrimage", "religious", "temple", "shrine",
         "mandir", "gurudwara", "mosque", "church", "monastery"):
            [{"destination":"Varanasi","country":"India","iata":"VNS",
              "tagline":"The oldest living city on Earth — sacred Ganges ghats and ancient temples.",
              "why_this_fits":"India's holiest Hindu city where every ghat has spiritual significance.",
              "highlights":["Ganga Aarti ceremony","Kashi Vishwanath Temple","Sarnath Buddhist site"],
              "best_time":"Oct–Mar","budget_pp_gbp":1600,"duration_suggestion":"5–7 nights",
              "sentiment_match":"Deeply spiritual immersion"},
             {"destination":"Amritsar","country":"India","iata":"ATQ",
              "tagline":"Home of the magnificent Golden Temple — a beacon of Sikh faith and humanity.",
              "why_this_fits":"The most visited place in India, welcoming all faiths equally.",
              "highlights":["Golden Temple (Harmandir Sahib)","Langar community kitchen","Wagah Border ceremony"],
              "best_time":"Oct–Mar","budget_pp_gbp":1200,"duration_suggestion":"3–5 nights",
              "sentiment_match":"Profound peace and community"},
             {"destination":"Bodh Gaya","country":"India","iata":"GAY",
              "tagline":"Where Buddha attained enlightenment under the Bodhi Tree.",
              "why_this_fits":"The most sacred site in Buddhism, with monasteries from 12 countries.",
              "highlights":["Mahabodhi Temple (UNESCO)","Bodhi Tree","International monasteries"],
              "best_time":"Oct–Mar","budget_pp_gbp":1000,"duration_suggestion":"3–4 nights",
              "sentiment_match":"Serene contemplation and history"}],

        ("beach", "sea", "ocean", "sun", "sand", "coast", "island"):
            [{"destination":"Maldives","country":"Maldives","iata":"MLE",
              "tagline":"Overwater villas above impossibly clear lagoons.",
              "why_this_fits":"The ultimate beach escape — coral atolls, reef snorkelling, sunset dhow cruises.",
              "highlights":["Overwater bungalows","World-class snorkelling","Sunset cruises"],
              "best_time":"Nov–Apr","budget_pp_gbp":3800,"duration_suggestion":"7–10 nights",
              "sentiment_match":"Pure relaxation and luxury"},
             {"destination":"Seychelles","country":"Seychelles","iata":"SEZ",
              "tagline":"Prehistoric granite boulders and powder-white beaches.",
              "why_this_fits":"Uncrowded luxury islands with some of the world's best beaches.",
              "highlights":["Anse Lazio beach","Giant tortoise sanctuary","Island hopping"],
              "best_time":"Apr–May, Oct–Nov","budget_pp_gbp":4200,"duration_suggestion":"7–10 nights",
              "sentiment_match":"Exclusive island paradise"},
             {"destination":"Bali","country":"Indonesia","iata":"DPS",
              "tagline":"Temple culture meets tropical beaches and terraced rice paddies.",
              "why_this_fits":"Perfect blend of beach, culture and spirituality.",
              "highlights":["Ubud Sacred Monkey Forest","Tanah Lot temple","Seminyak beach clubs"],
              "best_time":"Apr–Oct","budget_pp_gbp":2800,"duration_suggestion":"10–14 nights",
              "sentiment_match":"Exotic adventure and relaxation"}],

        ("adventure", "trek", "hike", "outdoor", "wild", "explore", "extreme"):
            [{"destination":"Nepal","country":"Nepal","iata":"KTM",
              "tagline":"Everest base camp, ancient temples and the world's highest peaks.",
              "why_this_fits":"The ultimate adventure destination — trekking through Himalayan landscapes.",
              "highlights":["Everest Base Camp trek","Annapurna Circuit","Kathmandu Durbar Square"],
              "best_time":"Mar–May, Sep–Nov","budget_pp_gbp":2200,"duration_suggestion":"14–21 nights",
              "sentiment_match":"Epic challenge and reward"},
             {"destination":"Patagonia","country":"Argentina/Chile","iata":"PMC",
              "tagline":"End of the earth — glaciers, granite towers and untamed wilderness.",
              "why_this_fits":"The world's most dramatic landscapes for serious hikers.",
              "highlights":["Torres del Paine National Park","Perito Moreno Glacier","Los Glaciares"],
              "best_time":"Nov–Mar","budget_pp_gbp":3500,"duration_suggestion":"14–21 nights",
              "sentiment_match":"Raw wilderness and achievement"},
             {"destination":"Iceland","country":"Iceland","iata":"KEF",
              "tagline":"Fire and ice — volcanos, geysers, Northern Lights and midnight sun.",
              "why_this_fits":"Otherworldly adventure in Europe's most dramatic landscape.",
              "highlights":["Northern Lights (Sep–Mar)","Golden Circle","Blue Lagoon"],
              "best_time":"Jun–Aug (midnight sun) or Dec–Feb (Northern Lights)",
              "budget_pp_gbp":2800,"duration_suggestion":"7–10 nights",
              "sentiment_match":"Awe and wonder"}],

        ("luxury", "five star", "5 star", "indulge", "pamper", "exclusive"):
            [{"destination":"Maldives","country":"Maldives","iata":"MLE",
              "tagline":"The world's most exclusive overwater villas — total seclusion.",
              "why_this_fits":"Unrivalled luxury in your own private island setting.",
              "highlights":["Private overwater villa with pool","World-class spa","Private beach"],
              "best_time":"Nov–Apr","budget_pp_gbp":5500,"duration_suggestion":"7–10 nights",
              "sentiment_match":"Ultimate luxury escape"},
             {"destination":"Amalfi Coast","country":"Italy","iata":"NAP",
              "tagline":"Cliffside villages above a turquoise sea — la dolce vita.",
              "why_this_fits":"Italy's most glamorous coastline with 5-star cliff-top hotels.",
              "highlights":["Positano village","Private boat trips","Michelin dining"],
              "best_time":"May–Jun, Sep","budget_pp_gbp":4500,"duration_suggestion":"7–10 nights",
              "sentiment_match":"Glamour and sophistication"},
             {"destination":"Bora Bora","country":"French Polynesia","iata":"BOB",
              "tagline":"The iconic overwater bungalow birthplace — Tahitian paradise.",
              "why_this_fits":"The world's most photographed luxury destination for good reason.",
              "highlights":["Overwater bungalows","Lagoon snorkelling","Mount Otemanu views"],
              "best_time":"May–Oct","budget_pp_gbp":6500,"duration_suggestion":"7–10 nights",
              "sentiment_match":"Once-in-a-lifetime luxury"}],

        ("food", "culinary", "cuisine", "eat", "foodie", "gastronomy", "restaurant"):
            [{"destination":"Tokyo","country":"Japan","iata":"NRT",
              "tagline":"More Michelin stars than any city on Earth — a foodie's paradise.",
              "why_this_fits":"Japan's food culture is meticulous, diverse and extraordinary at every level.",
              "highlights":["Tsukiji outer market","Ramen exploration","Michelin-starred dining"],
              "best_time":"Mar–May, Sep–Nov","budget_pp_gbp":3200,"duration_suggestion":"10–14 nights",
              "sentiment_match":"Culinary obsession"},
             {"destination":"Bangkok","country":"Thailand","iata":"BKK",
              "tagline":"Street food capital of the world — every meal is an adventure.",
              "why_this_fits":"From $1 pad thai to world-class fine dining, Bangkok does it all.",
              "highlights":["Street food night markets","Floating markets","Cooking classes"],
              "best_time":"Nov–Feb","budget_pp_gbp":2000,"duration_suggestion":"7–10 nights",
              "sentiment_match":"Sensory food adventure"},
             {"destination":"Barcelona","country":"Spain","iata":"BCN",
              "tagline":"Tapas culture, Michelin masters and La Boqueria market magic.",
              "why_this_fits":"Catalonia's food scene blends tradition with avant-garde creativity.",
              "highlights":["La Boqueria market","El Born neighbourhood tapas","Catalan fine dining"],
              "best_time":"Apr–Jun, Sep–Oct","budget_pp_gbp":1800,"duration_suggestion":"5–7 nights",
              "sentiment_match":"European culinary culture"}],

        ("solo", "alone", "by myself", "just me", "single traveller"):
            [{"destination":"Japan","country":"Japan","iata":"NRT",
              "tagline":"The world's safest solo destination — perfectly designed for one.",
              "why_this_fits":"Solo-friendly culture, excellent transport, incredible food at any budget.",
              "highlights":["Bullet train network","Capsule hotels","Solo dining culture"],
              "best_time":"Mar–May, Sep–Nov","budget_pp_gbp":2800,"duration_suggestion":"14 nights",
              "sentiment_match":"Safe independence and discovery"},
             {"destination":"Lisbon","country":"Portugal","iata":"LIS",
              "tagline":"Europe's sunniest capital — walkable, friendly and deeply soulful.",
              "why_this_fits":"Ideal solo city — affordable, English-speaking, excellent hostels.",
              "highlights":["Alfama neighbourhood","Fado music evenings","Day trip to Sintra"],
              "best_time":"Apr–Oct","budget_pp_gbp":1200,"duration_suggestion":"5–7 nights",
              "sentiment_match":"Solo freedom and connection"},
             {"destination":"Chiang Mai","country":"Thailand","iata":"CNX",
              "tagline":"Digital nomad mecca meets ancient temples and elephant sanctuaries.",
              "why_this_fits":"Warm, cheap, safe and full of like-minded solo travellers.",
              "highlights":["Elephant Nature Park","Doi Inthanon National Park","Night Bazaar"],
              "best_time":"Nov–Feb","budget_pp_gbp":1400,"duration_suggestion":"7–14 nights",
              "sentiment_match":"Affordable solo adventure"}],

        ("family", "kids", "children", "child"):
            [{"destination":"Japan","country":"Japan","iata":"NRT",
              "tagline":"Bullet trains, robot restaurants and safe streets — kids are amazed.",
              "why_this_fits":"Japan is famously child-friendly with endless interactive experiences.",
              "highlights":["DisneySea Tokyo","teamLab digital art","Shinkansen rides"],
              "best_time":"Mar–May, Sep–Nov","budget_pp_gbp":3000,"duration_suggestion":"14 nights",
              "sentiment_match":"Family wonder"},
             {"destination":"Tenerife","country":"Spain","iata":"TFS",
              "tagline":"Year-round sunshine, Siam Park and Mount Teide adventures.",
              "why_this_fits":"Europe's best family island — beaches, theme parks and easy flight.",
              "highlights":["Siam Park","Loro Parque","Mount Teide cable car"],
              "best_time":"Year-round","budget_pp_gbp":1600,"duration_suggestion":"7–10 nights",
              "sentiment_match":"Stress-free family fun"},
             {"destination":"Costa Rica","country":"Costa Rica","iata":"SJO",
              "tagline":"Rainforest zip-lines, volcanic beaches and sloths — kids go wild.",
              "why_this_fits":"Nature adventure that sparks curiosity in children of all ages.",
              "highlights":["Arenal Volcano","Manuel Antonio National Park","Zip-lining"],
              "best_time":"Dec–Apr","budget_pp_gbp":3200,"duration_suggestion":"10–14 nights",
              "sentiment_match":"Family adventure and education"}],
    }

    for keywords, suggestions in QUICK_MAP.items():
        if any(kw in q for kw in keywords):
            # Filter already visited
            return [s for s in suggestions if s["destination"] not in visited][:3] or suggestions[:3]

    # Generic fallback
    return [
        {"destination":"Japan","country":"Japan","iata":"NRT",
         "tagline":"One of the world's most rewarding and accessible travel destinations.",
         "why_this_fits":"Exceptional safety, culture, food and transport for any traveller.",
         "highlights":["Rich culture","World-class cuisine","Unique experiences"],
         "best_time":"Mar–May, Sep–Nov","budget_pp_gbp":3200,"duration_suggestion":"10–14 nights",
         "sentiment_match":"Unforgettable discovery"},
        {"destination":"Portugal","country":"Portugal","iata":"LIS",
         "tagline":"Europe's most charming destination — beautiful, affordable and sunny.",
         "why_this_fits":"Great food, history, beaches and weather at excellent value.",
         "highlights":["Historic Lisbon","Algarve beaches","Douro Valley wine"],
         "best_time":"Apr–Oct","budget_pp_gbp":1500,"duration_suggestion":"7–10 nights",
         "sentiment_match":"European charm"},
        {"destination":"Thailand","country":"Thailand","iata":"BKK",
         "tagline":"Ancient temples, tropical beaches and some of the world's best food.",
         "why_this_fits":"Incredible value, warmth and diversity for every type of traveller.",
         "highlights":["Bangkok street food","Northern Thailand trekking","Southern islands"],
         "best_time":"Nov–Feb","budget_pp_gbp":1800,"duration_suggestion":"10–14 nights",
         "sentiment_match":"Exotic Asia at great value"},
    ]


# ── Helpers ───────────────────────────────────────────────────

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
