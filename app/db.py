"""Storage layer. Uses Postgres (Neon) when DATABASE_URL is set, SQLite otherwise.

Connections open per operation and close immediately, which lets Neon's
free compute scale to zero between user actions. `now` parameters exist so
tests can control time. SQL is written with %s placeholders (psycopg style)
and converted to ? for SQLite."""
import contextlib
import secrets
import time

from . import game
from .config import DATABASE_URL, DB_PATH

_USE_PG = bool(DATABASE_URL)

if _USE_PG:
    import psycopg
    from psycopg.rows import dict_row
else:
    import sqlite3


def _q(sql: str) -> str:
    """Translate psycopg-style placeholders for SQLite."""
    return sql if _USE_PG else sql.replace("%s", "?")


@contextlib.contextmanager
def _conn():
    if _USE_PG:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            yield conn  # commits on clean exit, rolls back on error, then closes
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()


_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    ref_code TEXT UNIQUE NOT NULL,
    referred_by BIGINT REFERENCES users(id),
    points BIGINT NOT NULL DEFAULT 0,
    total_earned BIGINT NOT NULL DEFAULT 0,
    rig_level INTEGER NOT NULL DEFAULT 1,
    cooldown_level INTEGER NOT NULL DEFAULT 1,
    first_claim_done INTEGER NOT NULL DEFAULT 0,
    joined_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    started_at DOUBLE PRECISION NOT NULL,
    ready_at DOUBLE PRECISION NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    amount BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    claimed_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, status);
"""

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    ref_code TEXT UNIQUE NOT NULL,
    referred_by INTEGER REFERENCES users(id),
    points INTEGER NOT NULL DEFAULT 0,
    total_earned INTEGER NOT NULL DEFAULT 0,
    rig_level INTEGER NOT NULL DEFAULT 1,
    cooldown_level INTEGER NOT NULL DEFAULT 1,
    first_claim_done INTEGER NOT NULL DEFAULT 0,
    joined_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    started_at REAL NOT NULL,
    ready_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    claimed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, status);
"""


def init_db():
    schema = _PG_SCHEMA if _USE_PG else _SQLITE_SCHEMA
    with _conn() as c:
        for statement in schema.split(";"):
            if statement.strip():
                c.execute(statement)


def _new_ref_code(c) -> str:
    while True:
        code = secrets.token_hex(4)
        if not c.execute(_q("SELECT 1 FROM users WHERE ref_code = %s"), (code,)).fetchone():
            return code


def register_user(tg_id: int, username: str, first_name: str, ref_code: str | None = None):
    """Create the user if new. Returns (user_dict, created, inviter_id)."""
    with _conn() as c:
        row = c.execute(_q("SELECT * FROM users WHERE id = %s"), (tg_id,)).fetchone()
        if row:
            return dict(row), False, None
        inviter = None
        if ref_code:
            r = c.execute(_q("SELECT id FROM users WHERE ref_code = %s"), (ref_code,)).fetchone()
            if r and r["id"] != tg_id:
                inviter = r["id"]
        code = _new_ref_code(c)
        c.execute(
            _q("INSERT INTO users (id, username, first_name, ref_code, referred_by, points, total_earned, joined_at)"
               " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"),
            (tg_id, username or "", first_name or "", code, inviter,
             game.WELCOME_BONUS, game.WELCOME_BONUS, time.time()),
        )
        if inviter:
            c.execute(
                _q("UPDATE users SET points = points + %s, total_earned = total_earned + %s WHERE id = %s"),
                (game.REF_JOIN_BONUS, game.REF_JOIN_BONUS, inviter),
            )
        return dict(c.execute(_q("SELECT * FROM users WHERE id = %s"), (tg_id,)).fetchone()), True, inviter


def get_user(tg_id: int):
    with _conn() as c:
        row = c.execute(_q("SELECT * FROM users WHERE id = %s"), (tg_id,)).fetchone()
        return dict(row) if row else None


def get_active_session(user_id: int, now: float | None = None):
    """Return the user's live session, lazily expiring it if the grace window passed."""
    now = now if now is not None else time.time()
    with _conn() as c:
        row = c.execute(
            _q("SELECT * FROM sessions WHERE user_id = %s AND status = 'active' ORDER BY id DESC LIMIT 1"),
            (user_id,),
        ).fetchone()
        if row and now > row["expires_at"]:
            c.execute(_q("UPDATE sessions SET status = 'expired' WHERE id = %s"), (row["id"],))
            return None
        return dict(row) if row else None


def start_session(user_id: int, now: float | None = None):
    """Start a mining session. Returns (session_dict, error_code)."""
    now = now if now is not None else time.time()
    if get_active_session(user_id, now):
        return None, "already_active"
    with _conn() as c:
        user = c.execute(_q("SELECT * FROM users WHERE id = %s"), (user_id,)).fetchone()
        amount = game.session_amount(user["rig_level"])
        ready = now + game.cooldown_sec(user["cooldown_level"])
        row = c.execute(
            _q("INSERT INTO sessions (user_id, started_at, ready_at, expires_at, amount)"
               " VALUES (%s, %s, %s, %s, %s) RETURNING id"),
            (user_id, now, ready, ready + game.GRACE_SEC, amount),
        ).fetchone()
        return dict(c.execute(_q("SELECT * FROM sessions WHERE id = %s"), (row["id"],)).fetchone()), None


def claim_session(user_id: int, now: float | None = None):
    """Claim the current session. Returns (result_dict, error_code).

    error_code: no_session | too_early (result carries seconds_left).
    On success result carries amount, new_balance, inviter (id or None), first_claim.
    """
    now = now if now is not None else time.time()
    session = get_active_session(user_id, now)
    if not session:
        return None, "no_session"
    if now < session["ready_at"]:
        return {"seconds_left": int(session["ready_at"] - now)}, "too_early"
    with _conn() as c:
        c.execute(
            _q("UPDATE sessions SET status = 'claimed', claimed_at = %s WHERE id = %s"),
            (now, session["id"]),
        )
        user = c.execute(_q("SELECT * FROM users WHERE id = %s"), (user_id,)).fetchone()
        amount = session["amount"]
        c.execute(
            _q("UPDATE users SET points = points + %s, total_earned = total_earned + %s, first_claim_done = 1 WHERE id = %s"),
            (amount, amount, user_id),
        )
        inviter, first_claim = None, False
        if user["referred_by"] and not user["first_claim_done"]:
            inviter, first_claim = user["referred_by"], True
            c.execute(
                _q("UPDATE users SET points = points + %s, total_earned = total_earned + %s WHERE id = %s"),
                (game.REF_FIRST_CLAIM_BONUS, game.REF_FIRST_CLAIM_BONUS, inviter),
            )
        balance = c.execute(_q("SELECT points FROM users WHERE id = %s"), (user_id,)).fetchone()["points"]
        return {
            "amount": amount,
            "new_balance": balance,
            "inviter": inviter,
            "first_claim": first_claim,
        }, None


def buy_upgrade(user_id: int, kind: str):
    """kind: 'rig' or 'cooldown'. Returns (new_level, error_code)."""
    col = "rig_level" if kind == "rig" else "cooldown_level"
    if col not in ("rig_level", "cooldown_level"):
        raise ValueError(kind)
    with _conn() as c:
        user = c.execute(_q("SELECT * FROM users WHERE id = %s"), (user_id,)).fetchone()
        level = user[col]
        cost = game.upgrade_cost(level)
        if user["points"] < cost:
            return None, "not_enough_points"
        c.execute(
            _q(f"UPDATE users SET points = points - %s, {col} = {col} + 1 WHERE id = %s"),
            (cost, user_id),
        )
        return level + 1, None


def leaderboard(limit: int = 10):
    with _conn() as c:
        return [dict(r) for r in c.execute(
            _q("SELECT first_name, username, total_earned FROM users ORDER BY total_earned DESC LIMIT %s"),
            (limit,),
        ).fetchall()]


def referral_count(user_id: int) -> int:
    with _conn() as c:
        return c.execute(_q("SELECT COUNT(*) AS n FROM users WHERE referred_by = %s"), (user_id,)).fetchone()["n"]


def all_user_ids():
    with _conn() as c:
        return [r["id"] for r in c.execute("SELECT id FROM users").fetchall()]


def stats(now: float | None = None):
    now = now if now is not None else time.time()
    with _conn() as c:
        c.execute(_q("UPDATE sessions SET status = 'expired' WHERE status = 'active' AND expires_at < %s"), (now,))
        row = c.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM users) AS users,
              (SELECT COUNT(*) FROM sessions) AS sessions,
              (SELECT COUNT(*) FROM sessions WHERE status = 'claimed') AS claims,
              (SELECT COUNT(*) FROM sessions WHERE status = 'active') AS active_sessions,
              (SELECT COALESCE(SUM(total_earned), 0) FROM users) AS points_issued
            """
        ).fetchone()
        return dict(row)
