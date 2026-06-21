# dtalite_qa — QA / control layer for the DTALite/TAPLite kernel

A small, **standard-library-only** Python package that sits in front of the C++
kernel to keep automated runs stable and reproducible. It validates inputs,
fills the kernel's default values (normalizes), inventories `allowed_use`, and
checks per-mode accessibility — so a scenario that passes the gate has explicit
defaults, sorted links, no dangling references, and a known reachability profile
before a single iteration runs.

## Install

```bash
pip install -e .            # from the repo root (uses pyproject.toml); stdlib only
# or just run in place, no install needed:
python -m dtalite_qa <command> ...
```

## Commands

```bash
python -m dtalite_qa validate      <scenario>                 # errors + warnings
python -m dtalite_qa fill          <scenario> --out <dir>     # normalized copy (defaults, sorted links)
python -m dtalite_qa inventory     <scenario>                 # allowed_use / network inventory
python -m dtalite_qa accessibility <scenario>                 # per-mode reachability of demanded OD
python -m dtalite_qa check         <scenario>                 # validate + inventory + accessibility
python -m dtalite_qa schema        [--out schemas/...json]    # machine-readable GMNS field spec
python -m dtalite_qa manifest      <scenario>                 # provenance manifest (sha256, units, rows)
python -m dtalite_qa run           <scenario> --exe bin/DTALite.exe   # gate, then run the kernel
python -m dtalite_qa report        <run_dir>                  # post-run summary (gap, VMT/VHT, by FT, enforcement)
python -m dtalite_qa demand-bin    <scenario>                 # convert demand CSVs to fast .bin
python -m dtalite_qa adapt         <scenario> --out <dir>     # convert an older/foreign network to current format
```

### Adapting an older / foreign network (`adapt`)

Older TAPLite or other-tool networks often differ in column NAMES (`VDF_alpha`,
`allowed_uses`) and UNITS (`free_speed` in mph, `length` in miles). `adapt` writes
a current-format copy and a checklist of changes:

```bash
python -m dtalite_qa adapt private/2023_MAG/assignment --out private/2023_MAG/current_format \
       --free-speed mph --length mi
python -m dtalite_qa validate private/2023_MAG/current_format
```

It case-insensitively maps column names (`VDF_alpha`->`vdf_alpha`), applies an
alias table (`allowed_uses`->`allowed_use`), adds `vdf_free_speed_mph`/
`vdf_length_mi` from the declared units, repairs `lanes==0`/`capacity==0` links the
current kernel would otherwise skip, and sorts links by `from_node_id` (CSR
requirement). Run `validate` on the output to confirm it is clean.

## What each piece does

- **validate** — hard ERRORS (missing node/link, links not sorted by
  `from_node_id` → CSR corruption, bad node/zone/link references, non-positive
  lanes/capacity/free_speed, `end ≤ start` period) and WARNINGS (missing
  settings → kernel defaults, missing demand file, unknown `allowed_use` token,
  QVDF columns absent).
- **fill** — writes a normalized scenario: every optional column the kernel
  reads is present with the kernel's own default (`vdf_alpha=0.15`, `vdf_beta=4`,
  `vdf_type=0`, QVDF `cp/cd/n/s`, `cutoff_speed=0.75·free_speed`, …), links are
  **sorted** ascending by `from_node_id`, and `settings.csv` is materialized.
  The filled scenario runs **byte-identically** to the kernel's implicit
  behavior — it just leaves nothing implicit (key to reproducible batch runs).
- **inventory** — per-mode count of usable links and the restriction classes
  (`all` / `closed` / `only:<mode>` / `no:<mode>` / `custom`) plus the explicit
  restricted-link list.
- **accessibility** — for each mode, builds the `allowed_use`-respecting graph
  and reports **demanded** OD pairs that cannot be routed (origin with no allowed
  outbound, destination with no allowed inbound, or unreachable across SCCs).
  Demand-aware, so a legitimate one-way corridor passes as long as every
  demanded OD is feasible.
- **control** — `prepare()` / `run()` orchestrate validate → fill → inventory →
  accessibility → kernel, the stable entry point for automation.

## Library use

```python
from dtalite_qa import validate, control
rep = validate.validate("my_scenario/")
if rep.ok:
    result = control.run("my_scenario/", exe="bin/DTALite.exe")
    print(result["returncode"], result["normalized"])
```

## Default values

`schema.py` is the single source of truth for the kernel defaults; if the kernel
changes a default, update it there and the filler/validator follow.
