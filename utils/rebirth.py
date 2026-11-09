import json
import os
from typing import Tuple

from utils.economy import get_rebirths, increment_rebirths, set_rebirths

REBIRTH_CONFIG_FILE = "rebirth_config.json"  # { guild_id: { "cost": int } }

DEFAULT_REBIRTH_COST = 1_000_000
DEFAULT_MAX_REBIRTHS = 1_000_000  # effectively unlimited unless configured


def _load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_json(path: str, data: dict):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


def get_rebirth_cost(guild_id: int | str) -> int:
    cfg = _load_json(REBIRTH_CONFIG_FILE)
    g = cfg.get(str(guild_id), {}) if isinstance(cfg, dict) else {}
    try:
        cost = int(g.get("cost", DEFAULT_REBIRTH_COST))
    except Exception:
        cost = DEFAULT_REBIRTH_COST
    return max(0, cost)


def get_required_rebirth_cost(guild_id: int | str, user_id: int | str) -> int:
    """Return the required coins to rebirth for this user in this guild.

    Cost scales with rebirths: required = base_cost * 2^(rebirth_count).
    This matches the multiplier progression.
    """
    base = max(0, int(get_rebirth_cost(guild_id)))
    count = max(0, int(get_rebirth_count(guild_id, user_id)))
    try:
        required = base * (2 ** count)
    except Exception:
        required = base
    # prevent absurd runaway values breaking embeds/json
    return max(0, min(int(required), 10_000_000_000_000))


def set_rebirth_cost(guild_id: int | str, cost: int):
    cfg = _load_json(REBIRTH_CONFIG_FILE)
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault(str(guild_id), {})["cost"] = int(cost)
    _save_json(REBIRTH_CONFIG_FILE, cfg)


def get_max_rebirths(guild_id: int | str) -> int:
    """Return the max allowed rebirths for this guild.

    If not set, returns a very large default (effectively unlimited).
    """
    cfg = _load_json(REBIRTH_CONFIG_FILE)
    g = cfg.get(str(guild_id), {}) if isinstance(cfg, dict) else {}
    try:
        mx = int(g.get("max_rebirths", DEFAULT_MAX_REBIRTHS))
    except Exception:
        mx = DEFAULT_MAX_REBIRTHS
    # Clamp to a sane range to avoid broken configs
    return max(0, min(mx, DEFAULT_MAX_REBIRTHS))


def set_max_rebirths(guild_id: int | str, max_rebirths: int):
    """Set the max allowed rebirths for this guild.

    Set to 0 to prevent rebirthing.
    """
    cfg = _load_json(REBIRTH_CONFIG_FILE)
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault(str(guild_id), {})["max_rebirths"] = int(max_rebirths)
    _save_json(REBIRTH_CONFIG_FILE, cfg)


def get_rebirth_count(guild_id: int | str, user_id: int | str) -> int:
    return get_rebirths(str(user_id), guild_id=str(guild_id))


def set_rebirth_count(guild_id: int | str, user_id: int | str, count: int):
    set_rebirths(str(user_id), int(count), guild_id=str(guild_id))


def increment_rebirth_count(guild_id: int | str, user_id: int | str) -> int:
    return increment_rebirths(str(user_id), guild_id=str(guild_id))


def get_rebirth_multiplier(guild_id: int | str, user_id: int | str) -> int:
    """Multiplier doubles each rebirth: 0->1x, 1->2x, 2->4x, 3->8x, ..."""
    count = max(0, get_rebirth_count(guild_id, user_id))
    # 2**0 = 1 (no rebirth), 2**1 = 2 (first rebirth), etc.
    try:
        return 2 ** int(count)
    except Exception:
        return 1


def get_rebirth_status(guild_id: int | str, user_id: int | str) -> Tuple[int, int]:
    """Return (rebirth_count, multiplier)."""
    c = get_rebirth_count(guild_id, user_id)
    return c, get_rebirth_multiplier(guild_id, user_id)
