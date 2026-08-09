# CR-0008 — PR-3 STRICT_MODEL_RESOLUTION: the two-questions gate

status: COMMITTED (local branch cr-0006-selftest-spine; NOT pushed)
class:  TOOLING + CONTRACT (configuration.yml resolution semantics)
wp:     Verification Twin Spine PR-3
author: Claude (AI agent) · approver: Owner (batch directive 2026-08-09)

## Scope
`dtalite_qa/resolve.py` (audit + strict gate, RS-1…RS-5),
`test_networks/bad_vdf_config/` (synthetic negative fixture that MUST fail),
`tests/test_resolve_gate.py`, `docs/VERIFICATION_SPINE_GUIDE.md` (user &
teaching guide for the whole spine).

## Evidence
- Negative fixture: strict FAIL with RS-3 (claimed conical family resolves
  to default BPR) + RS-4 (flat placeholder PLF on a 4-hour period) — the
  generic reproduction of a real delivered-run failure class.
- `sf_conic` (explicit conic_a): strict PASS, conic_fallback = 0.
- Chicago Sketch: clean BPR audit (2,950 links, 0 fallback).
- No kernel change; regression unaffected.
