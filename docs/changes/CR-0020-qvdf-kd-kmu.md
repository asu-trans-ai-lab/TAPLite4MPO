# CR-0020 — QVDF reads `k_d` and `k_mu` from `link.csv`

**Date:** 2026-08-10 · **Status:** implemented, selftest green (351/0 with GOLD-001)
**Agency evidence:** the corridor-level tables behind this record are
agency-confidential and live in the private analysis repo; the engineering
content below is complete without them.

**Files:** `kernel/src/TAPLite.cpp`, `kernel/tests_cpp/selftest_main.cpp`

## Why

`Link_QueueVDF` computed its demand as

```cpp
IncomingDemand = Volume / lanes / H / VDF_plf;
```

which is `k_d = 1/vdf_plf` **hard-coded into the kernel**. CR-0019 removed PLF
from the static VDFs; this removes it from QVDF, which is where the V→D
mapping actually lives.

## What changed

Two new columns, both `0 = not supplied`:

| column (aliases) | meaning | effect |
|---|---|---|
| `kd` / `demand_modifier_kd` | `D = k_d · (V / lanes / H)` | replaces `1/vdf_plf` |
| `kmu` / `capacity_retention_kmu` | `μ ≤ k_μ · C_lane` | lowers the discharge ceiling |

```cpp
double lane_hourly_volume = Volume / lanes / H;
if (Link[k].Q_kd > 0.0) IncomingDemand = Link[k].Q_kd * lane_hourly_volume;
else                    IncomingDemand = lane_hourly_volume / VDF_plf;  // legacy
DOC = IncomingDemand / Lane_Capacity;
...
double mu_ceiling = (Q_kmu > 0.0) ? Q_kmu * Lane_Capacity : Lane_Capacity;
Q_mu = std::min(mu_ceiling, IncomingDemand / std::max(0.01, P));
```

`k_d` is deliberately **unbounded above**. `x_D > 1` is not an error state in
QVDF — it is the mechanism that produces a queue.

`k_μ` only lowers the ceiling; the analytical `min(·, D/P)` form is kept, so
the duration model stays internally consistent rather than being overridden by
a measured discharge that need not satisfy `D_Q = μ·P`.

## Tests (10 new, written before the kernel change)

`D = k_d·(V/lanes/H)` · `DOC = D/C_lane` · `k_d = 1.6 ⇒ x_D > 1` ·
`P = f_d·x_D^n` · `vdf_plf` inert once `k_d` supplied (1e-12) · `P` unchanged
by `vdf_plf` · legacy `D = (V/lanes/H)/plf` exact when `k_d` absent ·
`μ ≤ k_μ·C` · `μ = min(k_μ·C, D/P)` · `μ` ceiling reverts to `C` when `k_μ`
absent. **351 pass, 0 fail (whole suite).**

## Field staging — what actually got written

Every parameter explicit in `link.csv`; no side tables read at run time.

| column | source | coverage |
|---|---|---|
| `kd` | measured where identifiable, else declared | see below |
| `kd_source` | provenance stamp | 100 % |
| `kd_at_sensor`, `kd_xD_measured` | inventory — the measured value is always visible even when not used | 1,236 links |
| `kmu` | measured discharge | 1,236 links, else 1.0 |
| `vdf_cd`, `vdf_n`, `vdf_cp`, `vdf_s` | SLCLab-anchored where available | 1,236 links, else kernel default |
| `cutoff_speed` | measured `v_cutoff`, else 0.75·free speed | 1,236 links |
| `slclab_episodes` | how many episodes backed the estimate | 100 % |
| `capacity_period` | CR-0019, `I{P}HRLKCAP × 3.4014` | 100 % |

**The `k_d` selection rule** — a measured value is used only if the estimator
was not saturated (`x_D < 0.98`); otherwise the declared PM profile
`1/0.8503 = 1.176` is used and stamped as such:

| `kd_source` | links |
|---|---|
| `declared_profile` | 48,957 |
| `measured_at_sensor_unsaturated` | **372** |

Of the 1,236 links with a measurement, **864 were saturated** and fell back to
declared. That is the identifiability boundary from
`QVDF_KD_IDENTIFIABILITY.md` showing up as a count: at-sensor flow cannot see
demand above capacity, so on the links that queue hardest the measurement
carries no information and is not used.

`n = 1.000` and `s = 2.000` on every measured link — these are SLCLab anchor
assumptions, not estimates. Only `f_d`, `f_p`, `k_μ` and `cutoff_speed` are
genuinely measured. Recorded here so nobody later reads `vdf_n` as calibrated.

## Standing caveat

This run is **not** a validated QVDF calibration. It is a QVDF assignment on
declared demand peaking with 372 measured exceptions. Treat the volumes as a
mechanism test, not as evidence about `k_d`.
