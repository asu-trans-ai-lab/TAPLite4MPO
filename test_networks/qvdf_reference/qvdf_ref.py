#!/usr/bin/env python3
"""
Clean, transparent QVDF (Queue VDF / fluid-queue) reference.

Recomputes the per-link QVDF quantities from a GMNS link.csv plus the assigned
link volume, using EXACTLY the formulas in the kernel's Link_QueueVDF()
(kernel/src/TAPLite.cpp). It then diffs the recomputed period speed / DOC /
demand / travel time against the kernel's own link_performance.csv so we can
confirm the kernel matches its intended math (and see, in one place, what that
math is). The original Fluid_Queue_Approximation_v3.0.xlsx is the calibration
artifact; this is the minimal, readable restatement.

Usage:
    python qvdf_ref.py <case_dir>
where <case_dir> contains link.csv, settings.csv and a kernel-produced
link_performance.csv.
"""
import csv, math, sys, os


def fnum(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def read_settings(path):
    with open(path) as f:
        r = list(csv.DictReader(f))[0]
    h0 = fnum(r.get('demand_period_starting_hours'), 7)
    h1 = fnum(r.get('demand_period_ending_hours'), 8)
    return h0, h1


def qvdf_link(p, volume, H, t_start, t_end):
    """Mirror of Link_QueueVDF(). p = per-link params dict. Returns dict."""
    lanes   = fnum(p['lanes'], 1)
    lane_cap = fnum(p['capacity'], 1)          # capacity column is per-lane
    plf     = fnum(p.get('vdf_plf'), 1) or 1.0
    alpha   = fnum(p.get('vdf_alpha'), 0.15)
    beta    = fnum(p.get('vdf_beta'), 4)
    free_mph = fnum(p.get('vdf_free_speed_mph')) or (fnum(p['free_speed']) / 1.609)
    cutoff  = fnum(p.get('cutoff_speed')) or free_mph * 0.75
    length  = fnum(p.get('vdf_length_mi'), -1)
    if length < 0:
        length = fnum(p['length']) / 1609.0
    q_cp = fnum(p.get('vdf_cp'), 0.28125)
    q_cd = fnum(p.get('vdf_cd'), 1.0)
    q_n  = fnum(p.get('vdf_n'), 1.0)
    q_s  = fnum(p.get('vdf_s'), 4.0)
    fftt = length / max(0.001, free_mph) * 60.0

    incoming = volume / max(0.01, lanes) / max(0.001, H) / max(0.0001, plf)
    doc = incoming / max(0.1, lane_cap)

    cong_ref = cutoff if doc >= 1 else (1 - doc) * free_mph + doc * cutoff
    avg_queue_speed = cong_ref / (1.0 + alpha * doc ** beta)
    P = q_cd * doc ** q_n
    if P > H:
        avg_period_speed = avg_queue_speed
    else:
        avg_period_speed = P / H * avg_queue_speed + (1.0 - P / H) * (cong_ref + free_mph) / 2.0
    qvdf_tt = length / max(0.1, avg_period_speed) * 60.0

    vt2 = cutoff / max(0.001, q_cp * P ** q_s + 1.0)
    mu = min(lane_cap, incoming / max(0.01, P))
    RTT = length / max(0.01, cong_ref)
    wt2 = length / vt2 - RTT
    gamma = wt2 * 64 * mu / P ** 4 if P > 0 else 0.0

    return dict(D=incoming, doc=doc, P=P, fftt=fftt, vt2=vt2, mu=mu, gamma=gamma,
                cong_ref_speed=cong_ref, avg_queue_speed=avg_queue_speed,
                qvdf_period_speed=avg_period_speed, qvdf_tt=qvdf_tt,
                free_mph=free_mph, cutoff_mph=cutoff)


def main():
    case = sys.argv[1] if len(sys.argv) > 1 else '.'
    links = {r['link_id']: r for r in csv.DictReader(open(os.path.join(case, 'link.csv')))}
    H0, H1 = read_settings(os.path.join(case, 'settings.csv'))
    H = H1 - H0
    perf = list(csv.DictReader(open(os.path.join(case, 'link_performance.csv'))))

    print(f"case={case}  period {H0}-{H1} (H={H} h)")
    print(f"{'link':>5} {'volume':>10} | {'D ref':>9} {'D ker':>9} | "
          f"{'doc ref':>8} {'doc ker':>8} | {'spd ref':>8} {'spd ker':>8} | {'maxdiff':>8}")
    worst = 0.0
    for r in perf:
        ext_id = r['link_id']
        lk = links.get(ext_id)
        if lk is None:
            continue
        vol = fnum(r['volume'])
        ref = qvdf_link(lk, vol, H, H0, H1)
        D_k = fnum(r.get('D'));  doc_k = fnum(r.get('doc'))
        spd_k = fnum(r.get('speed_mph'))
        dmax = max(abs(ref['D'] - D_k), abs(ref['doc'] - doc_k),
                   abs(ref['qvdf_period_speed'] - spd_k))
        worst = max(worst, dmax)
        print(f"{ext_id:>5} {vol:10.1f} | {ref['D']:9.2f} {D_k:9.2f} | "
              f"{ref['doc']:8.4f} {doc_k:8.4f} | {ref['qvdf_period_speed']:8.3f} {spd_k:8.3f} | {dmax:8.2e}")
    print(f"\nworst abs diff (ref vs kernel) = {worst:.3e}")
    print("(speed compares the QVDF period speed; for vdf_type=2 the kernel's "
          "speed_mph IS the QVDF period speed, so it should match to ~1e-3.)")


if __name__ == '__main__':
    main()
