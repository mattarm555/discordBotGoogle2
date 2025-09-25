# utils/debug.py

def debug_command(command_name, user, guild=None, channel=None, **kwargs):
    """Print a standardized debug line for commands.

    Usage examples (backwards compatible):
      debug_command('play', user, guild)
      debug_command('scrape', user, limit=100)

    The function will print server name and a clickable channel link when possible.
    """
    # Keep backward-compatible kwarg handling but only print user, guild name and params.
    if not guild and 'guild' in kwargs:
        guild = kwargs.pop('guild')
    if not channel and 'channel' in kwargs:
        # remove channel if passed; we no longer display it
        kwargs.pop('channel')

    guild_name = "DM/Unknown"
    try:
        if guild and hasattr(guild, 'name'):
            guild_name = guild.name
        elif guild:
            guild_name = str(guild)
    except Exception:
        guild_name = str(guild)

    base = f"\033[1;32m[COMMAND] /{command_name}\033[0m triggered by \033[1;33m{user.display_name}\033[0m"
    context = f" in \033[1;34m{guild_name}\033[0m"

    print(base + context)

    if kwargs:
        print("\033[1;36mInput:\033[0m")
        for key, value in kwargs.items():
            print(f"\033[1;31m  {key}: {value}\033[0m")
