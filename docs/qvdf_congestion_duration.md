# QVDF — D/C-consistent congestion-duration output

Standard BPR/conical VDFs return only a **period-average travel time**. The
**Queue-based VDF (QVDF, `vdf_type=2`)** is the new-generation output: from the same
demand/capacity ratio it produces a **D/C-consistent congestion *duration* and queue
speed profile**, so a static assignment can report *how long* a link is congested — not
just how slow on average. This is what meets the **the agency congestion-duration
requirements** (and similar agency LOS/duration deliverables).

---

## 1. What QVDF adds to `link_performance.csv`

For every link, QVDF writes (in addition to volume / `doc` / speed / VMT / VHT):

| column | meaning |
|---|---|
| **`P`** | **congestion duration (hours)** — how long inflow exceeds capacity: `P = Q_cd · (D/C)^Q_n` |
| **`Severe_Congestion_P`** | duration (h) below the severe-congestion threshold |
| `t0,t2,t3` | band-limited queue onset / observed trough / recovery times; optional observed episode endpoints can make the analytical `P` split asymmetric around `t2` |
| `vt2_mph` | speed at the peak of the queue |
| `congestion_ref_speed_mph`, `avg_queue_speed_mph` | the queue speed model |
| `avg_QVDF_period_speed_mph`, `avg_QVDF_period_travel_time` | period-average speed/time the assignment uses as the link cost |
| `VHT_QVDF`, `PHT_QVDF` | queue-consistent vehicle/person hours |
| `qvdf_profile_status` | whether a profile was generated, or the reason a flat fallback was used |

`P` is **monotone in D/C**, so duration is *consistent with* the assigned
volume/capacity — the same D/C that drives route choice drives the reported duration.
`Severe_Congestion_P` is derived from the emitted speed profile and therefore also
reflects any observed boundary-speed anchors. The period-average QVDF speed is a valid
(monotone) link cost, so QVDF runs as the assignment VDF, not just a post-processor.

## 2. Inputs (per link)

```
vdf_type = 2
cutoff_speed                 # speed at capacity (v_congestion_cutoff)
vdf_cp, vdf_cd, vdf_n, vdf_s # queue VDF parameters (cp, cd, n, s)
vdf_alpha, vdf_beta          # speed-flow shape
qvdf_profile_mode            # optional: blank legacy auto; 0 disabled; 1 model; 2 observed-gated
t0_hour, t3_hour             # optional observed episode start/end
t2_hour                      # optional observed trough time, decimal hour-of-day
qvdf_start_speed_mph         # optional observed first profile-sample speed
qvdf_end_speed_mph           # optional observed last profile-sample speed
```

### Profile activation

`qvdf_profile_mode` controls the full-output reporting profile independently
from `vdf_type`, which continues to select the assignment travel-time function:

| value | profile behavior |
|---|---|
| missing or blank | legacy auto: generate for `link_type=1`, a Cube-style code ending in `01`, or a link with valid observed `t2_hour` |
| `0` | disabled: write a flat period-average profile |
| `1` | model-generated on any link; use valid observed `t2_hour`, otherwise the assignment-period midpoint |
| `2` | observed-gated: require valid observed `t2_hour`; otherwise use the boundary/flat fallback policy below |

Positive assigned volume is required before QVDF generation, and
`qvdf_volume_threshold` remains a hard computational guard after profile
eligibility is determined. Therefore mode `1` overrides link-type selection but
does not bypass either volume guard. Missing or blank mode cells preserve the
legacy selector; invalid values warn and also use legacy auto.

Every full-output row includes `qvdf_profile_status`. Generated values are
`generated_legacy_link_type`, `generated_legacy_observed_t2`,
`generated_model`, `generated_observed`, and
`generated_low_anchor_connector`. Observed-only fallback values are
`smoothed_boundary_missing_observation`,
`smoothed_boundary_below_volume_threshold`, and
`smoothed_boundary_legacy_not_selected`. Flat reasons are `flat_disabled`,
`flat_zero_volume`, `flat_missing_observation`, `flat_below_volume_threshold`, and
`flat_legacy_not_selected`.

When assigned volume is zero, the kernel skips QVDF generation and boundary
smoothing for every activation mode. It emits `flat_zero_volume`, keeps the
link row and numeric schema intact, and fills every sample with the assigned
period-average speed `length / (travel_time / 60)` (or free speed when travel
time is unusable). For positive-volume links where QVDF generation is skipped,
mode `0` always remains flat. In every other mode, either valid boundary-speed
observation produces an observed-only cubic smoothstep connector across the
emitted period; the assigned period-average speed supplies any missing endpoint.
With no valid boundary observation, every sample remains at that assigned speed.
In all fallback cases the scalar QVDF fields retain the assigned period-average
speed and travel time, so `VHT_QVDF` and `PHT_QVDF` remain meaningful and the
connector cannot be mistaken for an analytically generated QVDF calculation.

`t2_hour` is link- and assignment-period-specific. For example, `7.5` means
07:30. Put the appropriate period-specific values in that period's `link.csv`;
the kernel joins nothing by row order or across periods. A blank cell or an
absent column uses `(demand_period_starting_hours +
demand_period_ending_hours) / 2`, preserving prior behavior. A supplied value
must be finite and within the configured period. Invalid values are reported
with the link ID and rejected in favor of the midpoint; they are never clamped.
The compatibility alias `t2` is also accepted, but `t2_hour` is the documented
input name used by the CBI handoff. `t2` remains the output column name in
`link_performance.csv`.

When a valid ordered `t0_hour < t2_hour < t3_hour` trio is present, the kernel
uses the guarded observed before-trough fraction
`(t2_hour-t0_hour)/(t3_hour-t0_hour)`, limited to `[0.05,0.95]`. It projects
that fraction of analytical `P` before `t2` and the remainder after `t2`.
No new QVDF parameter or output field is introduced. Missing, partial,
malformed, or unordered endpoints silently use the historical `P/2` split.
Observed endpoints may extend outside the selected period because only their
proportion is used.

Only the profile's time position changes: `P`, DOC, `vt2_mph`, period-average
QVDF speed, and assignment travel time use the same demand and QVDF parameters
as before. The reported `t0` and `t3` and the five-minute profile are clipped
to the configured assignment-period band. When clipping occurs, `P` remains
the analytical QVDF duration and can therefore exceed `t3-t0`; the in-band
profile becomes asymmetric but retains its minimum speed exactly at `t2`.

Within the assignment period but outside the queue window, the five-minute
profile connects free-flow speed `vf` to
`vb = max(congestion_ref_speed, avg_queue_speed)` with the parameter-free cubic
smoothstep `psi(r) = r^2(3-2r)`. Before `t0`,
`r = clip((t-period_start)/max(0.001,t0-period_start),0,1)` and
`v(t) = vf + (vb-vf)*psi(r)`. After `t3`,
`r = clip((t-t3)/max(0.001,period_end-t3),0,1)` and
`v(t) = vb + (vf-vb)*psi(r)`. This replaces the former linear connectors
without changing the queue shape inside `[t0,t3]` or adding a calibrated input.
A transparent reference implementation + spreadsheet are in
[`../test_networks/qvdf_reference/`](../test_networks/qvdf_reference/)
(`qvdf_ref.py`, `QVDF_clean_reference.xlsx`) — use it to check the kernel's `P`, speeds,
and period-average time against the closed-form model.

### Observed speeds at profile boundaries

Valid positive `qvdf_start_speed_mph` and `qvdf_end_speed_mph` observations
anchor the first and last emitted five-minute profile samples. The profile is
half-open (`period_start <= t < period_end`), so the final emitted sample is
five minutes before `period_end`. Each side falls back independently to the
existing modeled/free-flow profile when its column is missing, blank, invalid,
or non-positive; invalid nonblank values produce a link-specific warning.

For a generated QVDF profile, each missing boundary observation independently
uses the existing modeled profile on that side. When QVDF generation is
skipped for a missing observed `t2`, the volume threshold, or legacy selection,
any valid start or end observation instead activates an observed-only fallback.
The missing side uses the assigned period-average speed. Explicit mode `0`
remains flat even when boundary-speed columns are supplied.

Let `v_raw(t)` be the modeled QVDF profile, `v_b=max(congestion_ref_speed,
avg_queue_speed)`, `margin=max(2 mph, 0.10*(v_b-vt2))`, and
`psi(r)=r^2(3-2r)`. With an observed `t2`, each side selects its connector
independently:

- If `v_anchor < v_b` and `v_anchor <= vt2 + margin`, a direct cubic
  smoothstep connects the boundary anchor to `vt2`. This suppresses a raw QVDF
  shoulder that would otherwise make a low anchor rise toward `v_b`, reverse at
  `t2`, and rise again. When `v_anchor < vt2`, the boundary observation becomes
  the side's minimum and `vt2` is a pivot rather than the global profile trough;
  this exposes the observation/model conflict without an artificial overshoot.
- If `vt2 + margin < v_anchor < v_b`, a monotone cubic Hermite splice searches
  inward for a raw point below the anchor whose raw slope satisfies the monotone
  bound. It uses zero slope at the observed boundary and matches the raw QVDF
  slope at the join; the raw profile is unchanged inward of that join.
- Otherwise, or when no suitable Hermite join exists, the historical rule
  blends the starting observation from the first sample to `t2` with weight
  `1-psi(r)` and the ending observation from `t2` to the last sample with weight
  `psi(r)`. The observation is exact at its boundary and has zero influence at
  `t2`.

Missing anchors, modeled-midpoint `t2` profiles, and skipped QVDF profiles
retain their existing behavior. All generated-profile paths preserve `P`,
`t0/t2/t3`, `vt2`, and the analytical period-average QVDF speed/travel time.
`Severe_Congestion_P` is recomputed from the final anchored samples because it
is profile-derived.

For an observed-only fallback, let `v_start` and `v_end` be the valid observed
speeds or the assigned period-average speed on a missing side. Across the first
through last emitted samples,
`r=(t-period_start)/(profile_last-period_start)` and
`v(t)=(1-psi(r))*v_start+psi(r)*v_end`. This connector does not invent
`P`, `t0`, `t2`, `t3`, or a QVDF trough; those remain fallback values.

---

## 3. The CBI sister project — where the QVDF parameters come from

The QVDF parameters (`cutoff_speed`, `cp/cd/n/s`) are **calibrated from corridor speed
data** by the **CBI tool** (Calibration-Based Inference / Fundamental-Diagram pipeline) —
a *sister project* to TAPLite4MPO. Clean pipeline:

```
  corridor speed data (PeMS / INRIX TMC, AM & PM)
        │
        ▼   CBI pipeline  (four layers)
   1. QC          quality-control the speed series
   2. episodes    extract congestion episodes (onset → recovery)
   3. FD          fit the fundamental diagram (speed–density–flow)
   4. mu → QVDF   back out queue discharge rate -> QVDF params (cutoff_speed, cp/cd/n/s)
        │            (+ quality gates: predicted vs observed mu, S3-prior for TMC w/o volume)
        ▼
   per-link / corridor QVDF parameters and observed t0/t2/t3 hours
        │
        ▼   write into the period GMNS link.csv
            (vdf_type=2 + cutoff_speed + vdf_cp/cd/n/s
             + optional t0_hour/t2_hour/t3_hour)
   TAPLite4MPO QVDF assignment
        │
        ▼
   link `P` / `Severe_Congestion_P` / queue speeds  ──►  agency congestion-duration deliverable
```

So the two projects compose: **CBI turns observed speeds into QVDF parameters; TAPLite4MPO
assigns with QVDF and reports the D/C-consistent congestion duration.** In the the agency work
this is what produces the per-link congestion-duration measure the agency requires.

> The CBI tool is maintained as a separate repository (the QVDF-E project: corridor FD/CBI
> calibration, teaching spreadsheets, and the per-corridor workflow). It is not bundled
> here; this page documents the interface (its output = TAPLite's QVDF input). See
> `test_networks/qvdf_reference/` for the QVDF math used on both sides.

---

### See also
- `USER_GUIDE.md` §4 (VDF mechanics) · `USER_GUIDE_VOL2_MPO.md` §3 (VDF library)
- `test_networks/qvdf_reference/` (reference implementation + spreadsheet)
