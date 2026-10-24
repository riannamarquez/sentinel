# Decisions

Choices made without asking, one line each: decision · why · how to undo.

1. Tuned R1 as well as R2 to get the baseline under 15% · with R2 alone (even removed entirely) v1 still flagged 20–22%, from R1 on student bill-splitting · revert R1 to the single `velocity_out_count >= 5` condition in `BASELINE_V1`.
2. R2's AND condition is on money received (`velocity_in_amount >= $5,000` in 6 h), not money sent · an outflow minimum still flagged 41–80 small businesses paying payroll from their balance · swap the condition back to `velocity_out_amount`.
3. Added the `velocity_in_amount` feature · needed by decision 2 · remove it together with decision 2.
4. Modules live under one `sentinel/` package (`sentinel/sim`, `sentinel/eval`, ...) instead of top-level `sim/`, `eval/` · avoids a top-level package named `eval` shadowing the builtin, and keeps imports unambiguous · move the folders up a level and drop the `sentinel.` prefix from imports.
5. Added `sentinel/scenarios/` even though the step list didn't name it · design-v2 §6 puts the scenario factory there · fold it into `sentinel/sim/`.
6. Dependencies are pinned with uv (`pyproject.toml` + `uv.lock`), not `requirements.lock` · uv was installed and produces a full hash-pinned lock · `uv export --format requirements-txt > requirements.lock` if pip is preferred.
7. No NetworkX dependency · `short_hold_hop_count` is a time-respecting DP in plain Python (review 2.8), nothing else needs a graph library · add `networkx` to `pyproject.toml` when a feature needs it.
