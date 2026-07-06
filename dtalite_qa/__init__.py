"""dtalite_qa -- a QA / control layer for the DTALite/TAPLite C++ kernel.

Validate inputs, fill kernel default values (normalize), inventory allowed_use,
and check per-mode accessibility before running the kernel, so automated runs
are stable and reproducible.

Library entry points:
    from dtalite_qa import validate, fill, inventory, accessibility, control
    rep = validate.validate("my_scenario/")
    result = control.prepare("my_scenario/")
    result = control.run("my_scenario/", exe="bin/DTALite.exe")
"""
from . import (schema, csvio, validate, fill, inventory, accessibility, control,
               manifest, report, demandbin, adapt, plf)

__all__ = ["schema", "csvio", "validate", "fill", "inventory", "accessibility",
           "control", "manifest", "report", "demandbin", "adapt", "plf"]
try:  # single-source: the installed distribution version (pyproject.toml)
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("taplite4mpo")
except Exception:  # repo checkout without install
    __version__ = "0.3.0"
