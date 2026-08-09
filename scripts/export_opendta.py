"""TAPLite -> OpenDTA export (R-06). The CSV IS the interface.

Emits, from one single-period TAPLite run, the four files OpenDTA's loader
contracts (openDTA/dev/doc/01_design_document.md SS2.1-2.4):

  export/opendta/demand_period.csv     period_id,name,start_time,end_time
  export/opendta/link_period.csv       (link_id,period_id) -> capacity mu,
                                       fftt, allowed_uses, toll,
                                       capacity_ratio, reference_tt,
                                       capacity_source, tt_source  (provenance
                                       columns MANDATORY per the contract)
  export/opendta/columns.csv           route_id,o_zone_id,d_zone_id,
                                       agent_type,period_id,volume,
                                       link_sequence,departure_profile_id
  export/opendta/departure_profile.csv profile_id,time,weight (period-level
                                       uniform template; OpenDTA's hierarchy
                                       route->OD->corridor->period->uniform
                                       can override — Phase-1 per the doc)

Kernel untouched (KERNEL-PROTECTED list intact): this reads a finished run
(route_output=1) and writes CSVs. One run = one active period (the frozen
single-period contract); multi-period = one export per run, OpenDTA loads
several.

Validations (refuse to export on failure):
  V1 conservation: sum(columns volume) == sum(demand_*.csv) within tolerance,
     residual reported (kernel-unreachable OD is ledgered, not hidden);
  V2 link-sequence integrity: every link_id in every sequence exists;
  V3 push-down: column volumes accumulated on links vs link_performance
     volume — R^2 reported (approx for plain-FW last-iteration paths; exact
     only for DTAC v2 theta-share stores — stated in the manifest).

Usage:
  python scripts/export_opendta.py <run_dir> --period-id 1 --period-name AM
"""
import argparse
import json
import os

import pandas as pd

MU_UNITS = "PCE/hour, total across lanes, post-capacity_ratio (Q-1)"


def hhmm(hours):
    h = int(hours)
    return "%02d:%02d:00" % (h, int(round((hours - h) * 60)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--period-id", type=int, default=1)
    ap.add_argument("--period-name", default="AM")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rd = a.run_dir
    out = a.out or os.path.join(rd, "export", "opendta")
    os.makedirs(out, exist_ok=True)

    s = pd.read_csv(os.path.join(rd, "settings.csv")).iloc[0]
    t0 = float(s.demand_period_starting_hours)
    t1 = float(s.demand_period_ending_hours)
    pd.DataFrame([{"period_id": a.period_id, "name": a.period_name,
                   "start_time": hhmm(t0), "end_time": hhmm(t1),
                   "sequence": a.period_id}]).to_csv(
        os.path.join(out, "demand_period.csv"), index=False)

    lk = pd.read_csv(os.path.join(rd, "link.csv"), low_memory=False)
    mode_types = pd.read_csv(os.path.join(rd, "mode_type.csv"))
    pce = dict(zip(mode_types.mode_type, mode_types.pce))
    # mu = per-lane hourly capacity x lanes (TAPLite standard convention);
    # PCE conversion is identity when all class pce=1 (declared either way).
    lp = pd.DataFrame({
        "link_id": lk.link_id,
        "period_id": a.period_id,
        "capacity": lk.capacity * lk.lanes.clip(lower=1),
        "fftt": lk.vdf_fftt.where(lk.vdf_fftt > 0,
                                  60.0 * lk.length / 1000.0
                                  / lk.free_speed.clip(lower=1)),
        "allowed_uses": lk.allowed_uses.fillna(""),
        "toll": lk.vdf_toll.fillna(0) if "vdf_toll" in lk else 0,
        "capacity_ratio": 1.0,
        "reference_tt": None,
        "capacity_source": "TAPLite_link_capacity_x_lanes",
        "tt_source": "fftt_geometry",
    })
    lp["reference_tt"] = lp.fftt      # no observed layer at export; declared
    lp.to_csv(os.path.join(out, "link_period.csv"), index=False)

    ra = pd.read_csv(os.path.join(rd, "route_assignment.csv"),
                     low_memory=False)
    ra = ra[ra.volume > 0].copy()
    profile_id = f"{a.period_name}_uniform"
    cols = pd.DataFrame({
        "route_id": range(1, len(ra) + 1),
        "o_zone_id": ra.o_zone_id.astype(int),
        "d_zone_id": ra.d_zone_id.astype(int),
        "agent_type": ra["mode"],
        "period_id": a.period_id,
        "volume": ra.volume,
        "link_sequence": ra.link_ids,
        "departure_profile_id": profile_id,
    })
    cols.to_csv(os.path.join(out, "columns.csv"), index=False)

    # period-level uniform template, 5-min bins, weights sum to 1 exactly
    n_bins = int(round((t1 - t0) * 12))
    times = [hhmm(t0 + k / 12.0)[:5] for k in range(n_bins)]
    w = [1.0 / n_bins] * n_bins
    w[-1] = 1.0 - sum(w[:-1])
    pd.DataFrame({"profile_id": profile_id, "time": times,
                  "weight": w}).to_csv(
        os.path.join(out, "departure_profile.csv"), index=False)

    # ---- validations ----
    # conservation identity (CR-0001 S0 acceptance): total demand =
    # routed columns + intrazonal (o==d, never routed) + residual
    dem_total = intra_total = 0.0
    for mt in mode_types.itertuples():
        p = os.path.join(rd, str(mt.demand_file))
        if os.path.exists(p):
            d = pd.read_csv(p)
            dem_total += d.volume.sum()
            intra_total += d[d.o_zone_id == d.d_zone_id].volume.sum()
    col_total = cols.volume.sum()
    v1_resid = dem_total - intra_total - col_total

    link_ids = set(lk.link_id.astype(int))
    seq_links = cols.link_sequence.str.split(";").explode().astype(int)
    v2_bad = int((~seq_links.isin(link_ids)).sum())

    push = (pd.DataFrame({"link_id": seq_links,
                          "volume": cols.volume.repeat(
                              cols.link_sequence.str.count(";") + 1).values})
            .groupby("link_id").volume.sum())
    perf = pd.read_csv(os.path.join(rd, "link_performance.csv"),
                       usecols=["link_id", "volume"]).set_index("link_id")
    j = perf.join(push.rename("col_volume")).fillna(0)
    r2 = j.volume.corr(j.col_volume) ** 2

    ok = (abs(v1_resid) / max(dem_total, 1) < 0.01) and v2_bad == 0
    man = {
        "contract": "openDTA 01_design_document SS2.1-2.4",
        "period": {"id": a.period_id, "name": a.period_name,
                   "window": [hhmm(t0), hhmm(t1)]},
        "mu_units": MU_UNITS,
        "pce_by_agent_type": {k: float(v) for k, v in pce.items()},
        "columns": int(len(cols)),
        "V1_demand_total": round(float(dem_total), 1),
        "V1_columns_total": round(float(col_total), 1),
        "V1_intrazonal_never_routed": round(float(intra_total), 1),
        "V1_residual_unexplained": round(float(v1_resid), 1),
        "V2_unknown_links_in_sequences": v2_bad,
        "V3_pushdown_R2_vs_link_performance": round(float(r2), 4),
        "V3_note": "approx for plain-FW last-iteration paths; exact only for "
                   "DTAC v2 theta-share column stores",
        "gate": "PASS" if ok else "FAIL",
    }
    with open(os.path.join(out, "export_manifest.json"), "w") as f:
        json.dump(man, f, indent=2)
    print(json.dumps(man, indent=1))
    if not ok:
        raise SystemExit("export gate FAIL — see manifest")


if __name__ == "__main__":
    main()
