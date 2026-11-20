"""Game rules and balance constants for the GLN mining simulation.

All values are points, not real tokens. Points convert to GLN at TGE.
"""

BASE_RATE = 100                 # points per mining session at rig level 1
BASE_COOLDOWN_SEC = 4 * 3600    # time from session start until claimable
GRACE_SEC = 8 * 3600            # unclaimed sessions expire this long after they become ready
MIN_COOLDOWN_SEC = 3600         # cooldown can never go below 1 hour
COOLDOWN_STEP_SEC = 15 * 60     # each cooldown level shortens the cooldown by this much

RATE_STEP = 0.25                # each rig level adds 25% of the base rate

REF_JOIN_BONUS = 250            # inviter reward when a referred user joins
REF_FIRST_CLAIM_BONUS = 500     # inviter reward when the referred user claims for the first time
WELCOME_BONUS = 100             # points gifted to every new user


def session_amount(rig_level: int) -> int:
    """Points earned by one session at the given rig level."""
    return round(BASE_RATE * (1 + RATE_STEP * (rig_level - 1)))


def cooldown_sec(cooldown_level: int) -> int:
    """Seconds from session start until the session is claimable."""
    return max(MIN_COOLDOWN_SEC, BASE_COOLDOWN_SEC - (cooldown_level - 1) * COOLDOWN_STEP_SEC)


def upgrade_cost(current_level: int) -> int:
    """Cost in points to go from current_level to current_level + 1."""
    return 300 * current_level


def fmt_duration(seconds: int) -> str:
    """Human-readable Arabic duration like '3 ساعات و 20 دقيقة'."""
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    parts = []
    if hours:
        parts.append(f"{hours} ساعة" if hours == 1 else f"{hours} ساعات")
    if minutes or not parts:
        parts.append(f"{minutes} دقيقة" if minutes == 1 else f"{minutes} دقائق")
    return " و ".join(parts)
