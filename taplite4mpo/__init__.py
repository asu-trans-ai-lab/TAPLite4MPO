"""taplite4mpo -- the distribution's front-door namespace.

Re-exports the stable public surface so users can write the natural import:

    from taplite4mpo import TAPCI, Network, Demand, Scenario, AssignmentEngine, Result

The implementation lives in the ``dtalite_qa`` (QA/orchestration + API + TAPCI) and
``pytaplite`` (kernel driver) packages; this module is a thin, stable alias layer so
the import path matches the PyPI project name. Nothing here adds behavior.
"""
from dtalite_qa.api import Network, Demand, Scenario, AssignmentEngine, Result
from dtalite_qa.tapci import TAPCI

try:  # single-source the version from installed metadata (pyproject)
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("taplite4mpo")
except Exception:  # repo checkout without install
    __version__ = "0.4.0rc1"

__all__ = ["TAPCI", "Network", "Demand", "Scenario", "AssignmentEngine", "Result",
           "__version__"]
