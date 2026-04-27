"""Chat and demo endpoints — main reasoning pipeline."""
import time
from flask import Blueprint, request, jsonify
from config import Config
from rag.memory_store import memory_store
from reasoning.engine import ReasoningEngine

bp     = Blueprint("chat", __name__)

def _format_visa(d: dict) -> str:
    """Format AI visa data into a concise advisory string."""
    if not d:
        return "Verify entry requirements with destination embassy."
    required  = d.get("visa_required")
    entry     = d.get("entry_type","")
    stay      = d.get("max_stay_days")
    cost      = d.get("cost","")
    
    parts = []
    if required is False or entry == "visa_free":
        parts.append("✅ No visa required")
    elif entry == "eta_required":
        parts.append(f"⚡ ETA required ({cost or 'small fee'})")
    elif entry == "evisa_required":
        parts.append(f"💻 eVisa required ({cost or 'fee applies'})")
    elif entry == "visa_on_arrival":
        parts.append(f"✈️ Visa on arrival ({cost or 'fee at airport'})")
    elif entry == "embassy_visa":
        parts.append("🏛️ Embassy visa required — apply in advance")
    else:
        parts.append("⚠️ Check entry requirements")
    
    if stay:
        parts.append(f"up to {stay} days")
    
    pv = d.get("passport_validity","")
    if pv:
        parts.append(pv)
        
    return ". ".join(parts) + "."


_engine: ReasoningEngine | None = None


def get_engine() -> ReasoningEngine:
    """Lazy singleton — avoids slow imports at module load time."""
    global _engine
    if _engine is None:
        _engine = ReasoningEngine()
    return _engine


@bp.route("/chat", methods=["POST"])
def chat():
    """
    Main reasoning endpoint.
    Accepts: { message, session_id, customer_context? }
    Returns: full itinerary with confidence scores, MCP data, provider info.
    """
    body    = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    sid     = body.get("session_id") or ""
    ctx     = body.get("customer_context")        # optional enrichment

    if not message:
        return jsonify({"error": "message is required"}), 400

    # Create or validate session
    if not sid or not memory_store.get_session(sid):
        sid = memory_store.create_session()

    # GDS session window check
    age = memory_store.session_age_seconds(sid)
    if age > Config.GDS_SESSION_TIMEOUT:
        new_sid = memory_store.create_session()
        return jsonify({
            "session_id": new_sid,
            "status":     "session_expired",
            "message":    "GDS session expired (10-min window). Starting fresh — preferences saved.",
        })

    # Enrich session with customer context if provided
    if ctx:
        for key, val in ctx.items():
            if val:
                memory_store.store_entity(sid, key, val, confidence=1.0)

    # Store detected/user origin airport in session
    origin = body.get("origin_iata", "").strip().upper()
    if origin and len(origin) == 3:
        memory_store.store_entity(sid, "origin_iata", origin, confidence=1.0)
    elif not memory_store.retrieve_entity(sid, "origin_iata"):
        # Detect from request IP if not already known
        from core.geo_location import locate_ip
        ip  = (request.headers.get("X-Forwarded-For","").split(",")[0].strip()
                or request.remote_addr or "")
        geo = locate_ip(ip)
        if geo and geo.get("iata"):
            memory_store.store_entity(sid, "detected_origin_iata", geo["iata"], confidence=0.85)
            memory_store.store_entity(sid, "detected_origin_city", geo["city"], confidence=0.85)

    t0     = time.time()
    result = get_engine().reason(message, sid)
    elapsed = round((time.time() - t0) * 1000)

    return jsonify({
        **result,
        "elapsed_ms":             elapsed,
        "gds_window_remaining_s": max(0, Config.GDS_SESSION_TIMEOUT - age),
    })


@bp.route("/demo", methods=["POST"])
def demo():
    """
    Demo mode — uses MCP data but bypasses LLM (template provider only).
    Useful for demos without any API keys.
    """
    body    = request.get_json(silent=True) or {}
    message = body.get("message", "")
    sid     = body.get("session_id") or memory_store.create_session()

    memory_store.add_turn(sid, "user", message)

    from mcp_servers import MCP_REGISTRY
    flights  = MCP_REGISTRY["flights"].call({"origin":"LHR","destination":"LIS","date":"2025-10-01","adults":4})
    hotels   = MCP_REGISTRY["hotels"].call({"city":"LIS","check_in":"2025-10-01","check_out":"2025-10-08",
                                             "guests":4,"pool":True,"family_rooms":True})
    weather  = MCP_REGISTRY["weather"].call({"city":"LIS","month":10})
    currency = MCP_REGISTRY["currency"].call({"base":"GBP","target":"EUR","amount":3000})
    visa     = MCP_REGISTRY["visa"].call({"passport_country":"GB","destination_country":"PT"})
    maps     = MCP_REGISTRY["maps"].call({"origin":"LIS_AIRPORT","destination":"CHIADO"})
    exp      = MCP_REGISTRY["experiences"].call({"city":"LIS","guests":4,"interests":["family","culture"]})
    cars     = MCP_REGISTRY["cars"].call({"airport":"LIS","guests":4,"days":7})

    bf    = (flights["data"]["flights"] or [{}])[0]
    bh    = (hotels["data"]["hotels"]   or [{}])[0]
    exps  = (exp["data"]["experiences"] or [])[:3]
    fc, hc = bf.get("price_gbp",568), bh.get("total_price_gbp",1365)
    ec    = sum(e.get("total_gbp",0) for e in exps[:2])
    total = round(fc + hc + 65 + ec, 2)
    conf  = {"intent":0.94,"rag":0.88,"gds":0.91,"hallucination":0.92,"overall":0.91}

    result = {
        "session_id":   sid,
        "status":       "awaiting_confirmation",
        "llm_provider": "demo",
        "llm_model":    "mock-v1",
        "llm_cost_usd": 0.0,
        "confidence":   conf,
        "llm_output": {
            "intent": {
                "destination":"Lisbon","city_code":"LIS","country_code":"PT",
                "dates":{"departure_date":"2025-10-01","return_date":"2025-10-08","nights":7,"flexible":False},
                "guests":4,"adults":2,"children":2,"budget_gbp":3000,
                "preferences":{"direct_flight":True,"pool":True,"family_rooms":True,"min_hotel_stars":4},
            },
            "destinations":["Lisbon"],
            "summary":f"7-night family trip to Lisbon for 4 guests. Direct flights from LHR, 4★ pool hotel. Total: £{total:.0f}",
            "recommendations":{
                "flights":[bf],"hotels":[bh],
                "transfers":(cars["data"]["options"] or [{}])[:1],
                "experiences":exps,
                "weather_advisory":weather["data"].get("desc","Mild and pleasant in October."),
                "visa_advisory":    _format_visa(visa.get("data",{})),
                "visa_full":        visa.get("data",{}),
                "currency_tip":f"£1 = €{currency['data'].get('rate',1.17):.2f}",
                "airport_transfer":maps["data"],
            },
            "total_cost_gbp":total,"confidence_scores":conf,
            "reasoning":"Demo mode — template itinerary built from live MCP data.",
        },
        "mcp_data":{"flights":flights,"hotels":hotels,"weather":weather,
                    "currency":currency,"visa":visa,"maps":maps,"experiences":exp,"cars":cars},
        "action_check":{"passed":False,"action":"human_confirm",
                        "reason":f"High-value booking £{total:.0f} requires confirmation",
                        "data":{"amount":total}},
        "elapsed_ms":320,
    }
    memory_store.add_turn(sid, "assistant", result["llm_output"]["summary"])
    return jsonify(result)
