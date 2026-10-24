#!/bin/sh
# Regenerates docs/feasibility-results.md from the feasibility script's output.
set -e
OUT="$(uv run --frozen python scripts/feasibility.py)" || STATUS=$?
{
  echo "# Feasibility results"
  echo
  echo "Output of \`make feasibility\` (seed 7, plus 10 robustness seeds). No LLM is involved. Regenerate this file with \`make feasibility-results\`."
  echo
  echo "- **Data:** the scenario factory's final holdout per seed: 500 benign households (salaried, gig, student, small business) and 48 hop-chain fraud scenarios (6 templates x 8 seeded copies)."
  echo "- **Baseline v1:** R1 velocity (>= 5 out in 1 h AND >= \$1,000 out in 1 h), R2 pass-through (ratio >= 0.9 in 6 h AND >= \$5,000 in within 6 h), R3 new device (< 24 h) AND transfer >= \$1,000."
  echo "- **Fix (R4):** \`short_hold_hop_count >= 4\`, window 72 h, each hold < 24 h, each hop forwards >= 40% of what arrived."
  echo "- **Gate:** FPR increase <= 0.5 pp (2 FPs on 500 benign households), no regression loss, recall improves, schema valid."
  echo
  echo '```'
  echo "$OUT"
  echo '```'
} > docs/feasibility-results.md
exit ${STATUS:-0}
