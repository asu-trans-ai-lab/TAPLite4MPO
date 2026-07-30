# Observed QVDF episode regression fixture

Two independent, otherwise identical QVDF links carry equal demand in the
06:00-09:00 period. Link 101 has an observed
`t0/t2/t3 = 6.5/7.0/8.5` episode, while link 102 has
`6.5/8.0/8.5`. The analytical `P`, DOC, period-average speed, and travel time
must match. The observed endpoints position 25% of `P` before link 101's
trough and 75% before link 102's trough, and the five-minute speed minima must
remain at their supplied `t2_hour` values.

`tests/test_qvdf_observed_t2.py` also derives temporary variants to verify the
missing-column midpoint fallback, silent symmetric endpoint fallback, endpoint
fraction limiting, invalid-`t2` diagnostics, and the GitHub issue #10 profile
contract (`t0 <= t2 <= t3`, `vt2 <= cutoff`, and every five-minute speed within
`[vt2, free_speed]`). Boundary variants place `t2_hour` at 06:15 and 08:45 to
verify that `t0` and `t3` clamp to the assignment-period band while the speed
trough remains centered at the supplied `t2_hour`.
