"""generate_world(config): the lab's background bank, built from benign household templates."""
from __future__ import annotations

from sentinel.schemas import Account, BankConfig, Customer, Split, World
from sentinel.sim.benign import BENIGN_TEMPLATES
from sentinel.sim.builder import HouseholdBuilder
from sentinel.sim.rng import derive_seed, rng_for


def generate_world(config: BankConfig) -> World:
    """Households cycle through the configured segments until account_count accounts exist."""
    customers, accounts, transactions = [], [], []
    segments = list(config.customer_segments)
    n = 0
    while len(accounts) < config.account_count:
        segment = segments[n % len(segments)]
        hid = f"W{n:05d}"
        b = HouseholdBuilder(hid, segment.value, derive_seed(config.seed, "world", n), Split.SEARCH)
        BENIGN_TEMPLATES[segment.value](b, rng_for(config.seed, "world", n))
        household = b.build()
        rename = {a: f"{hid}.{a}" for a in household.owned_account_ids}
        customers.append(Customer(
            customer_id=hid, segment=segment, income_band="mid",
            device_ids=sorted({f"{hid}.{d}" for d in household.initial_devices.values()}),
        ))
        for a in household.owned_account_ids:
            accounts.append(Account(account_id=rename[a], customer_id=hid, created_at=0,
                                    balance_cents=household.opening_balances_cents[a]))
        for t in household.transactions:
            transactions.append(t.model_copy(update={
                "from_id": rename.get(t.from_id, t.from_id), "to_id": rename.get(t.to_id, t.to_id),
            }))
        n += 1
    transactions.sort(key=lambda t: (t.timestamp, t.transaction_id))
    return World(seed=config.seed, customers=customers, accounts=accounts, transactions=transactions)


def world_summary(world: World) -> dict:
    return {
        "customers": len(world.customers),
        "accounts": len(world.accounts),
        "transactions": len(world.transactions),
        "edges": len({(t.from_id, t.to_id) for t in world.transactions}),
    }
