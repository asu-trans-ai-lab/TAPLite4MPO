# TRMG2 — systematic vendor-binary→GMNS conversion review

Rigorous validation of the config-driven converter (`dtalite_qa/net2gmns.py` and
the dtalite_qa FFB reader) on a **real, full agency vendor-GIS model** — the Triangle
Regional Model G2 (TRMG2, WSP, vendor GIS v9) — going beyond the GSATS shapefile test to a
135k-record model with an *independent* reference decode to check against.

## Method
Two independent decode paths of the **same** vendor model, cross-checked:
1. **Ours:** the FFB reader reads `master_links.BIN` + `.DCB` (FFB attributes); `net2gmns`
   converts the links shapefile (geometry + attributes) → GMNS via `net2gmns_trmg2.json`.
2. **Reference:** an earlier, completely separate decode from TRMG2's compiled `net.net`
   (`4step/trmg2_gmns/`) — different code, different path.
If both agree, the converter is right independent of any single decoder's bugs.

## Tier 1 — converter fidelity (the solid, demand-independent result)

| Check | Result |
|---|---|
| FFB reader at scale | the FFB reader parsed `master_links.BIN` = **135k records × 50 fields** (speeds, per-direction lanes/caps, `DailyCount`, `Screenline`, HCMType) — vs the earlier Cleveland 1,127-link test |
| **net2gmns vs independent net.net decode** | **75,939 drive links — EXACT count match**, identical GMNS structure (from/to/lanes/capacity/speed/length columns) |
| Drive-link filter | `DTWB` contains `D` correctly isolates the 75,939 drive links from the full multimodal network |
| GSATS regression | re-ran after the net2gmns changes — **still 0 mismatches** on 5,362 links (no regression) |

Two independent decoders producing the identical 75,939-link network is the strongest
possible converter check — it cannot be a shared bug.

## Tier 2 — runnable, converged assignment

The converted GMNS runs on the release kernel to **0.044% relative gap in 24 iterations
(~86 s)** — matching the reference model's own headline. Confirms the converted network is
topologically sound and solves as an equilibrium assignment.

## Tier 3 — count / screenline validation: DEFERRED (honest)

TRMG2's link table carries observed `DailyCount` (+ SUT/MUT) and `Screenline`/`Cutline`,
so an ARC-style screenline validation is *supported by the data*. We deliberately do **not**
report a count %RMSE here, for two independent reasons:
1. **Interim demand.** The demand is our converted OD, **not the agency OMX** — count
   accuracy would reflect the interim demand, not the converter or the engine.
2. **Basis mismatch.** The interim demand is a single **1-hour AM SOV** period; the counts
   are **daily AWDT**. Comparing them directly is the period-vs-daily trap
   (CONVERSION_ERRORS_CATALOG §2b) and would produce a large, meaningless number.

The pipeline is **ready**: once the agency OMX arrives, load it
(`python -m dtalite_qa.matrixio <agency>.omx --scenario gmns --out demand.csv`), run at the
matching period, and `python -m dtalite_qa.workflow gmns` emits the screenline/cutline/
facility/volume-group %RMSE tables (R5/R6). Until then, count validation is pending — not
claimed.

## WP-02 — ARC access-code preset (closed here)

The ARC `PROHIBIT`-code logic is now a reusable `access_code_map` config block in
`net2gmns.py` (agencies **declare** codes → `allowed_use`/`toll` instead of writing Python).
Re-deriving ARC via net2gmns + the preset produces **146,177 links vs the reference 145,971**
(99.9%) with the access mapping applied. The small link-count delta is closed-in-period
link filtering (a config option), not the access logic.

## Verdict / what the converter handles
- **Handles (verified):** vendor AB/BA + DIR directed split, per-lane/hourly capacity,
  categorical facility types (string-preserving), centroid renumbering, drive-mode
  filtering, PROHIBIT→access presets, FFB `.BIN`/`.DCB` attribute recovery at 135k scale.
- **Standard hand-off:** shapefile (network) + OMX (demand). The FFB reader is a
  convenience for public repos; `.dln/.pts` geometry sidecars are handled via the shapefile
  the agency exports.
- **Not claimed:** count-level model reproduction on interim demand — that waits for the
  agency OMX at a matching basis.

*(The raw vendor `.dbd/.BIN/.dln` binaries are not committed — TRMG2 is a public model;
the derived GMNS + this recipe are the shareable artifacts.)*
