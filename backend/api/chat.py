"""
VoyageAI Chat API — Context Engine drives every decision.

Every user message goes through context_engine.understand() which:
  1. Tries real LLM (Groq/Gemini) with full conversation context
  2. Falls back to deterministic rule-based extraction
  3. Returns a structured action — never hallucinates

The old fragmented pipeline (universal_extractor + intent_extractor +
conversational_llm + modification_handler) is replaced by ONE clear call.
"""
import json, copy
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

from rag.memory_store   import memory_store
from reasoning.engine   import ReasoningEngine
from reasoning.context_engine import understand, resolve_destination
from data.conversation_store import (
    upsert_conversation, save_turn, save_itinerary_version,
    get_latest_itinerary, restore_session_to_memory,
    update_entities, get_itinerary_history,
)
from core.logging_config import get_logger
from core.trace import set_trace_id, new_trace_id, get_trace_id

bp  = Blueprint("chat", __name__)
log = get_logger("app")
_engine = None


def _get_engine() -> ReasoningEngine:
    global _engine
    if _engine is None:
        _engine = ReasoningEngine()
    return _engine


@bp.route("/chat", methods=["POST"])
def chat():
    data       = request.get_json(silent=True) or {}
    if get_trace_id() == "NO-TRACE":
        set_trace_id(new_trace_id())

    message     = (data.get("message") or "").strip()
    session_id  = (data.get("session_id") or "").strip()
    origin_iata = (data.get("origin_iata") or "").strip().upper() or None
    ctx         = data.get("customer_context") or {}

    if not message:
        return jsonify({"error": "message is required"}), 400

    # ── Ensure session ────────────────────────────────────────
    if not session_id or not memory_store.get_session(session_id):
        if not session_id:
            session_id = memory_store.create_session()
        else:
            memory_store._sessions.setdefault(session_id, {
                "created_at":0,"last_active":0,
                "entities":{},"history":[],"confirmed":{},"last_itinerary":None,
            })
            restore_session_to_memory(session_id)

    # Persist session
    upsert_conversation(
        session_id,
        ctx.get("id") or ctx.get("customer_id"),
        ctx.get("name") or ctx.get("customer_name"),
        origin_iata,
    )
    if origin_iata and len(origin_iata) == 3:
        memory_store.store_entity(session_id, "origin_iata", origin_iata, 0.99)

    # Save user turn
    memory_store.add_turn(session_id, "user", message)
    save_turn(session_id, "user", message)

    # ── Load context ──────────────────────────────────────────
    last_plan = (memory_store.get_last_itinerary(session_id)
                 or get_latest_itinerary(session_id))
    if last_plan and not memory_store.get_last_itinerary(session_id):
        memory_store.store_itinerary(session_id, last_plan)

    history = memory_store.get_history(session_id, max_turns=10)

    # ── Context Engine — understand intent ────────────────────
    action = understand(message, history, last_plan, session_id)
    log.info("Context Engine result", extra={
        "session": session_id,
        "action":  action.get("action"),
        "subtype": action.get("subtype"),
        "dest":    action.get("destination_iata"),
        "source":  action.get("_source"),
        "reason":  (action.get("reasoning",""))[:60],
    })

    # Store any extracted entities
    _store_entities(session_id, action)
    update_entities(session_id, memory_store.retrieve_all_entities(session_id))

    # ── Route by action ───────────────────────────────────────
    act = action.get("action","plan")

    if act == "cancel":
        return _cancel(session_id)

    if act == "confirm" and last_plan:
        return _confirm(session_id, last_plan, message)

    if act == "clarify":
        return _clarify(session_id, action)

    if act == "modify" and last_plan:
        return _run_modify(session_id, message, action, last_plan, origin_iata, ctx)

    if act in ("suggest",):
        return _run_suggest(session_id, message, action, ctx)

    # Default: plan (fresh trip)
    return _run_plan(session_id, message, action, origin_iata, ctx)


# ─── Action handlers ──────────────────────────────────────────

def _cancel(session_id):
    s = memory_store.get_session(session_id)
    if s: s["last_itinerary"] = None
    msg = "Plan cancelled. Where would you like to go next?"
    memory_store.add_turn(session_id, "assistant", msg)
    save_turn(session_id, "assistant", msg, "cancel")
    return jsonify({"session_id":session_id,"status":"cancelled",
                    "message":msg,"conversation_state":"idle"})


def _confirm(session_id, last_plan, message):
    ver = save_itinerary_version(session_id, last_plan, message, "confirmed", 0.99, "user")
    msg = f"Booking confirmed! Reference: VGI-{session_id[:8].upper()}"
    memory_store.add_turn(session_id, "assistant", msg)
    save_turn(session_id, "assistant", msg, "confirm")
    return jsonify({"session_id":session_id,"status":"confirmed",
                    "llm_output":last_plan,"message":msg,
                    "itinerary_version":ver,"conversation_state":"confirmed",
                    "confidence":{"overall":0.99,"passed":True}})


def _clarify(session_id, action):
    q = action.get("response") or "Could you give me a bit more detail?"
    memory_store.store_entity(session_id, "pending_modification",
                               action.get("subtype","general"), 0.99)
    memory_store.add_turn(session_id, "assistant", q)
    save_turn(session_id, "assistant", q, "clarify", action.get("subtype"))
    return jsonify({"session_id":session_id,"status":"clarifying","message":q,
                    "modification_type":action.get("subtype"),
                    "conversation_state":"clarifying"})


def _run_plan(session_id, message, action, origin_iata, ctx):
    """Fresh trip planning."""
    # Check if vague (should be suggestions instead)
    try:
        from llm.template_provider import TemplateProvider
        if TemplateProvider()._is_vague_request(message):
            return _run_suggest(session_id, message, action, ctx)
    except Exception:
        pass

    # Build prompt with extracted params so engine has correct values
    prompt = _build_plan_prompt(message, action)
    result = _get_engine().reason(prompt, session_id)
    result["session_id"]         = session_id
    result["conversation_state"] = "planning"
    result["is_modification"]    = False

    if result.get("status") in ("ready","awaiting_confirmation"):
        llm_out = result.get("llm_output", {})
        ver = save_itinerary_version(
            session_id, llm_out, message, None,
            result.get("confidence",{}).get("overall",0),
            result.get("llm_provider","template"),
        )
        result["itinerary_version"] = ver
        summary = llm_out.get("summary","Plan ready.")
        memory_store.add_turn(session_id, "assistant", summary)
        save_turn(session_id, "assistant", summary, "plan")
        update_entities(session_id, memory_store.retrieve_all_entities(session_id))
    return jsonify(result)


def _run_modify(session_id, message, action, last_plan, origin_iata, ctx):
    """Apply modification and re-run full pipeline with new params."""
    subtype = action.get("subtype","general")

    # Patch the plan with the action's extracted values
    patched = _patch_plan(last_plan, action)

    # Build a complete prompt from the patched plan
    prompt = _build_modify_prompt(patched, subtype, action)

    log.info("Running modification", extra={
        "session":  session_id,
        "subtype":  subtype,
        "new_dest": action.get("destination_iata"),
        "new_date": action.get("departure_date"),
        "prompt":   prompt[:100],
    })

    result = _get_engine().reason(prompt, session_id)
    result["session_id"]       = session_id
    result["is_modification"]  = True
    result["modification_type"]= subtype
    result["conversation_state"]= "modified"

    llm_out = result.get("llm_output") or patched
    conf    = result.get("confidence",{}).get("overall",0.82)
    prov    = result.get("llm_provider","template")

    if result.get("status") not in ("ready","awaiting_confirmation"):
        result["status"]     = "awaiting_confirmation"
        result["llm_output"] = patched
        llm_out = patched; conf = 0.80; prov = "fallback"

    summary = _make_summary(subtype, action, llm_out)
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


def _run_suggest(session_id, message, action, ctx):
    """Generate destination suggestions via LLM."""
    try:
        from reasoning.llm_destination_suggester import suggest_destinations_with_llm
        profile = {
            "name": ctx.get("name","Guest"),
            "travel_style": ctx.get("travel_style","leisure"),
            "interests": ctx.get("interests",[]),
            "loyalty_tier": ctx.get("loyalty_tier","Blue"),
            "typical_budget_gbp": int(ctx.get("budget_gbp",3000)),
            "typical_nights": 7,
            "visited_destinations": ctx.get("visited_destinations",[]),
        }
        history = memory_store.get_history(session_id, max_turns=4)
        last    = memory_store.get_last_itinerary(session_id)
        result  = suggest_destinations_with_llm(message, profile, history, last)
        if result and result.get("suggestions"):
            result["session_id"]         = session_id
            result["status"]             = "suggestions"
            result["conversation_state"] = "suggesting"
            summary = result.get("summary","")
            memory_store.add_turn(session_id, "assistant", summary)
            save_turn(session_id, "assistant", summary, "suggest")
            return jsonify(result)
    except Exception as e:
        log.debug("Suggest error: %s", e)
    # Fallback to plan
    return _run_plan(session_id, message, action, None, ctx)


# ─── Helpers ──────────────────────────────────────────────────

def _store_entities(session_id: str, action: dict):
    """Store all extracted values in session."""
    MAP = {
        "destination_iata":  "city_code",
        "destination":       "destination",
        "departure_date":    "departure_date",
        "return_date":       "return_date",
        "nights":            "nights",
        "guests":            "guests",
        "adults":            "adults",
        "children":          "children",
        "budget_gbp":        "budget_gbp",
        "min_hotel_stars":   "min_hotel_stars",
        "direct_flight":     "direct_flight",
    }
    for src_key, entity_key in MAP.items():
        val = action.get(src_key)
        if val is not None:
            memory_store.store_entity(session_id, entity_key, val, 0.95)


def _patch_plan(last: dict, action: dict) -> dict:
    """Apply action values to a copy of the existing plan."""
    patched = copy.deepcopy(last)
    intent  = patched.setdefault("intent",{})
    dates   = intent.setdefault("dates",{})
    prefs   = intent.setdefault("preferences",{})

    if action.get("destination_iata"):
        intent["city_code"]   = action["destination_iata"]
        intent["destination"] = action.get("destination", intent.get("destination",""))
    if action.get("departure_date"):
        dates["departure_date"] = action["departure_date"]
    if action.get("nights"):
        dates["nights"] = action["nights"]
        dep = dates.get("departure_date")
        if dep:
            try:
                d = datetime.strptime(dep, "%Y-%m-%d")
                dates["return_date"] = (d + timedelta(days=action["nights"])).strftime("%Y-%m-%d")
            except Exception:
                pass
    if action.get("return_date") and not dates.get("return_date"):
        dates["return_date"] = action["return_date"]
    if action.get("guests") is not None:
        intent["guests"] = action["guests"]
    if action.get("adults") is not None:
        intent["adults"] = action["adults"]
    if action.get("children") is not None:
        intent["children"] = action["children"]
    if action.get("budget_gbp") is not None:
        intent["budget_gbp"] = action["budget_gbp"]
    if action.get("min_hotel_stars") is not None:
        prefs["min_hotel_stars"] = action["min_hotel_stars"]
    if action.get("direct_flight") is not None:
        prefs["direct_flight"] = action["direct_flight"]
    return patched


def _build_plan_prompt(message: str, action: dict) -> str:
    """Build a complete prompt for the reasoning engine."""
    parts = []
    dest   = action.get("destination")
    iata   = action.get("destination_iata")
    guests = action.get("guests", 2)
    adults = action.get("adults", guests)
    children = action.get("children", 0)
    budget = action.get("budget_gbp", 3000)
    dep    = action.get("departure_date","")
    nights = action.get("nights", 7)
    stars  = action.get("min_hotel_stars", 4)
    direct = action.get("direct_flight", False)

    if dest and iata:
        guest_str = f"{adults} adults and {children} children" if children else f"{adults} adults"
        parts.append(f"Plan a trip to {dest} ({iata}) for {guest_str}.")
    else:
        parts.append(message)
        return " ".join(parts)

    if dep:
        parts.append(f"Departure: {dep}. Duration: {nights} nights.")
    parts.append(f"Budget: GBP {budget}.")
    parts.append(f"Hotel: {stars}-star or above.")
    if direct:
        parts.append("Direct flights preferred.")
    parts.append("Build a complete itinerary with flights, hotels, experiences and cost breakdown.")
    return " ".join(parts)


def _build_modify_prompt(patched: dict, subtype: str, action: dict) -> str:
    """Build a complete prompt from the patched plan."""
    intent = patched.get("intent",{})
    dates  = intent.get("dates",{})
    prefs  = intent.get("preferences",{})

    dest     = intent.get("destination","")
    iata     = intent.get("city_code","")
    guests   = intent.get("guests",2)
    adults   = intent.get("adults",guests)
    children = intent.get("children",0)
    budget   = intent.get("budget_gbp",3000)
    dep      = dates.get("departure_date","")
    nights   = dates.get("nights",7)
    stars    = prefs.get("min_hotel_stars",4)
    direct   = prefs.get("direct_flight",False)

    guest_str = f"{adults} adults and {children} children" if children else f"{adults} adults"
    parts = [f"Plan a trip to {dest} ({iata}) for {guest_str}."]
    if dep:
        parts.append(f"Departure: {dep}. Duration: {nights} nights.")
    parts.append(f"Budget: GBP {budget}.")
    parts.append(f"Hotel: {stars}-star or above.")
    if direct: parts.append("Direct flights preferred.")
    parts.append(f"[MODIFICATION: {subtype} updated]")
    parts.append("Provide updated flights, hotels, experiences and full cost breakdown.")
    return " ".join(parts)


def _make_summary(subtype: str, action: dict, result: dict) -> str:
    """Build a clear, honest summary of what changed."""
    intent = result.get("intent",{})
    dates  = intent.get("dates",{})
    dest   = intent.get("destination","your destination")
    total  = result.get("total_cost_gbp",0)
    dep    = dates.get("departure_date","")
    ret    = dates.get("return_date","")
    nights = dates.get("nights",0)
    guests = intent.get("guests",2)

    msgs = {
        "destination": f"Destination updated to {dest}. New itinerary ready. Total: GBP {total:,.0f}",
        "dates":       f"Dates updated: {dep} to {ret} ({nights} nights). Total: GBP {total:,.0f}",
        "guests":      f"Updated for {guests} guests. Total: GBP {total:,.0f}",
        "hotel":       f"Hotel preference updated. Total: GBP {total:,.0f}",
        "flight":      f"Flight preference updated. Total: GBP {total:,.0f}",
        "budget":      f"Budget updated. Plan adjusted. Total: GBP {total:,.0f}",
    }
    return msgs.get(subtype, f"Plan updated. Total: GBP {total:,.0f}")


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
