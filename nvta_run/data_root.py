"""Resolve the NVTA data root WITHOUT committing any agency path.

The NVTA dataset is agency data and is NOT distributed with this repository.
Point the runner at your own copy via (in order):
  1. environment variable  DTALITE_NVTA_INTERNAL  (and DTALITE_NVTA_SUBAREA)
  2. nvta_run/local_config.json  ->  {"internal": "...", "subarea": "..."}
  3. a `data/nvta_internal/` folder placed under this repo

If none is set, the NVTA runner raises a clear error. The open benchmark
networks in kernel/data_sets/ and test_networks/ reproduce fully without it.

Usage:
    from data_root import internal, subarea
    INTERNAL = internal()
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _local_config():
    p = os.path.join(HERE, "local_config.json")
    if os.path.exists(p):
        try:
            return json.load(open(p))
        except (OSError, ValueError):
            pass
    return {}


def _resolve(env_key, cfg_key, repo_default):
    v = os.environ.get(env_key)
    if v:
        return v
    v = _local_config().get(cfg_key)
    if v:
        return v
    for cand in (os.path.join(REPO, "data", repo_default),
                 os.path.join(REPO, "private", repo_default)):
        if os.path.isdir(cand):
            return cand
    raise FileNotFoundError(
        f"NVTA data not configured. Set ${env_key}, add '{cfg_key}' to "
        f"nvta_run/local_config.json, or place the data in data/{repo_default}/. "
        f"The NVTA dataset is agency-restricted and not shipped with this repo.")


def internal():
    return _resolve("DTALITE_NVTA_INTERNAL", "internal", "nvta_internal")


def subarea():
    return _resolve("DTALITE_NVTA_SUBAREA", "subarea", "nvta_subarea")
