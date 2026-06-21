# MPO onboarding guideline — from a raw hand-off to a trustworthy assignment

**Audience: MPO modeling staff handing a model to TAPLite, and the analyst onboarding it.**

A typical hand-off is a *shapefile + a demand matrix + a couple of "alpha/beta" numbers*.
That is **not enough to run a correct assignment**, and pretending it is — by guessing the
missing conventions and running anyway — produces a plausible-looking, wrong result. This
guideline defines the **process** that turns a hand-off into a trustworthy run: declare →
convert → intake → resolve → validate. It is auditable (every step is logged) and iterative
(you re-run until the gate is clean).

> The single rule: **the tool never guesses a convention. Anything the MPO did not declare
> becomes a blocking issue that names the field to provide and why it matters.**

---

## Why a shapefile + matrix is not enough

These files carry geometry, lane counts, and raw numbers. They **cannot** tell you the
facts that actually decide the answer:

| The data shows… | …but it cannot tell you (you must declare) | If you guess wrong |
|---|---|---|
| a `capacity` column | per-lane or per-link? **hourly, period, or daily?** | daily cap ⇒ network looks empty (V/C≈0); hourly cap over a 3-h period ⇒ over-congested |
| `alpha`, `beta` | which VDF, and where the coefficients came from | wrong curve shape near capacity, not reproducible |
| a length column | miles, metres, or km | metres-as-miles inflates distance cost ~1609× |
| a trip matrix | vehicles or persons? what period? what occupancy? | person trips loaded as vehicles over-load by the occupancy factor |
| free-flow speed | mph or km/h | 1.6× error in free-flow time |
| matrix row labels | how they map to zone ids | a silent mapping error scrambles the whole OD table |
| — | the **peak-load factor** (peak-hour share of the period) | flat PLF=1 under-states peak congestion |
| — | which column is the **observed count** | the run can't be validated against reality |

This is exactly what the **ARC example** gets right: ARC publishes *Section 7 — Trip
Assignment*, which states the VDF, the capacity basis, the period factor, VOT, and the
validation targets. **Every MPO must provide the equivalent** — for TAPLite that equivalent
is the `submission.yml` declaration.

---

## The workflow (the layers)

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │ 1. DECLARE   MPO fills submission.yml (from templates/                │
  │              mpo_submission_template.yml) — the README for the data   │
  │ 2. CONVERT   network shapefile + matrix -> GMNS (converter logs steps)│
  │ 3. INTAKE    python -m dtalite_qa intake <scenario>                   │
  │              -> intake_issues.json + intake_log.md + dashboard.html   │
  │ 4. RESOLVE   open the dashboard; fix every BLOCKER (fill submission   │
  │              .yml, guided); re-run intake.  ── iterate ──┐            │
  │                  ▲──────────────────────────────────────┘            │
  │ 5. VALIDATE  gate READY -> dtalite_qa check -> run -> validate vs    │
  │              counts (%RMSE by volume group)                          │
  └─────────────────────────────────────────────────────────────────────┘
```

### 1. Declare
Copy `dtalite_qa/templates/mpo_submission_template.yml` into the scenario as
`submission.yml` and fill **every** field. Leaving a field as `TODO` is not a shortcut —
the intake will block on it. If you genuinely don't know a value (e.g. the peak-load
factor), that is a finding to resolve *with the MPO*, not a default to invent.

### 2. Convert
Convert the network to GMNS (`node.csv`, `link.csv`, demand, `settings.csv`,
`mode_type.csv`). A converter should **emit a log** of what it did and every assumption
(snapping tolerance, unit conversions, id renumbering). The intake consolidates this into
`intake_log.md`.

### 3. Intake (the audit)
```bash
python -m dtalite_qa intake <scenario>
```
Produces three artifacts in the scenario folder:
- **`intake_issues.json`** — machine-readable issues, severity-sorted.
- **`intake_log.md`** — the time-ordered trail: every step, every detected fact, every
  assumption. This is your conversion record.
- **`intake_dashboard.html`** — open it in a browser: a gate banner, the issue list, and a
  **guided form** that explains each missing declaration and generates the `submission.yml`
  block to paste back.

Issues have four severities:

| severity | meaning | blocks the gate? |
|---|---|---|
| **BLOCKER** | the run cannot be correct without it (capacity convention, length unit, missing demand zones) | **yes** |
| **DECISION** | the MPO must choose; a default exists but is risky (PLF, speed unit, trip kind, VOT) | no, but review |
| **MISSING** | a field is absent; a safe default is applied, but it's recorded | no |
| **INFO** | a detected fact or step | no |

The intake also runs **evidence cross-checks**: if you declare `length_unit: mi` but the
median length is 710, it flags the contradiction. A declaration that disagrees with the
data is caught, not trusted.

### 4. Resolve — iteratively
Open `intake_dashboard.html`. For each open field, the form gives the question, the help,
and *why it matters*. Fill what you can, click **Generate submission.yml**, paste into the
scenario's `submission.yml`, and re-run `intake`. Repeat until **GATE: READY** (0 blockers).
This is the loop — you are not expected to get it right in one pass; you are expected to
drive the blockers to zero.

### 5. Validate and run
Once READY:
```bash
python -m dtalite_qa check <scenario>     # input validation + accessibility
python -m dtalite_qa run   <scenario> --exe bin/DTALite.exe
# then validate assigned vs observed counts (see examples/arc_atlanta)
```

### 6. Traceable staged workflow (R1–R6)
For a full auditable record across conversion → assignment → validation, run the staged
workflow. It is the generalized form of the **MAG Traceable-Workflow**; every stage
writes a numbered report + tables (+ figures) and a verification **gate**:

```bash
python -m dtalite_qa workflow <scenario> [--reference <perf_with_ref.csv>] [--period PM]
```

| Stage | Gate |
|---|---|
| **R1** inventory & directionality | directed AB/BA present; network by FT-AT |
| **R2** OD & allowed-uses | demand totals by class; allowed_use flags |
| **R3** capacity & VDF join | **100%** capacity + α/β join rate |
| **R4** period & PLF | PLF declared / not flat over a multi-hour period |
| **R5** TAP consistency | model-vs-reference volume slope ≈ 1; problem-link list |
| **R6** VMT/VHT validation | total VMT vs reference **≤ 5%**, by FT-AT |

Outputs land in `<scenario>/traceability/` (`reports/00_traceability.md` index +
`workflow_dashboard.html`). R5–R6 need a completed `link_performance.csv`; R5/R6 also need
**reference columns** — period-prefixed (`PM_FLOW`, `PM_VMT`, …) or `ref_volume` — otherwise
they cleanly report `SKIP`. This replaces hand-edited per-model comparison scripts with one
reusable, gated, reproducible pipeline.

---

## Worked cautionary example — GSATS capacity

GSATS handed over `2025BY_Links_v9.shp` + `VehicleTrips_AM.xlsx` and the BPR `ALPHA`/`BETA`
fields. Nothing stated the capacity convention. The DBF actually carries **three** capacity
columns — `AB_CAP` (daily), `AB_CAP_PK` (peak), `AB_CAP_OFF` (off-peak), differing ~5×. A
first conversion used `AB_CAP` (daily) and the AM run came out at **median V/C ≈ 0.007** —
i.e. "no congestion anywhere", which is obviously wrong for a peak assignment.

The right response is **not** to quietly switch to `AB_CAP_PK` and report a new number. It
is to **block** and ask GSATS: *which column is the assignment capacity, for what duration,
and what is the peak-load factor?* That is exactly what `dtalite_qa intake` does — on the
raw hand-off it reports `BLOCKER capacity_period: undeclared AND PLF flat over a 3-h
period`. Only once GSATS declares it (in `submission.yml`) does the gate open — and the
declared value is now on the record, reproducible, and reviewable.

---

## What the MPO must deliver (checklist)

- [ ] the network (GMNS or a documented shapefile + the converter)
- [ ] the demand matrices, with the period and trip-kind stated
- [ ] **`submission.yml`** — every field filled (the README for the data)
- [ ] the observed-count / reference-volume column for validation
- [ ] a pointer to the agency's own assignment documentation (the ARC *Section 7* equivalent)

See also: `peak_load_factor.md` (the PLF convention), `examples/arc_atlanta/` (a complete,
correct submission), and `USER_GUIDE_VOL2_MPO.md` (the kernel mechanics).
