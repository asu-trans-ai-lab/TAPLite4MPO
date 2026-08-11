# Releasing `taplite4mpo`

Two audiences: **(A)** users learning the pipeline (start below), and **(B)** maintainers
cutting a PyPI release (§0 onward).

> **The release gate (run before every tag):**
> ```bash
> python scripts/release_smoke.py --full
> ```
> One self-checking command covering every public-network QA/QC gate — kernel build,
> regression suite, the synthetic sparse-id repro (issue #6), ARC intake/VDF gates,
> the full ARC equilibrium (region %RMSE must be <= 38), the the agency public-safe path,
> and the pytaplite APIs. CI runs the quick version on every push/PR; `--full` is the
> pre-tag requirement. Exit code 0 = safe to ship.

---

## What's in this release — for users

### ⭐ New: the onboarding & handoff folder
[`HANDOFF/`](HANDOFF/) is the front door for a new engineer (and for partner staff onboarding
a new agency model). It gives the **order to read the docs, the runs to reproduce, and the
issues to understand**:
- [`HANDOFF/README.md`](HANDOFF/README.md) — the reading path + reproduction path + the
  "which agency taught us this" issue index.
- [`HANDOFF/BPR_AND_VDF_CONFIG_RULES.md`](HANDOFF/BPR_AND_VDF_CONFIG_RULES.md) — the one-page
  **BPR / VDF / capacity / PLF configuration-rules card** (which `vdf_type`, which α/β, per-lane
  vs total capacity, `φ = L·PLF`, the 8-line setup checklist).
- [`HANDOFF/REPRODUCE_THE_ISSUES.md`](HANDOFF/REPRODUCE_THE_ISSUES.md) — a **hands-on lab**:
  trip each classic failure on the open networks and watch `intake` catch it.

### Lessons learned — the error-source document
[`docs/CONVERSION_ERRORS_CATALOG.md`](docs/CONVERSION_ERRORS_CATALOG.md) is the canonical
"every way an MPO hand-off goes wrong" reference — symptom → cause → fix → *which agency*, with
a master table and a fixed order-to-check. **The one principle:** onboarding is *model-meaning*
conversion, not file-format conversion, and **TAPLite never guesses** capacity/period/PLF/
units/demand-kind/zones/VDF — a wrong run is a convention mismatch, not a solver bug.

### How to use super-zones (accelerate without losing corridors)
Super-zones **merge zones that respond alike** so the assignment solves far fewer origin
shortest-path trees, while keeping the **full link network** — corridor volumes and the
full-resolution zone-to-zone skim are preserved. Use it for scenario sweeps and sketch
planning, **never as the model of record**. Runnable recipe (after a trusted full run):
```bash
cd examples/arc_atlanta
python arc_superzone.py 1500                       # ~1,431 super-zones (4.2x fewer origins)
cp ../../bin/DTALite.exe gmns_superzone/ && ( cd gmns_superzone && ./DTALite.exe )
python arc_superzone.py validate gmns_superzone    # %RMSE vs ARC reference
python arc_superzone.py identity                   # S=N corner case: MUST reproduce full exactly
python arc_skim.py sz                              # full-resolution skim from the fast run (R^2=0.9985)
```
Guides: [`examples/arc_atlanta/SUPERZONE.md`](examples/arc_atlanta/SUPERZONE.md) (the run) and
[`docs/superzone_design_principles.md`](docs/superzone_design_principles.md) (the P0–P10 rules,
including the **`S=N` correctness gate**). Measured on ARC: ~**2× faster**, corridor %RMSE
9–10%, and the recovered skim R²=0.9985 — trade local-street detail (the dropped intra-super
trips, always report the share) for corridor-level speed.

### Agency data stays private (with worked case studies)
Real agency networks/matrices are restricted and are **never committed** — `.gitignore` keeps
`private/*` out of Git (only READMEs tracked). Each agency model gets its own **private
subfolder** with a case-study README documenting its conventions and issues. The first is
[`private/SCAG/README.md`](private/README.md) — the SCAG RTP24 build (network done, tier-2 zone
correspondence resolved, piecewise VDF, and the open "missing volume" demand question), mapped
entry-by-entry to the error catalog. Reproduce private runs by pointing scripts at your own
copy of the data (same pattern as `agency_run/`, README §6).

---

## Releasing to PyPI (maintainers)

The package ships the **Python layers** (`dtalite_qa`, `pytaplite`) and the **C++ kernel
source**; the in-process `pytaplite._native` extension is compiled at build time. The kernel
exe (`bin/DTALite.exe`) is built separately with `build.sh` — it is not part of the wheel.

## 0. One-time setup
- A PyPI account, and the project name `taplite4mpo` registered (first upload claims it).
- **Trusted Publishing (recommended, no tokens):** on PyPI → your project → *Publishing* →
  add a GitHub publisher: owner `asu-trans-ai-lab`, repo `TAPLite4MPO`, workflow
  `wheels.yml`, environment `pypi`. (Alternative: a PyPI API token in repo secrets + switch
  the publish step to use it.)
- Before the first release, set a real maintainer in `pyproject.toml`
  (`[project].authors` name + email) and confirm the `version`.

## 1. Build & test locally (any one platform)
```bash
pip install build twine
python -m build                 # -> dist/taplite4mpo-<ver>.tar.gz (sdist) + ...-<py>-<plat>.whl
twine check dist/*

# smoke test in a clean venv
python -m venv /tmp/v && /tmp/v/bin/pip install dist/*.whl     # Windows: \tmp\v\Scripts\pip
/tmp/v/bin/python -c "import pytaplite, dtalite_qa; print(pytaplite.__version__, \
  'native:', pytaplite.kernel._native_mod is not None)"
```
A wheel includes the compiled `pytaplite._native`; the sdist compiles it on install (needs a
C++ compiler). If no compiler is present the install still succeeds and `pytaplite` uses the
subprocess path (build `bin/DTALite.exe` with `build.sh`).

## 2. (Optional) TestPyPI dry run
```bash
twine upload --repository testpypi dist/*
pip install -i https://test.pypi.org/simple/ taplite4mpo
```

## 3. Release via CI (recommended)
Bump `version` in `pyproject.toml`, commit, then tag:
```bash
git tag v0.1.0
git push origin v0.1.0
```
The **build-wheels** workflow builds wheels for Windows/Linux/macOS (CPython 3.8–3.12) + the
sdist and publishes them to PyPI via Trusted Publishing. Watch it under the repo's *Actions*
tab. You can also run it manually (Actions → build-wheels → Run workflow) to build wheels
without publishing.

## 4. Manual release (alternative)
```bash
python -m build && twine upload dist/*
```
(Builds only for your current platform — prefer the CI for multi-platform wheels.)

## Versioning
Semantic-ish: bump `[project].version` in `pyproject.toml`. Keep the kernel and Python
versions in lockstep for now (one number for the whole `taplite4mpo` distribution).

## What gets shipped (and what doesn't)
- **In the wheel/sdist:** `dtalite_qa/`, `pytaplite/`, the kernel source (`kernel/src/*.cpp,*.h`),
  the binding (`kernel/python/binding.cpp`), `README.md`, `LICENSE`, key docs.
- **Excluded** (via `MANIFEST.in`): `examples/`, `test_networks/`, `kernel/data_sets/`,
  `agency_run/`, `private/` — these are repo content, not package payload. Users get those by
  cloning the GitHub repo.
