# Change Record Index

One line per record. Statuses: DRAFT | IN-REVIEW | APPROVED | MERGED | REJECTED.
Process: see the release planning package (planning/02_CHANGE_CONTROL.md and
03_REVIEW_APPROVE_MECHANISM.md, kept outside this repo until adopted in-repo).

| CR | Title | Class | Status | Approver |
|----|-------|-------|--------|----------|
| [CR-0001](CR-0001-freeze-baseline.md) | Freeze single-period reference baseline + golden capture | FIXTURE | MERGED (main, 2026-08-08) | Owner (2026-08-08) |
| [CR-0002](CR-0002-transit-assignment-bart.md) | BART transit-assignment example (T1 observed-demand gold, 4 eras) | FIXTURE | MERGED (main, 2026-08-08) | Owner (2026-08-08) |
| [CR-0003](CR-0003-dc-multiagency-transit.md) | DC multi-agency transit (T2): contracts, pipeline, manifests | FIXTURE | MERGED (main, 2026-08-08) | Owner (2026-08-08) |
| [CR-0004](CR-0004-golden-a-multimodal.md) | Golden A synthetic multimodal teaching fixture (T0) | FIXTURE | MERGED (main, 2026-08-08) | Owner (2026-08-08) |
| [CR-0005](CR-0005-opendta-export.md) | TAPLite -> OpenDTA export (R-06): four-CSV contract + fail-closed gates | TOOLING/CONTRACT | MERGED (main, 2026-08-09) | Owner (2026-08-09) |
| [CR-0006](CR-0006-selftest-spine.md) | PR-1 C++ selftest spine (265/0, drift fixed, zero behavior change) | TOOLING | COMMITTED local | Owner (2026-08-09) |
| [CR-0007](CR-0007-independent-twin.md) | PR-2 independent twin + oracle (240/240, 480/480; finding TW-1) | TOOLING | COMMITTED local | Owner (2026-08-09) |
| [CR-0008](CR-0008-strict-model-resolution.md) | PR-3 strict model resolution (RS-1..5, negative fixture) | TOOLING/CONTRACT | COMMITTED local | Owner (2026-08-09) |
| [CR-0009](CR-0009-agency-conical-gate.md) | PR-4 agency conical Gate A (private root; NOT CERTIFIED yet) | FIXTURE | IN PROGRESS | Owner (2026-08-09) |
| [CR-0010](CR-0010-auto-core-detection.md) | Auto core detection: processors=0 -> cores-3 reserved for user | KERNEL-adjacent | COMMITTED local | Owner (2026-08-09) |
| [CR-0011](CR-0011-select-link-foundation.md) | Select-link foundation (WP-05): exact conservation, method-stamped | TOOLING | COMMITTED local | Owner (2026-08-09) |
| [CR-0012/13](CR-0012-0013-network-adapter.md) | Network Adapter: locked wide contract + GIS round trip (gates PASS) | TOOLING/CONTRACT | COMMITTED local | Owner (2026-08-09) |
| [CR-0014](CR-0014-output-contract-integrity.md) | Output-contract integrity: QVDF lineage guard + TAP_log schema (K-1..K-5) | KERNEL (output layer) | COMMITTED local | Owner (2026-08-09) |
| [CR-0015](CR-0015-route-output-binary.md) | Route output levels 2/3: volume-floor CSV + binary route_pool.bin with read-back self-test | KERNEL (output) | COMMITTED local | Owner (2026-08-10) |
