# TAPLite4MPO v0.2.0-efficiency — release staging (WP-07)

*(Folder renamed from `release_v0.1.0`; v0.1.0 content is fully superseded by
this build.)*

**Contents**
- `taplite4mpo-0.2.0-cp311-cp311-win_amd64.whl` — the Python package (dtalite_qa
  control layer + pytaplite binding), built from `github_taplite/pyproject.toml`.
- `DTALite.exe` — the kernel (MinGW x86_64 -O2 build, Dijkstra SP default,
  vdf_type 0–8, FW/CFW/BFW) **now including the full efficiency ladder
  P0/P1/P2/L3**. Feature list: `docs/KERNEL_FEATURE_CHANGES.md` (kernel repo).

**New in v0.2.0 — the efficiency ladder (all default-off; cold runs byte-identical)**

| Setting | What it does |
|---|---|
| `warm_start_times` | L1: preload congested link times from a prior `link_performance` CSV / DTLP bin (by external link id) |
| `flow_snapshot` | writes `link_flows.bin` (DTLR + 16-byte demand fingerprint) at end of run |
| `warm_start_flows` | L2: restore link volumes, skip iteration-0 AoN — fingerprint-guarded; mismatch demotes loudly to L1 |
| `column_output` | leveled `route_columns.bin` writer: `1` = DTAC v1 (last-iteration path per OD, light), **`2` = DTAC v2 (per-OD path sets with theta shares — the L3 store, use this for the rerun recipe)**, `3+` reserved (warns, acts as 2) |
| `warm_start_columns` | L3: replay theta × the **current** OD table (demand-invariant routing policy), drop/renormalize on network edits, mandatory RESTRICTED + TRUE gap report |
| `column_adjust_sweeps` | fixed-policy gradient-projection sweeps over stored columns (no SP calls) for targets below the FW plateau |

**The standard rerun recipe** (user decision — see
[docs/RERUN_RECIPE.md](../docs/RERUN_RECIPE.md)): baseline run once with
`column_output=2`, then rerunning ANY model =
`warm_start_columns=route_columns.bin` + `convergence_gap_pct=0.1` +
`column_adjust_sweeps=0`. Replay+FW reaches the 0.1% TRUE gap in ~1 iteration
on SCAG-scale models; add sweeps only for tighter targets.

**Headline (SCAG RTP24 AM, 246,806 links, perturbed demand, same-gap compute):**
**139x** faster to a 0.10% TRUE gap (0.7 s scatter vs 101.7 s cold), **8.4x** to
0.05%; targets at/below 0.02% are reachable **only** via the GP sweeps (plain FW
— cold or warm — plateaus above ~0.03%; GP reaches 7.6e-4%). Figures:
`docs/l3_tradeoff_scag.png`, `docs/l3_tradeoff_sketch.png` (kernel repo).

**Install / run (no compiler needed)**
```
pip install taplite4mpo-0.2.0-cp311-cp311-win_amd64.whl
python -m dtalite_qa intake <scenario>        # audit + declare (gate)
python -m dtalite_qa run <scenario> --exe DTALite.exe
```
The run command enforces the intake gate: an un-audited, BLOCKED, or stale
scenario refuses to run; `--override "who/why"` bypasses and is recorded in the
emitted `manifest.json` (per-run manifest + `dtalite_qa diff`).

**Verification at build time**: 13-network regression **30/30 PASS with no
re-baselining**, and with all new features off, `link_performance.csv` AND
`route_assignment.csv` are **byte-identical** to the pre-change kernel
(Chicago Sketch gate). ARC Atlanta calibrated reproduction region %RMSE 22%
(target 38%). Replication index: `soft/README.md` (kernel repo) — includes the
cold-run + warm-rerun replication row.

Cross-platform wheels: `.github/workflows/wheels.yml` (cibuildwheel) — this
folder is the manual Windows staging until a tag is cut.
