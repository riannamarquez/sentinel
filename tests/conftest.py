import pytest

from sentinel.detector.baseline import BASELINE_V1
from sentinel.detector.patches import apply_patch
from sentinel.fixtures import load_golden_patch, load_splits


@pytest.fixture(scope="session")
def fixture_splits():
    return load_splits()


@pytest.fixture(scope="session")
def candidate_rules():
    return apply_patch(BASELINE_V1, load_golden_patch())
