# CR-0009 — PR-4 Agency conical Gate A (private data root)

status: IN PROGRESS — first certification attempt scored NOT CERTIFIED
        (expected for a parity gate; findings below). All data, staging and
        results live in the PRIVATE data root; this public record carries
        only the method and anonymized findings.
class:  FIXTURE (private) + harness
wp:     Verification Twin Spine PR-4
author: Claude (AI agent) · approver: Owner

## Method (the gate harness — public knowledge, private data)

From the delivered agency package, change ONLY the three audited defects,
one contract at a time (the elevator principle):
explicit conical by facility type (connectors excluded from congestion VDF)
· real per-link PLF back-extracted from the agency model's own volume/
capacity/V-C fields · tight convergence (60 it vs the delivered 9).
Score every variant against the agency reference volumes: R², ±10% band,
total-volume ratio, per-facility breakdown. The strict resolution gate
(CR-0008) rejects the delivered configuration (RS-3 + RS-4 pattern) and
passes the staged one.

## Findings so far

- **F-GA-1 · The tuned-wrong-model trap.** The delivered run (default BPR,
  foreign α/β, flat PLF, 9 iterations) scores HIGHER against reference
  volumes (R² 0.975, 53% within ±10%) than the first correct-form run
  (R² 0.954, 37%). Its parameters were evidently fitted to reproduce
  volumes under the wrong conventions — "looks calibrated" while failing
  the model-resolution gate. Certification must therefore never be a
  volume-R² beauty contest alone: configuration validity gates FIRST.
- **F-GA-2 · The real period capacity convention recovered.** Back-extracted
  per-link PLF is a tight uniform ≈0.60 across ALL facility types (no
  clipping): the agency's 4-hour AM period carries 2.4 effective capacity
  hours. The delivered flat PLF=1.0 overstated effective capacity 1.67×
  network-wide.
- **F-GA-3 · Open: collector over-assignment under correct conventions**
  (volume ratio 1.39 on FT4) — under investigation via one-change-at-a-time
  variants (V3: conical+flat-PLF isolates the two effects). Candidate
  causes: per-class assignment semantics (6 demand classes), turn
  penalties, VOT/toll interactions in the reference model.
- Supply side verified IN the delivered file: capacity == the agency's
  hourly lane-capacity field exactly; free-speed matches the model's
  free-flow speed field — the FT×AT lookup outputs are baked per link.

## Certification status

NOT CERTIFIED. The gate exists, refuses correctly, and the variant matrix
is converging on the cause. Next: V3/V4 isolation results, per-class volume
comparison, corridor-level scoring.
