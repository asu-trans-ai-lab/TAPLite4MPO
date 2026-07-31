# TAPLite engine wheel

- Build date: 2026-07-31
- Source branch: `taplite4nvta`
- Source commit: `c49b4efad56b4d06a161fcdcd1e32b1206d6a3ea`
- Distribution: `taplite4mpo`
- Prerelease version: `0.4.0rc2`
- Python ABI: CPython 3.11
- Platform: Windows x64
- Native extension: `pytaplite/_native.cp311-win_amd64.pyd`
- Compiler family: Microsoft Visual C++
- OpenMP: required and enabled
- Output: `wheels/taplite4mpo-0.4.0rc2-cp311-cp311-win_amd64.whl`
- Size: 4,940,139 bytes
- SHA-256:
  `183A1520595485803D23F230FF21F49A3979C2B52854D25278323A3C7CDE1BFD`

The wheel contains the `dtalite_qa`, `taplite4mpo`, and `pytaplite` Python
namespaces plus the compiled assignment kernel. The NVTA workflow starts a
fresh Python child process for every period and calls `pytaplite.assign` on the
prepared period folder. The wheel's `_native` extension runs the kernel in that
child process, preserving period-level kernel-state isolation without a
standalone DLL or executable.

Validation:

- wheel metadata reports `taplite4mpo 0.4.0rc2`
- all three Python namespaces are present
- isolated CPython 3.11 import loaded the packaged `_native` extension
- OpenMP two-worker probe returned two workers
- observed-QVDF native regression suite: 8 passed
- smoothstep profile-shoulder regression passed against the packaged kernel
- NVTA workflow test suite: 37 passed
- QVDF runtime source check: packaged `resources/link_qvdf.csv`, including the
  final `vdf_code=all` fallback for unlisted link types
- public golden-network regression: all 18 cases passed
- release-smoke gates G1-G7 passed against the packaged native kernel
- ARC quick smoke: assignment completed and validation parsed successfully

This managed Windows machine blocked launching a newly compiled standalone
executable. The standalone kernel still compiled successfully; regression and
release-smoke kernel calls therefore used the wheel's `_native` engine in a
fresh Python process for each run.
