# Route Output User Guide (CR-0015)

How to produce, configure, and consume TAPLite path/route output — written
so that an AI agent or a new user can operate it without reading the kernel
source. Companion documents:
- `ROUTE_POOL_BINARY_FORMAT.md` — exact byte-level schema of route_pool.bin
- `docs/changes/CR-0015-route-output-binary.md` — change record

## 1. Configuration (settings.csv)

One row, CSV. The relevant fields:

| field | values | meaning |
|---|---|---|
| `route_output` | 0 | no route output (fastest; no path store is allocated) |
| | 1 | `route_assignment.csv`, legacy full CSV. On networks with >= 1000 zones a volume floor drops OD pairs with volume < `TAPLITE_ROUTE_VOL_MIN` (env var, default 1.0); their volume goes to link `background_volume`. |
| | 2 | CSV with the volume floor applied on EVERY network size (small networks too) |
| | 3 | `route_pool.bin` binary, FULL coverage (no floor), kernel read-back self-test |
| `number_of_iterations` | int | FW iterations. **Pipeline development: use 1-2** (path pool is schema-complete; equilibrium quality is not the point). Production baselines: full iterations. |

Environment variable: `TAPLITE_ROUTE_VOL_MIN` (float, default 1.0) — the
CSV volume floor for levels 1 (>=1000 zones) and 2 (always).

## 2. Cost model — what to expect

Enabling any route output (level >= 1) allocates the 5D path store and makes
each assignment iteration substantially more expensive (regional NVTA PM,
49k links / 3.9k zones / 6 classes, 16 cores: ~15 s/iteration without the
store vs ~5.5 min/iteration with it, plus ~12 s store allocation). This is
the path STORAGE cost, not the output-format cost. Hence the frozen
workflow:

    fast data-producing run: number_of_iterations=2, route_output=3
    production numbers run:  full iterations, route_output=0
    (two runs; the tensor layer reconciles them)

## 3. Outputs

| level | file | notes |
|---|---|---|
| 1, 2 | `route_assignment.csv` | header: mode,route_id,o_zone_id,d_zone_id,unique_route_id,prob,node_ids,link_ids,distance_mile,total_distance_km,total_free_flow_travel_time,total_travel_time,route_key,seed_od_volume,target_od_volume,final_est_od_volume,volume — `link_ids`/`node_ids` are `;`-separated external ids |
| 3 | `route_pool.bin` | binary; see ROUTE_POOL_BINARY_FORMAT.md; the run log MUST show `route_pool binary: N records -> route_pool.bin | read-back self-test PASS` — treat anything else as a failed run |

## 4. Consuming (AI/tooling checklist)

1. Prefer level 3. Parse per ROUTE_POOL_BINARY_FORMAT.md (Python reference
   reader included there); reject on magic/version/link-entry-count mismatch.
2. Rebuild the three objects: q (OD demand: Σ volume per mode,o,d), f (path
   flows), A (link-path incidence from the external link-id sequences).
3. Verify BEFORE using: `A·f` must equal link_performance.csv `volume`
   (level 3: exact; level 1 on big networks: only up to the volume floor —
   the missing part sits in `background_volume`).
4. `prob` is the path share within its OD x mode; Σ per OD ≈ 1. Never
   re-normalize silently.
5. Departure-time expansion (OpenDTA): λ_p(t) = volume · g_p(t),
   Σ_t g_p(t) = 1; enforce Σ_t u = volume as a hard gate.

## 5. Data schema quick reference

    q[mode, o_zone, d_zone]  veh/period    = Σ pool volume over records
    f[path]                  veh/period    = record volume
    A[link, path]            0/1           from link_ext_ids sequences
    B[path, od]              share         = volume / q of its OD
    identities: f = B·q (columns sum to 1) ;  x = A·f = A·B·q

Units: volumes are vehicles per assignment period (settings
demand_period_starting/ending_hours); link ids join to link.csv `link_id`;
zone ids are external (zone_id in node.csv); mode index order follows
mode_type.csv (1-based).

## 6. Worked example (4-node network)

    settings.csv: ...,route_output=3,...   ->  run TAPLite
    log: route_pool binary: 2 records -> route_pool.bin | read-back
         self-test PASS (max per-link |dv| = 0.00e+00)
    reader: rec0 = (mode 1, o 1, d 2, prob 0.219, vol 3062.5, links (2,4))
            rec1 = (mode 1, o 1, d 2, prob 0.781, vol 10937.5, links (1,3))
    Σ volume = 14000 = the OD demand.  A·f reproduces link volumes exactly.
