"""L3 trade-off analysis: same-gap compute-time comparison + 2-panel figure.

Curves (per network, all on the SAME perturbed demand):
  cold FW          : per-iteration TRUE gap trace; compute = 'elapsed' printed at
                     each gap line (window starts at the kernel compute timer).
  warm replay + FW : warm_start_columns, 0 sweeps, then FW; compute = elapsed
                     minus the printed DTAC-load time (load is SETUP). Includes
                     the mandatory fresh-SP gap audit (intrinsic to the mode).
  warm + GP sweeps : replay runs with column_adjust_sweeps=k (k=1,2,3,5,8);
                     gap point = the FINAL TRUE gap of each run; compute =
                     scatter time + cumulative sweep seconds (the fresh-SP gap
                     audit is excluded -- it is a report, not solver work).
Crossing times use the best-so-far (running-min) gap trace, log-linear
interpolation between the bracketing points.
"""
import os, re, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import os as _os
# Root holding the trace-run folders (scag_t_*/cs_t_*, each with run.log) and
# the output dir for the PNGs. Override via env for reruns.
S = _os.environ.get("L3_RUN_ROOT", ".")
DOCS = _os.environ.get("L3_DOCS_DIR", "docs")

RE_ITER = re.compile(r"iter No = (\d+).*?gap = ([\d.eE+-]+) %, elapsed = ([\d.]+) s")
RE_LOAD = re.compile(r"DTAC column load \+ pool build \(SETUP\) = ([\d.]+) s")
RE_SCAT = re.compile(r"column scatter \+ uncovered one-shot AoN \(COMPUTE\) = ([\d.]+) s")
RE_SWEEP = re.compile(r"column_adjust sweep (\d+): .*?([\d.]+) % -> ([\d.]+) %.*?, ([\d.]+) s\s*$", re.M)
RE_BOTH = re.compile(r"RESTRICTED gap \(STORED paths only, NOT an equilibrium claim\) = ([\d.eE+-]+) %; TRUE relative gap [^=]*= ([\d.eE+-]+) %")


def read(p):
    with open(p, errors="replace") as f:
        return f.read()


def fw_trace(run_dir, warm):
    """[(compute_s, gap_pct, iter_no)] from per-iteration prints."""
    txt = read(os.path.join(run_dir, "run.log"))
    load = float(RE_LOAD.search(txt).group(1)) if warm and RE_LOAD.search(txt) else 0.0
    out = []
    for m in RE_ITER.finditer(txt):
        it, gap, el = int(m.group(1)), float(m.group(2)), float(m.group(3))
        out.append((el - load, gap, it))
    return out


def sweep_points(dirs_by_k):
    """[(compute_s, true_gap_pct, k)] one point per sweeps=k replay run,
    plus the k=0 scatter-only point from the smallest-k run's sweep-1 'before' gap
    (== restricted gap at load; equals the replay TRUE gap to ~1e-4 abs)."""
    pts = []
    k0 = None
    for k, d in sorted(dirs_by_k.items()):
        txt = read(os.path.join(d, "run.log"))
        scat = float(RE_SCAT.search(txt).group(1))
        sweeps = [(int(m.group(1)), float(m.group(4)), float(m.group(2)))
                  for m in RE_SWEEP.finditer(txt)]
        t = scat + sum(sec for _, sec, _ in sweeps)
        both = RE_BOTH.search(txt)
        true_gap = float(both.group(2))
        pts.append((t, true_gap, k))
        if k0 is None and sweeps:
            k0 = (scat, sweeps[0][2], 0)   # restricted gap before sweep 1 ~= true gap at load
    if k0:
        pts.insert(0, k0)
    return pts


def best_so_far(trace):
    out, best = [], float("inf")
    for t, g, n in trace:
        best = min(best, g)
        out.append((t, best, n))
    return out


def cross_time(trace, target):
    """first MEASURED point (iteration/sweep boundary -- they are atomic units of
    work, so no interpolation inside one) where the gap is <= target."""
    for t, g, n in best_so_far(trace):
        if g <= target:
            return t, n
    return None, None


def analyze(name, cold_dir, warm0_dir, sweep_dirs, targets, png):
    cold = fw_trace(cold_dir, warm=False)
    warm = fw_trace(warm0_dir, warm=True)
    swp = sweep_points(sweep_dirs)

    rows = []
    for tgt in targets:
        tc, nc = cross_time(cold, tgt)
        tw, nw = cross_time(warm, tgt)
        ts, ns = cross_time(swp, tgt)
        rows.append((tgt, tc, nc, tw, nw, ts, ns))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 5.0))
    for ax, xk in ((ax1, 0), (ax2, 2)):
        ax.semilogy([p[xk] for p in cold], [p[1] for p in cold],
                    "-o", ms=3, color="#1f77b4", label="cold FW")
        ax.semilogy([p[xk] for p in warm], [p[1] for p in warm],
                    "-s", ms=3, color="#2ca02c", label="warm replay + FW")
        ax.semilogy([p[xk] for p in swp], [p[1] for p in swp],
                    "-^", ms=6, color="#d62728", label="warm + GP sweeps")
        for tgt in targets:
            ax.axhline(tgt, color="gray", ls="--", lw=0.8)
            ax.text(ax.get_xlim()[1], tgt, f" {tgt}%", va="center", fontsize=8, color="gray")
        ax.grid(True, which="both", alpha=0.25)
        ax.set_ylabel("TRUE relative gap (%)")
    ax1.set_xlabel("cumulative COMPUTE seconds (setup/DTAC load excluded)")
    ax2.set_xlabel("FW iteration / GP sweep count")
    ax1.legend()
    fig.suptitle(f"{name}: perturbed demand (+5% x 1,000 OD cells) -- same-gap trade-off\n"
                 "cold FW & warm+FW traces = per-iteration TRUE gap; GP-sweep points = final TRUE gap per sweeps=k replay run "
                 "(sweep-time axis excludes the fresh-SP gap audit)", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(png, dpi=140)
    print(f"wrote {png}")

    print(f"\n{name}: compute seconds to reach TRUE gap target "
          f"(setup + DTAC load excluded; n = iterations or sweeps)")
    print(f"{'target':>8} | {'cold FW':>16} | {'warm replay+FW':>16} | {'warm+GP sweeps':>16} | speedup (cold/best-warm)")
    for tgt, tc, nc, tw, nw, ts, ns in rows:
        def fmt(t, n, unit):
            return f"{t:8.1f}s @{n:>3}{unit}" if t is not None else "  not reached  "
        best = min([x for x in (tw, ts) if x is not None], default=None)
        sp = f"{tc / best:6.1f}x" if (tc and best) else "   --"
        print(f"{tgt:>7}% | {fmt(tc, nc, 'it')} | {fmt(tw, nw, 'it')} | {fmt(ts, ns, 'sw')} | {sp}")
    return rows


if __name__ == "__main__":
    targets = [0.10, 0.05, 0.02, 0.01]
    net = sys.argv[1] if len(sys.argv) > 1 else "both"
    if net in ("scag", "both"):
        analyze("SCAG RTP24 AM (246,806 links, 342,712 OD cells)",
                S + "/scag_t_cold", S + "/scag_t_warm0",
                {k: S + f"/scag_t_sw{k}" for k in (1, 2, 3, 5, 8)},
                targets, os.path.join(DOCS, "l3_tradeoff_scag.png"))
    if net in ("sketch", "both"):
        analyze("Chicago Sketch (2,950 links, 93,513 OD cells)",
                S + "/cs_t_cold", S + "/cs_t_warm0",
                {k: S + f"/cs_t_sw{k}" for k in (1, 2, 3, 5, 8)},
                targets, os.path.join(DOCS, "l3_tradeoff_sketch.png"))
