"""Composable Python API over the TAPLite/DTALite kernel + the dtalite_qa QA layer.

This is the *developer* interface of the third-generation MPO workflow: a handful
of small, composable objects instead of an argv orchestrator. It is a thin skin --
every run goes through ``control.run``, so the no-guessing intake gate and the
reproducibility manifest come for free; nothing here bypasses them.

    from dtalite_qa.api import Network, Demand, Scenario, AssignmentEngine

    net = Network.read_gmns("kernel/data_sets/03_chicago_sketch")
    scen = Scenario(net, Demand.from_network(net),
                    settings={"number_of_iterations": 20})
    result = AssignmentEngine().run(scen, exe="cmake_build_rel/DTALite_exe.exe")
    print(result.moe())                 # {'vmt':..., 'vht':..., 'mean_speed_mph':...}
    result.export("out/chicago_run")    # copy the whole run folder somewhere durable

Design rules (from TAPLITE4MPO_STRATEGY.md): SMALL, few params, composable. The
kernel is the solver; these objects only marshal inputs and read outputs.
"""
import datetime as _dt
import json
import os
import shutil

from . import control as _control
from . import csvio
from . import manifest as _manifest
from . import report as _report


class Network:
    """A GMNS network folder (node.csv + link.csv, and whatever else lives beside them).

    ``Network`` does not copy or mutate the folder; it is a lightweight handle plus
    a couple of read-only summaries. The kernel reads the folder directly at run time.
    """

    def __init__(self, folder):
        self.folder = os.path.abspath(folder)
        if not os.path.isdir(self.folder):
            raise FileNotFoundError(f"network folder not found: {folder}")

    @classmethod
    def read_gmns(cls, folder):
        """Open a GMNS scenario folder. Requires node.csv and link.csv.

        >>> net = Network.read_gmns("kernel/data_sets/03_chicago_sketch")
        >>> net.n_links > 0 and net.n_zones > 0
        True
        """
        for req in ("node.csv", "link.csv"):
            if not os.path.exists(os.path.join(folder, req)):
                raise FileNotFoundError(f"{req} missing in {folder} (not a GMNS scenario)")
        return cls(folder)

    def _read(self, name):
        p = os.path.join(self.folder, name)
        return csvio.read(p) if os.path.exists(p) else ([], [])

    @property
    def n_nodes(self):
        return len(self._read("node.csv")[1])

    @property
    def n_links(self):
        return len(self._read("link.csv")[1])

    @property
    def n_zones(self):
        _, rows = self._read("node.csv")
        return len({csvio.inum(r.get("zone_id")) for r in rows
                    if csvio.is_num(r.get("zone_id")) and csvio.inum(r.get("zone_id")) > 0})

    def summary(self):
        """Dict of {nodes, links, zones} -- the one-line network header."""
        return {"nodes": self.n_nodes, "links": self.n_links, "zones": self.n_zones,
                "folder": self.folder}

    def __repr__(self):
        return f"<Network {os.path.basename(self.folder)}: {self.n_nodes} nodes, {self.n_links} links, {self.n_zones} zones>"


class Demand:
    """The OD demand of a scenario.

    Demand lives in the scenario folder as the CSV(s) named in mode_type.csv
    (``demand_file`` column). This object references those in place -- it does not
    re-key or rescale trips (that is the intake gate's job, deliberately, so trips
    are never silently transformed). ``from_network`` is the common case: use the
    demand already sitting in the network folder.
    """

    def __init__(self, network, files=None):
        self.network = network
        self.files = files or self._discover(network)

    @staticmethod
    def _discover(network):
        p = os.path.join(network.folder, "mode_type.csv")
        files = []
        if os.path.exists(p):
            _, rows = csvio.read(p)
            for r in rows:
                df = (r.get("demand_file") or "").strip()
                if df and df not in files and os.path.exists(os.path.join(network.folder, df)):
                    files.append(df)
        if not files and os.path.exists(os.path.join(network.folder, "demand.csv")):
            files = ["demand.csv"]
        return files

    @classmethod
    def from_network(cls, network):
        """Use the demand CSV(s) already declared in the network's mode_type.csv.

        >>> net = Network.read_gmns("kernel/data_sets/03_chicago_sketch")
        >>> Demand.from_network(net).files
        ['demand.csv', ...]
        """
        return cls(network)

    def total_trips(self):
        """Sum of the 'volume' column across all demand files (vehicles/persons as coded)."""
        tot = 0.0
        for f in self.files:
            _, rows = csvio.read(os.path.join(self.network.folder, f))
            tot += sum(csvio.fnum(r.get("volume")) for r in rows)
        return tot

    def __repr__(self):
        return f"<Demand {self.files} total={self.total_trips():,.0f}>"


# settings keys the API exposes with friendly aliases -> kernel settings.csv columns
_SETTING_ALIASES = {
    "iterations": "number_of_iterations",
    "gap_tolerance": "convergence_gap_pct",
    "gap_pct": "convergence_gap_pct",
    "processors": "number_of_processors",
    "warm_start_columns": "warm_start_columns",
    "assignment_method": "assignment_method",
}


class Scenario:
    """A network + its demand + solver settings -- everything needed for one run.

    ``settings`` accepts either raw kernel columns (e.g. ``number_of_iterations``)
    or the friendly aliases ``iterations`` / ``gap_tolerance`` / ``processors``.
    The settings are applied to a *copy* of the network folder at run time; the
    source network is never modified.
    """

    def __init__(self, network, demand=None, settings=None):
        self.network = network
        self.demand = demand or Demand.from_network(network)
        self.settings = self._normalize(settings or {})

    @staticmethod
    def _normalize(settings):
        out = {}
        for k, v in settings.items():
            out[_SETTING_ALIASES.get(k, k)] = v
        return out

    def __repr__(self):
        return f"<Scenario {self.network!r} settings={self.settings}>"


class Result:
    """The outputs of one kernel run: a folder + convenience readers.

    Created by ``AssignmentEngine.run``. Points at the (temporary or exported) run
    folder holding link_performance.csv, summary_log_file.txt, and manifest.json.
    """

    def __init__(self, run_dir, returncode=0, log="", manifest=None):
        self.run_dir = os.path.abspath(run_dir)
        self.returncode = returncode
        self.log = log
        self.manifest = manifest or {}

    @property
    def ok(self):
        return self.returncode == 0 and os.path.exists(
            os.path.join(self.run_dir, "link_performance.csv"))

    def moe(self):
        """System measures of effectiveness: VMT / VHT / mean speed / loaded links.

        >>> r.moe()
        {'links': 2950, 'loaded_links': 2210, 'vmt': ..., 'vht': ..., 'mean_speed_mph': ...}
        """
        m = self.manifest.get("moe") if self.manifest else None
        if m:
            return m
        return _manifest._moe_from_link_performance(self.run_dir)

    def convergence(self):
        """Per-iteration gap trajectory (list of dicts: iter, system_vmt, gap_pct, ...)."""
        return _report.parse_gap(self.run_dir)

    def final_gap_pct(self):
        traj = self.convergence()
        return traj[-1]["gap_pct"] if traj else None

    def link_volumes(self):
        """List of dicts from link_performance.csv (link_id, volume, speed, doc, VMT ...)."""
        p = os.path.join(self.run_dir, "link_performance.csv")
        if not os.path.exists(p):
            return []
        _, rows = csvio.read(p)
        return rows

    def report(self):
        """The structured post-run report dict (see dtalite_qa.report.build)."""
        return _report.build(self.run_dir)

    def export(self, folder):
        """Copy the entire run folder to a durable location; returns the path.

        The run folder is otherwise a tempdir that may be cleaned up. Use this to
        keep a run (its inputs, outputs, and manifest travel together)."""
        folder = os.path.abspath(folder)
        if os.path.abspath(self.run_dir) == folder:
            return folder
        if os.path.exists(folder):
            shutil.rmtree(folder)
        shutil.copytree(self.run_dir, folder)
        self.run_dir = folder
        return folder

    def __repr__(self):
        g = self.final_gap_pct()
        return f"<Result {self.run_dir} rc={self.returncode} gap={g}%>"


class AssignmentEngine:
    """Runs a Scenario on the C++ kernel through the QA gate + manifest.

    ``run`` delegates to ``control.run`` (validate -> fill -> **intake gate** ->
    kernel -> manifest), so a Scenario that has not declared its conventions
    refuses to run unless you pass an ``override`` string (recorded in the manifest).
    """

    def run(self, scenario, exe, out_dir=None, override=None, enforce_intake=True,
            timeout=1800):
        """Solve the assignment. Returns a ``Result``.

        Parameters
        ----------
        scenario : Scenario
        exe : str      path to the built DTALite kernel executable
        out_dir : str  where to run (default: a fresh tempdir)
        override : str "who/why" to bypass a non-READY intake gate (recorded)
        enforce_intake : bool  keep True in production; False only for legacy nets

        >>> eng = AssignmentEngine()
        >>> res = eng.run(scen, exe="cmake_build_rel/DTALite_exe.exe")
        >>> res.ok
        True
        """
        if not isinstance(scenario, Scenario):
            raise TypeError("scenario must be a dtalite_qa.api.Scenario")

        src = scenario.network.folder
        # If the caller set solver settings, run against a settings-patched COPY so
        # the source network is untouched; else run the source folder directly.
        work_src = src
        tmp_patch = None
        if scenario.settings:
            import tempfile
            tmp_patch = tempfile.mkdtemp(prefix="dtalite_api_")
            _copy_scenario(src, tmp_patch)
            _patch_settings(tmp_patch, scenario.settings)
            # carry the intake audit forward so the gate still sees a READY scenario
            for f in ("intake_issues.json", "submission.yml"):
                sp = os.path.join(src, f)
                if os.path.exists(sp):
                    shutil.copy(sp, os.path.join(tmp_patch, f))
            work_src = tmp_patch

        res = _control.run(work_src, exe=exe, out_dir=out_dir, override=override,
                           enforce_intake=enforce_intake, timeout=timeout)
        if res.get("gate_refusal"):
            raise RuntimeError(
                f"intake gate {res.get('intake_gate')}: {res['gate_refusal']}\n"
                f"  declare conventions in {src}/submission.yml and run intake, "
                f"or pass override='who/why'.")
        if not res.get("ran"):
            rep = res.get("validate")
            errs = "; ".join(rep.errors) if rep else "validation failed"
            raise RuntimeError(f"scenario did not run: {errs}")

        run_dir = res["normalized"]
        man = _manifest.build_run_manifest(
            run_dir, scenario=src, exe=exe, override=res.get("override"),
            intake_gate=res.get("intake_gate"),
            created=_dt.datetime.now().isoformat(timespec="seconds"))
        with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(man, f, indent=1)
        return Result(run_dir, returncode=res.get("returncode", 0),
                      log=res.get("log", ""), manifest=man)


def _copy_scenario(src, dst):
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        p = os.path.join(src, name)
        if os.path.isfile(p):
            shutil.copy(p, os.path.join(dst, name))


def _patch_settings(folder, settings):
    """Overwrite/add columns in settings.csv (single-row) with the given values."""
    p = os.path.join(folder, "settings.csv")
    if os.path.exists(p):
        header, rows = csvio.read(p)
        row = dict(rows[0]) if rows else {}
    else:
        header, row = [], {}
    for k, v in settings.items():
        row[str(k)] = v
        if k not in header:
            header.append(str(k))
    csvio.write(p, header, [row])
