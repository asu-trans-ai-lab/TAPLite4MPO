# route_pool.bin — Binary Route/Column Pool Format (v1)

**For OpenDTA and any downstream consumer.** Written by TAPLite when
`route_output = 3` (settings.csv). Full path coverage — unlike the CSV
levels, NO volume floor is applied, so the tensor identity
`link_volume = Σ paths-through-link path_volume` holds exactly. The kernel
verifies this itself: after writing, it re-reads the file and re-accumulates
per-link volumes (read-back self-test; the run log prints
`route_pool binary: N records ... self-test PASS`).

All integers and floats are **little-endian**. No alignment padding.

## Layout

    HEADER — 24 bytes
      offset 0   u32   magic     = 0x52504154  (ASCII 'TAPR' read as LE u32)
      offset 4   u32   version   = 1
      offset 8   u64   n_records
      offset 16  u64   total_link_entries   (sum of n_links over all records
                                             — integrity check on read)

    RECORD — repeated n_records times
      i32   mode        (1-based mode index; order matches mode_type.csv)
      i32   o_zone_id   (external zone id)
      i32   d_zone_id   (external zone id)
      f64   prob        (path share within this OD x mode; Σ over the OD ≈ 1)
      f64   volume      (path flow, vehicles for the assignment period)
      i32   n_links
      i32 x n_links     external link ids (order = traversal order,
                        origin -> destination; join to link.csv link_id)

## Semantics

- One record = one unique path (deduplicated by node/link checksum).
- `volume = od_volume x prob` at the final assignment state.
- Departure-time expansion for DNL: λ_p(t) = volume x g_p(t) with
  Σ_t g_p(t) = 1 — the profile g is NOT stored here; it comes from the
  departure-profile contract. Temporal conservation Σ_t u = volume is the
  consumer's gate.
- OD demand recovery: q(mode,o,d) = Σ records volume. Link volume recovery:
  x(l) = Σ records containing l volume. Both must reproduce the run's
  link_performance.csv volumes (full coverage, level 3 only).

## Reference readers

Python (numpy-free, stdlib only):

```python
import struct

def read_route_pool(fn):
    with open(fn, "rb") as f:
        magic, ver = struct.unpack("<II", f.read(8))
        assert magic == 0x52504154 and ver == 1
        n, total_links = struct.unpack("<QQ", f.read(16))
        seen = 0
        for _ in range(n):
            mode, o, d = struct.unpack("<iii", f.read(12))
            prob, vol = struct.unpack("<dd", f.read(16))
            (nl,) = struct.unpack("<i", f.read(4))
            links = struct.unpack(f"<{nl}i", f.read(4 * nl))
            seen += nl
            yield mode, o, d, prob, vol, links
        assert seen == total_links, "corrupt file: link-entry count mismatch"
```

C++ (matches the kernel's own reader):

```cpp
struct RoutePoolRecord {
    int mode, o_zone, d_zone;
    double prob, volume;
    std::vector<int> link_ext_ids;
};
// see ReadRoutePool() in TAPLite.cpp — 24-byte header, then per record:
// 3 x i32, 2 x f64, i32 n_links, n_links x i32. Reject the file unless
// magic/version match AND the accumulated link-entry count equals the
// header's total_link_entries.
```

## Consumer checklist (OpenDTA)

1. Verify magic/version/link-entry total (reject, never guess).
2. Rebuild q, x from the pool; cross-check x against link_performance.csv.
3. Apply departure profiles with Σ_t u_kt = f_k conservation gate.
4. Never re-normalize prob silently — Σ prob per OD should already be ~1;
   a violation is a producer bug to report, not to patch.

## route_output levels (settings.csv)

    0 = off
    1 = full CSV route_assignment.csv (legacy; on networks >= 1000 zones a
        volume floor TAPLITE_ROUTE_VOL_MIN, default 1.0, drops small-OD
        paths into background_volume)
    2 = CSV with the volume floor applied on EVERY network size
    3 = route_pool.bin binary, full coverage, kernel read-back self-test
