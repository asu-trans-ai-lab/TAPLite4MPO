# The self-demonstrating installation — walkthrough

*One command proves your install works: bundled public data → intake gate →
native C++ kernel → output checks → golden-baseline regression → dashboards.
Exit code 0 only when every gate passes. This same check gates every release.*

```bash
pip install taplite4mpo
taplite self-demo                        # Chicago Sketch (fast regression)
taplite self-demo --case arc-superzone   # ARC Superzone (MPO-scale demo)
```

![ARC Superzone self-demo — assigned volumes on the recognizable Atlanta freeway network](https://raw.githubusercontent.com/asu-trans-ai-lab/TAPLite4MPO/main/docs/images/selfdemo_arc_superzone.svg)

## What you see — real output (ARC Superzone case)

```console
$ taplite self-demo --case arc-superzone
== TAPLite4MPO self-demo: ARC Superzone (MPO-scale workflow demonstration) ==
[PASS] bundled data -- 9 files from the installed package
[PASS] intake gate -- GATE: READY (0 blockers)
[PASS] crosswalk -- deterministic mapping, sha256 ..., 6031 zones -> 151 superzones (39.94x)
[PASS] demand conservation -- original 3,398,701 == aggregated 2,275,731 + intrazonal
       1,122,970 (33.041%, excluded from network loading, retained in this audit)
[PASS] superzone connectivity -- all 151 superzones have outbound+inbound connectors
[PASS] native assignment -- kernel rc=0
[PASS] output checks -- 145969 rows, all required fields finite and physical
[PASS] manifest + report -- manifest.json + report.html written
[PASS] corridor extraction -- GA-400=18,918; I-20=15,064; I-285=26,489; I-75=22,868; I-85=26,806
[PASS] golden regression -- all structural + numerical checks within tolerance
       (VMT rel 0.00e+00, tol 0.0025; VHT rel 0.00e+00; total volume rel 0.00e+00)

TAPLite4MPO self-demo: PASS
```

## The two cases

| | Chicago Sketch (default) | ARC Superzone |
|---|---|---|
| Command | `taplite self-demo` | `taplite self-demo --case arc-superzone` (alias `taplite demo arc-superzone`) |
| Purpose | fast deterministic kernel + packaging regression | complete real-world MPO workflow |
| Network | 933 nodes / 2,950 links / 387 zones | **full recognizable ARC network**: 60,666 nodes / 145,969 links |
| Demand | 93,513 OD, 1,260,907 veh | 6,031 zones superzoned to **151** (39.9×); 3,398,701 veh conserved to machine precision, 33% intrazonal explicitly audited |
| Golden metrics | VMT 12,166,635 / VHT 306,560 / gap 0.19% | VMT 17,056,235 / VHT 488,688 / gap 0.18% + five corridor pins (I-75, I-85, I-20, I-285, GA-400) |
| Runtime | well under a minute | ~1–3 minutes |
| CI | every PR, every release (wheel-gated) | main pushes, weekly schedule, manual dispatch |

Both run the **native C++ TAPLite kernel** in a deterministic golden
configuration (standard Frank–Wolfe, one processor, fixed iterations) so
results are reproducible to `rel 0.00e+00` on the same platform; drift beyond
the per-metric tolerances (0.1–1.0%) exits nonzero.

## What lands in the artifact folder

```text
taplite_selfdemo_output/
  selfdemo_dashboard.html      <- gate summary: Run / Trust / Reproduce panels
                                  (+ compression panel and superzone map for ARC)
  selfdemo_summary.json / .md  <- machine-readable result (CI-friendly)
  network_dashboard.html       <- OPTIONAL interactive map (pip install gui4gmns):
                                  pan/zoom, embedded OSM+satellite basemap,
                                  volume tiers, OD desire lines, QC layers
  input/                       <- the bundled scenario, copied out of the package
  run/                         <- kernel outputs: link_performance.csv,
                                  manifest.json, report.html, console log
```

The ARC fixture ships lon/lat coordinates (reprojected from Georgia State
Plane with a built-in inverse Transverse Mercator, verified against pyproj to
~3 cm), so the interactive dashboard places a real Atlanta basemap under the
network.

## Guarantees

- **Never writes inside site-packages** — everything goes to a writable output
  folder (`--output`, `$TAPLITE_SELFDEMO_OUT`, or `./taplite_selfdemo_output`).
- **The golden baseline can never change silently** — normal runs only compare;
  `--record-baseline` is an explicit maintainer action that announces the
  repository changed.
- **Tampering fails loudly** — a modified demand file, crosswalk row, or
  baseline metric produces a named FAIL and a nonzero exit (verified).
- **No agency-restricted data** — Chicago Sketch and Sioux Falls are public
  benchmarks; the ARC fixture is derived from the public ARC GMNS case bundled
  in this repository.

## Where it runs in CI

`.github/workflows/selfdemo.yml`: contract tests + the installed-wheel Chicago
demo on Ubuntu/Windows/macOS for every PR; the ARC Superzone job on main
pushes, a weekly schedule, and manual dispatch. `wheels.yml` runs the
installed-wheel self-demo as a **release gate** — publication depends on it.
The pre-tag requirement is `python scripts/release_smoke.py --full`
(see RELEASE.md).
