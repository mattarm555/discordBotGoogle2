"""Shared "what day is it for the daily games" helper (Wordle, daily trivia, profile)."""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.getenv("WORDLE_TZ", "America/New_York"))
    except Exception:
        return ZoneInfo("UTC")


def today() -> date:
    return datetime.now(_tz()).date()
