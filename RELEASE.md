# Releasing `taplite4mpo` to PyPI

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
  `nvta_run/`, `private/` — these are repo content, not package payload. Users get those by
  cloning the GitHub repo.
