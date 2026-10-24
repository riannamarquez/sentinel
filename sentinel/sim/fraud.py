"""Hand-written hop-chain fraud templates, expressed as Red-style SimulationActions."""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from sentinel.schemas import ActionType, SimulationAction
from sentinel.sim.clock import hold, rand_time

SOURCE = "SRC"
CASHOUT = "EXT-cashout"


@dataclass
class Plan:
    """Events at absolute times, turned into actions with offsets from the previous one."""
    start_ts: int
    funding_cents: int
    _events: list[tuple[int, int, dict]] = field(default_factory=list)

    def _add(self, ts: int, **fields):
        assert ts >= self.start_ts
        self._events.append((ts, len(self._events), fields))

    def open(self, ts: int, account: str):
        self._add(ts, type=ActionType.OPEN_SYNTHETIC_ACCOUNT, target_id=account)

    def transfer(self, ts: int, src: str, dst: str, amount_cents: int):
        self._add(ts, type=ActionType.SIMULATED_TRANSFER, source_id=src, target_id=dst, amount_cents=amount_cents)

    def change_device(self, ts: int, account: str, device_id: str):
        self._add(ts, type=ActionType.CHANGE_SIMULATED_DEVICE, source_id=account, device_id=device_id)

    def actions(self) -> list[SimulationAction]:
        out, prev = [], self.start_ts
        for ts, _, fields in sorted(self._events, key=lambda e: (e[0], e[1])):
            out.append(SimulationAction(timestamp_offset=ts - prev, **fields))
            prev = ts
        return out


def fwd(rng: random.Random, amount: int) -> int:
    return amount * rng.randint(92, 99) // 100  # each mule keeps a small cut


def start(rng: random.Random, lo: int = 400_000, hi: int = 900_000) -> Plan:
    return Plan(start_ts=rand_time(rng, rng.randint(2, 18), 0, 23), funding_cents=rng.randint(lo, hi))


def chain(rng, plan: Plan, t: int, amount: int, mules: list[str], holds: list[int]):
    """SRC -> mules[0] -> ... -> mules[-1] -> cash-out, holding holds[i] before each send."""
    for m in mules:
        plan.open(plan.start_ts, m)
    path = [SOURCE, *mules, CASHOUT]
    for i in range(len(path) - 1):
        t += holds[i]
        amount = fwd(rng, amount)
        plan.transfer(t, path[i], path[i + 1], amount)


def fast_ring(rng: random.Random) -> Plan:
    """Golden mule ring: SRC fans out 6 transfers inside an hour. Baseline velocity rule catches it."""
    plan = start(rng)
    mules = ["M1", "M2", "M3"]
    for m in mules:
        plan.open(plan.start_ts, m)
    t = plan.start_ts + hold(rng, 1, 3)
    for i in range(6):
        t += rng.randint(5, 10) * 60
        plan.transfer(t, SOURCE, mules[i % 3], plan.funding_cents // 6)
    for m in mules:
        plan.transfer(t + hold(rng, 30, 40), m, CASHOUT, fwd(rng, plan.funding_cents // 3))
    return plan


def slow_chain_3(rng: random.Random) -> Plan:
    """Three mules in a line, each holding 7-20h: under the 6h pass-through window, under 24h."""
    plan = start(rng)
    chain(rng, plan, plan.start_ts, plan.funding_cents, ["M1", "M2", "M3"], [hold(rng, 7, 20) for _ in range(4)])
    return plan


def slow_split(rng: random.Random) -> Plan:
    """SRC splits into two parallel two-mule branches."""
    plan = start(rng)
    t1 = plan.start_ts + hold(rng, 7, 20)
    t2 = t1 + hold(rng, 1, 3)
    half = plan.funding_cents // 2
    chain(rng, plan, t1, half, ["M1", "M2"], [0, hold(rng, 7, 20), hold(rng, 7, 20)])
    chain(rng, plan, t2, half, ["M3", "M4"], [0, hold(rng, 7, 20), hold(rng, 7, 20)])
    return plan


def slow_small_new_device(rng: random.Random) -> Plan:
    """Two mules, under $1,000, first mule on a new device: dodges new-device + large transfer."""
    plan = start(rng, 60_000, 95_000)
    chain(rng, plan, plan.start_ts, plan.funding_cents, ["M1", "M2"], [hold(rng, 7, 20) for _ in range(3)])
    plan.change_device(plan.start_ts, "M1", "M1-d1")  # sorts after M1 is opened (same time, added later)
    return plan


def slow_long_hold(rng: random.Random) -> Plan:
    """Four mules, but M2 sits on the money 26-40h, which breaks the < 24h chain."""
    plan = start(rng)
    holds = [hold(rng, 7, 20), hold(rng, 7, 20), hold(rng, 26, 40), hold(rng, 7, 20), hold(rng, 7, 20)]
    chain(rng, plan, plan.start_ts, plan.funding_cents, ["M1", "M2", "M3", "M4"], holds)
    return plan


def short_chain(rng: random.Random) -> Plan:
    """One mule only: as shallow as a legitimate payday -> allowance -> purchase chain."""
    plan = start(rng)
    chain(rng, plan, plan.start_ts, plan.funding_cents, ["M1"], [hold(rng, 7, 20) for _ in range(2)])
    return plan


ATTACK_TEMPLATES: dict[str, Callable[[random.Random], Plan]] = {
    "fast_ring": fast_ring,
    "slow_chain_3": slow_chain_3,
    "slow_split": slow_split,
    "slow_small_new_device": slow_small_new_device,
    "slow_long_hold": slow_long_hold,
    "short_chain": short_chain,
}
