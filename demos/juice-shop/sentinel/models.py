"""Shared data structures passed between the Red and Blue agents.

These are plain dataclasses (think of them like a typed dict / a Pydantic model
without the dependency). Everything that crosses the red->blue boundary is one of
these, so the two agents stay decoupled: Red only ever emits ``Finding`` objects,
Blue only ever consumes them and emits ``Remediation`` objects.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """CVSS-ish buckets. Subclassing ``str`` means it serializes straight to JSON."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
        return order[self.value]


class OwaspCategory(str, Enum):
    """OWASP Top 10 (2021) categories, so findings map to a recognised taxonomy."""
    A01_BROKEN_ACCESS_CONTROL = "A01:2021 Broken Access Control"
    A02_CRYPTO_FAILURES = "A02:2021 Cryptographic Failures"
    A03_INJECTION = "A03:2021 Injection"
    A04_INSECURE_DESIGN = "A04:2021 Insecure Design"
    A05_SECURITY_MISCONFIG = "A05:2021 Security Misconfiguration"
    A06_VULNERABLE_COMPONENTS = "A06:2021 Vulnerable & Outdated Components"
    A07_AUTH_FAILURES = "A07:2021 Identification & Authentication Failures"
    A08_INTEGRITY_FAILURES = "A08:2021 Software & Data Integrity Failures"
    A09_LOGGING_FAILURES = "A09:2021 Security Logging & Monitoring Failures"
    A10_SSRF = "A10:2021 Server-Side Request Forgery"


@dataclass
class HttpEvidence:
    """The exact request Red sent and the response it got back.

    This is the contract between the two agents. Blue replays ``method``/``path``/
    ``body`` through its rule engine to prove a mitigation actually blocks the
    attack, so the loop is *verified*, not just asserted.
    """
    method: str
    path: str
    body: dict[str, Any] | None = None
    request_headers: dict[str, str] = field(default_factory=dict)
    status_code: int | None = None
    response_excerpt: str = ""  # truncated; never store secrets wholesale

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    """One confirmed vulnerability, produced by the Red agent."""
    id: str                      # stable slug, e.g. "sqli-login-bypass"
    title: str
    category: OwaspCategory
    severity: Severity
    summary: str                 # what Red did, in one or two sentences
    evidence: HttpEvidence
    confirmed: bool = True       # Red only reports what it could actually trigger
    discovered_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["severity"] = self.severity.value
        return d


@dataclass
class Remediation:
    """Blue's response to a single Finding.

    ``code_fix`` is the real, source-level fix (what you'd actually merge).
    ``rule`` is a compensating control Blue can enforce *right now* at the edge,
    which is what we replay against to verify the loop closes.
    """
    finding_id: str
    title: str
    rationale: str               # the "why" behind the fix
    code_fix_before: str         # vulnerable snippet (illustrative)
    code_fix_after: str          # patched snippet
    rule_name: str               # name of the compensating control
    blocks: bool = True          # did the rule block Red's replayed payload?

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
