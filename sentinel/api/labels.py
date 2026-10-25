"""Detector labels shared by the replay and breakdown endpoints, so both views name versions the same way."""
from __future__ import annotations

from collections.abc import Iterable


def approved_version(store, report_ids: Iterable[str]) -> int | None:
    """The version a patch actually became, or None if none of its reports was approved."""
    for report_id in report_ids:
        a = store.approval(report_id)
        if a and a["decision"] == "approve" and a["version_created"]:
            return a["version_created"]
    return None


def detector_label(base: int, approved: int | None) -> str:
    """'Detector v2' once approved; until then, the base version plus the proposed fix."""
    return f"Detector v{approved}" if approved else f"Detector v{base} + proposed fix"