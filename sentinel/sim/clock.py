"""Simulated time: integer seconds since the start of the window."""
from __future__ import annotations

import random

MINUTE = 60
HOUR = 3600
DAY = 24 * HOUR
WINDOW_DAYS = 28        # one benign scenario = one household over 28 days (design-v2 §6.2)


def at(day: int, hour: int, minute: int = 0) -> int:
    return day * DAY + hour * HOUR + minute * MINUTE


def rand_time(rng: random.Random, day: int, h_lo: int = 8, h_hi: int = 21) -> int:
    return at(day, rng.randint(h_lo, h_hi), rng.randrange(60))


def hold(rng: random.Random, lo_h: int, hi_h: int) -> int:
    """A random duration between lo_h and hi_h hours, to the minute."""
    return rng.randint(lo_h * 60, hi_h * 60) * MINUTE
