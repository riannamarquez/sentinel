# Sentinel — a red + blue purple-team loop vs. OWASP Juice Shop

Sentinel runs a **closed security loop** against a live web app:

```
recon  →  RED scans  →  BLUE remediates  →  VERIFY (replay)  →  report
```

- **Red agent** attacks [OWASP Juice Shop](https://owasp.org/projects/juice-shop) and, *only when an exploit actually fires*, records the exact request as a confirmed `Finding`.
- **Blue agent** answers each finding with a real source-level **code fix** (before/after) **and** a compensating **edge control** it can enforce right now.
- The loop then **replays Red's recorded request** through Blue's now-active controls. A finding only counts as mitigated if the attack is *actually blocked* — the loop is verified, not asserted.

The whole thing is the demo: **the red → blue → verify loop**, not the exploits (those are Juice Shop's canonical training bugs).

---

## Quick start

### 0. The integrated demo — `/demo` in the web app
The primary, styled walkthrough lives in the Sentinel web app at **`/demo`** (`web/app/demo/page.tsx`). From the repo root:
```bash
cd web && npm install && npm run dev   # then open http://localhost:3000/demo
```
It steps through the same loop — recon → Red scans → trace the critical exploit → Blue fixes → verify by replay → human decision → rechallenge — in the app's design system, driven by `web/app/demo/juice-capture.json` (generated from a real Sentinel run).

### 1. Watch the loop — the standalone dashboard (zero setup, no Node)
Open **`dashboard.html`** in any browser. Self-contained offline view that auto-plays the full loop: findings light up red, fixes deploy blue, then every finding gets a **✓ VERIFIED BLOCKED** stamp and the scoreboard closes to **0 residual**.

### 2. Run the loop — offline replay (zero setup)
```bash
pip install -r requirements.txt
python run_demo.py --mode replay
```
Prints the live-coloured red/blue loop in the terminal. Canned findings mirror exactly what the live probes return.

### 3. Run it for real — live target
```bash
# terminal 1 — start a Juice Shop you own
docker run --rm -p 3000:3000 bkimminich/juice-shop
#   (or: git clone https://github.com/juice-shop/juice-shop && cd juice-shop && npm install && npm start)

# terminal 2 — attack it and write a run log the dashboard reads
python run_demo.py --mode live --output run.json
```
Drop `run.json` next to `dashboard.html` and reload — the dashboard shows the **real** captured traffic instead of the embedded replay.

### 4. "Fix it in the browser" — the live mitigating proxy
```bash
python -m sentinel.proxy --upstream http://localhost:3000 --port 8080
```
Browse the **vulnerable** app on `:3000` and the **defended** app on `:8080`. Blue's controls run on real traffic: SQLi requests get a `403`, `/ftp` is guarded, security headers are injected, the version endpoint is redacted.

---

## 60-second demo script

1. **Open `dashboard.html`.** "This is OWASP Juice Shop, a deliberately vulnerable shop app. Sentinel runs two agents against it."
2. **Hit ▶ Run the loop.** "Red fires five probes — a SQL-injection login bypass, an error-leaking search, an exposed confidential file, missing headers, version disclosure. Each card is a *confirmed* exploit with the real request it sent."
3. **Point at the blue column.** "Blue answers each one with the actual code fix *and* an edge control it can deploy immediately."
4. **Point at the scoreboard closing to 0.** "Then we replay every attack through those controls. All five are blocked — 1 critical, 2 high, 2 medium/low, zero residual. That's the loop closing itself."
5. (optional) **Switch to the proxy on `:8080`** and run the SQLi login in the browser → `403 blocked by Sentinel`. "Same defence, live traffic."

---

## How it's built

| Module | Role |
|---|---|
| `sentinel/red_agent.py` | The attacker — one probe per weakness; returns a `Finding` only if the exploit triggers. |
| `sentinel/blue_agent.py` | The defender — a declarative remediation KB + a `RuleEngine` that actually evaluates requests. |
| `sentinel/orchestrator.py` | Runs recon → red → blue → verify and records one JSON run-log. |
| `sentinel/proxy.py` | Optional live reverse proxy that enforces Blue's controls on real traffic. |
| `sentinel/juice_shop.py` | HTTP client that **refuses any non-local target** unless `--allow-remote` is passed. |
| `sentinel/models.py` | The `Finding` / `Remediation` contract that keeps the two agents decoupled. |
| `dashboard.html` | Self-contained visual console (embeds a run-log; reads `run.json` if present). |
| `run_demo.py` | CLI entry point (`--mode replay|live`, `--output`). |

Findings map to the **OWASP Top 10 (2021)** taxonomy. Every probe is written to **confirm and stop** — it proves presence (gets a token, trips a DB error), it never dumps data.

## Scope & safety
Juice Shop is meant to be attacked — **but only the copy you run yourself**. The client resolves the target hostname and refuses anything that isn't loopback unless you explicitly pass `--allow-remote` for a host you're authorised to test.
