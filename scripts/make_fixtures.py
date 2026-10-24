#!/usr/bin/env python3
"""Regenerate everything under fixtures/ from sentinel.fixtures (deterministic). Run: make fixtures"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.fixtures import FIXTURE_DIR, write_fixture_files  # noqa: E402

for path in write_fixture_files():
    print(path.relative_to(FIXTURE_DIR.parent))
