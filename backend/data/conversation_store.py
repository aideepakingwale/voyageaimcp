"""
VoyageAI Conversation Persistence
==================================
Stores conversation context in SQLite so it survives server restarts
and can be reviewed/debugged.

Tables:
  conversations         — one row per user session
  conversation_turns    — every message in chronological order  
  itinerary_versions    — every plan generated/modified (full audit trail)

The in-memory RAG memory_store is the primary store during a session.
This SQLite store is the durable backup — written after each turn.
On session restore (page refresh), RAG is re-hydrated from SQLite.
"""
import os, sqlite3, json, time, logging
from pathlib import Path

log = logging.getLogger("voyageai.app")

DB_PATH = Path(__file__).parent / "voyageai.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_conversation_tables():
    """Create conversation tables if they don't exist. Safe to call repeatedly."""
    conn = get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                session_id      TEXT PRIMARY KEY,
                customer_id     TEXT,
                customer_name   TEXT,
                started_at      REAL NOT NULL,
                last_active     REAL NOT NULL,
                origin_iata     TEXT,
                entities_json   TEXT DEFAULT '{}',
                status          TEXT DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS conversation_turns (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT NOT NULL,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                intent_type     TEXT,
                intent_subtype  TEXT,
                ts              REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES conversations(session_id)
            );

            CREATE TABLE IF NOT EXISTS itinerary_versions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT NOT NULL,
                version         INTEGER NOT NULL,
                trigger_message TEXT,
                modification_type TEXT,
                itinerary_json  TEXT NOT NULL,
                total_cost_gbp  REAL,
                destination     TEXT,
                departure_date  TEXT,
                guests          INTEGER,
                confidence      REAL,
                provider        TEXT,
                created_at      REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES conversations(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_turns_session
                ON conversation_turns(session_id, ts);
            CREATE INDEX IF NOT EXISTS idx_versions_session
                ON itinerary_versions(session_id, version);
        """)
        conn.commit()
    finally:
        conn.close()


# ── Session management ────────────────────────────────────────

def upsert_conversation(session_id: str, customer_id: str = None,
                        customer_name: str = None, origin_iata: str = None,
                        entities: dict = None):
    """Create or update a conversation record."""
    now = time.time()
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO conversations (session_id, customer_id, customer_name,
                started_at, last_active, origin_iata, entities_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                last_active   = excluded.last_active,
                customer_id   = COALESCE(excluded.customer_id, customer_id),
                customer_name = COALESCE(excluded.customer_name, customer_name),
                origin_iata   = COALESCE(excluded.origin_iata, origin_iata),
                entities_json = COALESCE(excluded.entities_json, entities_json)
        """, (session_id, customer_id, customer_name, now, now,
              origin_iata, json.dumps(entities or {})))
        conn.commit()
    except Exception as e:
        log.debug("upsert_conversation error: %s", e)
    finally:
        conn.close()


def update_entities(session_id: str, entities: dict):
    """Persist updated session entities to DB."""
    conn = get_db()
    try:
        conn.execute("""
            UPDATE conversations SET entities_json=?, last_active=?
            WHERE session_id=?
        """, (json.dumps(entities), time.time(), session_id))
        conn.commit()
    except Exception as e:
        log.debug("update_entities error: %s", e)
    finally:
        conn.close()


# ── Turn storage ──────────────────────────────────────────────

def save_turn(session_id: str, role: str, content: str,
              intent_type: str = None, intent_subtype: str = None):
    """Persist a conversation turn to SQLite."""
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO conversation_turns
                (session_id, role, content, intent_type, intent_subtype, ts)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, role, str(content)[:4000],
              intent_type, intent_subtype, time.time()))
        conn.commit()
    except Exception as e:
        log.debug("save_turn error: %s", e)
    finally:
        conn.close()


def load_turns(session_id: str, limit: int = 30) -> list[dict]:
    """Load recent conversation turns from SQLite."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT role, content, intent_type, intent_subtype, ts
            FROM conversation_turns
            WHERE session_id=?
            ORDER BY ts DESC LIMIT ?
        """, (session_id, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]
    except Exception as e:
        log.debug("load_turns error: %s", e)
        return []
    finally:
        conn.close()


# ── Itinerary versioning ──────────────────────────────────────

def save_itinerary_version(session_id: str, itinerary: dict,
                            trigger_message: str = None,
                            modification_type: str = None,
                            confidence: float = 0.0,
                            provider: str = ""):
    """Save a new itinerary version (full audit trail)."""
    conn = get_db()
    try:
        # Get next version number
        row = conn.execute("""
            SELECT COALESCE(MAX(version), 0) + 1 as next_v
            FROM itinerary_versions WHERE session_id=?
        """, (session_id,)).fetchone()
        version = row["next_v"] if row else 1

        intent = itinerary.get("intent", {})
        dates  = intent.get("dates", {})

        conn.execute("""
            INSERT INTO itinerary_versions
                (session_id, version, trigger_message, modification_type,
                 itinerary_json, total_cost_gbp, destination, departure_date,
                 guests, confidence, provider, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, version,
            (trigger_message or "")[:500],
            modification_type,
            json.dumps(itinerary),
            itinerary.get("total_cost_gbp", 0),
            intent.get("destination", ""),
            dates.get("departure_date", ""),
            intent.get("guests", 0),
            confidence,
            provider,
            time.time(),
        ))
        conn.commit()
        log.info("Itinerary v%d saved", version, extra={
            "session_id": session_id, "version": version,
            "dest": intent.get("destination"), "mod": modification_type,
        })
        return version
    except Exception as e:
        log.debug("save_itinerary_version error: %s", e)
        return 0
    finally:
        conn.close()


def get_latest_itinerary(session_id: str) -> dict | None:
    """Load the most recent itinerary version for a session."""
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT itinerary_json, version, modification_type
            FROM itinerary_versions
            WHERE session_id=?
            ORDER BY version DESC LIMIT 1
        """, (session_id,)).fetchone()
        if row:
            data = json.loads(row["itinerary_json"])
            data["_db_version"] = row["version"]
            data["_modification_type"] = row["modification_type"]
            return data
    except Exception as e:
        log.debug("get_latest_itinerary error: %s", e)
    finally:
        conn.close()
    return None


def get_itinerary_history(session_id: str) -> list[dict]:
    """Get all itinerary versions for a session (for audit/display)."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT version, trigger_message, modification_type,
                   total_cost_gbp, destination, departure_date,
                   guests, confidence, provider, created_at
            FROM itinerary_versions
            WHERE session_id=?
            ORDER BY version ASC
        """, (session_id,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug("get_itinerary_history error: %s", e)
        return []
    finally:
        conn.close()


def restore_session_to_memory(session_id: str) -> dict | None:
    """
    Restore a session from SQLite to in-memory RAG store.
    Called when a user refreshes the page or reconnects.
    Returns the last itinerary if found.
    """
    from rag.memory_store import memory_store

    # Restore turns
    turns = load_turns(session_id, limit=20)
    existing_session = memory_store.get_session(session_id)
    if not existing_session:
        memory_store._sessions[session_id] = {
            "created_at":     time.time(),
            "last_active":    time.time(),
            "entities":       {},
            "history":        [],
            "confirmed":      {},
            "last_itinerary": None,
        }

    for turn in turns:
        memory_store.add_turn(session_id, turn["role"], turn["content"])

    # Restore entities from DB
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT entities_json, origin_iata FROM conversations WHERE session_id=?",
            (session_id,)
        ).fetchone()
        if row and row["entities_json"]:
            entities = json.loads(row["entities_json"])
            for k, v in entities.items():
                if v:
                    memory_store.store_entity(session_id, k, v, 0.90)
        if row and row["origin_iata"]:
            memory_store.store_entity(session_id, "origin_iata",
                                       row["origin_iata"], 0.99)
    except Exception as e:
        log.debug("restore entities error: %s", e)
    finally:
        conn.close()

    # Restore last itinerary
    last = get_latest_itinerary(session_id)
    if last:
        memory_store.store_itinerary(session_id, last)
        log.info("Session restored from DB", extra={
            "session_id": session_id,
            "turns": len(turns),
            "itinerary_version": last.get("_db_version"),
        })
    return last


# Initialise tables on import
try:
    init_conversation_tables()
except Exception as e:
    log.debug("Table init deferred: %s", e)
