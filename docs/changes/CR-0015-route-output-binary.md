# CR-0015 (DRAFT) — Route output: binary format + thresholded levels

**Status:** DRAFT — awaiting owner approval · **Kernel change:** YES (output)

## Problem
`route_output` supports only 0/1. On a regional network (49k links, 3.9k
zones, 6 classes) route_assignment.csv is written as text: hundreds of MB,
minutes of wall time, and downstream consumers immediately re-encode it to
sparse binary anyway. Iterating on the flow-through-tensor layer pays the
full text cost every run.

## Proposed
1. `route_output` levels: 0=off · 1=full CSV (unchanged) ·
   2=CSV, only paths with volume ≥ threshold (`route_volume_min`, default
   1.0) · 3=binary only.
2. Binary format: `route_pool.bin` — header (magic, version, counts) +
   per-path records (mode, o, d, volume, prob, n_links, link_idx[int32]...)
   little-endian; ~5-10x smaller than CSV, ~50x faster to parse.
3. **Write/read self-test built in**: after writing, the kernel re-opens the
   file, re-accumulates Σ path volume per link, and asserts equality with
   assignment link volume (the A·f identity) before reporting success.
4. Fast-iteration guidance: pipeline development runs use
   number_of_iterations=1-2 (AON-ish path pool, schema-complete) and level 3;
   production baselines keep full iterations.

## Interim (already in place at the tooling layer)
The tensor compiler treats CSV as a transient intermediate: parse once →
`A_link_path.npz`/`B_path_od.npz`/`T_link_od.npz` (compressed binary
sparse) + `baseline_manifest.json` block index with per-file SHA-256 and
shapes + a mandatory reload-and-reverify self-test. The npz package is the
durable contract; the CSV may be deleted after verification.

## Verification plan (on approval)
selftest cases for the binary writer/reader round trip; regression: level 1
output unchanged byte-for-byte; level 3 reload reproduces link volumes to
1e-9.
