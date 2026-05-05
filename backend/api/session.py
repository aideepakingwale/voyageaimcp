"""Session management endpoints."""
from flask import Blueprint, jsonify, request
from config import Config
from rag.memory_store import memory_store

bp = Blueprint("session", __name__)


@bp.route("/session", methods=["POST"])
def create_session():
    """Create a new booking session."""
    sid = memory_store.create_session()
    return jsonify({
        "session_id":    sid,
        "created":       True,
        "gds_window_s":  Config.GDS_SESSION_TIMEOUT,
    })


@bp.route("/session/<sid>", methods=["GET"])
def get_session(sid: str):
    """Get current session state — entities, confirmed elements, age."""
    session = memory_store.get_session(sid)
    if not session:
        return jsonify({"error": "Session not found or expired"}), 404

    return jsonify({
        "session_id":  sid,
        "entities":    memory_store.retrieve_all_entities(sid),
        "confirmed":   memory_store.get_confirmed(sid),
        "history_len": len(session.get("history", [])),
        "age_seconds": round(memory_store.session_age_seconds(sid)),
        "gds_remaining": max(0, Config.GDS_SESSION_TIMEOUT - memory_store.session_age_seconds(sid)),
    })


@bp.route("/session/<sid>", methods=["DELETE"])
def clear_session(sid: str):
    """Clear session data (without destroying it)."""
    session = memory_store.get_session(sid)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    session["entities"] = {}
    session["confirmed"] = {}
    return jsonify({"cleared": True, "session_id": sid})


@bp.route("/confirm", methods=["POST"])
def confirm():
    """Record human confirmation of a booking element."""
    body    = request.get_json(silent=True) or {}
    sid     = body.get("session_id", "")
    element = body.get("element", "booking")
    data    = body.get("data", {})
    action  = body.get("action", "confirm")

    if action == "reject":
        return jsonify({"status": "rejected", "message": "Booking cancelled by user."})

    if element == "package":
        package_payload = data if isinstance(data, dict) else {}
        for key in ("flight", "hotel", "payment"):
            memory_store.confirm_element(sid, key, package_payload.get(key, {}))
        memory_store.confirm_element(sid, "package", package_payload)
    else:
        memory_store.confirm_element(sid, element, data)
    confirmed = memory_store.get_confirmed(sid)
    all_done  = all(k in confirmed for k in ("flight", "hotel", "payment"))

    return jsonify({
        "status":    "confirmed" if all_done else "partial",
        "element":   element,
        "confirmed": confirmed,
        "next_step": "payment" if ("flight" in confirmed and "hotel" in confirmed
                                   and "payment" not in confirmed) else None,
        "message":   "Package confirmed in one go." if element == "package" else (
            "Booking complete!" if all_done else f"{element.title()} confirmed."
        ),
    })
