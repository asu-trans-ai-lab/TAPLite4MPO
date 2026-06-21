# QVDF — D/C-consistent congestion-duration output

Standard BPR/conical VDFs return only a **period-average travel time**. The
**Queue-based VDF (QVDF, `vdf_type=2`)** is the new-generation output: from the same
demand/capacity ratio it produces a **D/C-consistent congestion *duration* and queue
speed profile**, so a static assignment can report *how long* a link is congested — not
just how slow on average. This is what meets the **NVTA congestion-duration
requirements** (and similar agency LOS/duration deliverables).

---

## 1. What QVDF adds to `link_performance.csv`

For every link, QVDF writes (in addition to volume / `doc` / speed / VMT / VHT):

| column | meaning |
|---|---|
| **`P`** | **congestion duration (hours)** — how long inflow exceeds capacity: `P = Q_cd · (D/C)^Q_n` |
| **`Severe_Congestion_P`** | duration (h) below the severe-congestion threshold |
| `t0,t2,t3` | queue onset / peak / recovery times within the period |
| `vt2_mph` | speed at the peak of the queue |
| `congestion_ref_speed_mph`, `avg_queue_speed_mph` | the queue speed model |
| `avg_QVDF_period_speed_mph`, `avg_QVDF_period_travel_time` | period-average speed/time the assignment uses as the link cost |
| `VHT_QVDF`, `PHT_QVDF` | queue-consistent vehicle/person hours |

`P` (and `Severe_Congestion_P`) are **monotone in D/C**, so duration is *consistent with*
the assigned volume/capacity — the same D/C that drives route choice drives the reported
duration. The period-average QVDF speed is also a valid (monotone) link cost, so QVDF
runs as the assignment VDF, not just a post-processor.

## 2. Inputs (per link)

```
vdf_type = 2
cutoff_speed                 # speed at capacity (v_congestion_cutoff)
vdf_cp, vdf_cd, vdf_n, vdf_s # queue VDF parameters (cp, cd, n, s)
vdf_alpha, vdf_beta          # speed-flow shape
```
A transparent reference implementation + spreadsheet are in
[`../test_networks/qvdf_reference/`](../test_networks/qvdf_reference/)
(`qvdf_ref.py`, `QVDF_clean_reference.xlsx`) — use it to check the kernel's `P`, speeds,
and period-average time against the closed-form model.

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
   per-corridor QVDF parameters
        │
        ▼   write into the GMNS link.csv (vdf_type=2 + cutoff_speed + vdf_cp/cd/n/s)
   TAPLite4MPO QVDF assignment
        │
        ▼
   link `P` / `Severe_Congestion_P` / queue speeds  ──►  agency congestion-duration deliverable
```

So the two projects compose: **CBI turns observed speeds into QVDF parameters; TAPLite4MPO
assigns with QVDF and reports the D/C-consistent congestion duration.** In the NVTA work
this is what produces the per-link congestion-duration measure the agency requires.

> The CBI tool is maintained as a separate repository (the QVDF-E project: corridor FD/CBI
> calibration, teaching spreadsheets, and the per-corridor workflow). It is not bundled
> here; this page documents the interface (its output = TAPLite's QVDF input). See
> `test_networks/qvdf_reference/` for the QVDF math used on both sides.

---

### See also
- `USER_GUIDE.md` §4 (VDF mechanics) · `USER_GUIDE_VOL2_MPO.md` §3 (VDF library)
- `test_networks/qvdf_reference/` (reference implementation + spreadsheet)
