# CR-0007 — PR-2 INDEPENDENT_CPP_TWIN: three-way acceptance for every VDF form

status: COMMITTED (local branch cr-0006-selftest-spine; NOT pushed)
class:  TOOLING
wp:     Verification Twin Spine PR-2
author: Claude (AI agent) · approver: Owner (batch directive 2026-08-09)

## Scope

- `kernel/twin/twin_vdf.{hpp,cpp}` — independent reference implementations of
  all nine performance forms, written FROM THE SPEC (guide §3), scalar and
  plain; never includes production code; meets production only at link time
  via the neutral `VdfInput` struct.
- `test_cases/analytical/vdf_grid.yml` — the SINGLE SOURCE case spec: 20
  parameter cases (incl. all five agency conical facility profiles, two QVDF
  calibrations, both SCAG piecewise variants, MAG added-delay) × 12-point
  D/C grid with breakpoint probes at 1±1e-6.
- `test_cases/case_compiler.py` — compiles YAML → `vdf_cases.inc` (committed;
  `--check` mode detects staleness). The Python oracle reads the YAML
  directly, so a compiler bug surfaces as a three-way disagreement.
- `kernel/tests_cpp/twin_differential_main.cpp` — production vs twin over the
  grid + CSV dump for the oracle; CTest `twin_differential_certification`.
- `external_reference/python/vdf_reference.py` — cross-language oracle; no
  shared code with either C++ implementation.

## Finding TW-1 (caught by the twin on its FIRST run — the spine working)

The Spiess-b derivation `(2a−1)/(2a−2)` exists ONLY in ReadLinks (load-time,
TAPLite.cpp 6354–6355). The runtime fallback in `Link_Travel_Time` uses
**vdf_beta as conic b**. Consequence demonstrated numerically: a conic link
reaching evaluation without positive `conic_b` (e.g., constructed
programmatically, or a data path that skips normalization) evaluates with
b=4.0 → **travel time 0.0 at x=0.8** (negative, zero-clamped) — a silently
FREE link. Production+twin+oracle all agree once the load-time normalization
is replicated; the divergence was the harness exposing the two-stage
contract. Disposition: PR-3 strict mode makes the state unrepresentable
(explicit columns required, fallback rejected); the harness documents the
normalization step inline.

## Evidence

- twin_differential: **PASS 240/240** (20 cases × 12 grid points, rel tol 1e-9).
- external oracle: **480/480 agreements** (production AND twin vs Python).
- ctest: 2/2 (scalar_certification, twin_differential_certification).
- Production sources untouched.
