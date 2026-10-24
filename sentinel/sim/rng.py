"""One seeded RNG per component (design-v2 §5.1)."""
from __future__ import annotations

import hashlib
import random


def derive_seed(seed: int, *component) -> int:
    key = "|".join(str(p) for p in (seed, *component))
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")


def rng_for(seed: int, *component) -> random.Random:
    """An independent stream for (seed, component...). SHA-256, never Python's hash()."""
    return random.Random(derive_seed(seed, *component))
