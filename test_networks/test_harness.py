import os
"""
test_harness.py
---------------
Validate the TAPLite/DTALite engine on the two SMALL multimodal test networks
built by build_multimodal.py, BEFORE running the huge NVTA model.

For each network (sf_multimodal, cs_multimodal) and each iteration count
(1, 10, 20):
  - copy settings_<n>iter.csv -> settings.csv
  - run DTALite.assignment() *in a fresh subprocess* (IMPORTANT: the DTALite DLL
    keeps global link-volume state between assignment() calls in the SAME Python
    process, so volumes ACCUMULATE if you call it repeatedly in one process.
    Each run must be isolated in its own process to get correct results.)
  - read link_performance.csv (renamed to lp_<net>_<n>iter.csv to preserve it)

Then:
  (a) join link_performance back to the INPUT link.csv on (from_node_id,
      to_node_id). The engine RESEQUENCES link_id to 1..N internal order, so the
      output link_id does NOT match the input link_id -- always join on (from,to).
  (b) allowed_use enforcement: for each restricted link, verify the disallowed
      modes carry ZERO volume (PASS/FAIL per link). Also report whether ALLOWED
      modes actually USE the link (so the test is not vacuous).
  (c) per-mode total link volume + sample link travel_times.
  (d) Frank-Wolfe convergence: total link volume / VMT and max per-link volume
      change across 1 vs 10 vs 20 iterations.

Run:  python test_harness.py
"""
import os
import sys
import shutil
import subprocess
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
MODES = ["sov", "hov2", "hov3", "com", "trk", "apv"]

ALL = set(MODES)
SF_DISALLOWED = {
    26: ALL - {"hov2", "hov3"},   # HOV-only (most-used bottleneck)
    25: ALL - {"hov2", "hov3"},
    30: {"trk"},                  # no truck
    51: {"trk"},
    43: ALL - {"apv"},            # apv-only
    33: ALL,                      # closed
    36: ALL,
}
CS_DISALLOWED = {
    1084: ALL - {"hov2", "hov3"},  # HOV-only (busy 563-564 corridor)
    1081: ALL - {"hov2", "hov3"},
    1009: {"trk"},                 # no truck
    1079: {"trk"},
    1087: ALL - {"apv"},           # apv-only
    2822: ALL,                     # closed
}
NETS = [
    ("sf_multimodal", SF_DISALLOWED),
    ("cs_multimodal", CS_DISALLOWED),
]


def run_one(folder, n_iter):
    """Run DTALite.assignment() in a FRESH subprocess (state isolation) and
    return the link_performance dataframe."""
    shutil.copyfile(os.path.join(folder, f"settings_{n_iter}iter.csv"),
                    os.path.join(folder, "settings.csv"))
    code = (
        "import os, DTALite\n"
        f"os.chdir(r'{folder}')\n"
        "DTALite.assignment()\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    src = os.path.join(folder, "link_performance.csv")
    dst = os.path.join(folder, f"lp_{n_iter}iter.csv")
    shutil.copyfile(src, dst)
    lp = pd.read_csv(dst)
    lp.columns = [c.strip() for c in lp.columns]
    return lp


def join_to_input(lp, folder):
    link = pd.read_csv(os.path.join(folder, "link.csv"))
    cols = ["link_id", "from_node_id", "to_node_id", "allowed_use"]
    return lp.merge(link[cols], on=["from_node_id", "to_node_id"],
                    how="left", suffixes=("_out", "_in"))


def build_baseline(net):
    """Build (and assign) an UNRESTRICTED copy of the network so we can measure
    how much volume each restriction displaces. A restriction is non-vacuous if
    it changed the link's volume vs this baseline. Returns dict link_id->volume."""
    import build_multimodal as bm
    base = bm.BASE_SF if net == "sf_multimodal" else bm.BASE_CS
    short = "sf" if net == "sf_multimodal" else "cs"
    tmp = os.path.join(ROOT, f"{net}_baseline_tmp")
    bm.build(base, tmp, short, {})  # empty restriction set = all links open
    lp = run_one(tmp, 20)
    j = join_to_input(lp, tmp)
    vols = {int(r.link_id_in): float(r.volume)
            for r in j.dropna(subset=["link_id_in"]).itertuples()}
    shutil.rmtree(tmp, ignore_errors=True)
    return vols


def check_enforcement(j, disallowed, baseline):
    """Returns list of dicts. status PASS iff disallowed modes carry 0 volume.
    `bites` is True if the link's total volume differs materially from the
    unrestricted baseline (proves the restriction is NOT vacuous)."""
    results = []
    for lid, dis in sorted(disallowed.items()):
        rows = j[j["link_id_in"] == lid]
        base_v = baseline.get(lid, float("nan"))
        if rows.empty:
            results.append(dict(lid=lid, au="?", status="MISSING",
                                detail="link not found", allowed_vol=0.0,
                                vol=0.0, base=base_v, bites=False))
            continue
        row = rows.iloc[0]
        au = str(row["allowed_use"])
        allowed = ALL - dis
        bad = [f"{m}={float(row.get(f'mod_vol_{m}',0.0)):.2f}"
               for m in dis if float(row.get(f"mod_vol_{m}", 0.0)) > 1e-6]
        allowed_vol = sum(float(row.get(f"mod_vol_{m}", 0.0)) for m in allowed)
        vol = float(row["volume"])
        status = "PASS" if not bad else "FAIL"
        detail = "zero for disallowed" if not bad else "NONZERO: " + ", ".join(bad)
        # non-vacuous if total link volume moved >= 1% of baseline (or baseline
        # was nonzero and link now near-zero, i.e. volume was displaced off it)
        bites = (not pd.isna(base_v) and base_v > 1.0
                 and abs(vol - base_v) > 0.01 * base_v)
        results.append(dict(lid=lid, au=au, status=status, detail=detail,
                            allowed_vol=allowed_vol, vol=vol, base=base_v,
                            bites=bites))
    return results


def main():
    summary = {}
    for net, disallowed in NETS:
        folder = os.path.join(ROOT, net)
        print("\n" + "=" * 78)
        print(f"NETWORK: {net}")
        print("=" * 78)
        per_iter = {}
        for n_iter in (1, 10, 20):
            lp = run_one(folder, n_iter)
            j = join_to_input(lp, folder)
            per_iter[n_iter] = j
            print(f"  ran {n_iter:2d} iter -> {len(lp)} links, "
                  f"total link volume={j['volume'].sum():,.0f}, "
                  f"VMT(veh-dist)={j['VMT'].sum():,.0f}")

        j20 = per_iter[20]
        print("\n  Per-mode total link volume (20 iter):")
        mode_tot = {}
        for m in MODES:
            col = f"mod_vol_{m}"
            tot = j20[col].sum() if col in j20 else 0.0
            mode_tot[m] = tot
            print(f"    {col:14s} = {tot:,.1f}")
        print(f"    {'volume(total)':14s} = {j20['volume'].sum():,.1f}")

        print("\n  building unrestricted baseline to measure displacement...")
        baseline = build_baseline(net)

        print("\n  allowed_use enforcement (20 iter), joined on (from,to):")
        print("    (PASS = disallowed modes carry 0; BITES = link volume moved "
              "vs unrestricted baseline => restriction is not vacuous)")
        enf = check_enforcement(j20, disallowed, baseline)
        n_fail = sum(1 for e in enf if e["status"] != "PASS")
        for e in enf:
            bite = "BITES" if e["bites"] else "no-change"
            print(f"    link {e['lid']:5d}  use='{e['au']:25s}' [{e['status']}] "
                  f"{e['detail']}; vol={e['vol']:,.1f} (baseline={e['base']:,.1f}) "
                  f"[{bite}]  allowed-mode vol={e['allowed_vol']:,.1f}")

        print("\n  Sample link travel_time (input link_id -> tt @ 1/10/20 iter):")
        sample_ids = [lid for lid in sorted(disallowed)][:3]
        busy = j20.sort_values("volume", ascending=False)
        for lid in busy["link_id_in"].dropna().astype(int).head(4):
            if lid not in sample_ids:
                sample_ids.append(int(lid))
        for lid in sample_ids[:6]:
            tts = []
            for n_iter in (1, 10, 20):
                rr = per_iter[n_iter][per_iter[n_iter]["link_id_in"] == lid]
                tts.append(rr["travel_time"].iloc[0] if not rr.empty else float("nan"))
            print(f"    link {lid:5d}: {tts[0]:9.3f} -> {tts[1]:9.3f} -> {tts[2]:9.3f}")

        print("\n  Frank-Wolfe convergence:")
        def vmt(n):
            return per_iter[n]["VMT"].sum()
        v1, v10, v20 = vmt(1), vmt(10), vmt(20)
        print(f"    total VMT:  1iter={v1:,.0f}  10iter={v10:,.0f}  20iter={v20:,.0f}")

        def maxchg(a, b):
            key = ["from_node_id", "to_node_id"]
            m = per_iter[a][key + ["volume"]].merge(
                per_iter[b][key + ["volume"]], on=key, suffixes=("_a", "_b"))
            return (m["volume_b"] - m["volume_a"]).abs().max()
        d_1_10 = maxchg(1, 10)
        d_10_20 = maxchg(10, 20)
        print(f"    max |dVolume| 1->10  = {d_1_10:,.2f}")
        print(f"    max |dVolume| 10->20 = {d_10_20:,.2f}  "
              f"(should be << the 1->10 change as FW converges)")
        rel = (abs(v20 - v10) / v10 * 100) if v10 else float("nan")
        print(f"    |VMT 20 - VMT 10| / VMT10 = {rel:.2f}%")

        summary[net] = dict(mode_tot=mode_tot, enf=enf, n_fail=n_fail,
                            v1=v1, v10=v10, v20=v20,
                            d_1_10=d_1_10, d_10_20=d_10_20)

    print("\n" + "#" * 78)
    print("SUMMARY")
    print("#" * 78)
    for net, s in summary.items():
        print(f"\n{net}:")
        print("  per-mode total volume:",
              {m: round(v, 1) for m, v in s["mode_tot"].items()})
        n_bite = sum(1 for e in s["enf"] if e["bites"])
        print(f"  allowed_use: {len(s['enf'])} restricted links, "
              f"{s['n_fail']} FAIL, {n_bite}/{len(s['enf'])} bite "
              f"(volume moved vs baseline)")
        print(f"  VMT 1/10/20 = {s['v1']:,.0f} / {s['v10']:,.0f} / {s['v20']:,.0f}")
        print(f"  max dVol 1->10 = {s['d_1_10']:,.1f} ; 10->20 = {s['d_10_20']:,.1f}")
    allpass = all(s["n_fail"] == 0 for s in summary.values())
    allbite = all(e["bites"] for s in summary.values() for e in s["enf"])
    print(f"\nOVERALL allowed_use enforcement: "
          f"{'ALL PASS' if allpass else 'FAILURES PRESENT'}")
    print(f"OVERALL restrictions non-vacuous (all bite): "
          f"{'YES' if allbite else 'NO - some links unchanged vs baseline'}")


if __name__ == "__main__":
    main()
