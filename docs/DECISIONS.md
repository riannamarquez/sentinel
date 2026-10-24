# Decisions

Choices made without asking, one line each: decision · why · how to undo.

1. Tuned R1 as well as R2 to get the baseline under 15% · with R2 alone (even removed entirely) v1 still flagged 20–22%, from R1 on student bill-splitting · revert R1 to the single `velocity_out_count >= 5` condition in `BASELINE_V1`.
2. R2's AND condition is on money received (`velocity_in_amount >= $5,000` in 6 h), not money sent · an outflow minimum still flagged 41–80 small businesses paying payroll from their balance · swap the condition back to `velocity_out_amount`.
3. Added the `velocity_in_amount` feature · needed by decision 2 · remove it together with decision 2.
4. Modules live under one `sentinel/` package (`sentinel/sim`, `sentinel/eval`, ...) instead of top-level `sim/`, `eval/` · avoids a top-level package named `eval` shadowing the builtin, and keeps imports unambiguous · move the folders up a level and drop the `sentinel.` prefix from imports.
5. Added `sentinel/scenarios/` even though the step list didn't name it · design-v2 §6 puts the scenario factory there · fold it into `sentinel/sim/`.
6. Dependencies are pinned with uv (`pyproject.toml` + `uv.lock`), not `requirements.lock` · uv was installed and produces a full hash-pinned lock · `uv export --format requirements-txt > requirements.lock` if pip is preferred.
7. No NetworkX dependency · `short_hold_hop_count` is a time-respecting DP in plain Python (review 2.8), nothing else needs a graph library · add `networkx` to `pyproject.toml` when a feature needs it.
8. Scenarios store their materialized `transactions` plus `start_ts`, `source_account_id`, `funding_cents`, `opening_balances_cents`, `initial_devices` (beyond design-v2's field list) · fixtures must be self-contained and §6.2 needs owned accounts; the stolen amount has to enter the source account somehow · drop the fields and regenerate from (template_id, seed).
9. `SimulationAction.timestamp_offset` is seconds after the previous action, and a new `device_id` field carries the device for `change_simulated_device` · design was silent on both · switch to offsets from scenario start, or reuse `target_id` for the device.
10. Benign households get segment-specific opening balances, and a payment an owned account can't cover is dropped at build time · enforces "balance never below 0" (review 1.2.9 suggested emitting it as declined) · add a `status` field and keep declined rows instead. Drop rate is 2–3% for gig, student and business; 10.6% for salaried, almost all on dependents' accounts.
11. Raised the salaried opening balance from 0.25–1× to 0.5–1.5× monthly income · rent is due on day 0, before the first payday · revert the `gen_salaried` opening balance line.
12. `BankConfig.initial_balance_range_cents` is validated but not yet used; the world and holdouts use per-segment template balances · one balance model for templates and world · wire it into `generate_world` if the Builder agent needs it.
13. `BankConfig` keeps `detector_version` (design-v2 lists it) and gains `holdout_benign_n` / `holdout_attack_copies` · design-v2 kept the field; holdout sizes had to live somewhere per lab · move sizes to an evaluator config.
14. The feasibility numbers changed after the refactor (baseline now 5.0–9.8%, was 9.4–12.8%) · fraud now goes through `apply_actions`, households can't overdraw, and the factory uses per-split RNG streams · not a regression; the fix still passes 11/11 seeds.
15. Rule features with no window (`new_device_before_transfer`, `transfer_amount`) reject `window_hours`; windowed features require it · makes `validate_condition` strict · relax `needs_window` in `FeatureSpec`.
