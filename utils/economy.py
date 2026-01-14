import json
import os
from datetime import datetime, timedelta

ECON_FILE = "economy.json"

def load_json(file):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}


def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


economy = load_json(ECON_FILE)
economy.setdefault("global", {})
economy.setdefault("guilds", {})


def _ensure_user_record(container: dict, user_id: str) -> dict:
    """Return a mutable user record dict, creating it if needed.

    This preserves additional fields (e.g., rebirths) when updating balances.
    """
    uid = str(user_id)
    rec = container.get(uid)
    if not isinstance(rec, dict):
        rec = {}
        container[uid] = rec
    return rec


def get_balance(user_id: str, guild_id: str = None) -> int:
    """Return the balance for the user.

    If guild_id is provided, return the guild-scoped balance. Otherwise use global balance.
    """
    if guild_id:
        rec = economy.get("guilds", {}).get(str(guild_id), {}).get(str(user_id), {})
        return int(rec.get("balance", 0)) if isinstance(rec, dict) else 0
    rec = economy.get("global", {}).get(str(user_id), {})
    return int(rec.get("balance", 0)) if isinstance(rec, dict) else 0


def set_balance(user_id: str, amount: int, guild_id: str = None):
    if guild_id:
        g = economy.setdefault("guilds", {}).setdefault(str(guild_id), {})
        rec = _ensure_user_record(g, str(user_id))
        rec["balance"] = int(amount)
    else:
        g = economy.setdefault("global", {})
        rec = _ensure_user_record(g, str(user_id))
        rec["balance"] = int(amount)
    save_json(ECON_FILE, economy)


def add_currency(user_id: str, amount: int, guild_id: str = None):
    if guild_id:
        g = economy.setdefault("guilds", {}).setdefault(str(guild_id), {})
        rec = _ensure_user_record(g, str(user_id))
        rec["balance"] = int(rec.get("balance", 0)) + int(amount)
    else:
        g = economy.setdefault("global", {})
        rec = _ensure_user_record(g, str(user_id))
        rec["balance"] = int(rec.get("balance", 0)) + int(amount)
    save_json(ECON_FILE, economy)


def get_rebirths(user_id: str, guild_id: str | None = None) -> int:
    """Return the rebirth count for a user in a guild (server).

    Rebirths are guild-scoped.
    """
    if not guild_id:
        return 0
    rec = economy.get("guilds", {}).get(str(guild_id), {}).get(str(user_id), {})
    if not isinstance(rec, dict):
        return 0
    try:
        return int(rec.get("rebirths", 0))
    except Exception:
        return 0


def set_rebirths(user_id: str, count: int, guild_id: str | None = None):
    """Set the rebirth count for a user in a guild (server)."""
    if not guild_id:
        return
    g = economy.setdefault("guilds", {}).setdefault(str(guild_id), {})
    rec = _ensure_user_record(g, str(user_id))
    rec["rebirths"] = int(count)
    save_json(ECON_FILE, economy)


def increment_rebirths(user_id: str, guild_id: str | None = None) -> int:
    """Increment and return the user's guild-scoped rebirth count."""
    current = get_rebirths(user_id, guild_id=guild_id)
    new_val = int(current) + 1
    set_rebirths(user_id, new_val, guild_id=guild_id)
    return new_val


def remove_currency(user_id: str, amount: int, guild_id: str = None) -> bool:
    bal = get_balance(user_id, guild_id=guild_id)
    if bal < amount:
        return False
    set_balance(user_id, bal - amount, guild_id=guild_id)
    return True


_last_daily = economy.get("_last_daily", {})
_global_daily = economy.get("_global_daily", {})


def can_claim_daily(user_id: str, guild_id: str = None) -> bool:
    """Return True if the user can claim their daily reward.

    This uses a calendar-day reset based on UTC `reset_hour` (default 0 — midnight UTC).
    If guild_id is provided, checks per-guild daily claims. Otherwise uses global tracking.
    If the user's last claim is before the current reset boundary, they may claim now.
    """
    if guild_id:
        # Guild-scoped daily tracking
        guild_dailies = _last_daily.get("guilds", {}).get(str(guild_id), {})
        last = guild_dailies.get(str(user_id))
    else:
        # Global daily tracking (legacy)
        last = _last_daily.get(str(user_id))
    
    now = datetime.utcnow()
    boundary = _get_reset_boundary(now, reset_hour=0)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except Exception:
        return True
    # user can claim if their last claim was before the current boundary
    return last_dt < boundary


def set_daily_claim(user_id: str, guild_id: str = None):
    if guild_id:
        # Guild-scoped daily tracking
        _last_daily.setdefault("guilds", {}).setdefault(str(guild_id), {})[str(user_id)] = datetime.utcnow().isoformat()
    else:
        # Global daily tracking (legacy)
        _last_daily[str(user_id)] = datetime.utcnow().isoformat()
    
    economy["_last_daily"] = _last_daily
    save_json(ECON_FILE, economy)


def get_guild_balances(guild_id: str) -> dict:
    """Return a mapping of user_id -> balance for the given guild.

    Returns empty dict if no balances exist for the guild.
    """
    return {uid: data.get("balance", 0) for uid, data in economy.get("guilds", {}).get(str(guild_id), {}).items()}


def _get_reset_boundary(now: datetime, reset_hour: int = 0) -> datetime:
    """Return the most recent reset boundary (UTC) before or equal to now at reset_hour."""
    boundary = datetime(year=now.year, month=now.month, day=now.day, hour=reset_hour)
    if now < boundary:
        boundary = boundary - timedelta(days=1)
    return boundary


def can_claim_global_daily(reset_hour: int = 0) -> bool:
    """Return True if the global daily reward is available (based on reset_hour UTC).

    Behavior: there is a single global daily window. Once any user claims, no other user may claim
    again until the next reset boundary. The reset boundary is daily at `reset_hour` UTC.
    """
    last_iso = _global_daily.get("last_claim")
    now = datetime.utcnow()
    boundary = _get_reset_boundary(now, reset_hour)
    # If there is no last claim, it's available
    if not last_iso:
        return True
    try:
        last_dt = datetime.fromisoformat(last_iso)
    except Exception:
        return True
    # If last claim is before the current boundary, available
    return last_dt < boundary


def set_global_daily_claim(user_id: str):
    _global_daily["last_claim"] = datetime.utcnow().isoformat()
    _global_daily["last_user"] = user_id
    economy["_global_daily"] = _global_daily
    save_json(ECON_FILE, economy)


def daily_time_until_next(user_id: str, guild_id: str = None, reset_hour: int = 0):
    """Return a timedelta of how long until the user can claim daily again.

    If the user can already claim, returns timedelta(0).
    Uses the same boundary logic as can_claim_daily (calendar day boundary at reset_hour UTC).
    """
    now = datetime.utcnow()
    boundary = _get_reset_boundary(now, reset_hour=reset_hour)
    if guild_id:
        last = _last_daily.get("guilds", {}).get(str(guild_id), {}).get(str(user_id))
    else:
        last = _last_daily.get(str(user_id))
    if not last:
        return timedelta(0)
    try:
        last_dt = datetime.fromisoformat(last)
    except Exception:
        return timedelta(0)
    # If last claim before boundary, can claim now
    if last_dt < boundary:
        return timedelta(0)
    # Otherwise next boundary is boundary + 1 day
    next_boundary = boundary + timedelta(days=1)
    remaining = next_boundary - now
    if remaining.total_seconds() < 0:
        return timedelta(0)
    return remaining


def delete_balance(user_id: str, guild_id: str | None = None):
    """Delete a user's balance entry.

    If guild_id is provided, delete from that guild's scoped balances and clean
    up any guild-scoped daily tracking for the user. Otherwise delete from global.
    """
    uid = str(user_id)
    if guild_id:
        gid = str(guild_id)
        # Remove balance from guild scope
        try:
            g = economy.setdefault("guilds", {}).setdefault(gid, {})
            g.pop(uid, None)
            if not g:
                # Remove empty guild bucket to keep file tidy
                economy.get("guilds", {}).pop(gid, None)
        except Exception:
            pass
        # Clean guild-scoped daily tracking
        try:
            guild_dailies = _last_daily.setdefault("guilds", {}).setdefault(gid, {})
            guild_dailies.pop(uid, None)
            # If empty, remove guild entry
            if not guild_dailies:
                _last_daily.get("guilds", {}).pop(gid, None)
            economy["_last_daily"] = _last_daily
        except Exception:
            pass
    else:
        try:
            economy.setdefault("global", {}).pop(uid, None)
        except Exception:
            pass
    save_json(ECON_FILE, economy)


def reset_guild_balances(guild_id: str):
    """Reset all balances for a specific guild by removing its entry.

    Also cleans up any empty containers and persists the change.
    """
    gid = str(guild_id)
    try:
        g = economy.get("guilds", {}).get(gid, {})
        if isinstance(g, dict):
            # Preserve other fields (e.g., rebirths) while zeroing balances.
            for uid, rec in g.items():
                if isinstance(rec, dict):
                    rec["balance"] = 0
    except Exception:
        pass
    save_json(ECON_FILE, economy)
