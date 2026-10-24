#!/usr/bin/env python3
"""No-LLM feasibility check for Sentinel's demo fix (design-v2 §10).

Generates seeded benign scenarios and hand-written hop-chain fraud
scenarios, scores them with baseline detector v1 and with v1 plus a
hand-coded short_hold_hop_count rule, and checks the result against the
hackathon gate from the design doc. Standard library only.

    python3 scripts/feasibility.py [--seed 7] [--k 4] [--benign 500] [--attack-copies 8]

Exit code 0 if the candidate passes the gate on --seed, 1 if it fails.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import operator
import random
import sys
from collections import defaultdict
from dataclasses import dataclass

HOUR = 3600
DAY = 24 * HOUR
WINDOW_DAYS = 28        # one benign scenario = one household over 28 days (design-v2 §6.2)
FPR_BUDGET_BP = 50      # gate: FPR increase <= 0.5 percentage points = 50 basis points


# --- Seeded RNG, one stream per component (design-v2 §5.1) ---------------------------

def rng_for(seed: int, *component) -> random.Random:
    key = "|".join(str(p) for p in (seed, *component))
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


# --- Data model: integer cents, integer seconds ---------------------------------------

@dataclass(frozen=True, slots=True)
class Txn:
    ts: int
    txn_id: str
    from_id: str
    to_id: str
    amount_cents: int
    device_id: str | None = None


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    template: str
    malicious: bool
    owned: frozenset[str]           # accounts the detector scores; EXT-* counterparties are not scored
    initial_devices: dict[str, str]  # device each owned account already used before the window
    txns: tuple[Txn, ...]           # sorted by (ts, txn_id)


class ScenarioBuilder:
    def __init__(self, scenario_id: str, template: str, malicious: bool):
        self.scenario_id, self.template, self.malicious = scenario_id, template, malicious
        self._raw: list[tuple] = []
        self._owned: set[str] = set()

    def account(self, account_id: str) -> str:
        self._owned.add(account_id)
        return account_id

    def add(self, ts: int, from_id: str, to_id: str, amount_cents: int, device_id: str | None = None):
        assert isinstance(amount_cents, int) and amount_cents > 0, amount_cents
        self._raw.append((ts, len(self._raw), from_id, to_id, amount_cents, device_id))

    def build(self) -> Scenario:
        raw = sorted(self._raw)  # by ts, then insertion order: deterministic
        txns = tuple(
            Txn(ts, f"{self.scenario_id}-{i:05d}", f, t, a, d)
            for i, (ts, _, f, t, a, d) in enumerate(raw)
        )
        return Scenario(
            self.scenario_id, self.template, self.malicious, frozenset(self._owned),
            {a: f"{a}-d0" for a in self._owned}, txns,
        )


def at(day: int, hour: int, minute: int = 0) -> int:
    return day * DAY + hour * HOUR + minute * 60


def rand_time(rng: random.Random, day: int, h_lo: int = 8, h_hi: int = 21) -> int:
    return at(day, rng.randint(h_lo, h_hi), rng.randrange(60))


# --- Benign templates (one household per scenario) ------------------------------------

HOUSEHOLD_PROB = 0.3    # salaried customer has a dependent in the scenario
SIBLING_PROB = 0.25     # that dependent relays part of the allowance to a sibling


def device_fn(rng: random.Random, account: str, upgrade_prob: float):
    upgrade_at = rand_time(rng, rng.randrange(WINDOW_DAYS)) if rng.random() < upgrade_prob else None
    return lambda ts: f"{account}-d1" if upgrade_at is not None and ts >= upgrade_at else f"{account}-d0"


def purchases(b, rng, acct, dev, per_week, lo, hi, days=range(WINDOW_DAYS)):
    days = list(days)
    for week in range(WINDOW_DAYS // 7):
        week_days = [d for d in days if d // 7 == week]
        for _ in range(rng.randint(*per_week)):
            ts = rand_time(rng, rng.choice(week_days))
            b.add(ts, acct, f"EXT-merchant-{rng.randrange(40)}", rng.randint(lo, hi), dev(ts))


def gen_salaried(b: ScenarioBuilder, rng: random.Random):
    c = b.account("C1")
    dev = device_fn(rng, c, 0.10)
    monthly = rng.randint(300_000, 700_000)
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

    if rng.random() >= HOUSEHOLD_PROB:
        return
    d1 = b.account("D1")
    dev1 = device_fn(rng, d1, 0.05)
    purchases(b, rng, d1, dev1, (2, 8), 300, 6_000)
    has_sibling = rng.random() < SIBLING_PROB
    if has_sibling:
        d2 = b.account("D2")
        dev2 = device_fn(rng, d2, 0.05)
        purchases(b, rng, d2, dev2, (1, 5), 300, 4_000)
    for pay_ts in paydays:
        if rng.random() < 0.6:
            allowance = rng.randint(5_000, 30_000)
            ts = pay_ts + rng.randint(1 * 60, 6 * 60) * 60
            b.add(ts, c, d1, allowance, dev(ts))
            if has_sibling and rng.random() < 0.5:
                ts2 = ts + rng.randint(1 * 60, 10 * 60) * 60
                b.add(ts2, d1, d2, allowance * rng.randint(30, 60) // 100, dev1(ts2))


def gen_gig(b: ScenarioBuilder, rng: random.Random):
    c = b.account("C1")
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


def gen_student(b: ScenarioBuilder, rng: random.Random):
    c = b.account("C1")
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


def gen_small_business(b: ScenarioBuilder, rng: random.Random):
    biz = b.account("B1")
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
        owner = b.account("O1")
        dev_o = device_fn(rng, owner, 0.10)
        purchases(b, rng, owner, dev_o, (3, 8), 500, 10_000)
        for week in range(WINDOW_DAYS // 7):
            week_payments = [p for p in client_payments if p // DAY // 7 == week]
            ts = rng.choice(week_payments) + rng.randint(10, 20 * 60) * 60
            b.add(ts, biz, owner, rng.randint(50_000, 200_000), dev(ts))


BENIGN_TEMPLATES = {
    "salaried": gen_salaried,
    "gig": gen_gig,
    "student": gen_student,
    "small_business": gen_small_business,
}


# --- Hand-written hop-chain fraud templates -------------------------------------------

def hold(rng: random.Random, lo_h: int, hi_h: int) -> int:
    return rng.randint(lo_h * 60, hi_h * 60) * 60


def fwd(rng: random.Random, amount: int) -> int:
    return amount * rng.randint(92, 99) // 100  # each mule keeps a small cut


def fraud_start(rng: random.Random, b: ScenarioBuilder, lo=400_000, hi=900_000):
    src = b.account("SRC")
    t0 = rand_time(rng, rng.randint(2, 18), 0, 23)
    amount = rng.randint(lo, hi)
    b.add(t0, "EXT-victim", src, amount)
    return src, t0, amount


def chain(rng, b, src, t, amount, mules, holds, device=None):
    """src -> mules[0] -> ... -> mules[-1] -> EXT-cashout, holding holds[i] before each send."""
    path = [src, *[b.account(m) for m in mules], "EXT-cashout"]
    for i in range(len(path) - 1):
        t += holds[i]
        amount = fwd(rng, amount)
        dev = (device or {}).get(path[i], f"{path[i]}-d0")
        b.add(t, path[i], path[i + 1], amount, dev)


def gen_fast_ring(b, rng):
    """Golden mule ring: SRC fans out 6 transfers inside an hour. Baseline velocity rule catches it."""
    src, t, amount = fraud_start(rng, b)
    mules = [b.account(f"M{i}") for i in (1, 2, 3)]
    t += hold(rng, 1, 3)
    for i in range(6):
        t += rng.randint(5, 10) * 60
        b.add(t, src, mules[i % 3], amount // 6, f"{src}-d0")
    for m in mules:
        b.add(t + hold(rng, 30, 40), m, "EXT-cashout", fwd(rng, amount // 3), f"{m}-d0")


def gen_slow_chain_3(b, rng):
    """Three mules in a line, each holding 7-20h: under the 6h pass-through window, under 24h."""
    src, t, amount = fraud_start(rng, b)
    chain(rng, b, src, t, amount, ["M1", "M2", "M3"], [hold(rng, 7, 20) for _ in range(4)])


def gen_slow_split(b, rng):
    """SRC splits into two parallel two-mule branches."""
    src, t, amount = fraud_start(rng, b)
    t1 = t + hold(rng, 7, 20)
    t2 = t1 + hold(rng, 1, 3)
    chain(rng, b, src, t1, amount // 2, ["M1", "M2"], [0, hold(rng, 7, 20), hold(rng, 7, 20)])
    chain(rng, b, src, t2, amount // 2, ["M3", "M4"], [0, hold(rng, 7, 20), hold(rng, 7, 20)])


def gen_slow_small_new_device(b, rng):
    """Two mules, under $1,000, first mule on a new device: dodges new-device + large transfer."""
    src, t, amount = fraud_start(rng, b, 60_000, 95_000)
    chain(rng, b, src, t, amount, ["M1", "M2"], [hold(rng, 7, 20) for _ in range(3)],
          device={"M1": "M1-d1"})


def gen_slow_long_hold(b, rng):
    """Four mules, but M2 sits on the money 26-40h, which breaks the < 24h chain."""
    src, t, amount = fraud_start(rng, b)
    holds = [hold(rng, 7, 20), hold(rng, 7, 20), hold(rng, 26, 40), hold(rng, 7, 20), hold(rng, 7, 20)]
    chain(rng, b, src, t, amount, ["M1", "M2", "M3", "M4"], holds)


def gen_short_chain(b, rng):
    """One mule only: as shallow as a legitimate payday -> allowance -> purchase chain."""
    src, t, amount = fraud_start(rng, b)
    chain(rng, b, src, t, amount, ["M1"], [hold(rng, 7, 20) for _ in range(2)])


ATTACK_TEMPLATES = {
    "fast_ring (golden)": gen_fast_ring,
    "slow_chain_3": gen_slow_chain_3,
    "slow_split": gen_slow_split,
    "slow_small_new_device": gen_slow_small_new_device,
    "slow_long_hold": gen_slow_long_hold,
    "short_chain": gen_short_chain,
}


def generate(seed: int, n_benign: int, attack_copies: int) -> list[Scenario]:
    scenarios = []
    names = list(BENIGN_TEMPLATES)
    for i in range(n_benign):
        name = names[i % len(names)]
        b = ScenarioBuilder(f"B-{name}-{i:04d}", name, malicious=False)
        BENIGN_TEMPLATES[name](b, rng_for(seed, "benign", name, i))
        scenarios.append(b.build())
    for name, gen in ATTACK_TEMPLATES.items():
        for i in range(attack_copies):
            b = ScenarioBuilder(f"A-{name.split()[0]}-{i:02d}", name, malicious=True)
            gen(b, rng_for(seed, "fraud", name, i))
            scenarios.append(b.build())
    return scenarios


def dataset_hash(scenarios: list[Scenario]) -> str:
    h = hashlib.sha256()
    for s in scenarios:
        for t in s.txns:
            h.update(f"{t.ts}|{t.txn_id}|{t.from_id}|{t.to_id}|{t.amount_cents}|{t.device_id}\n".encode())
    return h.hexdigest()


# --- Features: they only ever receive a HistoryView (no lookahead, design-v2 §5.3) ------

@dataclass(frozen=True, slots=True)
class HistoryView:
    """Transactions with ts <= at_time, plus the outgoing transaction being scored."""
    txns: tuple[Txn, ...]
    scored: Txn
    initial_devices: dict[str, str]


def f_velocity_out_count(v: HistoryView, window_h: int, p: dict) -> float:
    a, lo = v.scored.from_id, v.scored.ts - window_h * HOUR
    return sum(1 for x in v.txns if x.from_id == a and x.ts > lo)


def f_velocity_out_amount(v: HistoryView, window_h: int, p: dict) -> float:
    a, lo = v.scored.from_id, v.scored.ts - window_h * HOUR
    return sum(x.amount_cents for x in v.txns if x.from_id == a and x.ts > lo)


def f_velocity_in_amount(v: HistoryView, window_h: int, p: dict) -> float:
    a, lo = v.scored.from_id, v.scored.ts - window_h * HOUR
    return sum(x.amount_cents for x in v.txns if x.to_id == a and x.ts > lo)


def f_pass_through_ratio(v: HistoryView, window_h: int, p: dict) -> float:
    a, lo = v.scored.from_id, v.scored.ts - window_h * HOUR
    out = sum(x.amount_cents for x in v.txns if x.from_id == a and x.ts > lo)
    inflow = sum(x.amount_cents for x in v.txns if x.to_id == a and x.ts > lo)
    return out / inflow if inflow else 0.0  # no inflow in window: nothing passed through


def f_new_device_before_transfer(v: HistoryView, window_h: int, p: dict) -> float:
    a, dev = v.scored.from_id, v.scored.device_id
    if dev is None or dev == v.initial_devices.get(a):
        return 0.0
    first_seen = min(x.ts for x in v.txns if x.from_id == a and x.device_id == dev)
    return 1.0 if v.scored.ts - first_seen < p["n_hours"] * HOUR else 0.0


def f_transfer_amount(v: HistoryView, window_h: int, p: dict) -> float:
    return v.scored.amount_cents


def f_short_hold_hop_count(v: HistoryView, window_h: int, p: dict) -> float:
    """Longest chain of transfers ending at the scored one, where each transfer is sent
    < hold_hours after the previous one arrived and forwards >= min_carry_pct of its amount
    (the same money moving on). Time-respecting DP over the window, in timestamp order."""
    lo, hold_s = v.scored.ts - window_h * HOUR, p.get("hold_hours", 24) * HOUR
    carry = p.get("min_carry_pct", 40)
    arrivals: dict[str, list[tuple[int, int, int]]] = defaultdict(list)  # account -> [(ts, hops, cents)]
    for x in v.txns:
        if x.ts <= lo:
            continue
        hops = 1 + max((h for ts, h, cents in arrivals[x.from_id]
                        if x.ts - ts < hold_s and x.amount_cents * 100 >= cents * carry), default=0)
        if x is v.scored:
            return hops
        arrivals[x.to_id].append((x.ts, hops, x.amount_cents))
    raise AssertionError("scored transaction missing from its own history view")


FEATURES = {
    "velocity_out_count": f_velocity_out_count,
    "velocity_out_amount": f_velocity_out_amount,
    "velocity_in_amount": f_velocity_in_amount,
    "pass_through_ratio": f_pass_through_ratio,
    "new_device_before_transfer": f_new_device_before_transfer,
    "transfer_amount": f_transfer_amount,
    "short_hold_hop_count": f_short_hold_hop_count,
}
OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}


# --- Rules: a list of conditions combined with AND (design-v2 §4.2) -------------------

@dataclass(frozen=True)
class Condition:
    feature_key: str
    operator: str
    threshold: float
    window_hours: int = 0
    params: tuple = ()

    def holds(self, v: HistoryView) -> bool:
        value = FEATURES[self.feature_key](v, self.window_hours, dict(self.params))
        return OPS[self.operator](value, self.threshold)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    all_of: tuple[Condition, ...]

    def matches(self, v: HistoryView) -> bool:
        return all(c.holds(v) for c in self.all_of)


BASELINE_V1 = (
    # Velocity only counts when real money leaves: >= $1,000 out in the same hour (not bill-splitting).
    Rule("R1", (
        Condition("velocity_out_count", ">=", 5, 1),
        Condition("velocity_out_amount", ">=", 100_000, 1),
    )),
    # Pass-through only counts when a mule-sized sum came in: >= $5,000 received in the same 6h window.
    Rule("R2", (
        Condition("pass_through_ratio", ">=", 0.9, 6),
        Condition("velocity_in_amount", ">=", 500_000, 6),
    )),
    Rule("R3", (
        Condition("new_device_before_transfer", ">=", 1, 0, (("n_hours", 24),)),
        Condition("transfer_amount", ">=", 100_000),
    )),
)


def hop_rule(k: int) -> Rule:
    return Rule("R4", (Condition("short_hold_hop_count", ">=", k, 72,
                                 (("hold_hours", 24), ("min_carry_pct", 40))),))


# --- Detector: online, one HistoryView per outgoing transaction -----------------------

@dataclass(frozen=True)
class Detection:
    alert: bool
    first_alert_time: int | None
    rule_ids: tuple[str, ...]


def views(s: Scenario):
    timestamps = [t.ts for t in s.txns]
    for t in s.txns:
        if t.from_id in s.owned:
            cut = bisect.bisect_right(timestamps, t.ts)  # everything with ts <= t.ts, nothing later
            yield HistoryView(s.txns[:cut], t, s.initial_devices)


def score(s: Scenario, rules) -> Detection:
    for v in views(s):
        fired = tuple(r.rule_id for r in rules if r.matches(v))
        if fired:
            return Detection(True, v.scored.ts, fired)
    return Detection(False, None, ())


def rules_fired(s: Scenario, rules) -> set[str]:
    """Every rule that fires anywhere in the scenario, not just at the first alert."""
    return {r.rule_id for v in views(s) for r in rules if r.matches(v)}


def max_hops(s: Scenario) -> int:
    rule = hop_rule(0).all_of[0]
    return max((FEATURES[rule.feature_key](v, rule.window_hours, dict(rule.params)) for v in views(s)), default=0)


def check_no_lookahead(s: Scenario, rules, d: Detection):
    """Cutting the trace at the alert time must not change the alert."""
    if not d.alert:
        return
    cut = Scenario(s.scenario_id, s.template, s.malicious, s.owned, s.initial_devices,
                   tuple(t for t in s.txns if t.ts <= d.first_alert_time))
    assert score(cut, rules) == d, f"lookahead detected in {s.scenario_id}"


# --- Gate (design §1 defaults) --------------------------------------------------------

@dataclass
class Evaluation:
    n_attack: int
    n_benign: int
    base_tp: set
    cand_tp: set
    base_fp: set
    cand_fp: set

    @property
    def fp_budget(self) -> int:
        return self.n_benign * FPR_BUDGET_BP // 10_000

    def gates(self) -> dict[str, bool]:
        return {
            "fpr_budget": len(self.cand_fp) - len(self.base_fp) <= self.fp_budget,
            "regression_no_loss": self.base_tp <= self.cand_tp,
            "recall_improves": len(self.cand_tp) > len(self.base_tp),
            "schema_valid": True,  # hand-coded rule uses registered features and allowlisted operators
        }

    def passed(self) -> bool:
        return all(self.gates().values())


def evaluate(scenarios, base_flags, hop_max, k) -> Evaluation:
    attack = [s for s in scenarios if s.malicious]
    benign = [s for s in scenarios if not s.malicious]
    cand = {s.scenario_id for s in scenarios if base_flags[s.scenario_id] or hop_max[s.scenario_id] >= k}
    base = {sid for sid, f in base_flags.items() if f}
    return Evaluation(
        len(attack), len(benign),
        {s.scenario_id for s in attack} & base, {s.scenario_id for s in attack} & cand,
        {s.scenario_id for s in benign} & base, {s.scenario_id for s in benign} & cand,
    )


def run(seed: int, n_benign: int, attack_copies: int, k: int, verify: bool):
    scenarios = generate(seed, n_benign, attack_copies)
    base_flags = {s.scenario_id: score(s, BASELINE_V1).alert for s in scenarios}
    hop_max = {s.scenario_id: max_hops(s) for s in scenarios}
    if verify:
        candidate = BASELINE_V1 + (hop_rule(k),)
        for s in scenarios:
            d = score(s, candidate)
            # The real detector run with the hand-coded rule must agree with the fast path.
            assert d.alert == (base_flags[s.scenario_id] or hop_max[s.scenario_id] >= k), s.scenario_id
            check_no_lookahead(s, candidate, d)
    return scenarios, base_flags, hop_max


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "n/a"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--k", type=int, default=4, help="short_hold_hop_count threshold for the fix")
    ap.add_argument("--benign", type=int, default=500)
    ap.add_argument("--attack-copies", type=int, default=8, help="seeded copies of each fraud template")
    ap.add_argument("--robustness-seeds", type=int, default=10)
    args = ap.parse_args()

    scenarios, base_flags, hop_max = run(args.seed, args.benign, args.attack_copies, args.k, verify=True)
    ev = evaluate(scenarios, base_flags, hop_max, args.k)

    print("Sentinel feasibility check (no LLM)")
    print(f"seed={args.seed}  benign={ev.n_benign}  attack={ev.n_attack}  "
          f"dataset sha256={dataset_hash(scenarios)[:16]}")
    print(f"Fix under test: R4 = short_hold_hop_count >= {args.k} (window 72h, each hold < 24h, "
          f"each hop forwards >= 40%), OR'ed onto v1")
    print("Lookahead check: passed (every alert reproduces with the trace cut at the alert time)\n")

    print(f"{'':22}{'baseline v1':>18}{'v1 + R4':>18}")
    print(f"{'attack recall':22}{pct(len(ev.base_tp), ev.n_attack):>18}{pct(len(ev.cand_tp), ev.n_attack):>18}")
    print(f"{'benign FPR':22}{pct(len(ev.base_fp), ev.n_benign):>18}{pct(len(ev.cand_fp), ev.n_benign):>18}\n")

    print("Attack recall by template")
    for name in ATTACK_TEMPLATES:
        ids = {s.scenario_id for s in scenarios if s.template == name}
        print(f"  {name:26} baseline {len(ids & ev.base_tp)}/{len(ids)}   v1+R4 {len(ids & ev.cand_tp)}/{len(ids)}")
    print("Benign FPR by template")
    for name in BENIGN_TEMPLATES:
        ids = {s.scenario_id for s in scenarios if s.template == name}
        print(f"  {name:26} baseline {len(ids & ev.base_fp)}/{len(ids)}   v1+R4 {len(ids & ev.cand_fp)}/{len(ids)}")

    benign = [s for s in scenarios if not s.malicious]
    per_rule = defaultdict(int)
    for s in benign:
        for rid in rules_fired(s, BASELINE_V1):
            per_rule[rid] += 1
    r4_alone = {s.scenario_id for s in benign if hop_max[s.scenario_id] >= args.k}
    print("Benign scenarios each rule flags on its own (rules overlap)")
    for r in BASELINE_V1:
        print(f"  {r.rule_id} {r.all_of[0].feature_key:26} {pct(per_rule[r.rule_id], len(benign))}")
    print(f"  R4 short_hold_hop_count     {pct(len(r4_alone), len(benign))}"
          f"  ({len(r4_alone & ev.base_fp)} of these were already flagged by v1, so the gate never sees them)")
    by_template = defaultdict(int)
    for s in benign:
        if s.scenario_id in r4_alone:
            by_template[s.template] += 1
    print(f"  R4 benign hits by template: {dict(by_template) or 'none'}\n")

    new_fp = len(ev.cand_fp) - len(ev.base_fp)
    delta_pp = 100 * new_fp / ev.n_benign
    g = ev.gates()
    mark = lambda ok: "PASS" if ok else "FAIL"
    print("\nGate (design §1 defaults)")
    print(f"  FPR increase <= 0.5 pp    +{new_fp} FPs = +{delta_pp:.2f} pp (budget {ev.fp_budget} FPs)  "
          f"{mark(g['fpr_budget'])}")
    print(f"  regression: no loss       {len(ev.base_tp & ev.cand_tp)}/{len(ev.base_tp)} still caught"
          f"{'':18}{mark(g['regression_no_loss'])}")
    print(f"  recall improves           +{len(ev.cand_tp) - len(ev.base_tp)} attacks caught"
          f"{'':20}{mark(g['recall_improves'])}")
    print(f"  schema valid{'':48}{mark(g['schema_valid'])}")
    print(f"\nRESULT: {'PASS' if ev.passed() else 'FAIL'}")
    if not g["fpr_budget"]:
        print(f"  over the FPR budget by {new_fp - ev.fp_budget} FP(s) "
              f"(+{delta_pp - FPR_BUDGET_BP / 100:.2f} pp over the 0.5 pp limit)")

    print("\nThreshold sweep, same data")
    print(f"  {'k':>3}  {'new FPs':>8}  {'dFPR':>8}  {'recall':>16}  gate")
    for k in range(2, 7):
        e = evaluate(scenarios, base_flags, hop_max, k)
        nf = len(e.cand_fp) - len(e.base_fp)
        print(f"  {k:>3}  {nf:>8}  {100 * nf / e.n_benign:>7.2f}%  {pct(len(e.cand_tp), e.n_attack):>16}  "
              f"{mark(e.passed())}")

    seeds = [args.seed, *range(1000, 1000 + args.robustness_seeds)]
    print(f"\nAll seeds, k={args.k}")
    print(f"  {'seed':>5}  {'v1 benign flagged':>18}  {'fix new FPs':>11}  {'budget':>6}  "
          f"{'R4 alone':>8}  {'fraud caught v1 -> v1+R4':>24}  gate")
    results = []
    for seed in seeds:
        if seed == args.seed:
            sc, bf, hm, e = scenarios, base_flags, hop_max, ev
        else:
            sc, bf, hm = run(seed, args.benign, args.attack_copies, args.k, verify=False)
            e = evaluate(sc, bf, hm, args.k)
        results.append(e.passed())
        r4 = sum(1 for s in sc if not s.malicious and hm[s.scenario_id] >= args.k)
        caught = f"{len(e.base_tp)}/{e.n_attack} -> {len(e.cand_tp)}/{e.n_attack}"
        print(f"  {seed:>5}  {pct(len(e.base_fp), e.n_benign):>18}  {len(e.cand_fp) - len(e.base_fp):>11}  "
              f"{e.fp_budget:>6}  {r4:>8}  {caught:>24}  {mark(e.passed())}")
    print(f"  passed on {sum(results)}/{len(results)} seeds")

    return 0 if ev.passed() else 1


if __name__ == "__main__":
    sys.exit(main())
