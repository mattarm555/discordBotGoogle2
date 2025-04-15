# utils/debug.py

def debug_command(command_name, user, **kwargs):
    print(f"\033[1;32m[COMMAND] /{command_name}\033[0m triggered by \033[1;33m{user.display_name}\033[0m")
    if kwargs:
        print("\033[1;36mInput:\033[0m")
        for key, value in kwargs.items():
            print(f"\033[1;31m  {key.capitalize()}: {value}\033[0m")
