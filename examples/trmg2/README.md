# TRMG2 — Triangle Regional Model (TransCAD → GMNS example)

A **public-model** example of the config-driven TransCAD→GMNS conversion, using the
**Triangle Regional Model G2** (TRMG2, WSP / Triangle-Modeling-and-Analytics, TransCAD 9,
~76k drive links). This is the second agency example after `arc_atlanta/`.

> **What this example proves — and what it does not (read first).** The **converter** is
> validated rigorously (below). The **count/screenline accuracy is NOT** — the demand here
> is an *interim converted OD*, not the agency's OMX, and it is a single 1-hour AM SOV
> period while the observed counts are *daily AWDT*. So this example demonstrates the
> **conversion + a runnable, converged assignment**, and is **one command away** from a
> real count validation once the agency OMX arrives. Credibility rests on converter
> fidelity, not on a count %RMSE.

## What TRMG2 ships (upstream)
TransCAD `.dbd` network (geometry in `.dln/.pts` sidecars) + `.BIN`/`.DCB` attribute
tables + `.mtx` demand. The link table carries observed `DailyCount` / `DailyCountSUT` /
`DailyCountMUT` and `Screenline` / `Cutline` groupings — so a real screenline validation
is *possible* once the demand basis matches.

## The conversion (this example)
Input = a **links shapefile** (geometry + attributes; TRMG2's `.dln/.pts` geometry paired
with the `.BIN` attributes) + a **nodes** layer. Convert with the config-driven engine:

```bash
python -m dtalite_qa.net2gmns  trmg2_links.shp  --nodes trmg2_nodes.shp \
       --config net2gmns_trmg2.json  --out gmns/
python -m dtalite_qa.intake gmns/          # declare conventions -> GATE READY
( cd gmns && ../../../release_v0.2.0/DTALite.exe )   # run the assignment
```

Field map (`net2gmns_trmg2.json`) — GMNS ← TransCAD:

| GMNS | TransCAD field | Note |
|---|---|---|
| from/to_node_id | `FROM_ID` / `TO_ID` | directed endpoints |
| lanes | `ABLANES` / `BALANES` | per direction (DIR split) |
| capacity | (per-lane, hourly) | `capacity_basis: per_lane` |
| free_speed | `POSTEDSPEE` | mph |
| length | `LENGTH` | mi → m |
| factype | `HCMTYPE` | categorical (string preserved) |
| vdf_alpha/beta | `_ALPHA` / `_BETA` | |
| centroids | node `CENTROID` > 0 | renumbered 1..Z |
| drive-only filter | `DTWB` contains `D` | drops walk/bike/transit geometry |

## Demand — interim now, agency OMX later
The demand shipped/used here is an **interim converted OD** (single AM SOV period). When
the agency releases the **OMX** demand, swap it in with one command (coverage +
Excel-truncation checks run automatically):

```bash
python -m dtalite_qa.matrixio  trmg2_am.omx  --scenario gmns/  --out gmns/demand.csv
```

## Validation — two tiers (honest)

**Tier 1 — converter fidelity (solid, demand-independent):**
- `net2gmns` produced **75,939 drive links — an exact match** to an *independent* decode
  of the same model from `net.net` (75,939), with identical GMNS structure. Two separate
  decode paths agree on the network.
- `transcad_bin` parsed the full `master_links.BIN` (135k records × 50 fields) — the
  FFB reader at real-model scale.

**Tier 2 — runnable assignment (confirms the network solves):**
- The converted GMNS converges to **0.044% relative gap in 24 iterations (~86 s)** — matching
  the reference headline.

**Tier 3 — count/screenline validation: DEFERRED, pending the agency OMX.**
The link table has `DailyCount` + `Screenline` + `Cutline`, and the traceable workflow
(`python -m dtalite_qa.workflow gmns/`) will produce the screenline/cutline/facility/
volume-group %RMSE tables — **but only meaningfully once (a)** the demand is the agency OMX
(not our interim OD) **and (b)** the run period matches the count basis (daily, or the
counts scaled to AM). Running it on the interim AM-SOV demand vs daily counts would report
a large, meaningless mismatch (catalog §2b, the period-vs-daily trap). We do not report
that number.

## Files
- `net2gmns_trmg2.json` — the conversion config (the reproducible recipe)
- `submission.yml` — declared conventions (interim demand; OMX pending; count/screenline fields)
- the derived GMNS network is **not committed** (large, and pending the OMX demand) —
  regenerate it with the command above from the public TRMG2 model.

See `../../docs/TRMG2_CONVERSION_REVIEW.md` for the full systematic review.
