"""
VoyageAI RAG Memory Store
Stores session context (entities, history, confirmed bookings) outside the LLM
context window. Solves context overflow for long multi-step booking conversations.

In production: replace _sessions dict with Redis or a vector store.
"""
import time
import uuid
import json
from config import Config


class MemoryStore:
    """
    In-memory session store with TTL matching the GDS session window (30 min).
    
    Schema per session:
      created_at  — Unix timestamp of session creation
      last_active — Unix timestamp of last access
      entities    — dict[entity_type → list[{value, confidence, timestamp}]]
      history     — list[{role, content, ts}]  (capped at 20 turns)
      confirmed   — dict[element → {data, confirmed_at}]
    """

    def __init__(self, ttl: int = None):
        self._sessions: dict[str, dict] = {}
        self._ttl = ttl or Config.SESSION_TTL_SECONDS

    # ── Session lifecycle ─────────────────────────────────────

    def create_session(self) -> str:
        sid = str(uuid.uuid4())[:8]
        self._sessions[sid] = {
            "created_at":  time.time(),
            "last_active": time.time(),
            "entities":    {},
            "history":     [],
            "confirmed":   {},
        }
        return sid

    def get_session(self, sid: str) -> dict | None:
        s = self._sessions.get(sid)
        if not s:
            return None
        if time.time() - s["created_at"] > self._ttl:
            del self._sessions[sid]
            return None
        s["last_active"] = time.time()
        return s

    def session_age_seconds(self, sid: str) -> float:
        s = self._sessions.get(sid)
        return time.time() - s["created_at"] if s else float("inf")

    # ── Entity store (RAG write) ──────────────────────────────

    def store_entity(self, sid: str, entity_type: str,
                     value, confidence: float = 1.0):
        s = self._sessions.get(sid)
        if not s:
            return
        s["entities"].setdefault(entity_type, [])
        s["entities"][entity_type].append({
            "value":      value,
            "confidence": confidence,
            "timestamp":  time.time(),
        })

    # ── Entity retrieval (RAG read) ───────────────────────────

    def retrieve_entity(self, sid: str, entity_type: str,
                        min_confidence: float = None):
        """Return the most recently stored entity above confidence threshold."""
        threshold = min_confidence or Config.RAG_SIMILARITY_THRESHOLD
        s = self._sessions.get(sid)
        if not s:
            return None
        entries = s["entities"].get(entity_type, [])
        valid   = [e for e in entries if e["confidence"] >= threshold]
        return valid[-1]["value"] if valid else None

    def retrieve_all_entities(self, sid: str) -> dict:
        """Return latest value for every stored entity type."""
        s = self._sessions.get(sid)
        if not s:
            return {}
        return {
            etype: entries[-1]["value"]
            for etype, entries in s["entities"].items()
            if entries
        }

    # ── Conversation history ──────────────────────────────────

    def add_turn(self, sid: str, role: str, content: str):
        s = self._sessions.get(sid)
        if not s:
            return
        s["history"].append({"role": role, "content": content, "ts": time.time()})
        s["history"] = s["history"][-20:]   # keep last 20 turns

    def get_history(self, sid: str, max_turns: int = 10) -> list:
        s = self._sessions.get(sid)
        return s["history"][-max_turns:] if s else []

    # ── Booking confirmations ─────────────────────────────────

    def confirm_element(self, sid: str, element: str, data: dict):
        s = self._sessions.get(sid)
        if s:
            s["confirmed"][element] = {**data, "confirmed_at": time.time()}

    def get_confirmed(self, sid: str) -> dict:
        s = self._sessions.get(sid)
        return s["confirmed"] if s else {}

    # ── LLM context summary ───────────────────────────────────

    def build_context_summary(self, sid: str) -> str:
        """Build a compact context string to inject into LLM prompts."""
        entities  = self.retrieve_all_entities(sid)
        confirmed = self.get_confirmed(sid)
        history   = self.get_history(sid, max_turns=6)

        lines = ["=== SESSION CONTEXT ==="]

        if entities:
            lines.append("Confirmed preferences:")
            for k, v in entities.items():
                lines.append(f"  {k}: {json.dumps(v)}")

        if confirmed:
            lines.append("Confirmed booking elements:")
            for k, v in confirmed.items():
                lines.append(f"  ✓ {k}: {json.dumps(v)}")

        if history:
            lines.append("Recent conversation:")
            for turn in history[-4:]:
                preview = str(turn["content"])[:200]
                lines.append(f"  [{turn['role']}]: {preview}")

        lines.append("======================")
        return "\n".join(lines)


# Module-level singleton — import this everywhere
memory_store = MemoryStore()
