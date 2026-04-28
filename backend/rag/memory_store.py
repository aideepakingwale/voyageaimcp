"""
VoyageAI RAG Memory Store
Stores session context (entities, history, last itinerary, confirmed bookings).
Each login gets a fresh session — full isolation.
"""
import time
import uuid
import json
from config import Config


class MemoryStore:

    def __init__(self, ttl: int = None):
        self._sessions: dict[str, dict] = {}
        self._ttl = ttl or Config.SESSION_TTL_SECONDS

    # ── Session lifecycle ─────────────────────────────────────

    def create_session(self) -> str:
        sid = str(uuid.uuid4())[:8]
        self._sessions[sid] = {
            "created_at":    time.time(),
            "last_active":   time.time(),
            "entities":      {},
            "history":       [],   # [{role, content, ts}]
            "confirmed":     {},
            "last_itinerary": None,  # full LLM output from last successful plan
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

    # ── Entity store ──────────────────────────────────────────

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

    def retrieve_entity(self, sid: str, entity_type: str,
                        min_confidence: float = None):
        threshold = min_confidence or Config.RAG_SIMILARITY_THRESHOLD
        s = self._sessions.get(sid)
        if not s:
            return None
        entries = s["entities"].get(entity_type, [])
        valid   = [e for e in entries if e["confidence"] >= threshold]
        return valid[-1]["value"] if valid else None

    def retrieve_all_entities(self, sid: str) -> dict:
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
        s["history"] = s["history"][-30:]

    def get_history(self, sid: str, max_turns: int = 10) -> list:
        s = self._sessions.get(sid)
        return s["history"][-max_turns:] if s else []

    # ── Last itinerary (full plan) ────────────────────────────

    def store_itinerary(self, sid: str, itinerary: dict):
        """Store the full last successful itinerary for modification requests."""
        s = self._sessions.get(sid)
        if s:
            s["last_itinerary"] = {
                "data":      itinerary,
                "stored_at": time.time(),
            }

    def get_last_itinerary(self, sid: str) -> dict | None:
        s = self._sessions.get(sid)
        if not s or not s.get("last_itinerary"):
            return None
        return s["last_itinerary"]["data"]

    # ── Booking confirmations ─────────────────────────────────

    def confirm_element(self, sid: str, element: str, data: dict):
        s = self._sessions.get(sid)
        if s:
            s["confirmed"][element] = {**data, "confirmed_at": time.time()}

    def get_confirmed(self, sid: str) -> dict:
        s = self._sessions.get(sid)
        return s["confirmed"] if s else {}

    # ── Intent detection ──────────────────────────────────────

    def is_modification_request(self, message: str) -> bool:
        """Detect if the user is modifying a previous plan rather than starting fresh."""
        msg_lower = message.lower().strip()
        modification_patterns = [
            # Date changes
            "change the date", "change dates", "different date", "different dates",
            "change the departure", "change the return", "new dates", "other dates",
            "move it to", "move the trip", "reschedule", "postpone", "bring forward",
            "earlier date", "later date", "same trip but",
            # Guest changes
            "change the number", "add another", "one more person", "fewer people",
            "just two of us", "only one", "actually three", "we are",
            # Budget changes
            "increase the budget", "reduce the budget", "cheaper option", "more expensive",
            "upgrade", "downgrade", "better hotel", "cheaper hotel",
            # Hotel changes
            "different hotel", "change the hotel", "upgrade the room", "different room",
            "5 star", "4 star", "beachfront", "city centre",
            # Flight changes
            "different flight", "earlier flight", "later flight", "direct flight",
            "change the airline", "upgrade to business",
            # General modification intent
            "i want to change", "can we change", "could we change", "let's change",
            "instead", "actually", "instead of that", "not that one",
            "what if", "what about", "how about", "can you update",
            "update the", "modify the", "adjust the", "tweak the",
            "keep everything but", "keep the same", "same but",
            "amend", "alter", "revise",
        ]
        return any(p in msg_lower for p in modification_patterns)

    # ── Context summary for LLM ───────────────────────────────

    def build_context_summary(self, sid: str) -> str:
        """
        Build a rich context string injected into the LLM prompt.
        Includes: entities, last plan summary, conversation history.
        """
        entities       = self.retrieve_all_entities(sid)
        confirmed      = self.get_confirmed(sid)
        history        = self.get_history(sid, max_turns=10)
        last_itinerary = self.get_last_itinerary(sid)

        lines = ["=== SESSION CONTEXT ==="]

        # ── Previously confirmed preferences ──────────────────
        if entities:
            lines.append("\nConfirmed preferences from this conversation:")
            priority = ["destination","city_code","country_code","departure_date",
                        "return_date","guests","adults","children","budget_gbp",
                        "origin_iata","loyalty_tier","travel_style"]
            shown = set()
            for k in priority:
                if k in entities:
                    lines.append(f"  {k}: {json.dumps(entities[k])}")
                    shown.add(k)
            for k, v in entities.items():
                if k not in shown:
                    lines.append(f"  {k}: {json.dumps(v)}")

        # ── Last itinerary — critical for modifications ────────
        if last_itinerary:
            intent = last_itinerary.get("intent", {})
            recs   = last_itinerary.get("recommendations", {})
            dates  = intent.get("dates", {})
            lines.append("\nLAST PLANNED ITINERARY (the trip already discussed):")
            lines.append(f"  Destination: {intent.get('destination','?')} ({intent.get('city_code','?')})")
            lines.append(f"  Dates:       {dates.get('departure_date','?')} → {dates.get('return_date','?')} ({dates.get('nights','?')} nights)")
            lines.append(f"  Guests:      {intent.get('guests','?')} ({intent.get('adults','?')} adults, {intent.get('children','?')} children)")
            lines.append(f"  Budget:      £{intent.get('budget_gbp','?')}")
            lines.append(f"  Total cost:  £{last_itinerary.get('total_cost_gbp','?')}")
            # Include first flight and hotel so LLM can reference them
            flights = recs.get("flights", [])
            if flights:
                f0 = flights[0]
                lines.append(f"  Best flight: {f0.get('airline','?')} {f0.get('flight_number','?')} £{f0.get('price_gbp','?')}")
            hotels = recs.get("hotels", [])
            if hotels:
                h0 = hotels[0]
                lines.append(f"  Best hotel:  {h0.get('name','?')} {h0.get('stars','?')}★ £{h0.get('price_per_night','?')}/night")
            prefs = intent.get("preferences", {})
            if prefs:
                lines.append(f"  Preferences: {json.dumps(prefs)}")

        # ── Confirmed bookings ─────────────────────────────────
        if confirmed:
            lines.append("\nConfirmed booking elements:")
            for k, v in confirmed.items():
                lines.append(f"  ✓ {k}: {json.dumps(v)}")

        # ── Full conversation history (not truncated) ──────────
        if history:
            lines.append("\nConversation so far:")
            for turn in history:
                role    = turn["role"].upper()
                content = str(turn["content"])
                # Show full user messages; summarise long AI responses
                if role == "USER":
                    lines.append(f"  [{role}]: {content}")
                else:
                    # For AI turns, show first 300 chars (summary)
                    preview = content[:300] + ("…" if len(content) > 300 else "")
                    lines.append(f"  [{role}]: {preview}")

        lines.append("\n======================")
        return "\n".join(lines)


# Module-level singleton
memory_store = MemoryStore()
