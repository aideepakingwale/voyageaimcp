"""
VoyageAI Chat API — Conversational State Machine with full pipeline re-run.
Context persisted to SQLite + in-memory RAG.
"""
import json
from flask              import Blueprint, request, jsonify
from rag.memory_store   import memory_store
from reasoning.engine   import ReasoningEngine
from reasoning.conversation_engine import (
    classify_intent, apply_modification,
)
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

    # Persist to DB
    upsert_conversation(
        session_id,
        ctx.get("id") or ctx.get("customer_id"),
        ctx.get("name") or ctx.get("customer_name"),
        origin_iata
    )

    if origin_iata and len(origin_iata) == 3:
        memory_store.store_entity(session_id, "origin_iata", origin_iata, 0.99)

    if ctx:
        for key in ("travel_style", "loyalty_tier", "adults", "children"):
            if ctx.get(key) is not None:
                memory_store.store_entity(session_id, key, ctx[key], 0.95)

    # Save user turn
    memory_store.add_turn(session_id, "user", message)
    save_turn(session_id, "user", message)
    update_entities(session_id, memory_store.retrieve_all_entities(session_id))

    # Load last itinerary (memory first, then DB)
    last_itinerary = memory_store.get_last_itinerary(session_id)
    if not last_itinerary:
        last_itinerary = get_latest_itinerary(session_id)
        if last_itinerary:
            memory_store.store_itinerary(session_id, last_itinerary)

    # Classify intent
    intent = classify_intent(message, bool(last_itinerary))
    log.info("Intent classified", extra={
        "session": session_id, "type": intent["type"],
        "subtype": intent.get("subtype"), "has_plan": bool(last_itinerary),
    })

    # Check if answering a clarification
    pending = memory_store.retrieve_entity(session_id, "pending_modification")
    if pending and intent["type"] == "plan":
        intent = _resolve_clarification(pending, message)
        memory_store.store_entity(session_id, "pending_modification", None, 0)

    # ── CANCEL ──────────────────────────────────────────
    if intent["type"] == "cancel":
        s = memory_store.get_session(session_id)
        if s:
            s["last_itinerary"] = None
        msg = "Plan cancelled. Where would you like to go next?"
        memory_store.add_turn(session_id, "assistant", msg)
        save_turn(session_id, "assistant", msg, "cancel")
        return jsonify({"session_id": session_id, "status": "cancelled",
                        "message": msg, "conversation_state": "idle"})

    # ── CONFIRM ─────────────────────────────────────────
    if intent["type"] == "confirm" and last_itinerary:
        ver = save_itinerary_version(session_id, last_itinerary, message,
                                     "confirmed", 0.99, "user_confirmed")
        msg = "Booking confirmed! Reference: VGI-" + session_id.upper()
        memory_store.add_turn(session_id, "assistant", msg)
        save_turn(session_id, "assistant", msg, "confirm")
        return jsonify({"session_id": session_id, "status": "confirmed",
                        "llm_output": last_itinerary,
                        "confidence": {"overall": 0.99, "passed": True},
                        "message": msg, "itinerary_version": ver,
                        "conversation_state": "confirmed"})

    # ── CLARIFY ─────────────────────────────────────────
    if intent["type"] == "modify" and intent.get("needs_clarification"):
        q = intent["clarify_question"]
        memory_store.store_entity(session_id, "pending_modification",
                                   intent.get("subtype"), 0.99)
        memory_store.add_turn(session_id, "assistant", q)
        save_turn(session_id, "assistant", q, "clarify", intent.get("subtype"))
        return jsonify({"session_id": session_id, "status": "clarifying",
                        "message": q, "modification_type": intent.get("subtype"),
                        "conversation_state": "clarifying"})

    # ── MODIFY — full pipeline re-run ────────────────────
    if intent["type"] == "modify" and last_itinerary:
        return _run_modification(session_id, message, intent,
                                  last_itinerary, origin_iata, ctx)

    # ── PLAN — fresh request ─────────────────────────────
    return _run_plan(session_id, message, origin_iata, ctx)


def _run_plan(session_id, message, origin_iata, ctx):
    result = _get_engine().reason(message, session_id)
    result["session_id"] = session_id
    result["conversation_state"] = "planning"
    result["is_modification"] = False

    if result.get("status") in ("ready", "awaiting_confirmation"):
        llm_out = result.get("llm_output", {})
        ver = save_itinerary_version(
            session_id, llm_out, message, None,
            result.get("confidence", {}).get("overall", 0),
            result.get("llm_provider", "template")
        )
        result["itinerary_version"] = ver
        memory_store.add_turn(session_id, "assistant",
                               llm_out.get("summary", "Plan ready."))
        save_turn(session_id, "assistant",
                  llm_out.get("summary", "Plan ready."), "plan")
        update_entities(session_id, memory_store.retrieve_all_entities(session_id))

    return jsonify(result)


def _run_modification(session_id, message, intent, last_itinerary, origin_iata, ctx):
    """Apply modification + full ReasoningEngine re-run."""
    subtype   = intent.get("subtype", "")
    extracted = intent.get("extracted", {})

    # Patch the stored itinerary intent block
    patched = apply_modification(session_id, intent) or last_itinerary

    # Update session entities
    # Store ALL changed entities BEFORE engine runs so MCP scorer reads fresh values
    entity_map = {
        "departure_date": extracted.get("departure_date"),
        "return_date":    patched.get("intent",{}).get("dates",{}).get("return_date"),
        "nights":         extracted.get("nights") or patched.get("intent",{}).get("dates",{}).get("nights"),
        "guests":         extracted.get("guests") or patched.get("intent",{}).get("guests"),
        "adults":         extracted.get("adults") or patched.get("intent",{}).get("adults"),
        "children":       extracted.get("children") or patched.get("intent",{}).get("children"),
        "budget_gbp":     extracted.get("budget_gbp") or patched.get("intent",{}).get("budget_gbp"),
        "city_code":      patched.get("intent",{}).get("city_code"),
        "min_hotel_stars":extracted.get("min_stars") or patched.get("intent",{}).get("preferences",{}).get("min_hotel_stars"),
    }
    for key, val in entity_map.items():
        if val is not None:
            memory_store.store_entity(session_id, key, val, 0.99)

    # Sync to DB immediately so restore works
    update_entities(session_id, memory_store.retrieve_all_entities(session_id))
    log.info("Entities updated for modification", extra={"session": session_id, "entities": entity_map})

    # Build complete prompt from patched intent
    rebuilt = _build_prompt(patched, subtype)
    log.info("Modification re-run", extra={
        "session": session_id, "subtype": subtype, "prompt": rebuilt[:100]
    })

    # Full ReasoningEngine re-run
    result = _get_engine().reason(rebuilt, session_id)
    result["session_id"]       = session_id
    result["is_modification"]  = True
    result["modification_type"] = subtype
    result["conversation_state"] = "modified"

    llm_out = result.get("llm_output") or patched
    conf    = result.get("confidence", {}).get("overall", 0.80)
    prov    = result.get("llm_provider", "template")

    if result.get("status") not in ("ready", "awaiting_confirmation"):
        # Engine failed — use patched plan
        result["status"]     = "awaiting_confirmation"
        result["llm_output"] = patched
        llm_out = patched
        conf = 0.80
        prov = "conversation_fallback"

    # Build change summary and inject into output
    summary = _change_summary(subtype, extracted, llm_out)
    llm_out["summary"] = summary
    llm_out["is_modification"] = True
    llm_out["modification_type"] = subtype

    ver = save_itinerary_version(session_id, llm_out, message, subtype, conf, prov)
    result["itinerary_version"] = ver
    result["version_history"] = get_itinerary_history(session_id)[-5:]

    memory_store.store_itinerary(session_id, llm_out)
    memory_store.add_turn(session_id, "assistant", summary)
    save_turn(session_id, "assistant", summary, "modify", subtype)
    update_entities(session_id, memory_store.retrieve_all_entities(session_id))

    return jsonify(result)


def _build_prompt(patched, subtype):
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
    nights   = dates.get("nights", 7)
    stars    = prefs.get("min_hotel_stars", 4)
    direct   = prefs.get("direct_flight", False)
    pool     = prefs.get("pool", False)
    cabin    = prefs.get("cabin_class", "ECONOMY")

    guests_str = (f"{adults} adults and {children} children"
                  if children else f"{adults} adults")
    parts = [f"Plan a trip to {dest} ({code}) for {guests_str}."]
    if dep:   parts.append(f"Departure: {dep}. Duration: {nights} nights.")
    parts.append(f"Budget: GBP {budget}.")
    hotel_desc = f"{stars}-star hotel"
    if pool:  hotel_desc += " with pool"
    parts.append(f"Hotel: {hotel_desc}.")
    if direct: parts.append("Direct flights only.")
    if cabin != "ECONOMY": parts.append(f"Cabin class: {cabin}.")
    parts.append(f"[MODIFICATION TYPE: {subtype}]")
    parts.append("Provide updated flights, hotels, experiences and full cost breakdown.")
    return " ".join(parts)


def _change_summary(subtype, extracted, result):
    intent = result.get("intent", {})
    dates  = intent.get("dates", {})
    dest   = intent.get("destination", "your destination")
    total  = result.get("total_cost_gbp", 0)
    nights = dates.get("nights", 0)
    guests = intent.get("guests", 2)
    dep    = dates.get("departure_date", "")
    ret    = dates.get("return_date", "")

    msgs = {
        "dates":       f"Dates updated to {dep} - {ret} ({nights} nights). Total: GBP {total:,.0f}",
        "guests":      f"Guest count updated to {guests}. Total: GBP {total:,.0f}",
        "hotel":       f"Hotel preference updated. Total: GBP {total:,.0f}",
        "flight":      f"Flight preference updated. Total: GBP {total:,.0f}",
        "budget":      f"Budget updated. Plan adjusted. Total: GBP {total:,.0f}",
        "destination": f"Destination changed to {dest}. Total: GBP {total:,.0f}",
    }
    return msgs.get(subtype, f"Plan updated. Total: GBP {total:,.0f}")


def _resolve_clarification(pending_mod, message):
    from reasoning.conversation_engine import (
        _extract_dates_from_text, _extract_guest_count, _extract_budget)
    extracted = {}
    if pending_mod == "dates":
        extracted = _extract_dates_from_text(message)
    elif pending_mod == "guests":
        extracted = _extract_guest_count(message)
    elif pending_mod == "budget":
        b = _extract_budget(message)
        if b:
            extracted = {"budget_gbp": b}
    return {"type": "modify", "subtype": pending_mod, "extracted": extracted,
            "needs_clarification": not bool(extracted),
            "clarify_question": f"Could you be more specific about the {pending_mod}?"}


@bp.route("/demo", methods=["POST"])
def demo():
    return chat()


@bp.route("/history/<session_id>", methods=["GET"])
def get_history(session_id):
    return jsonify({
        "session_id": session_id,
        "itinerary_history": get_itinerary_history(session_id),
        "conversation_turns": [],
    })
