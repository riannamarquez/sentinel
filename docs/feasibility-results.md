# Feasibility results

Output of `make feasibility` (seed 7, plus 10 robustness seeds). No LLM is involved. Regenerate this file with `make feasibility-results`.

- **Data:** the scenario factory's final holdout per seed: 500 benign households (salaried, gig, student, small business) and 48 hop-chain fraud scenarios (6 templates x 8 seeded copies).
- **Baseline v1:** R1 velocity (>= 5 out in 1 h AND >= $1,000 out in 1 h), R2 pass-through (ratio >= 0.9 in 6 h AND >= $5,000 in within 6 h), R3 new device (< 24 h) AND transfer >= $1,000.
- **Fix (R4):** `short_hold_hop_count >= 4`, window 72 h, each hold < 24 h, each hop forwards >= 40% of what arrived.
- **Gate:** FPR increase <= 0.5 pp (2 FPs on 500 benign households), no regression loss, recall improves, schema valid.

```
Sentinel feasibility check (no LLM)
seed=7  benign=500  attack=48  dataset sha256=6bd7b2469000e446
Fix under test: R4 = short_hold_hop_count >= 4 (window 72h, each hold < 24h, each hop forwards >= 40%), OR'ed onto v1
Lookahead check: passed (every alert reproduces with the trace cut at the alert time)

                             baseline v1           v1 + R4
attack recall               8/48 (16.7%)     32/48 (66.7%)
benign FPR                 49/500 (9.8%)     49/500 (9.8%)

Attack recall by template
  fast_ring                  baseline 8/8   v1+R4 8/8
  slow_chain_3               baseline 0/8   v1+R4 8/8
  slow_split                 baseline 0/8   v1+R4 8/8
  slow_small_new_device      baseline 0/8   v1+R4 8/8
  slow_long_hold             baseline 0/8   v1+R4 0/8
  short_chain                baseline 0/8   v1+R4 0/8
Benign FPR by template
  salaried                   baseline 0/125   v1+R4 0/125
  gig                        baseline 0/125   v1+R4 0/125
  student                    baseline 0/125   v1+R4 0/125
  small_business             baseline 49/125   v1+R4 49/125
Benign scenarios each rule flags on its own (rules overlap)
  R1 velocity_out_count         41/500 (8.2%)
  R2 pass_through_ratio         0/500 (0.0%)
  R3 new_device_before_transfer 11/500 (2.2%)
  R4 short_hold_hop_count     0/500 (0.0%)  (0 of these were already flagged by v1, so the gate never sees them)

Gate (design §1 defaults)
  fpr_budget             +0 false positives, budget 2 (0.5 pp)                      PASS
  regression_no_loss     8/8 previously caught attacks still caught                 PASS
  holdout_recall_gain    8 -> 32 of 48 caught                                       PASS
  schema_valid           hand-coded rule from the feature registry                  PASS

RESULT: PASS

Threshold sweep, same data
    k   new FPs            recall  gate
    2       242    48/48 (100.0%)  FAIL
    3         1    48/48 (100.0%)  PASS
    4         0     32/48 (66.7%)  PASS
    5         0     16/48 (33.3%)  PASS
    6         0      8/48 (16.7%)  FAIL

All seeds, k=4
   seed   v1 benign flagged  fix new FPs  budget  fraud caught v1 -> v1+R4  gate
      7       49/500 (9.8%)            0       2             8/48 -> 32/48  PASS
   1000       25/500 (5.0%)            0       2             8/48 -> 32/48  PASS
   1001       32/500 (6.4%)            0       2             8/48 -> 32/48  PASS
   1002       36/500 (7.2%)            0       2             8/48 -> 32/48  PASS
   1003       34/500 (6.8%)            0       2             8/48 -> 32/48  PASS
   1004       32/500 (6.4%)            0       2             8/48 -> 32/48  PASS
   1005       25/500 (5.0%)            0       2             8/48 -> 32/48  PASS
   1006       32/500 (6.4%)            0       2             8/48 -> 32/48  PASS
   1007       42/500 (8.4%)            0       2             8/48 -> 32/48  PASS
   1008       43/500 (8.6%)            0       2             8/48 -> 32/48  PASS
   1009       35/500 (7.0%)            0       2             8/48 -> 32/48  PASS
  passed on 11/11 seeds
```
