"""
sim/onboarding.py

Placeholder for CRS. Every account opening calls onboard(), for normal
customers and Red's accounts alike. Today it returns neutral signals;
later, replace the body with real CRS calls. Nothing else has to change.
"""

from __future__ import annotations

from typing import Optional

from schemas import Applicant, OnboardingResult  # adjust import to your package


def onboard(account_id: str, applicant: Optional[Applicant] = None) -> OnboardingResult:
    # TODO(CRS): identity verification + soft-pull credit report on `applicant`,
    # cache responses for replay, and map them into the fields below.
    return OnboardingResult(account_id=account_id, source="stub")