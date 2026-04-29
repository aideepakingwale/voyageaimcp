"""
VoyageAI Chat API — All messages routed through LLM intent extraction.
Every user message is understood by an LLM before any action is taken.
"""
import json
from flask              import Blueprint, request, jsonify
from rag.memory_store   import memory_store
from reasoning.engine   import ReasoningEngine
from reasoning.intent_extractor import extract_intent
from reasoning.conversation_engine import apply_modification
from data.conversation_store import (
    upsert_conversation, save_turn, save_itinerary_version,
    get_latest_itinerary, restore_session_to_memory,
    update_entities, get_itinerary_history,
)
from core.logging_config import get_logger
from core.trace          import set_trace_id, new_trace_id, get_trace_id

bp  = Blueprint("chat", __name__)
log = get_logger("app")
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = ReasoningEngine()
    return _engine


@bp.route("/chat", methods=["POST"])
def chat():
    data        = request.get_json(silent=True) or {}
    if get_trace_id() == "NO-TRACE":
        set_trace_id(new_trace_id())

    message     = (data.get("message") or "").strip()
    session_id  = (data.get("session_id") or "").strip()
    origin_iata = (data.get("origin_iata") or "").strip().upper() or None
    ctx         = data.get("customer_context") or {}

    if not message:
        return jsonify({"error": "message is required"}), 400

    # Ensure session exists
    if not session_id or not memory_store.get_session(session_id):
        if not session_id:
            session_id = memory_store.create_session()
        else:
            memory_store._sessions.setdefault(session_id, {
                "created_at": 0, "last_active": 0,
                "entities": {}, "history": [], "confirmed": {},
                "last_itinerary": None,
            })
            restore_session_to_memory(session_id)

    # Persist session to DB
    upsert_conversation(
        session_id,
        ctx.get("id") or ctx.get("customer_id"),
        ctx.get("name") or ctx.get("customer_name"),
        origin_iata,
    )

    # Store initial entities
    if origin_iata and len(origin_iata) == 3:
        memory_store.store_entity(session_id, "origin_iata", origin_iata, 0.99)
    if ctx:
        for key in ("travel_style", "loyalty_tier", "adults", "children"):
            if ctx.get(key) is not None:
                memory_store.store_entity(session_id, key, ctx[key], 0.95)

    # Save user turn to memory + DB
    memory_store.add_turn(session_id, "user", message)
    save_turn(session_id, "user", message)

    # Load last itinerary (memory first, then DB)
    last_itinerary = memory_store.get_last_itinerary(session_id)
    if not last_itinerary:
        last_itinerary = get_latest_itinerary(session_id)
        if last_itinerary:
            memory_store.store_itinerary(session_id, last_itinerary)

    # ── LLM INTENT EXTRACTION ─────────────────────────────────
    # Every message is routed through the LLM to understand intent.
    # This handles natural language dates, implicit modifications, etc.
    session_context = memory_store.build_context_summary(session_id)

    log.info("Extracting intent via LLM", extra={
        "session": session_id,
        "user_msg": message,
        "has_itinerary": bool(last_itinerary),
    })

    intent = extract_intent(message, session_context, last_itinerary)

    log.info("Intent extracted", extra={
        "session":   session_id,
        "type":      intent["type"],
        "subtype":   intent.get("subtype"),
        "extracted": intent.get("extracted", {}),
        "confidence":intent.get("confidence"),
        "reasoning": intent.get("reasoning",""),
        "source":    intent.get("source","llm"),
    })

    extracted = intent.get("extracted", {})

    # ── CANCEL ────────────────────────────────────────────────
    if intent["type"] == "cancel":
        s = memory_store.get_session(session_id)
        if s:
            s["last_itinerary"] = None
        msg = "Plan cancelled. Where would you like to go?"
        memory_store.add_turn(session_id, "assistant", msg)
        save_turn(session_id, "assistant", msg, "cancel")
        return jsonify({"session_id": session_id, "status": "cancelled",
                        "message": msg, "conversation_state": "idle"})

    # ── CONFIRM ───────────────────────────────────────────────
    if intent["type"] == "confirm" and last_itinerary:
        ver = save_itinerary_version(session_id, last_itinerary, message,
                                     "confirmed", 0.99, "user_confirmed")
        msg = "Booking confirmed! Reference: VGI-" + session_id.upper()
        memory_store.add_turn(session_id, "assistant", msg)
        save_turn(session_id, "assistant", msg, "confirm")
        return jsonify({
            "session_id": session_id, "status": "confirmed",
            "llm_output": last_itinerary,
            "confidence": {"overall": 0.99, "passed": True},
            "message": msg, "itinerary_version": ver,
            "conversation_state": "confirmed",
        })

    # ── CLARIFY ───────────────────────────────────────────────
    if intent.get("needs_clarification"):
        q = intent.get("clarify_question") or "Could you give me more details?"
        memory_store.add_turn(session_id, "assistant", q)
        save_turn(session_id, "assistant", q, "clarify", intent.get("subtype"))
        memory_store.store_entity(session_id, "pending_modification",
                                   intent.get("subtype"), 0.99)
        return jsonify({
            "session_id": session_id, "status": "clarifying",
            "message": q, "modification_type": intent.get("subtype"),
            "conversation_state": "clarifying",
        })

    # ── MODIFY ────────────────────────────────────────────────
    if intent["type"] == "modify" and last_itinerary:
        return _run_modification(session_id, message, intent, last_itinerary, origin_iata, ctx)

    # ── PLAN ─────────────────────────────────────────────────
    return _run_plan(session_id, message, extracted, origin_iata, ctx)


def _run_plan(session_id, message, extracted, origin_iata, ctx):
    """Run full ReasoningEngine for a new trip."""
    result = _get_engine().reason(message, session_id)
    result["session_id"] = session_id
    result["conversation_state"] = "planning"
    result["is_modification"] = False

    if result.get("status") in ("ready", "awaiting_confirmation"):
        llm_out  = result.get("llm_output", {})
        conf     = result.get("confidence", {}).get("overall", 0)
        provider = result.get("llm_provider", "template")
        summary  = llm_out.get("summary", "Plan ready.")

        ver = save_itinerary_version(session_id, llm_out, message, None, conf, provider)
        result["itinerary_version"] = ver
        memory_store.add_turn(session_id, "assistant", summary)
        save_turn(session_id, "assistant", summary, "plan")
        update_entities(session_id, memory_store.retrieve_all_entities(session_id))

    return jsonify(result)


def _run_modification(session_id, message, intent, last_itinerary, origin_iata, ctx):
    """
    Apply LLM-extracted modification + full pipeline re-run.
    The LLM has already resolved dates, guests etc. into concrete values.
    """
    subtype   = intent.get("subtype", "general")
    extracted = intent.get("extracted", {})

    # ── Store extracted entities BEFORE the engine runs ───────
    entity_map = {
        "departure_date":  extracted.get("departure_date"),
        "return_date":     extracted.get("return_date"),
        "nights":          extracted.get("nights"),
        "guests":          extracted.get("guests"),
        "adults":          extracted.get("adults"),
        "children":        extracted.get("children"),
        "budget_gbp":      extracted.get("budget_gbp"),
        "min_hotel_stars": extracted.get("min_hotel_stars"),
        "origin_iata":     extracted.get("origin_iata") or origin_iata,
        "city_code":       extracted.get("city_code") or
                           last_itinerary.get("intent",{}).get("city_code"),
    }
    for key, val in entity_map.items():
        if val is not None:
            memory_store.store_entity(session_id, key, val, 0.99)

    update_entities(session_id, memory_store.retrieve_all_entities(session_id))

    # ── Patch the stored itinerary with new values ─────────────
    patched = _patch_itinerary(last_itinerary, extracted, subtype)

    # ── Build a complete natural language prompt ───────────────
    rebuilt = _build_full_prompt(patched, subtype, extracted)

    log.info("Modification re-run", extra={
        "session":   session_id,
        "subtype":   subtype,
        "extracted": extracted,
        "prompt_preview": rebuilt[:120],
        "reasoning": intent.get("reasoning",""),
    })

    # ── Full pipeline re-run ───────────────────────────────────
    result   = _get_engine().reason(rebuilt, session_id)
    result["session_id"]        = session_id
    result["is_modification"]   = True
    result["modification_type"] = subtype
    result["conversation_state"] = "modified"

    llm_out  = result.get("llm_output") or patched
    conf     = result.get("confidence", {}).get("overall", 0.80)
    prov     = result.get("llm_provider", "template")

    if result.get("status") not in ("ready", "awaiting_confirmation"):
        result["status"]     = "awaiting_confirmation"
        result["llm_output"] = patched
        llm_out = patched
        conf = 0.80
        prov = "conversation_fallback"

    # Build human-readable summary
    summary = _build_summary(subtype, extracted, llm_out, intent.get("reasoning",""))
    llm_out["summary"]           = summary
    llm_out["is_modification"]   = True
    llm_out["modification_type"] = subtype

    ver = save_itinerary_version(session_id, llm_out, message, subtype, conf, prov)
    result["itinerary_version"] = ver
    result["version_history"]   = get_itinerary_history(session_id)[-5:]

    memory_store.store_itinerary(session_id, llm_out)
    memory_store.add_turn(session_id, "assistant", summary)
    save_turn(session_id, "assistant", summary, "modify", subtype)
    update_entities(session_id, memory_store.retrieve_all_entities(session_id))

    return jsonify(result)


def _patch_itinerary(last: dict, extracted: dict, subtype: str) -> dict:
    """Apply extracted values onto the stored itinerary."""
    import copy
    patched = copy.deepcopy(last)
    intent  = patched.setdefault("intent", {})
    dates   = intent.setdefault("dates", {})
    prefs   = intent.setdefault("preferences", {})

    if extracted.get("departure_date"):
        dates["departure_date"] = extracted["departure_date"]
    if extracted.get("return_date"):
        dates["return_date"] = extracted["return_date"]
    if extracted.get("nights"):
        dates["nights"] = extracted["nights"]
        # Recalculate return date from departure + nights
        dep = dates.get("departure_date")
        if dep and extracted.get("nights"):
            from datetime import datetime, timedelta
            try:
                d = datetime.strptime(dep, "%Y-%m-%d")
                dates["return_date"] = (d + timedelta(days=extracted["nights"])).strftime("%Y-%m-%d")
            except Exception:
                pass

    if extracted.get("guests") is not None:
        intent["guests"] = extracted["guests"]
    if extracted.get("adults") is not None:
        intent["adults"] = extracted["adults"]
    if extracted.get("children") is not None:
        intent["children"] = extracted["children"]
    if extracted.get("budget_gbp") is not None:
        intent["budget_gbp"] = extracted["budget_gbp"]
    if extracted.get("min_hotel_stars") is not None:
        prefs["min_hotel_stars"] = extracted["min_hotel_stars"]
    if extracted.get("pool") is not None:
        prefs["pool"] = extracted["pool"]
    if extracted.get("direct_flight") is not None:
        prefs["direct_flight"] = extracted["direct_flight"]
    if extracted.get("cabin_class"):
        prefs["cabin_class"] = extracted["cabin_class"]
    if extracted.get("city_code"):
        intent["city_code"]    = extracted["city_code"]
        intent["destination"]  = extracted.get("destination", intent.get("destination"))
    if extracted.get("origin_iata"):
        intent["origin_iata"] = extracted["origin_iata"]

    return patched


def _build_full_prompt(patched: dict, subtype: str, extracted: dict) -> str:
    """Build a complete natural language prompt from the patched itinerary."""
    intent = patched.get("intent", {})
    dates  = intent.get("dates", {})
    prefs  = intent.get("preferences", {})

    dest     = intent.get("destination", "")
    code     = intent.get("city_code", "")
    guests   = intent.get("guests", 2)
    adults   = intent.get("adults", guests)
    children = intent.get("children", 0)
    budget   = intent.get("budget_gbp", 3000)
    dep      = dates.get("departure_date", "")
    ret      = dates.get("return_date", "")
    nights   = dates.get("nights", 7)
    stars    = prefs.get("min_hotel_stars", 4)
    direct   = prefs.get("direct_flight", False)
    pool     = prefs.get("pool", False)
    cabin    = prefs.get("cabin_class", "ECONOMY")
    origin   = intent.get("origin_iata", "LHR")

    guests_str = (f"{adults} adults and {children} children"
                  if children else f"{adults} adults")
    hotel_desc = f"{stars}-star hotel" + (" with pool" if pool else "")

    parts = [
        f"Plan a trip to {dest} ({code}) for {guests_str}.",
        f"Departure: {dep}." if dep else "",
        f"Return: {ret}."    if ret else "",
        f"Duration: {nights} nights." if nights else "",
        f"Budget: GBP {budget}.",
        f"Hotel: {hotel_desc}.",
        "Direct flights only." if direct else "",
        f"Cabin class: {cabin}." if cabin and cabin != "ECONOMY" else "",
        f"Origin airport: {origin}.",
        f"[MODIFICATION: {subtype} updated]",
        "Provide complete updated itinerary with new flights, hotels, costs.",
    ]
    return " ".join(p for p in parts if p)


def _build_summary(subtype: str, extracted: dict, result: dict, reasoning: str) -> str:
    intent = result.get("intent", {})
    dates  = intent.get("dates", {})
    dest   = intent.get("destination", "your destination")
    total  = result.get("total_cost_gbp", 0)
    nights = dates.get("nights", 0)
    guests = intent.get("guests", 2)
    dep    = dates.get("departure_date", "")
    ret    = dates.get("return_date", "")

    base = {
        "dates": (
            f"Dates updated to {dep} → {ret} ({nights} nights). "
            f"Estimated total: GBP {total:,.0f}"
        ),
        "guests": (
            f"Guest count updated to {guests}. "
            f"Flights and hotels recalculated. "
            f"Estimated total: GBP {total:,.0f}"
        ),
        "hotel": (
            f"Hotel preference updated. "
            f"Best options shown below. "
            f"Estimated total: GBP {total:,.0f}"
        ),
        "flight": (
            f"Flights updated with your preference. "
            f"Estimated total: GBP {total:,.0f}"
        ),
        "budget": (
            f"Budget updated. Plan adjusted accordingly. "
            f"Estimated total: GBP {total:,.0f}"
        ),
        "destination": (
            f"Destination changed to {dest}! "
            f"New itinerary ready. "
            f"Estimated total: GBP {total:,.0f}"
        ),
    }.get(subtype, f"Plan updated. Estimated total: GBP {total:,.0f}")

    return base


@bp.route("/demo", methods=["POST"])
def demo():
    return chat()


@bp.route("/history/<session_id>", methods=["GET"])
def get_history(session_id):
    return jsonify({
        "session_id":        session_id,
        "itinerary_history": get_itinerary_history(session_id),
    })
