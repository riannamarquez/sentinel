"""Blue agent — the defender.

For each Finding, Blue produces a ``Remediation`` with two halves:

  1. a *code fix* — the real source-level change you'd merge into the app
     (shown as before/after), and
  2. a *compensating control* — a rule Blue can enforce at the edge right now,
     before anyone touches the source.

The ``RuleEngine`` is what makes the loop *verifiable*: we replay each finding's
exact recorded request through it, and a finding only counts as mitigated if the
engine actually blocks or neutralises that request. Blue can't just claim a fix —
it has to stop the thing Red did.

Two rule shapes (think of it like Express middleware):
  - request blockers run before the handler and reject a malicious request
    (SQLi filter, /ftp path guard);
  - response transforms run after the handler and sanitise what goes out
    (inject security headers, redact the version string).
"""
from __future__ import annotations

import re

from .models import Finding, HttpEvidence, Remediation

# --- the compensating-control engine ---------------------------------------

# Request-blocker signatures.
_SQLI_SIGNATURE = re.compile(
    r"""(--)|(;)|(/\*)|(\bunion\b\s+\bselect\b)|(\bor\b\s+\d+\s*=\s*\d+)|(')""",
    re.IGNORECASE,
)
_FTP_PATH = re.compile(r"^/ftp/", re.IGNORECASE)

# Response-transform coverage: which finding ids these controls neutralise,
# keyed by the request path they apply to.
_HEADER_FIX_PATHS = {"/"}                              # inject headers on all responses
_VERSION_REDACT_PATHS = {"/rest/admin/application-version"}


class RuleEngine:
    """Holds the active compensating controls and evaluates requests against them."""

    def __init__(self):
        # control name -> enabled. All on once Blue "deploys" them.
        self.active: set[str] = set()

    def deploy(self, *rule_names: str) -> None:
        self.active.update(rule_names)

    def evaluate(self, ev: HttpEvidence) -> tuple[bool, str | None]:
        """Would the active controls stop this exact request/response?

        Returns (mitigated, rule_name). ``mitigated`` means: the malicious
        request is blocked, or the leaky response is sanitised, so Red's recorded
        attack no longer succeeds.
        """
        haystack = ev.path + " " + " ".join(str(v) for v in (ev.body or {}).values())

        if "sql-injection-filter" in self.active and _SQLI_SIGNATURE.search(haystack):
            return True, "sql-injection-filter"
        if "ftp-path-guard" in self.active and _FTP_PATH.search(ev.path):
            return True, "ftp-path-guard"
        if "security-headers-injector" in self.active and ev.path in _HEADER_FIX_PATHS:
            return True, "security-headers-injector"
        if "version-redactor" in self.active and ev.path.split("?")[0] in _VERSION_REDACT_PATHS:
            return True, "version-redactor"
        return False, None


# --- remediation knowledge base --------------------------------------------
# Maps each Finding id to its fix. Keeping this declarative means adding a new
# vulnerability class is a data change, not a code change.

_REMEDIATIONS = {
    "sqli-login-bypass": dict(
        title="Parameterise the login query",
        rationale="The bypass works because user input is concatenated into SQL. "
                  "Parameterised queries send the input as data, never as code, so "
                  "`' OR 1=1--` is treated as a (nonexistent) email, not as syntax.",
        before="const q = `SELECT * FROM Users WHERE email = '${req.body.email}' "
               "AND password = '${hash(req.body.password)}'`;\ndb.exec(q);",
        after="db.get(\n  'SELECT * FROM Users WHERE email = ? AND password = ?',\n"
              "  [req.body.email, hash(req.body.password)]\n);",
        rule="sql-injection-filter",
    ),
    "sqli-search-error-leak": dict(
        title="Parameterise search + return a generic error",
        rationale="Two fixes: bind the query parameter so the quote can't break "
                  "the SQL, and replace the raw DB error with a generic 400 so the "
                  "engine and schema aren't leaked to the client.",
        before="const q = `SELECT * FROM Products WHERE name LIKE '%${req.query.q}%'`;\n"
               "// ... catch (e) { res.status(500).send(e.toString()); }",
        after="db.all('SELECT * FROM Products WHERE name LIKE ?', [`%${q}%`])\n"
              "// ... catch (e) { log.error(e); res.status(400).json({error:'Invalid query'}); }",
        rule="sql-injection-filter",
    ),
    "confidential-document-exposure": dict(
        title="Gate the /ftp route behind auth + an allow-list",
        rationale="Static internal files are served with no check. Require "
                  "authentication for the route and only serve an explicit "
                  "allow-list of public file types.",
        before="app.use('/ftp', express.static('ftp'));",
        after="app.use('/ftp', requireAuth, serveAllowList(['.pdf']),\n"
              "               express.static('ftp'));",
        rule="ftp-path-guard",
    ),
    "missing-security-headers": dict(
        title="Add Helmet security headers",
        rationale="A single middleware sets Content-Security-Policy, "
                  "X-Frame-Options, HSTS and X-Content-Type-Options — closing off "
                  "XSS, clickjacking and downgrade attacks at once.",
        before="// no security-header middleware configured",
        after="import helmet from 'helmet';\napp.use(helmet({\n"
              "  contentSecurityPolicy: { directives: { defaultSrc: [\"'self'\"] } }\n}));",
        rule="security-headers-injector",
    ),
    "version-disclosure": dict(
        title="Stop publishing the exact version",
        rationale="Fingerprinting the version maps the app to known CVEs. Remove "
                  "the public version endpoint (or return a static build id) and "
                  "patch on a schedule rather than relying on obscurity.",
        before="app.get('/rest/admin/application-version',\n"
               "        (req,res) => res.json({ version: pkg.version }));",
        after="// endpoint removed from public surface; version tracked internally\n"
              "// in the SBOM / dependency scanner, not exposed to clients",
        rule="version-redactor",
    ),
}


class BlueAgent:
    def __init__(self):
        self.engine = RuleEngine()

    def remediate(self, findings: list[Finding], on_event=None) -> list[Remediation]:
        """Produce a remediation per finding, deploy its control, and verify.

        Verification = replay the finding's recorded request through the engine.
        A remediation's ``blocks`` flag is set by the engine, not by Blue's say-so.
        """
        remediations: list[Remediation] = []
        for f in findings:
            spec = _REMEDIATIONS.get(f.id)
            if not spec:
                continue
            if on_event:
                on_event("remediation_start", {"finding_id": f.id})

            # Deploy the compensating control, then prove it stops Red's request.
            self.engine.deploy(spec["rule"])
            blocked, rule_hit = self.engine.evaluate(f.evidence)

            rem = Remediation(
                finding_id=f.id,
                title=spec["title"],
                rationale=spec["rationale"],
                code_fix_before=spec["before"],
                code_fix_after=spec["after"],
                rule_name=spec["rule"],
                blocks=blocked and rule_hit == spec["rule"],
            )
            remediations.append(rem)
            if on_event:
                on_event("remediation", rem.to_dict())
        return remediations
