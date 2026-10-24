import importlib

import pytest


@pytest.mark.parametrize("module", ["schemas", "sim", "features", "detector", "scenarios", "eval", "agents", "api"])
def test_subpackages_import(module):
    importlib.import_module(f"sentinel.{module}")
