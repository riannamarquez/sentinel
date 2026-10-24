"""Canonical JSON and SHA-256, the only hashing Sentinel uses (never Python's hash())."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def _encode(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    raise TypeError(f"{type(obj).__name__} is not JSON serializable")


def canonical_json(value: Any) -> str:
    """Sorted keys, no whitespace, ASCII only; models (also nested ones) dumped in JSON mode."""
    return json.dumps(value, default=_encode, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()
