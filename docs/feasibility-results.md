# Feasibility results

Output of `python3 scripts/feasibility.py` (seed 7, plus 10 robustness seeds). No LLM is involved. Re-run with `make feasibility` to regenerate.

- **Baseline v1:** R1 velocity (≥ 5 out in 1 h AND ≥ $1,000 out in 1 h), R2 pass-through (ratio ≥ 0.9 in 6 h AND ≥ $5,000 in within 6 h), R3 new device (< 24 h) AND transfer ≥ $1,000.
- **Fix (R4):** `short_hold_hop_count >= 4`, window 72 h, each hold < 24 h, each hop forwards ≥ 40% of what arrived.
- **Gate:** FPR increase ≤ 0.5 pp (2 FPs on 500 benign households), no regression loss, recall improves, schema valid.

```
Sentinel feasibility check (no LLM)
seed=7  benign=500  attack=48  dataset sha256=c55b853871fec99d
Fix under test: R4 = short_hold_hop_count >= 4 (window 72h, each hold < 24h, each hop forwards >= 40%), OR'ed onto v1
Lookahead check: passed (every alert reproduces with the trace cut at the alert time)

                             baseline v1           v1 + R4
attack recall               8/48 (16.7%)     32/48 (66.7%)
benign FPR                61/500 (12.2%)    61/500 (12.2%)

Attack recall by template
  fast_ring (golden)         baseline 8/8   v1+R4 8/8
  slow_chain_3               baseline 0/8   v1+R4 8/8
  slow_split                 baseline 0/8   v1+R4 8/8
  slow_small_new_device      baseline 0/8   v1+R4 8/8
  slow_long_hold             baseline 0/8   v1+R4 0/8
  short_chain                baseline 0/8   v1+R4 0/8
Benign FPR by template
  salaried                   baseline 0/125   v1+R4 0/125
  gig                        baseline 0/125   v1+R4 0/125
  student                    baseline 0/125   v1+R4 0/125
  small_business             baseline 61/125   v1+R4 61/125
Benign scenarios each rule flags on its own (rules overlap)
  R1 velocity_out_count         51/500 (10.2%)
  R2 pass_through_ratio         0/500 (0.0%)
  R3 new_device_before_transfer 17/500 (3.4%)
  R4 short_hold_hop_count     0/500 (0.0%)  (0 of these were already flagged by v1, so the gate never sees them)
  R4 benign hits by template: none


Gate (design §1 defaults)
  FPR increase <= 0.5 pp    +0 FPs = +0.00 pp (budget 2 FPs)  PASS
  regression: no loss       8/8 still caught                  PASS
  recall improves           +24 attacks caught                    PASS
  schema valid                                                PASS

RESULT: PASS

Threshold sweep, same data
    k   new FPs      dFPR            recall  gate
    2       226    45.20%    48/48 (100.0%)  FAIL
    3         0     0.00%    48/48 (100.0%)  PASS
    4         0     0.00%     32/48 (66.7%)  PASS
    5         0     0.00%     16/48 (33.3%)  PASS
    6         0     0.00%      8/48 (16.7%)  FAIL

All seeds, k=4
   seed   v1 benign flagged  fix new FPs  budget  R4 alone  fraud caught v1 -> v1+R4  gate
      7      61/500 (12.2%)            0       2         0             8/48 -> 32/48  PASS
   1000      59/500 (11.8%)            0       2         0             8/48 -> 32/48  PASS
   1001      51/500 (10.2%)            0       2         0             8/48 -> 32/48  PASS
   1002      64/500 (12.8%)            0       2         0             8/48 -> 32/48  PASS
   1003      56/500 (11.2%)            0       2         0             8/48 -> 32/48  PASS
   1004      52/500 (10.4%)            0       2         0             8/48 -> 32/48  PASS
   1005      61/500 (12.2%)            0       2         0             8/48 -> 32/48  PASS
   1006      56/500 (11.2%)            0       2         0             8/48 -> 32/48  PASS
   1007       47/500 (9.4%)            0       2         0             8/48 -> 32/48  PASS
   1008      55/500 (11.0%)            0       2         0             8/48 -> 32/48  PASS
   1009      54/500 (10.8%)            0       2         0             8/48 -> 32/48  PASS
  passed on 11/11 seeds
```
