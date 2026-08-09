# CR-0004 — Golden A: synthetic multimodal teaching network (T0)

status: MERGED (owner-authorized batch 2026-08-08)
class:  FIXTURE
wp:     T0 slot · training spine Golden A (06_TRAINING_MODELOPS_SPINE)
branch: cr-0004-golden-a-multimodal
author: Claude (AI agent) · approver: Owner

## Motivation & scope
Adds `examples/golden_a_multimodal/` (13 KB): the deterministic teaching +
regression fixture — 6 zones (Z6 a deliberate island), road with signal,
schedule-based rail L1 (12 trips) + frequency-based bus L2 (8 expanded),
B2↔R2 transfer hub, P&R/K&R as network arcs, submarket-labeled demand (1,200
trips incl. 50 deliberately unreachable), and `golden_a_check.py` — Gate-0
"Show Me the Path" as executable tests C1–C8.

## Evidence
`python golden_a_check.py` → ALL 8 PASS (five trip types as staged mode-legal
reachability; island detected not dropped; supply counts exact for both
service representations; conservation incl. the ledgered 50).
Purpose is deterministic teaching/regression, NOT realism.

## Decision
Owner approved commit+merge in the 2026-08-08 batch directive.
