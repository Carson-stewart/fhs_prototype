# NOTE: access_token is stored in plaintext for prototype.
# Phase 7 production deployment must encrypt at rest (e.g. Fernet with key from secrets manager).
# See CLAUDE.md Phase 7 deferred items.
"""
Plaid item-token persistence.

Reuses the existing fhs_history.db SQLite file (created by history.py) so the
prototype keeps a single DB file. New table: `plaid_items`.

Access tokens are LONG-LIVED CREDENTIALS — never log them, never return them
through any API path. The only consumer of `get_access_token()` is the
server-side fetch flow; it should never reach the wire.
"""
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("fhs.plaid_storage")

# Reuse the same SQLite file that history.py uses.
DB_PATH = Path(__file__).parent / "fhs_history.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the plaid_items table if it doesn't exist. Idempotent.

    Also adds the `session_id` column to existing databases (P4-4
    migration). The `ALTER TABLE ADD COLUMN` is wrapped to tolerate the
    `duplicate column name` error that fires on second-run.
    """
    try:
        with _conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plaid_items (
                    item_id          TEXT PRIMARY KEY,
                    access_token     TEXT NOT NULL,
                    institution_name TEXT,
                    institution_id   TEXT,
                    created_at       TEXT NOT NULL,
                    last_synced_at   TEXT,
                    session_id       TEXT
                )
            """)
            # Migration: existing DBs from P4-2 won't have session_id.
            try:
                conn.execute("ALTER TABLE plaid_items ADD COLUMN session_id TEXT")
            except sqlite3.OperationalError as exc:
                # SQLite raises "duplicate column name" once column exists.
                if "duplicate column name" not in str(exc).lower():
                    raise
            # Index for session lookups.
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_plaid_items_session
                ON plaid_items(session_id)
            """)
    except Exception:
        logger.exception("init_db failed")
        raise


def save_item(item_id: str, access_token: str,
              institution_name: str | None = None,
              institution_id: str | None = None,
              session_id: str | None = None) -> None:
    """Persist a freshly-exchanged access token + institution metadata.
    Upserts on item_id so re-connecting the same institution overwrites.
    `session_id` groups items connected within one browser session.
    """
    if not item_id or not access_token:
        raise ValueError("item_id and access_token are required")
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    try:
        with _conn() as conn:
            conn.execute("""
                INSERT INTO plaid_items
                    (item_id, access_token, institution_name, institution_id,
                     created_at, last_synced_at, session_id)
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    access_token     = excluded.access_token,
                    institution_name = excluded.institution_name,
                    institution_id   = excluded.institution_id,
                    session_id       = excluded.session_id
            """, (item_id, access_token, institution_name, institution_id,
                  now, session_id))
    except Exception:
        # Don't include token text in logs.
        logger.exception("save_item failed for item_id=%s", item_id)
        raise


def get_items_for_session(session_id: str) -> list[dict]:
    """Return the list of items connected within a session, newest first.
    Each entry: {item_id, institution_name, institution_id, last_synced_at}
    — never includes the access_token (that's a separate internal lookup)."""
    if not session_id:
        return []
    try:
        with _conn() as conn:
            rows = conn.execute("""
                SELECT item_id, institution_name, institution_id, last_synced_at
                FROM plaid_items
                WHERE session_id = ?
                ORDER BY created_at DESC
            """, (session_id,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("get_items_for_session failed for session_id=%s", session_id)
        return []


def get_access_token(item_id: str) -> str | None:
    """Read the access token for a given item_id. INTERNAL USE ONLY —
    must never be exposed to the API response surface."""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT access_token FROM plaid_items WHERE item_id = ?",
                (item_id,)
            ).fetchone()
        return row["access_token"] if row else None
    except Exception:
        logger.exception("get_access_token failed for item_id=%s", item_id)
        return None


def get_item_metadata(item_id: str) -> dict | None:
    """Return everything except the access token. Safe for API responses."""
    try:
        with _conn() as conn:
            row = conn.execute("""
                SELECT item_id, institution_name, institution_id,
                       created_at, last_synced_at
                FROM plaid_items WHERE item_id = ?
            """, (item_id,)).fetchone()
        return dict(row) if row else None
    except Exception:
        logger.exception("get_item_metadata failed for item_id=%s", item_id)
        return None


def delete_other_items_for_institution(session_id: str,
                                       institution_id,
                                       keep_item_id: str) -> int:
    """Delete any other items in the same session that share institution_id,
    preserving only `keep_item_id`. Returns the number of rows removed.

    P4-H4 Fix #1 — same-institution dedupe. Plaid returns a fresh item_id
    each time a user re-connects through Link, so the frontend pill list
    can't dedupe by item_id. Dedupe by institution_id at the exchange
    handler instead: when a user re-connects to the same bank, the new
    item supersedes the old one, preventing double-counted balances.

    `institution_id=None` is a no-op — Plaid Link occasionally returns
    None for the institution metadata, and we can't dedupe without it.
    """
    if not session_id or not institution_id or not keep_item_id:
        return 0
    try:
        with _conn() as conn:
            cur = conn.execute(
                "DELETE FROM plaid_items "
                "WHERE session_id = ? AND institution_id = ? AND item_id != ?",
                (session_id, institution_id, keep_item_id),
            )
            return cur.rowcount or 0
    except Exception:
        logger.exception(
            "delete_other_items_for_institution failed (session=%s, inst=%s)",
            session_id, institution_id,
        )
        return 0


def delete_item(item_id: str, session_id=None) -> bool:
    """Delete a single plaid_items row. If `session_id` is supplied, the
    delete only succeeds when the row matches both — protects against a
    forged item_id from another browser tab.

    Wired into the DELETE /plaid/item disconnect endpoint added in P4-H4.
    """
    if not item_id:
        return False
    try:
        with _conn() as conn:
            if session_id:
                cur = conn.execute(
                    "DELETE FROM plaid_items WHERE item_id = ? AND session_id = ?",
                    (item_id, session_id),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM plaid_items WHERE item_id = ?",
                    (item_id,),
                )
            return (cur.rowcount or 0) > 0
    except Exception:
        logger.exception("delete_item failed for item_id=%s", item_id)
        return False


def update_last_synced(item_id: str) -> None:
    """Stamp the last successful fetch timestamp."""
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    try:
        with _conn() as conn:
            conn.execute(
                "UPDATE plaid_items SET last_synced_at = ? WHERE item_id = ?",
                (now, item_id)
            )
    except Exception:
        logger.exception("update_last_synced failed for item_id=%s", item_id)
