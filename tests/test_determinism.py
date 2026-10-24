"""Same config and seed -> byte-identical trace, across processes with different hash seeds (US-01)."""
import os
import subprocess
import sys

from sentinel.fixtures import build_fixture_files, FIXTURE_DIR

TRACE_HASH = """
import hashlib
from sentinel.schemas import BankConfig, canonical_json
from sentinel.scenarios.factory import build_splits
from sentinel.sim.world import generate_world

h = hashlib.sha256()
world = generate_world(BankConfig(seed=7, account_count=60))
for t in world.transactions:
    h.update(canonical_json(t).encode())
for split, scenarios in sorted(build_splits(7, benign_n=40, attack_copies=2).items()):
    for s in scenarios:
        h.update(canonical_json(s).encode())
print(h.hexdigest())
"""


def trace_hash(hash_seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    out = subprocess.run([sys.executable, "-c", TRACE_HASH], env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_trace_is_identical_across_processes_and_hash_seeds():
    hashes = {trace_hash(seed) for seed in ("0", "1", "4242")}
    assert len(hashes) == 1, hashes
    assert len(hashes.pop()) == 64


def test_committed_fixtures_match_the_generator():
    """Catches drift: if this fails, run `make fixtures` and review the diff."""
    for rel, content in build_fixture_files().items():
        assert (FIXTURE_DIR / rel).read_text() == content, f"fixtures/{rel} is stale"
