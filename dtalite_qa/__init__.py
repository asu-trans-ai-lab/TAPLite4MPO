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
__version__ = "0.1.0"
