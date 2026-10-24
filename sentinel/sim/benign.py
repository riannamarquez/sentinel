"""Benign household templates (design-v2 §5.2, §6.2). One household = one benign scenario."""
from __future__ import annotations

import random
from collections.abc import Callable

from sentinel.sim.builder import HouseholdBuilder
from sentinel.sim.clock import DAY, WINDOW_DAYS, at, rand_time

HOUSEHOLD_PROB = 0.3    # salaried customer has a dependent in the scenario
SIBLING_PROB = 0.25     # that dependent relays part of the allowance to a sibling


def device_fn(rng: random.Random, account: str, upgrade_prob: float) -> Callable[[int], str]:
    upgrade_at = rand_time(rng, rng.randrange(WINDOW_DAYS)) if rng.random() < upgrade_prob else None
    return lambda ts: f"{account}-d1" if upgrade_at is not None and ts >= upgrade_at else f"{account}-d0"


def purchases(b, rng, acct, dev, per_week, lo, hi):
    for week in range(WINDOW_DAYS // 7):
        for _ in range(rng.randint(*per_week)):
            ts = rand_time(rng, week * 7 + rng.randrange(7))
            b.add(ts, acct, f"EXT-merchant-{rng.randrange(40)}", rng.randint(lo, hi), dev(ts))


def gen_salaried(b: HouseholdBuilder, rng: random.Random, force_relay: bool = False):
    monthly = rng.randint(300_000, 700_000)
    c = b.account("C1", rng.randint(monthly // 2, monthly * 3 // 2))
    dev = device_fn(rng, c, 0.10)
    d0 = rng.randrange(14)
    paydays = [at(d, rng.randint(6, 8), rng.randrange(60)) for d in (d0, d0 + 14)]
    for ts in paydays:
        b.add(ts, "EXT-employer", c, monthly // 2)
    ts = rand_time(rng, 0, 9, 12)
    b.add(ts, c, "EXT-landlord", monthly * rng.randint(25, 40) // 100, dev(ts))
    ts = rand_time(rng, rng.randint(3, 10))
    b.add(ts, c, "EXT-utility", rng.randint(5_000, 20_000), dev(ts))
    purchases(b, rng, c, dev, (3, 10), 500, 15_000)
    for week in range(WINDOW_DAYS // 7):
        if rng.random() < 0.5:
            ts = rand_time(rng, week * 7 + rng.randrange(7))
            b.add(ts, c, "EXT-friend", rng.randint(2_000, 20_000), dev(ts))

    if rng.random() >= HOUSEHOLD_PROB and not force_relay:
        return
    d1 = b.account("D1", rng.randint(0, 20_000))
    dev1 = device_fn(rng, d1, 0.05)
    purchases(b, rng, d1, dev1, (2, 8), 300, 6_000)
    has_sibling = rng.random() < SIBLING_PROB or force_relay
    if has_sibling:
        d2 = b.account("D2", rng.randint(0, 20_000))
        dev2 = device_fn(rng, d2, 0.05)
        purchases(b, rng, d2, dev2, (1, 5), 300, 4_000)
    for pay_ts in paydays:
        if rng.random() < 0.6 or force_relay:
            allowance = rng.randint(5_000, 30_000)
            ts = pay_ts + rng.randint(1 * 60, 6 * 60) * 60
            b.add(ts, c, d1, allowance, dev(ts))
            if has_sibling and (rng.random() < 0.5 or force_relay):
                ts2 = ts + rng.randint(1 * 60, 10 * 60) * 60
                b.add(ts2, d1, d2, allowance * rng.randint(30, 60) // 100, dev1(ts2))


def gen_salaried_relay(b: HouseholdBuilder, rng: random.Random):
    """Lookalike for the hop-count fix: payday -> allowance -> sibling relay, every payday."""
    gen_salaried(b, rng, force_relay=True)


def gen_gig(b: HouseholdBuilder, rng: random.Random):
    c = b.account("C1", rng.randint(20_000, 150_000))
    dev = device_fn(rng, c, 0.15)
    payouts = []
    for day in range(WINDOW_DAYS):
        if rng.random() < 0.7:
            ts = rand_time(rng, day, 10, 23)
            payouts.append(ts)
            b.add(ts, "EXT-platform", c, rng.randint(4_000, 25_000))
    ts = rand_time(rng, 0, 9, 12)
    b.add(ts, c, "EXT-landlord", rng.randint(60_000, 150_000), dev(ts))
    purchases(b, rng, c, dev, (4, 12), 500, 8_000)
    for week in range(WINDOW_DAYS // 7):
        week_payouts = [p for p in payouts if p // DAY // 7 == week]
        if week_payouts and rng.random() < 0.5:
            ts = rng.choice(week_payouts) + rng.randint(10, 12 * 60) * 60
            b.add(ts, c, "EXT-family-abroad", rng.randint(10_000, 60_000), dev(ts))


def gen_student(b: HouseholdBuilder, rng: random.Random):
    c = b.account("C1", rng.randint(5_000, 60_000))
    dev = device_fn(rng, c, 0.10)
    for week in range(WINDOW_DAYS // 7):
        b.add(rand_time(rng, week * 7 + rng.randrange(7)), "EXT-parent", c, rng.randint(5_000, 30_000))
    d0 = rng.randrange(14)
    for d in (d0, d0 + 14):
        b.add(rand_time(rng, d, 6, 9), "EXT-employer", c, rng.randint(30_000, 80_000))
    if rng.random() < 0.5:
        ts = rand_time(rng, 0, 9, 12)
        b.add(ts, c, "EXT-landlord", rng.randint(40_000, 120_000), dev(ts))
    purchases(b, rng, c, dev, (4, 12), 300, 4_000)
    for week in range(WINDOW_DAYS // 7):
        for _ in range(rng.randint(0, 4)):
            ts = rand_time(rng, week * 7 + rng.randrange(7))
            b.add(ts, c, f"EXT-friend-{rng.randrange(10)}", rng.randint(500, 3_000), dev(ts))
        if rng.random() < 0.2:  # splitting a group bill: several transfers within ~30 minutes
            ts = rand_time(rng, week * 7 + rng.randrange(7), 18, 22)
            for i in range(rng.randint(3, 6)):
                ts += rng.randint(1, 8) * 60
                b.add(ts, c, f"EXT-friend-{i}", rng.randint(1_000, 4_000), dev(ts))


def gen_small_business(b: HouseholdBuilder, rng: random.Random):
    biz = b.account("B1", rng.randint(200_000, 1_000_000))
    dev = device_fn(rng, biz, 0.10)
    client_payments = []
    for day in range(WINDOW_DAYS):
        for _ in range(rng.randint(1, 4)):
            ts = rand_time(rng, day, 9, 18)
            client_payments.append(ts)
            b.add(ts, f"EXT-client-{rng.randrange(30)}", biz, rng.randint(5_000, 80_000))
    ts = rand_time(rng, 0, 9, 12)
    b.add(ts, biz, "EXT-office-landlord", rng.randint(100_000, 400_000), dev(ts))
    for week in range(WINDOW_DAYS // 7):
        for _ in range(2):
            ts = rand_time(rng, week * 7 + rng.randrange(7), 9, 17)
            b.add(ts, biz, f"EXT-supplier-{rng.randrange(5)}", rng.randint(50_000, 300_000), dev(ts))
    n_emp = rng.randint(2, 6)
    d0 = rng.randrange(14)
    for d in (d0, d0 + 14):
        ts = at(d, 9)
        for e in range(n_emp):
            ts += rng.randint(1, 5) * 60
            b.add(ts, biz, f"EXT-employee-{e}", rng.randint(100_000, 300_000), dev(ts))
    if rng.random() < 0.5:  # owner's personal account is in the scenario
        owner = b.account("O1", rng.randint(50_000, 300_000))
        dev_o = device_fn(rng, owner, 0.10)
        purchases(b, rng, owner, dev_o, (3, 8), 500, 10_000)
        for week in range(WINDOW_DAYS // 7):
            week_payments = [p for p in client_payments if p // DAY // 7 == week]
            ts = rng.choice(week_payments) + rng.randint(10, 20 * 60) * 60
            b.add(ts, biz, owner, rng.randint(50_000, 200_000), dev(ts))


BENIGN_TEMPLATES: dict[str, Callable[[HouseholdBuilder, random.Random], None]] = {
    "salaried": gen_salaried,
    "gig": gen_gig,
    "student": gen_student,
    "small_business": gen_small_business,
}
LOOKALIKE_TEMPLATES = {"salaried_relay": gen_salaried_relay}
