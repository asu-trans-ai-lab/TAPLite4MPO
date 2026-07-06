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
        self._counts = None  # memoized (nodes, links, zones) for __repr__ / summary

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

    def _compute_counts(self):
        node_rows = self._read("node.csv")[1]
        link_rows = self._read("link.csv")[1]
        zones = len({csvio.inum(r.get("zone_id")) for r in node_rows
                     if csvio.is_num(r.get("zone_id")) and csvio.inum(r.get("zone_id")) > 0})
        return {"nodes": len(node_rows), "links": len(link_rows), "zones": zones}

    def _get_counts(self):
        if self._counts is None:
            self._counts = self._compute_counts()
        return self._counts

    @property
    def n_nodes(self):
        return self._get_counts()["nodes"]

    @property
    def n_links(self):
        return self._get_counts()["links"]

    @property
    def n_zones(self):
        return self._get_counts()["zones"]

    def summary(self):
        """Dict of {nodes, links, zones} -- the one-line network header."""
        c = self._get_counts()
        return {"nodes": c["nodes"], "links": c["links"], "zones": c["zones"],
                "folder": self.folder}

    def __repr__(self):
        c = self._get_counts()
        return f"<Network {os.path.basename(self.folder)}: {c['nodes']} nodes, {c['links']} links, {c['zones']} zones>"


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
        # None -> auto-discover; an explicit (even empty) list is honored as-is
        self.files = self._discover(network) if files is None else list(files)

    @staticmethod
    def _discover(network):
        import warnings
        p = os.path.join(network.folder, "mode_type.csv")
        files, missing = [], []
        if os.path.exists(p):
            _, rows = csvio.read(p)
            for r in rows:
                df = (r.get("demand_file") or "").strip()
                if not df or df in files or df in missing:
                    continue
                if os.path.exists(os.path.join(network.folder, df)):
                    files.append(df)
                else:
                    missing.append(df)
        if missing:
            warnings.warn(
                f"mode_type.csv declares demand file(s) that do not exist in "
                f"{network.folder} and were dropped: {', '.join(missing)}",
                stacklevel=2)
        if not files and os.path.exists(os.path.join(network.folder, "demand.csv")):
            files = ["demand.csv"]
        return files

    @classmethod
    def from_network(cls, network):
        """Use the demand CSV(s) already declared in the network's mode_type.csv.

        Only files that actually exist on disk are kept; declared-but-missing files
        are dropped with a warning (they are not silently ignored).

        >>> net = Network.read_gmns("kernel/data_sets/03_chicago_sketch")
        >>> Demand.from_network(net).files          # only files present on disk
        ['demand.csv']
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
            # only clobber an empty dir or a prior run export (has manifest.json);
            # anything else is the user's data
            is_run = os.path.isdir(folder) and (
                not os.listdir(folder)
                or os.path.exists(os.path.join(folder, "manifest.json")))
            if not is_run:
                raise ValueError(
                    f"refusing to overwrite non-run folder {folder} "
                    "(not empty and has no manifest.json); pick another path or delete it")
            shutil.rmtree(folder)
        shutil.copytree(self.run_dir, folder)
        self.run_dir = folder
        return folder

    def __repr__(self):
        # Prefer the manifest's recorded gap (no file I/O); fall back to parsing only
        # if the manifest is absent.
        conv = (self.manifest or {}).get("convergence") or {}
        g = conv.get("final_gap_pct", None)
        if g is None and not conv:
            g = self.final_gap_pct()
        return f"<Result {self.run_dir} rc={self.returncode} gap={g}%>"


class AssignmentEngine:
    """Runs a Scenario on the C++ kernel through the QA gate + manifest.

    ``run`` delegates to ``control.run`` (validate -> fill -> **intake gate** ->
    kernel -> manifest), so a Scenario that has not declared its conventions
    refuses to run unless you pass an ``override`` string (recorded in the manifest).
    """

    def run(self, scenario, exe, out_dir=None, override=None, timeout=1800):
        """Solve the assignment. Returns a ``Result``.

        The intake gate is ALWAYS enforced on this public surface -- there is no
        ``enforce_intake=False`` bypass, by design. A scenario that has not been
        audited (or whose audit is BLOCKED / stale) refuses to run unless you pass
        an ``override`` "who/why" string, which is recorded in the manifest. This
        keeps the intake gate (the product's whole point) unbypassable without a
        durable, recorded signal.

        Parameters
        ----------
        scenario : Scenario
        exe : str      path to the built DTALite kernel executable
        out_dir : str  where to run (default: a fresh tempdir)
        override : str "who/why" to waive a non-READY intake gate (recorded in manifest)

        >>> eng = AssignmentEngine()
        >>> res = eng.run(scen, exe="cmake_build_rel/DTALite_exe.exe")
        >>> res.ok
        True
        """
        if not isinstance(scenario, Scenario):
            raise TypeError("scenario must be a dtalite_qa.api.Scenario")

        src = scenario.network.folder
        # If the caller set solver settings OR composed an explicit demand that
        # differs from what mode_type.csv already declares, run against a patched
        # COPY so the source network is untouched; else run the source directly.
        demand_files = getattr(scenario.demand, "files", None) or []
        needs_demand_patch = _demand_differs(src, demand_files)
        work_src = src
        tmp_patch = None
        if scenario.settings or needs_demand_patch:
            # Gate-check the SOURCE first: the audit copied below gets a fresh
            # mtime (which would un-stale a stale audit), so carrying it forward is
            # only sound once the source itself passes -- the only diffs in the copy
            # vs the source are the API-authored settings/demand patches.
            ok, status, reason = _control.check_intake_gate(src, override=override)
            if not ok:
                raise RuntimeError(
                    f"intake gate {status}: {reason}\n"
                    f"  declare conventions in {src}/submission.yml and run intake, "
                    f"or pass override='who/why'.")
            import tempfile
            tmp_patch = tempfile.mkdtemp(prefix="dtalite_api_")
            _copy_scenario(src, tmp_patch)
            if scenario.settings:
                _patch_settings(tmp_patch, scenario.settings)
            if needs_demand_patch:
                # HONOR scenario.demand: write the composed demand file list into the
                # working copy's mode_type.csv so the Demand object is authoritative
                # (previously scenario.demand was silently discarded).
                _patch_demand(tmp_patch, demand_files)
            # carry the intake audit forward so the gate still sees a READY scenario
            for f in ("intake_issues.json", "submission.yml"):
                sp = os.path.join(src, f)
                if os.path.exists(sp):
                    shutil.copy(sp, os.path.join(tmp_patch, f))
            work_src = tmp_patch

        try:
            res = _control.run(work_src, exe=exe, out_dir=out_dir, override=override,
                               enforce_intake=True, timeout=timeout)
        finally:
            if tmp_patch:
                shutil.rmtree(tmp_patch, ignore_errors=True)
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
    """Copy the whole scenario tree (including subfolders) into dst.

    Uses copytree so subfolders (e.g. reference/, skims/) are not silently dropped.
    """
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _declared_demand_files(folder):
    """The demand_file list declared in a folder's mode_type.csv (order-preserving)."""
    p = os.path.join(folder, "mode_type.csv")
    files = []
    if os.path.exists(p):
        _, rows = csvio.read(p)
        for r in rows:
            df = (r.get("demand_file") or "").strip()
            if df and df not in files:
                files.append(df)
    return files


def _demand_differs(folder, composed_files):
    """True when the composed Demand.files differ from mode_type.csv's declaration.

    When they match as a SET of basenames (the common ``from_network`` case, in any
    order) no patch is needed: the declared mapping is authoritative and we can run
    the source folder directly.
    """
    if not composed_files:
        return False
    comp = {os.path.basename(f) for f in composed_files}
    decl = {os.path.basename(f) for f in _declared_demand_files(folder)}
    return comp != decl


def _patch_demand(folder, demand_files):
    """Write the composed demand file list into the working copy's mode_type.csv.

    A demand file's mode row decides its PCE/VOT, so files are matched to rows BY
    NAME wherever possible: every composed file whose basename appears in the
    declared demand_file column stays on its DECLARED row (no swap is possible),
    declared rows not covered by the composed list get their demand_file cleared
    (the kernel must not load a file the Demand dropped), and genuinely-new files
    are appended as additional single-mode rows. A list with NO name overlap maps
    positionally, and only when its count matches the mode rows -- anything else
    would silently reassign demand between modes and raises instead. If
    mode_type.csv is absent it is created.
    """
    p = os.path.join(folder, "mode_type.csv")
    if os.path.exists(p):
        header, rows = csvio.read(p)
    else:
        header, rows = ["mode_type_id", "mode_type", "name", "vot", "pce",
                        "occ", "demand_file"], []
    if "demand_file" not in header:
        header.append("demand_file")
    decl_pos = {}
    for i, r in enumerate(rows):
        df = (r.get("demand_file") or "").strip()
        if df:
            decl_pos.setdefault(os.path.basename(df), i)
    overlap = [f for f in demand_files if os.path.basename(f) in decl_pos]

    if rows and not overlap:
        # no name overlap: positional is the only mapping, and it must be total
        if len(demand_files) != len(rows):
            raise ValueError(
                f"{len(demand_files)} demand file(s) cannot map positionally onto "
                f"{len(rows)} mode_type.csv rows; edit mode_type.csv's demand_file "
                "column instead")
        new_rows = []
        for i, df in enumerate(demand_files):
            row = dict(rows[i])
            row["demand_file"] = df
            new_rows.append(row)
        csvio.write(p, header, new_rows)
        return

    # name-keyed: declared rows keep their own file; declared rows NOT covered by
    # the composed list are DROPPED (not blanked -- fill's MODE_DEFAULTS would
    # re-fill an empty demand_file with "demand.csv" and multi-load the demand);
    # genuinely-new files are appended as single-mode rows.
    covered = {os.path.basename(f): f for f in demand_files}
    new_rows = []
    for r in rows:
        row = dict(r)
        base = os.path.basename((r.get("demand_file") or "").strip())
        if base:
            if base not in covered:
                continue  # demand dropped by the composed list -> drop the mode row
            row["demand_file"] = covered.pop(base)
        new_rows.append(row)
    for base, df in covered.items():  # genuinely-new files
        new_rows.append({"mode_type_id": len(new_rows) + 1, "mode_type": "sov",
                         "name": "DRIVE", "vot": 10, "pce": 1, "occ": 1,
                         "demand_file": df})
    csvio.write(p, header, new_rows)


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
