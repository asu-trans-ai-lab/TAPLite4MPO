# CR-0006 — PR-1 CPP_SELFTEST_SPINE: certification harness, zero behavior change

status: COMMITTED (local branch cr-0006-selftest-spine; NOT pushed — owner
        will review before any publication)
class:  TOOLING (+ DOCS drift fix)
wp:     Verification Twin Spine PR-1 (governing architecture, planning doc 09
        kept outside this repo)
author: Claude (AI agent) · approver: Owner (batch directive 2026-08-09)

## Scope

- `kernel/tests_cpp/selftest_main.cpp` — `taplite_selftest`: #includes the
  production translation unit (main() is BUILD_EXE-guarded, so no production
  line changes) and certifies `Link_Travel_Time` for ALL nine vdf_type forms
  on hand-computed known values + property checks (non-negativity,
  monotonicity on the D/C grid 0…3, breakpoint continuity probes at
  x = 1±1e-6). Documents-and-tests the legacy conic alpha/beta fallback
  (deprecation target for PR-3 strict mode).
- `kernel/CMakeLists.txt` — `enable_testing()` + `taplite_selftest` target +
  CTest `scalar_certification`.
- `spec/capability_registry.yml` — machine-readable feature status
  (certified/implemented/prototype/interface/planned/deferred); honest:
  select-link = planned, entrance-exit = interface, raw FW columns marked
  NOT valid for official select-link reporting.
- Drift fixes (verified divergence): `dtalite_qa/manifest.py` vdf_type
  description 0/1/2 → full 0–8; USER_GUIDE_VOL2 §3 table completed with
  types 7/8 and the conic row rewritten to name the explicit
  `conic_a/conic_b` columns and flag the legacy fallback as deprecated.

## Evidence

- `taplite_selftest`: **PASS 265 / FAIL 0** (first build) — includes the
  Spiess identity t(1)=2·t0, SCAG piecewise continuity at x=1, QVDF
  closed-form free-flow limit, Akcelik t(0)=t0, Webster x=0 delay constant,
  MAG per-mile added delay.
- Zero-behavior-change proof: `test_networks/run_regression.py` re-run on
  this branch — result recorded below before merge.
- Production sources untouched: `git diff --stat` shows no change under
  `kernel/src/`.

## Regression result

- run_regression: ALL PASS (30/30 checks; recorded post-run).
