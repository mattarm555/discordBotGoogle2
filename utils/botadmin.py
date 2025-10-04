import os
import json
from typing import Iterable, Optional
import discord
from discord import app_commands

CONFIG_FILE = "xp_config.json"


def _load_json(file: str):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}


def _save_json(file: str, data: dict):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def _get_config() -> dict:
    return _load_json(CONFIG_FILE)


def get_bot_admin_role_ids(guild_id: str) -> list[str]:
    cfg = _get_config()
    return list(cfg.get(guild_id, {}).get("permissions_roles", []))


def add_bot_admin_role(guild_id: str, role_id: int) -> None:
    cfg = _get_config()
    guild_cfg = cfg.setdefault(guild_id, {})
    roles = set(guild_cfg.setdefault("permissions_roles", []))
    roles.add(str(role_id))
    guild_cfg["permissions_roles"] = list(roles)
    _save_json(CONFIG_FILE, cfg)


def remove_bot_admin_role(guild_id: str, role_id: int) -> None:
    cfg = _get_config()
    guild_cfg = cfg.setdefault(guild_id, {})
    roles = set(guild_cfg.setdefault("permissions_roles", []))
    roles.discard(str(role_id))
    guild_cfg["permissions_roles"] = list(roles)
    _save_json(CONFIG_FILE, cfg)


def get_owner_id() -> Optional[int]:
    # Optional convenience: top-level owner_id in xp_config.json
    cfg = _get_config()
    owner_id = cfg.get("owner_id")
    try:
        return int(owner_id) if owner_id is not None else None
    except Exception:
        return None


def is_bot_admin(member: discord.Member, *, allow_guild_owner: bool = True, allow_owner_id: Optional[int] = None) -> bool:
    """Check if a member is a bot-admin based on configured role IDs.

    - Ignores Discord-level permissions.
    - Optionally allows guild owner and a configured global owner id.
    """
    if not isinstance(member, discord.Member) or not member.guild:
        return False

    if allow_guild_owner and member.guild.owner_id == member.id:
        return True

    if allow_owner_id is None:
        allow_owner_id = get_owner_id()
    if allow_owner_id and member.id == allow_owner_id:
        return True

    role_ids = set(get_bot_admin_role_ids(str(member.guild.id)))
    if not role_ids:
        return False

    for role in member.roles:
        if str(role.id) in role_ids:
            return True
    return False


# Slash-command check decorator for easy reuse
async def _ensure_bot_admin(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if isinstance(member, discord.Member) and is_bot_admin(member):
        return True
    raise app_commands.CheckFailure("❌ You do not have permission to use this command.")


def app_check_bot_admin():
    return app_commands.check(_ensure_bot_admin)
