#!/usr/bin/env python3
"""Thin wrapper kept for backward compatibility.

The validator now lives in the `dtalite_qa` package (single source of truth).
Prefer:  python -m dtalite_qa validate <scenario>

Usage:   python validate_inputs.py <scenario_dir>
"""
import os
import sys

# make the repo-root dtalite_qa package importable when run as a loose script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dtalite_qa import validate  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("usage: python validate_inputs.py <scenario_dir>  "
              "(or: python -m dtalite_qa validate <scenario_dir>)")
        return 2
    rep = validate.validate(sys.argv[1])
    print(f"== validating {sys.argv[1]} ==")
    for w in rep.warnings:
        print(f"  WARN  {w}")
    for e in rep.errors:
        print(f"  ERROR {e}")
    if rep.ok:
        print(f"OK: 0 errors, {len(rep.warnings)} warning(s)")
        return 0
    print(f"FAILED: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
