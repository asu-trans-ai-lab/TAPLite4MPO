# CR-0011 - Select-Link Foundation (WP-05): query the path store with method discipline

status: COMMITTED (local; NOT pushed)
class:  TOOLING
author: Claude (AI agent) / approver: Owner (auto-mode directive 2026-08-09)

dtalite_qa/selectlink.py: select-link and ordered gate-pair (enter/then)
queries over route_assignment.csv - total/by-mode/top-OD/origin-destination
counts, ALWAYS stamped with path_flow_method=raw_fw_columns and
official_reporting_valid=false (doc-09 discipline: UE link flows unique,
route flows not; official reporting awaits proportional reconstruction).
Built-in conservation check = the WP-05 acceptance test.

Evidence: Chicago Sketch link 986 - selected path volume 1,912.8 equals
assigned link volume 1,912.8 exactly (gap 0.0); 4 origins, 94 destinations,
by-mode split reported.
