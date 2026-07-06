"""TAPCI -- Traffic Assignment Programming/Control Interface (preview).

The stable "build-on-top" surface for GMNS-based traffic assignment: open a
project, validate the intake gate, run to convergence, observe link / OD / path /
system state, save & reload the routing policy, and export. Inspired by the
ecosystem role of SUMO's TraCI/libsumo, but targeted at planning-scale assignment
/ ODME / corridor validation rather than vehicle-level microsimulation -- so the
unit of observation is an *assignment iteration / link-time state*, never a vehicle.

The surface is organized into three CATEGORIES so each level can be tested and
adopted independently (see :meth:`categories` and ``tests/test_tapci_*.py``):

  Category 1 -- CORE (real): open / validate / run_until_converged / observe_links /
    observe_convergence / observe_manifest / moe / set_setting / export / export_report.
  Category 2 -- SCENARIO, TIME, PERFORMANCE, ROUTING-POLICY I/O (real): set_time_period /
    observe_od / observe_system / query_paths / observe_paths / save_paths /
    save_routing_policy / load_routing_policy. These are backed by kernel output files
    (od_performance.csv, system_performance.csv, route_assignment.csv) and the DTAC
    column store (the route_assignment ``prob`` column IS the routing policy; the DTAC
    warm-start replays exactly those theta shares).
  Category 3 -- DYNAMIC / CONTROL / INFORMATION PROVISION (roadmap): step-style
    run_iteration, live scenario edits (set_link_capacity/closure/toll/vdf,
    set_od_multiplier), injecting an external routing policy (load_paths /
    set_routing_policy_from_paths), day-to-day / information-provision loops. These
    raise a clear NotImplementedError -- the names exist so the contract is legible
    and the error precise, but nothing is faked with a silent no-op.

This is a thin facade: every real method delegates to the audited dtalite_qa.api
layer (intake gate + reproducibility manifest included). It adds no solving logic.
"""
import json
import os
import shutil

from . import api as _api
from . import runconfig as _runconfig
from . import csvio as _csvio

_ROADMAP = ("TAPCI Category 3 (roadmap, not in this preview): {what}. "
            "The preview implements Categories 1-2 (batch run + observe + routing-policy "
            "I/O). See private_docs/TAPCI_STRATEGY.md for the R2/R3 plan.")

# friendly-name -> actual output column, per observed object
_LINK_COLS = {"volume": "volume", "speed": "speed_mph", "vc": "doc",
              "travel_time": "travel_time", "vmt": "VMT", "vht": "VHT"}
_OD_COLS = {"volume": "volume", "demand": "volume", "distance": "total_distance_mile",
            "travel_time": "total_congestion_travel_time",
            "free_flow_travel_time": "total_free_flow_travel_time"}
_SYS_COLS = {"volume": "total_volume", "vmt": "PMT (VMT in miles)",
             "vht": "PHT (VHT in hours)", "delay": "Delay (hours)", "tti": "TTI",
             "speed": "avg_speed_mph"}


class TAPCI:
    """A single assignment project: network + pending demand/settings + last run.

    Construct with :meth:`open`. Mutable across runs -- edit pending settings with
    :meth:`set_setting` / :meth:`set_time_period` / :meth:`load_routing_policy`, call
    :meth:`run_until_converged` again, and re-observe. The source network is never
    modified (runs happen in an isolated working copy).
    """

    def __init__(self, network, exe=None, settings=None, demand=None):
        self.network = network
        self.exe = exe
        self._settings = dict(settings or {})
        self._demand = demand
        self._result = None            # dtalite_qa.api.Result of the last run

    # =====================================================================
    # Category 1 -- CORE
    # =====================================================================
    @classmethod
    def open(cls, project, exe=None):
        """[Cat 1] Open a project.yml run-config OR a GMNS scenario folder.

        A ``.yml``/``.yaml`` path is parsed as a run-config (its
        ``input.scenario_folder``, ``assignment`` settings, and ``exe`` become the
        pending state). A directory is read as a GMNS network folder directly.
        """
        if os.path.isdir(project):
            return cls(_api.Network.read_gmns(project), exe=exe)
        cfg = _runconfig.load(project)
        base = os.path.dirname(os.path.abspath(project))
        inp = (cfg.get("input") or {}).get("scenario_folder")
        if not inp:
            raise ValueError(f"{project}: input.scenario_folder is required")
        folder = inp if os.path.isabs(inp) else os.path.normpath(os.path.join(base, inp))
        net = _api.Network.read_gmns(folder)
        settings = dict(cfg.get("assignment") or {})
        cfg_exe = cfg.get("exe")
        if cfg_exe and not os.path.isabs(cfg_exe):
            cfg_exe = os.path.normpath(os.path.join(base, cfg_exe))
        return cls(net, exe=exe or cfg_exe, settings=settings)

    def validate(self):
        """[Cat 1] Intake gate + schema/accessibility checks; returns the prepare() dict."""
        from . import control as _control
        return _control.prepare(self.network.folder)

    def set_setting(self, **kwargs):
        """[Cat 1] Set pending kernel settings (friendly aliases OK), applied on the
        NEXT run. Backs anything the kernel reads from settings.csv. Returns self."""
        self._settings.update(kwargs)
        return self

    def run_until_converged(self, max_iter=None, gap=None, exe=None,
                            override=None, timeout=1800):
        """[Cat 1] Solve to convergence (batch). Returns self so calls can chain.

        ``max_iter`` -> ``iterations``; ``gap`` (a fraction, 0.001 = 0.1%) ->
        ``gap_tolerance`` percent. Pending settings from :meth:`set_setting` /
        :meth:`set_time_period` / :meth:`load_routing_policy` / the opened config are
        carried through. The kernel exe must be given here, at :meth:`open`, or on the
        object.
        """
        settings = dict(self._settings)
        if max_iter is not None:
            settings["iterations"] = int(max_iter)
        if gap is not None:
            settings["gap_tolerance"] = gap * 100.0   # fraction -> percent (kernel unit)
        exe = exe or self.exe
        if not exe:
            raise ValueError("no kernel exe: pass exe= to open()/run_until_converged(), "
                             "or build one (bash build.sh -> bin/DTALite.exe)")
        scen = _api.Scenario(self.network, demand=self._demand, settings=settings)
        self._result = _api.AssignmentEngine().run(
            scen, exe=exe, override=override, timeout=timeout)
        return self

    def _require_run(self):
        if self._result is None:
            raise RuntimeError("no run yet: call run_until_converged() first")
        return self._result

    @staticmethod
    def _project(rows, variables, alias, key_cols):
        if not variables:
            return rows
        out = []
        for r in rows:
            o = {k: r.get(k) for k in key_cols}
            for v in variables:
                o[v] = r.get(alias.get(v, v))
            out.append(o)
        return out

    def observe_links(self, variables=None):
        """[Cat 1] link_performance rows, optionally projected to ``variables``
        (volume/speed/vc/travel_time/vmt/vht; unknown names pass through)."""
        rows = self._require_run().link_volumes()
        return self._project(rows, variables, _LINK_COLS, ["link_id"])

    def observe_convergence(self):
        """[Cat 1] Per-iteration gap trajectory (list of dicts)."""
        return self._require_run().convergence()

    def observe_manifest(self):
        """[Cat 1] The run manifest (version, hashes, effective settings, MOE, gate)."""
        return self._require_run().manifest

    def moe(self):
        """[Cat 1] System MOEs: VMT / VHT / mean speed / loaded links."""
        return self._require_run().moe()

    def export(self, folder):
        """[Cat 1] Copy the last run to a durable folder; returns the path."""
        return self._require_run().export(folder)

    def export_report(self, out_html=None):
        """[Cat 1] Build the self-contained HTML report for the last run."""
        from . import report_html as _rh
        run_dir = self._require_run().run_dir
        out_html = out_html or os.path.join(run_dir, "report.html")
        _rh.build_report(run_dir, out_html)
        return out_html

    # =====================================================================
    # Category 2 -- SCENARIO, TIME, PERFORMANCE, ROUTING-POLICY I/O
    # =====================================================================
    def set_time_period(self, start_hour, end_hour):
        """[Cat 2] Set the demand period (start/end hour), applied on the next run.

        Maps to the kernel's ``demand_period_starting_hours`` / ``ending_hours``. The
        VDF period length (peak-hour factor, queue duration) derives from this window.
        """
        self._settings["demand_period_starting_hours"] = start_hour
        self._settings["demand_period_ending_hours"] = end_hour
        return self

    def observe_od(self, variables=None):
        """[Cat 2] od_performance rows (per O-D: volume, distance, free-flow &
        congested travel time), optionally projected."""
        rows = self._read_output("od_performance.csv",
                                 "no od_performance.csv in the run")
        return self._project(rows, variables, _OD_COLS, ["o_zone_id", "d_zone_id", "mode"])

    def observe_system(self, variables=None):
        """[Cat 2] system_performance rows (per mode: VMT/VHT/delay/TTI/speed)."""
        rows = self._read_output("system_performance.csv",
                                 "no system_performance.csv in the run")
        return self._project(rows, variables, _SYS_COLS, ["mode_type"])

    def observe_paths(self, variables=None):
        """[Cat 2] route_assignment rows (needs route_output on). The ``prob`` column
        is the routing policy (theta share per path)."""
        rows = self._read_output(
            "route_assignment.csv",
            "no route_assignment.csv -- set route_output=1 before run_until_converged()")
        if not variables:
            return rows
        return [{k: r.get(k) for k in ["o_zone_id", "d_zone_id", *variables]} for r in rows]

    def query_paths(self, o_zone, d_zone):
        """[Cat 2] All routes for one O-D pair (read-only, Path4GMNS-style external
        query -- inspects route_assignment without touching the engine)."""
        rows = self._read_output(
            "route_assignment.csv",
            "no route_assignment.csv -- set route_output=1 before run_until_converged()")
        o, d = str(o_zone), str(d_zone)
        return [r for r in rows
                if str(r.get("o_zone_id")) == o and str(r.get("d_zone_id")) == d]

    def save_paths(self, path):
        """[Cat 2] Save the run's path set (route_assignment) to ``path``.

        ``.json`` writes a portable, engine-independent trajectory list
        (o/d/mode/route_id/prob/node_ids/link_ids/volume/travel_time); any other
        suffix copies the raw route_assignment.csv. Returns ``path``.
        """
        rows = self._read_output(
            "route_assignment.csv",
            "no route_assignment.csv -- set route_output=1 before run_until_converged()")
        if path.lower().endswith(".json"):
            keep = ["mode", "route_id", "o_zone_id", "d_zone_id", "prob",
                    "node_ids", "link_ids", "volume", "total_travel_time"]
            trips = [{k: r.get(k) for k in keep} for r in rows]
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"format": "tapci.paths.v1", "n": len(trips), "paths": trips},
                          f, indent=1)
        else:
            shutil.copy(os.path.join(self._require_run().run_dir,
                                     "route_assignment.csv"), path)
        return path

    def save_routing_policy(self, path):
        """[Cat 2] Persist the routing policy (DTAC column store) to ``path``.

        The last run must have written ``route_columns.bin`` (``column_output=2``);
        if it did not, this raises with the fix. The saved file is a complete
        theta-share routing policy that :meth:`load_routing_policy` replays.
        """
        src = os.path.join(self._require_run().run_dir, "route_columns.bin")
        if not os.path.exists(src):
            raise RuntimeError(
                "no route_columns.bin in the run -- set_setting(column_output=2) before "
                "run_until_converged() to capture the routing policy (DTAC store)")
        shutil.copy(src, path)
        return path

    def load_routing_policy(self, path, adjust_sweeps=0):
        """[Cat 2] Load a saved routing policy (DTAC store) as the warm start for the
        NEXT run. The kernel replays the stored theta shares against the current OD
        table (demand-invariant policy), so a changed OD reuses the same routing.
        ``adjust_sweeps`` runs fixed-policy GP sweeps over the loaded columns."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"routing policy not found: {path}")
        self._settings["warm_start_columns"] = os.path.abspath(path)
        self._settings["column_adjust_sweeps"] = adjust_sweeps
        return self

    def _read_output(self, name, missing_msg):
        p = os.path.join(self._require_run().run_dir, name)
        if not os.path.exists(p):
            raise RuntimeError(missing_msg)
        _, rows = _csvio.read(p)
        return rows

    # =====================================================================
    # Category 3 -- DYNAMIC / CONTROL / INFORMATION PROVISION (roadmap)
    # =====================================================================
    def run_iteration(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(
            what="step-style run_iteration (one FW iteration with hand-back) needs a "
                 "stepped/resident kernel"))

    def load_paths(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(
            what="injecting an EXTERNAL path set as the routing policy (vs replaying the "
                 "kernel's own DTAC store via load_routing_policy) needs a policy-import "
                 "loader"))

    def set_routing_policy_from_paths(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(
            what="building a routing policy from user-supplied paths (day-to-day / dynamic "
                 "assignment)"))

    def run_day_to_day(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(
            what="day-to-day / dynamic assignment loop (OD + routing-policy update per day)"))

    def set_information_provision(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(
            what="information-provision control (message -> path-response experiment)"))

    def set_loading_policy(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(what="network-loading policy control"))

    def set_link_capacity(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(what="live set_link_capacity (next-run edit)"))

    def set_link_closure(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(what="live set_link_closure (next-run edit)"))

    def set_toll(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(what="live set_toll (next-run edit)"))

    def set_vdf_parameters(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(what="live set_vdf_parameters (next-run edit)"))

    def set_od_multiplier(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(what="live set_od_multiplier (next-run edit)"))

    # =====================================================================
    # Introspection -- the API contract (used by docs + contract tests)
    # =====================================================================
    @classmethod
    def categories(cls):
        """Return the tiered method contract: {category: [method names]}.

        Category 1-2 methods are implemented and backed by the kernel; Category 3
        methods exist as roadmap stubs that raise NotImplementedError.
        """
        return {
            1: ["open", "validate", "set_setting", "run_until_converged",
                "observe_links", "observe_convergence", "observe_manifest", "moe",
                "export", "export_report"],
            2: ["set_time_period", "observe_od", "observe_system", "observe_paths",
                "query_paths", "save_paths", "save_routing_policy", "load_routing_policy"],
            3: ["run_iteration", "load_paths", "set_routing_policy_from_paths",
                "run_day_to_day", "set_information_provision", "set_loading_policy",
                "set_link_capacity", "set_link_closure", "set_toll",
                "set_vdf_parameters", "set_od_multiplier"],
        }

    def __repr__(self):
        state = "no-run" if self._result is None else (
            "ok" if self._result.ok else "failed")
        return f"<TAPCI {self.network!r} settings={self._settings} [{state}]>"
