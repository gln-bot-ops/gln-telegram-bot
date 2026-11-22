"""Logic tests for the GLN bot, run without Telegram: python tests/test_logic.py"""
import os
import sys
import tempfile

os.environ["GLN_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import db, game  # noqa: E402

T0 = 1_700_000_000.0
failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


db.init_db()

# Registration and referral join bonus
inviter, created, _ = db.register_user(1001, "mohamed", "Mohamed")
check("inviter created", created and inviter["points"] == game.WELCOME_BONUS)
friend, created, inv = db.register_user(2002, "ahmed", "Ahmed", ref_code=inviter["ref_code"])
check("friend created via referral", created and inv == 1001)
check("inviter got join bonus", db.get_user(1001)["points"] == game.WELCOME_BONUS + game.REF_JOIN_BONUS)
check("self-referral rejected", db.register_user(3003, "x", "X", ref_code=None)[2] is None)
again, created, _ = db.register_user(1001, "mohamed", "Mohamed")
check("re-register is a no-op", not created)

# Mining session lifecycle
session, err = db.start_session(2002, now=T0)
check("session started", err is None and session["amount"] == game.session_amount(1))
_, err = db.start_session(2002, now=T0)
check("second session blocked", err == "already_active")

res, err = db.claim_session(2002, now=T0 + 3600)
check("early claim rejected", err == "too_early" and res["seconds_left"] > 0)

ready_at = T0 + game.cooldown_sec(1)
res, err = db.claim_session(2002, now=ready_at + 60)
check("claim at ready time", err is None and res["amount"] == game.BASE_RATE)
check("first-claim referral bonus paid", res["first_claim"] and res["inviter"] == 1001)
check("balance after claim", db.get_user(2002)["points"] == game.WELCOME_BONUS + game.BASE_RATE)

inviter_pts = game.WELCOME_BONUS + game.REF_JOIN_BONUS + game.REF_FIRST_CLAIM_BONUS
check("inviter total", db.get_user(1001)["points"] == inviter_pts)

# Expiry after grace window
session, _ = db.start_session(2002, now=ready_at + 60)
expired = db.get_active_session(2002, now=session["expires_at"] + 1)
check("session expires after grace", expired is None)
res, err = db.claim_session(2002, now=session["expires_at"] + 1)
check("claim after expiry rejected", err == "no_session")

# Upgrades
check("upgrade blocked without funds", db.buy_upgrade(3003, "rig")[1] == "not_enough_points")
with db._conn() as c:  # test-only top-up
    c.execute("UPDATE users SET points = points + 10000 WHERE id = 1001")
lvl, err = db.buy_upgrade(1001, "rig")
check("rig upgrade works", err is None and lvl == 2)
check("rate scales with rig level", game.session_amount(2) == round(game.BASE_RATE * 1.25))
lvl, err = db.buy_upgrade(1001, "cooldown")
check("cooldown upgrade works", err is None and lvl == 2)
check("cooldown shortens", game.cooldown_sec(2) == game.BASE_COOLDOWN_SEC - game.COOLDOWN_STEP_SEC)
check("cooldown floor", game.cooldown_sec(99) == game.MIN_COOLDOWN_SEC)

# Leaderboard and stats
board = db.leaderboard()
check("leaderboard ordered", board[0]["username"] in {"ahmed", "mohamed"} and
      board[0]["total_earned"] >= board[1]["total_earned"])
s = db.stats(now=session["expires_at"] + 2)
check("stats shape", s["users"] == 3 and s["claims"] == 1 and s["points_issued"] > 0)

print()
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print(f"All tests passed ({game.session_amount(1)} base rate, cooldown {game.cooldown_sec(1)}s).")

# --- Force-join membership gate (fake bot, no Telegram) ----------------------
import asyncio
from types import SimpleNamespace
from app import handlers as h


class FakeBot:
    def __init__(self, behavior):
        self.behavior = behavior

    async def get_chat_member(self, chat_id, user_id):
        b = self.behavior
        if isinstance(b, Exception):
            raise b
        return SimpleNamespace(status=b, is_member=(b != "left"))


async def _gate_cases():
    ok = True
    ok &= await h._is_deals_member(FakeBot("member"), 1)
    ok &= await h._is_deals_member(FakeBot("administrator"), 2)
    ok &= not await h._is_deals_member(FakeBot("left"), 3)
    ok &= not await h._is_deals_member(FakeBot("kicked"), 4)
    ok &= not await h._is_deals_member(FakeBot(Exception("Bad Request: member not found")), 5)
    ok &= await h._is_deals_member(FakeBot(Exception("network timeout")), 6)  # fail open
    ok &= await h._is_deals_member(FakeBot("restricted"), 7)  # restricted but in chat
    return ok


check("force-join gate matrix", asyncio.run(_gate_cases()))
