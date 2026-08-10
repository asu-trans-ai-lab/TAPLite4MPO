# CR-0010 — auto core detection with user reservation (owner request)

status: COMMITTED (local branch cr-0006-selftest-spine; NOT pushed)
class:  KERNEL-PROTECTED-adjacent (thread configuration; no cost math)
author: Claude (AI agent) · approver: Owner (directive 2026-08-09: "do we
        detect # of cores and smartly run cores−3 to reserve CPU threads")

## Scope
`number_of_processors=0` in settings.csv now means AUTO: detect cores via
OpenMP and use max(1, cores−3), reserving 3 threads for the interactive
user. Two lines of semantics: the validation range accepts 0 as the
sentinel; ConfigureOpenMPRuntime resolves it before omp_set_num_threads and
prints the decision. Explicit positive values behave exactly as before.

## Evidence
- Live: "processors=0 (auto): detected 16 cores, using 13 (3 reserved for
  the user)"; OpenMP probe team = 13.
- taplite_selftest: 268/0 (3 new processor-contract checks: 0 accepted,
  1 accepted, −1 rejected). Twin differential unchanged 240/240.
- Full run_regression: **ALL PASS** after the kernel edit (all fixtures use
  explicit processor counts → byte-identical behavior).
