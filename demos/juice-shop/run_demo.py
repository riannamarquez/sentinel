#!/usr/bin/env python3
"""Sentinel — purple-team demo runner for OWASP Juice Shop.

Examples
--------
    # Offline — works with zero setup, great for a dry run:
    python run_demo.py --mode replay

    # Live — attack a Juice Shop you started on localhost:3000:
    python run_demo.py --mode live

    # Write a run log the dashboard can load:
    python run_demo.py --mode replay --output run.json
"""
from __future__ import annotations

import argparse
import json
import sys

from sentinel.orchestrator import run_loop

RESET, DIM, BOLD = "\033[0m", "\033[2m", "\033[1m"
RED, BLUE, GREEN, YELLOW = "\033[31m", "\033[34m", "\033[32m", "\033[33m"
SEV_COLOR = {"critical": RED, "high": RED, "medium": YELLOW, "low": DIM, "info": DIM}


def console_printer(kind: str, data: dict):
    """Pretty live output so the terminal itself is demo-able."""
    if kind == "recon":
        print(f"{DIM}recon · target={data['target']} · mode={data['mode']}{RESET}")
    elif kind == "probe_start":
        print(f"{RED}RED{RESET}  probing {data['probe']} ...", end="", flush=True)
    elif kind == "probe_clear":
        print(f" {GREEN}clear{RESET}")
    elif kind == "finding":
        sev = data["severity"]
        c = SEV_COLOR.get(sev, "")
        print(f"\r{RED}RED{RESET}  {c}[{sev.upper():8}]{RESET} {data['title']}")
        print(f"       {DIM}{data['category']} · {data['evidence']['method']} "
              f"{data['evidence']['path']}{RESET}")
    elif kind == "remediation":
        mark = f"{GREEN}verified{RESET}" if data["blocks"] else f"{YELLOW}code-fix only{RESET}"
        print(f"{BLUE}BLUE{RESET} {data['title']}  [{mark}]")
        print(f"       {DIM}control: {data['rule_name']}{RESET}")
    elif kind == "done":
        print(f"\n{BOLD}loop closed{RESET} · "
              f"{GREEN}{data['mitigated']} mitigated{RESET} · "
              f"{YELLOW}{data['residual']} residual{RESET}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Sentinel purple-team demo for OWASP Juice Shop")
    ap.add_argument("--target", default="http://localhost:3000",
                    help="Juice Shop base URL (default: http://localhost:3000)")
    ap.add_argument("--mode", choices=["live", "replay"], default="replay",
                    help="live attacks a running instance; replay uses canned data")
    ap.add_argument("--allow-remote", action="store_true",
                    help="permit a non-local target (only for hosts you own/are authorised to test)")
    ap.add_argument("--output", help="write the run log JSON to this path")
    args = ap.parse_args()

    print(f"{BOLD}Sentinel{RESET} — red + blue agents vs OWASP Juice Shop\n")
    try:
        log = run_loop(target=args.target, mode=args.mode,
                       allow_remote=args.allow_remote, on_event=console_printer)
    except (ConnectionError, RuntimeError) as e:
        print(f"{RED}error:{RESET} {e}", file=sys.stderr)
        return 1

    b, a = log["verification"]["before"], log["verification"]["after"]
    print(f"\n{BOLD}Summary{RESET}")
    print(f"  vulnerabilities found : {b['open']}  {DIM}{b['by_severity']}{RESET}")
    print(f"  mitigated (verified)  : {len(a['mitigated'])}")
    print(f"  residual              : {a['open']}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(log, f, indent=2)
        print(f"\nrun log -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
