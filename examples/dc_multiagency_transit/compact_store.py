"""Compressed schedule contract: factorize the time-expanded schedule into

  run_profiles      (profile_id, pattern_id, stop_ns_ids[], offsets_s[])
  frequency_blocks  (pattern_id, profile_id, start_s, headway_s, n_trips)
  exceptions        (trip_ns_id, pattern_id, profile_id, t0_s)  -- singletons

Everything else (per-trip stop_times, the event graph) is REGENERATED, not
stored. Compression is only accepted if reconstruction is LOSSLESS: the
round-trip must reproduce Stage B's stop_visits departure/arrival seconds
exactly, else the script fails.

Run:  python compact_store.py
"""
import json
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
B = os.path.join(HERE, "build_0_2", "stageB")
OUT = os.path.join(HERE, "build_0_2", "compact")
os.makedirs(OUT, exist_ok=True)


def main(stageB_dir=None, out_dir=None):
    global B, OUT
    if stageB_dir:
        B, OUT = stageB_dir, out_dir
        os.makedirs(OUT, exist_ok=True)
    sv = pd.read_parquet(os.path.join(B, "stop_visits.parquet"))
    sv = sv.sort_values(["trip_ns_id", "stop_sequence"])
    first = sv.groupby("trip_ns_id").departure_seconds.transform("first")
    sv["dep_off"] = sv.departure_seconds - first
    sv["arr_off"] = sv.arrival_seconds - first

    trips = sv.groupby("trip_ns_id").agg(
        pattern_id=("service_pattern_id", "first"),
        t0=("departure_seconds", "first"),
        stops=("stop_ns_id", tuple),
        dep=("dep_off", tuple), arr=("arr_off", tuple)).reset_index()

    # profiles: distinct (pattern, stop seq, offset vectors)
    key = trips[["pattern_id", "stops", "dep", "arr"]].apply(tuple, axis=1)
    trips["profile_key"] = key
    profs = (trips.drop_duplicates("profile_key")
             .reset_index(drop=True).reset_index()
             .rename(columns={"index": "profile_id"}))
    trips = trips.merge(profs[["profile_key", "profile_id"]], on="profile_key")

    # frequency blocks: consecutive equal headways within (pattern, profile)
    blocks, exceptions = [], []
    for (pat, pid), g in trips.groupby(["pattern_id", "profile_id"]):
        t0s = np.sort(g.t0.to_numpy())
        ids = g.sort_values("t0").trip_ns_id.to_numpy()
        i = 0
        while i < len(t0s):
            j = i + 1
            if j < len(t0s):
                h = t0s[j] - t0s[i]
                while j + 1 < len(t0s) and t0s[j + 1] - t0s[j] == h:
                    j += 1
            if j - i >= 2:                      # a real frequency run (>=3 deps)
                blocks.append({"pattern_id": pat, "profile_id": pid,
                               "start_s": int(t0s[i]),
                               "headway_s": int(t0s[i + 1] - t0s[i]),
                               "n_trips": int(j - i + 1),
                               "trip_ids": ";".join(ids[i:j + 1])})
                i = j + 1
            else:
                exceptions.append({"trip_ns_id": ids[i], "pattern_id": pat,
                                   "profile_id": pid, "t0_s": int(t0s[i])})
                i += 1

    pd.DataFrame(profs[["profile_id", "pattern_id"]]).assign(
        stops=profs.stops.map(list), dep_off=profs.dep.map(list),
        arr_off=profs.arr.map(list)).to_parquet(
        os.path.join(OUT, "run_profiles.parquet"), compression="zstd")
    pd.DataFrame(blocks, columns=["pattern_id", "profile_id", "start_s",
                                  "headway_s", "n_trips", "trip_ids"]
                 ).to_parquet(
        os.path.join(OUT, "frequency_blocks.parquet"), compression="zstd")
    pd.DataFrame(exceptions, columns=["trip_ns_id", "pattern_id",
                                      "profile_id", "t0_s"]).to_parquet(
        os.path.join(OUT, "exceptions.parquet"), compression="zstd")

    # ---- lossless round-trip check ----
    rp = pd.read_parquet(os.path.join(OUT, "run_profiles.parquet"))
    fb = pd.read_parquet(os.path.join(OUT, "frequency_blocks.parquet"))
    ex = pd.read_parquet(os.path.join(OUT, "exceptions.parquet"))
    pinfo = {r.profile_id: r for r in rp.itertuples()}
    rows = []
    def emit(trip_id, pid, t0):
        p = pinfo[pid]
        for s, d_off, a_off in zip(p.stops, p.dep_off, p.arr_off):
            rows.append((trip_id, s, t0 + d_off, t0 + a_off))
    for b in fb.itertuples():
        for k, tid in enumerate(b.trip_ids.split(";")):
            emit(tid, b.profile_id, b.start_s + k * b.headway_s)
    for e in ex.itertuples():
        emit(e.trip_ns_id, e.profile_id, e.t0_s)
    rec = pd.DataFrame(rows, columns=["trip_ns_id", "stop_ns_id",
                                      "departure_seconds", "arrival_seconds"])
    ref = sv[["trip_ns_id", "stop_ns_id", "departure_seconds",
              "arrival_seconds"]].reset_index(drop=True)
    a = ref.sort_values(["trip_ns_id", "departure_seconds", "stop_ns_id"]).reset_index(drop=True)
    b_ = rec.sort_values(["trip_ns_id", "departure_seconds", "stop_ns_id"]).reset_index(drop=True)
    lossless = a.equals(b_.astype(a.dtypes.to_dict()))
    if not lossless:
        raise SystemExit("ROUND-TRIP MISMATCH — compression rejected")

    size = lambda p: os.path.getsize(p)
    orig = sum(size(os.path.join(B, f)) for f in
               ("stop_visits.parquet", "trips.parquet",
                "service_patterns.parquet"))
    comp = sum(size(os.path.join(OUT, f)) for f in os.listdir(OUT))
    rep = {"trips": int(len(trips)), "stop_visits": int(len(sv)),
           "patterns": int(trips.pattern_id.nunique()),
           "run_profiles": int(len(profs)),
           "frequency_blocks": int(len(fb)),
           "block_covered_trips": int(fb.n_trips.sum()),
           "exception_trips": int(len(ex)),
           "roundtrip_lossless": True,
           "stageB_bytes": orig, "compact_bytes": comp,
           "ratio": round(orig / comp, 2)}
    with open(os.path.join(OUT, "compact_manifest.json"), "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    else:
        main()
