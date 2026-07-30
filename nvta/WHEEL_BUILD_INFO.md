# TAPLite engine wheel

- Build date: 2026-07-29
- Source branch: `taplite4nvta`
- Source commit: `a2366c81f1404b91b2025be7cb1026ea9b3f386b`
- Distribution: `taplite4mpo`
- Prerelease version: `0.4.0rc1`
- Python ABI: CPython 3.11
- Platform: Windows x64
- Native extension: `pytaplite/_native.cp311-win_amd64.pyd`
- Compiler family: Microsoft Visual C++
- OpenMP: required and enabled
- Output: `wheels/taplite4mpo-0.4.0rc1-cp311-cp311-win_amd64.whl`
- Size: 4,940,052 bytes
- SHA-256:
  `C96114B60DCD9584CA1E2A6875AB1B3DD7139EB7379C622A96DE9F69873514A5`

The wheel contains the `dtalite_qa`, `taplite4mpo`, and `pytaplite` Python
namespaces plus the compiled assignment kernel. The NVTA workflow starts a
fresh Python child process for every period and calls `pytaplite.assign` on the
prepared period folder. The wheel's `_native` extension runs the kernel in that
child process, preserving period-level kernel-state isolation without a
standalone DLL or executable.

Validation:

- wheel metadata reports `taplite4mpo 0.4.0rc1`
- all three Python namespaces are present
- isolated CPython 3.11 import loaded the packaged `_native` extension
- OpenMP two-worker probe returned two workers
- NVTA workflow test suite: 32 passed
- wheel-backed child-process assignment on the sparse external-ID fixture
  returned `0` and produced four loaded-link results
