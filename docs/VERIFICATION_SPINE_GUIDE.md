# The Verification Spine — user & teaching guide

Every performance function in TAPLite is certified by THREE independent
numerical views before anyone may call it "supported":

```
Specification (guide §3 + spec/*.yml)
   → Independent C++ twin      (kernel/twin/ — never calls production)
   → External Python oracle    (external_reference/python/ — no shared code)
   → Production kernel         (kernel/src/TAPLite.cpp)
```

Acceptance = all three agree on the full analytical grid. AI tools may
generate cases and diagnose failures; they are never the acceptance oracle.

## 1. Run the certification (no Python needed for the C++ layers)

```bash
cd kernel && mkdir build && cd build && cmake .. && cmake --build .
ctest                       # scalar_certification + twin_differential_certification
./taplite_selftest          # human-readable capability report
./twin_differential out.csv # production vs twin + dump for the oracle
python ../../external_reference/python/vdf_reference.py out.csv
```

What each proves:
- **taplite_selftest** — the production functions reproduce hand-computed
  known values (e.g. Spiess conic t(V/C=1) = 2·t0 exactly) and hold their
  mathematical properties (non-negativity, monotonicity, breakpoint
  continuity at V/C = 1±1e-6) for all nine `vdf_type` forms.
- **twin_differential** — an independently written implementation agrees
  with production to 1e-9 on 20 parameter cases × 12 grid points.
- **vdf_reference.py** — a third, cross-language implementation reads the
  YAML case spec directly and must agree with BOTH C++ implementations
  (three-way: a bug in the case compiler is also detectable).

The case spec is `test_cases/analytical/vdf_grid.yml` — the single source.
After editing it run `python test_cases/case_compiler.py` and rebuild.

## 2. The model-resolution gate (Python configuration testing tool)

Before trusting ANY run, answer: *what model am I actually running?*

```bash
python -m dtalite_qa.resolve configuration.yml            # audit + warnings
python -m dtalite_qa.resolve configuration.yml --strict   # gate: exit 2 on findings
```

`configuration.yml` (the run contract):

```yaml
scenario: my_run
network: {link: link.csv}
run:
  active_period: {id: 1, name: AM, start: "07:00", end: "10:00"}
vdf: {strict: true}
claims: {replication_family: conical}   # what you SAY you are replicating
```

The audit prints per-function link counts (with `unresolved` and
`conic_fallback` lines that must be 0) and writes
`resolved_model_manifest.json` — the provenance that travels with results.

Strict findings (each is a real, demonstrated failure class):
| ID | Meaning |
|---|---|
| RS-1 | conical links relying on the deprecated `vdf_alpha/vdf_beta` fallback — can evaluate to a zero-clamped FREE link (proven in CR-0007, finding TW-1) |
| RS-2 | qvdf links missing `vdf_cp/cd/n/s` |
| RS-3 | configuration claims a non-BPR replication family but links resolve to default BPR — "the program ran" ≠ "the model you claimed" |
| RS-4 | flat `vdf_plf=1.0` network-wide on a multi-hour period (placeholder PLF) |
| RS-5 | unknown `vdf_type` values |

## 3. The teaching case: `test_networks/bad_vdf_config/`

A six-link synthetic network reproducing a real failure class: the
configuration claims conical replication, but `vdf_type` is absent (all
links silently BPR), α/β carry foreign values, and PLF is a flat 1.0 on a
4-hour period. Run:

```bash
python -m dtalite_qa.resolve test_networks/bad_vdf_config/configuration.yml --strict
```

It MUST fail with RS-3 + RS-4. If it ever passes, the gate itself has
regressed. Contrast with `test_networks/sf_conic/` (explicit `conic_a`
columns) which passes strict — the difference between claiming a functional
form and declaring it.

## 4. Status vocabulary (spec/capability_registry.yml)

`certified > implemented > prototype > interface > planned > deferred`.
"Implemented" means ladder levels L0–L5 pass (schema/negative, scalar,
twin, oracle, tiny network, standard benchmark). Agency validation adds
L6–L8 (corridor, regional, memory/perf). Nothing is "supported" because a
branch exists.
