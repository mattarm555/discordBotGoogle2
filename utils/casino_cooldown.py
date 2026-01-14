import json
import os
from datetime import datetime

CASINO_COOLDOWNS_FILE = "casino_cooldowns.json"  # { guild_id: { user_id: iso_timestamp } }


def _load() -> dict:
    if os.path.exists(CASINO_COOLDOWNS_FILE):
        try:
            with open(CASINO_COOLDOWNS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save(data: dict):
    try:
        with open(CASINO_COOLDOWNS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


def get_last_casino_play(guild_id: str, user_id: str) -> datetime | None:
    data = _load()
    g = data.get(str(guild_id), {}) if isinstance(data, dict) else {}
    if not isinstance(g, dict):
        return None
    iso = g.get(str(user_id))
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return None


def set_last_casino_play(guild_id: str, user_id: str, when: datetime | None = None):
    if when is None:
        when = datetime.utcnow()
    data = _load()
    if not isinstance(data, dict):
        data = {}
    g = data.setdefault(str(guild_id), {})
    if not isinstance(g, dict):
        data[str(guild_id)] = {}
        g = data[str(guild_id)]
    g[str(user_id)] = when.isoformat()
    _save(data)


def cooldown_remaining_seconds(guild_id: str, user_id: str, cooldown_sec: int) -> int:
    last = get_last_casino_play(guild_id, user_id)
    if not last:
        return 0
    try:
        elapsed = (datetime.utcnow() - last).total_seconds()
        rem = float(cooldown_sec) - elapsed
        if rem <= 0:
            return 0
        return int(rem) if float(rem).is_integer() else int(rem) + 1
    except Exception:
        return 0
