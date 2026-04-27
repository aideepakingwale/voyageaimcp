"""
VoyageAI RAG Server
Stateful external memory store — keeps conversation context outside LLM token window.
Uses TF-IDF cosine similarity for retrieval (no heavy ML dependencies).
"""
import math
import time
import uuid
import json
import re
from collections import defaultdict
from config import RAG_SIMILARITY_THRESHOLD, RAG_MAX_RESULTS


class RAGServer:
    """
    External stateful memory for the VoyageAI orchestrator.
    Stores preference entities, session state, and conversation history
    indexed per session_id.  Retrieves by semantic similarity.
    """

    def __init__(self):
        # { session_id: [ {id, content, entity_type, timestamp, embedding} ] }
        self._store: dict[str, list] = defaultdict(list)
        # { session_id: { key: value } } — structured session state
        self._session_state: dict[str, dict] = defaultdict(dict)

    # ── Store ──────────────────────────────────────────────────────────
    def store(self, session_id: str, content: str,
              entity_type: str = "preference") -> dict:
        """Store a memory chunk and return its record."""
        record = {
            "id":          str(uuid.uuid4()),
            "content":     content,
            "entity_type": entity_type,
            "timestamp":   time.time(),
            "embedding":   self._embed(content),
        }
        self._store[session_id].append(record)
        return {"stored": True, "id": record["id"]}

    def store_state(self, session_id: str, key: str, value) -> None:
        """Store a structured key-value in session state."""
        self._session_state[session_id][key] = value

    def get_state(self, session_id: str, key: str, default=None):
        return self._session_state[session_id].get(key, default)

    def get_full_state(self, session_id: str) -> dict:
        return dict(self._session_state[session_id])

    # ── Retrieve ───────────────────────────────────────────────────────
    def retrieve(self, session_id: str, query: str,
                 entity_type: str = None, k: int = None) -> list:
        """
        Retrieve top-k most similar memories for a query.
        Returns list of {content, similarity, entity_type, age_seconds}.
        """
        k = k or RAG_MAX_RESULTS
        records = self._store.get(session_id, [])
        if not records:
            return []

        query_emb = self._embed(query)
        now = time.time()
        scored = []

        for r in records:
            if entity_type and r["entity_type"] != entity_type:
                continue
            sim = self._cosine(query_emb, r["embedding"])
            # Apply recency decay — older memories lose 2% per hour
            age_hours = (now - r["timestamp"]) / 3600
            decay = max(0.5, 1.0 - 0.02 * age_hours)
            scored.append({
                "content":     r["content"],
                "similarity":  round(sim * decay, 4),
                "entity_type": r["entity_type"],
                "age_seconds": int(now - r["timestamp"]),
                "id":          r["id"],
            })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        results = scored[:k]

        # Return score for confidence calculation
        top_score = results[0]["similarity"] if results else 0.0
        return results, top_score

    def retrieve_all(self, session_id: str) -> list:
        """Return all memories for a session (for context building)."""
        return [
            {"content": r["content"], "entity_type": r["entity_type"]}
            for r in self._store.get(session_id, [])
        ]

    def clear_session(self, session_id: str) -> None:
        """Clear all memory for a session after booking completes."""
        self._store.pop(session_id, None)
        self._session_state.pop(session_id, None)

    # ── TF-IDF Embedding ──────────────────────────────────────────────
    def _embed(self, text: str) -> dict:
        """
        Lightweight TF-IDF style term-frequency embedding.
        Returns {term: weight} dict.
        """
        tokens = re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())
        tf = defaultdict(float)
        for t in tokens:
            tf[t] += 1.0
        total = sum(tf.values()) or 1
        return {t: c / total for t, c in tf.items()}

    def _cosine(self, a: dict, b: dict) -> float:
        """Cosine similarity between two TF embedding dicts."""
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[t] * b[t] for t in common)
        mag_a = math.sqrt(sum(v**2 for v in a.values()))
        mag_b = math.sqrt(sum(v**2 for v in b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return min(1.0, dot / (mag_a * mag_b))


# Singleton instance
rag_server = RAGServer()
