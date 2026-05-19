"""
Score history and streak persistence.
Stores behavioral signals (streak_days, momentum_slope, score history)
per anonymous browser-minted user ID. No financial data is stored.
"""
import sqlite3
import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger("fhs.history")

DB_PATH = Path(__file__).parent / "fhs_history.db"


def compute_fingerprint(fields: dict) -> str:
    """Stable, deterministic fingerprint for a profile's core inputs.

    Rendered as a canonical pipe-delimited string — produces identical output
    from Python and JS given the same field values. Keep this in sync with
    the client-side fingerprint() helper in static/index.html.
    """
    keys = ("I_gross", "I_net", "E_ess", "E_house", "D_min",
            "D_hi", "D_lo", "S_liq", "S_ret", "age")
    parts = []
    for k in keys:
        v = fields.get(k, 0)
        if v is None:
            v = 0
        parts.append(f"{k}={float(v):.0f}")
    return "|".join(parts)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_state (
                user_id       TEXT PRIMARY KEY,
                streak_days   INTEGER NOT NULL DEFAULT 0,
                momentum_slope REAL NOT NULL DEFAULT 0.0,
                last_score_date TEXT,          -- ISO date string YYYY-MM-DD
                updated_at    TEXT NOT NULL DEFAULT (date('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS score_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                scored_at   TEXT NOT NULL DEFAULT (date('now')),  -- ISO date
                fhs         INTEGER NOT NULL,
                fss         INTEGER NOT NULL,
                frs         INTEGER NOT NULL,
                solver      TEXT NOT NULL DEFAULT 'multiperiod',
                input_fingerprint TEXT NOT NULL DEFAULT ''
            )
        """)
        # Additive upgrade for existing DBs — tolerates schema pre-dating the
        # input_fingerprint column.
        try:
            conn.execute("ALTER TABLE score_history ADD COLUMN input_fingerprint TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_user
            ON score_history(user_id, scored_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_user_fingerprint
            ON score_history(user_id, input_fingerprint, scored_at DESC)
        """)


def get_user_state(user_id: str) -> dict:
    """Return current streak_days, momentum_slope for a user.
    Returns defaults if user has never scored before — or if SQLite errors."""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT streak_days, momentum_slope, last_score_date "
                "FROM user_state WHERE user_id = ?",
                (user_id,)
            ).fetchone()
        if row is None:
            return {"streak_days": 0, "momentum_slope": 0.0, "last_score_date": None}
        return dict(row)
    except Exception:
        logger.warning("get_user_state failed for %s", user_id, exc_info=True)
        return {"streak_days": 0, "momentum_slope": 0.0, "last_score_date": None}


def record_score(user_id: str, fhs: int, fss: int, frs: int, solver: str,
                 fingerprint: str = "") -> dict:
    """Record a new score and update streak + momentum_slope.

    Streak rules:
    - First score ever: streak = 1
    - Scored yesterday or today: streak += 1 (today = no change to streak count,
      just updates last_score_date so the user doesn't lose their streak for
      scoring twice in one day)
    - Gap of exactly 1 day (yesterday): streak += 1
    - Gap > 1 day: streak resets to 1

    Momentum slope rules:
    - Computed as the linear regression slope of the last 7 FHS scores
    - Normalized to [-1, 1] range: divide raw slope by 50 (a 50-pt/week
      improvement is exceptional; above that we cap at 1.0)
    - Minimum 2 scores needed; returns 0.0 with only 1 score

    Returns the updated state dict: {streak_days, momentum_slope, last_score_date}

    On SQLite error: logs a warning and returns default zero-state so the API
    call still succeeds — persistence becomes best-effort.
    """
    today = date.today().isoformat()

    try:
        with _conn() as conn:
            # Noise filter: skip inserting a history row when the latest
            # SAME-FINGERPRINT FHS is within ±5 points (same-day refetches or
            # re-submits of the same form shouldn't flood the chart). Filter
            # by fingerprint so switching archetypes starts a fresh series.
            last_fhs_row = conn.execute(
                "SELECT fhs FROM score_history "
                "WHERE user_id = ? AND input_fingerprint = ? "
                "ORDER BY scored_at DESC, id DESC LIMIT 1",
                (user_id, fingerprint)
            ).fetchone()
            skip_insert = (
                last_fhs_row is not None
                and abs(int(last_fhs_row["fhs"]) - int(fhs)) < 5
            )
            if not skip_insert:
                conn.execute(
                    "INSERT INTO score_history "
                    "(user_id, scored_at, fhs, fss, frs, solver, input_fingerprint) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, today, fhs, fss, frs, solver, fingerprint)
                )

            # Fetch current state
            row = conn.execute(
                "SELECT streak_days, momentum_slope, last_score_date "
                "FROM user_state WHERE user_id = ?",
                (user_id,)
            ).fetchone()

            if row is None:
                new_streak = 1
            else:
                last = row["last_score_date"]
                current_streak = row["streak_days"]
                if last is None:
                    new_streak = 1
                elif last == today:
                    # Already scored today — preserve streak, just update timestamp
                    new_streak = current_streak
                else:
                    last_date = date.fromisoformat(last)
                    delta = (date.today() - last_date).days
                    if delta == 1:
                        new_streak = current_streak + 1
                    else:
                        new_streak = 1   # gap broke the streak

            # Compute momentum_slope from last 7 FHS scores (including just-inserted)
            rows = conn.execute(
                "SELECT fhs FROM score_history WHERE user_id = ? "
                "ORDER BY scored_at DESC, id DESC LIMIT 7",
                (user_id,)
            ).fetchall()
            fhs_vals = [r["fhs"] for r in rows]

            if len(fhs_vals) < 2:
                new_slope = 0.0
            else:
                # Simple linear regression on index vs FHS (oldest first)
                vals = list(reversed(fhs_vals))
                n = len(vals)
                x_mean = (n - 1) / 2
                y_mean = sum(vals) / n
                num = sum((i - x_mean) * (vals[i] - y_mean) for i in range(n))
                den = sum((i - x_mean) ** 2 for i in range(n))
                raw_slope = num / den if den > 0 else 0.0
                # Normalize: 50 FHS points per session = slope of 1.0
                new_slope = max(-1.0, min(1.0, raw_slope / 50.0))

            # Upsert user_state
            conn.execute("""
                INSERT INTO user_state (user_id, streak_days, momentum_slope, last_score_date, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    streak_days    = excluded.streak_days,
                    momentum_slope = excluded.momentum_slope,
                    last_score_date = excluded.last_score_date,
                    updated_at     = excluded.updated_at
            """, (user_id, new_streak, new_slope, today, today))

        return {
            "streak_days": new_streak,
            "momentum_slope": round(new_slope, 4),
            "last_score_date": today,
        }
    except Exception:
        logger.warning("record_score failed for %s", user_id, exc_info=True)
        return {"streak_days": 0, "momentum_slope": 0.0, "last_score_date": None}


def get_score_history(user_id: str, limit: int = 30, fingerprint: str = "") -> list:
    """Return the last `limit` score records for a user, newest first.
    When `fingerprint` is non-empty, only returns rows matching that input
    fingerprint — used to isolate each profile's history from others.
    On SQLite error: logs a warning and returns an empty list."""
    try:
        with _conn() as conn:
            if fingerprint:
                rows = conn.execute(
                    "SELECT scored_at, fhs, fss, frs, solver, input_fingerprint "
                    "FROM score_history "
                    "WHERE user_id = ? AND input_fingerprint = ? "
                    "ORDER BY scored_at DESC, id DESC LIMIT ?",
                    (user_id, fingerprint, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT scored_at, fhs, fss, frs, solver, input_fingerprint "
                    "FROM score_history WHERE user_id = ? "
                    "ORDER BY scored_at DESC, id DESC LIMIT ?",
                    (user_id, limit)
                ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.warning("get_score_history failed for %s", user_id, exc_info=True)
        return []


def history_interpretation(history: list) -> str:
    """One-sentence summary of the user's score history.

    `history` is newest-first (as returned by get_score_history).
    For fewer than 3 sessions we return a "still building" message.
    """
    if not history or len(history) < 3:
        return ("Your history is still building. "
                "Come back in a few days to see your trajectory.")

    # Work chronologically — oldest first.
    rows = list(reversed(history))
    try:
        first_date = date.fromisoformat(rows[0]["scored_at"])
        last_date  = date.fromisoformat(rows[-1]["scored_at"])
    except Exception:
        first_date = last_date = None

    first_fhs = int(rows[0]["fhs"])
    last_fhs  = int(rows[-1]["fhs"])
    total_gain = last_fhs - first_fhs

    # Largest single-session jump (delta vs previous session)
    biggest_delta = 0
    biggest_idx   = 0
    for i in range(1, len(rows)):
        d = int(rows[i]["fhs"]) - int(rows[i-1]["fhs"])
        if abs(d) > abs(biggest_delta):
            biggest_delta = d
            biggest_idx = i

    big_date = rows[biggest_idx]["scored_at"]
    try:
        big_date_str = date.fromisoformat(big_date).strftime("%b %-d")
    except (ValueError, TypeError):
        # %-d is POSIX; fall back for Windows.
        try:
            big_date_str = date.fromisoformat(big_date).strftime("%b %#d")
        except Exception:
            big_date_str = big_date

    span_days = (last_date - first_date).days if first_date and last_date else len(rows)
    span_label = (f"{span_days} day{'s' if span_days != 1 else ''}"
                  if span_days > 0 else "a few sessions")

    if total_gain > 0:
        head = (f"You've gained {total_gain} points in {span_label}"
                if total_gain > 1 else
                f"You've edged up {total_gain} point in {span_label}")
        if biggest_delta > 4:
            return (f"{head} — your biggest jump was "
                    f"+{biggest_delta} on {big_date_str}.")
        return f"{head} — steady, consistent progress."
    elif total_gain < 0:
        return (f"Your score has moved {abs(total_gain)} points lower over "
                f"{span_label} — let's get it climbing again.")
    else:
        return (f"Your score has held steady over {span_label} — "
                "room to make your next move.")
