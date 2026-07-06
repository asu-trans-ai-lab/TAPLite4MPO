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
  Category 2 -- SCENARIO ENV: TIME, PERFORMANCE, SKIMS, ROUTING-POLICY I/O, and
    NEXT-RUN SCENARIO EDITS (all real). Observe: observe_od / observe_system /
    observe_paths / query_paths / observe_skims / query_skim. Save/load: save_paths /
    save_skims / save_routing_policy / load_routing_policy (the route_assignment
    ``prob`` column IS the routing policy; the DTAC warm-start replays those theta
    shares). Scenario edits applied to a working copy before the NEXT run (source
    untouched): set_time_period / set_link_capacity / set_link_closure / set_toll /
    set_od_multiplier / clear_edits, plus run_day_to_day (an offline day-to-day /
    information-provision loop driven by an external policy_fn). This is the one-period
    ENVIRONMENT that a Choice-Graph / ABM / LLM-scenario / RL loop calls repeatedly.
  Category 3 -- DYNAMIC / LIVE / STEP (roadmap): step-style run_iteration, LIVE
    (mid-solve) control, injecting an external routing policy (load_paths /
    set_routing_policy_from_paths), the live message-control primitive
    set_information_provision, set_loading_policy, per-link VDF edits. These raise a
    clear NotImplementedError -- the names exist so the contract is legible and the
    error precise, but nothing is faked with a silent no-op. NOTE: next-run
    capacity/closure/toll/OD edits and the offline day-to-day loop are Category 2
    (real); only LIVE/step control is Category 3.

This is a thin facade: every real method delegates to the audited dtalite_qa.api
layer (intake gate + reproducibility manifest included). It adds no solving logic.
"""
import json
import os
import shutil
import tempfile

from . import api as _api
from . import runconfig as _runconfig
from . import csvio as _csvio

_ROADMAP = ("TAPCI Category 3 (roadmap, not in this preview): {what}. "
            "The preview implements Categories 1-2 (batch run + observe + skims + "
            "routing-policy I/O + next-run scenario edits). See "
            "private_docs/TAPCI_STRATEGY.md for the R2/R3 plan.")


def _f(v):
    """Lenient float; None/'' -> None."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _idset(ids):
    """Normalize a scalar-or-iterable of ids to a set of strings."""
    if isinstance(ids, (str, int)):
        ids = [ids]
    return {str(i) for i in ids}


def _copytree(src, dst):
    shutil.copytree(src, dst, dirs_exist_ok=True)

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
        self._edits = []               # pending next-run scenario edits (Cat 2)
        self._work = None              # persistent scenario-edit working copy

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
        # apply any pending scenario edits to a working copy (source untouched)
        folder = self._run_folder()
        net = self.network if folder == self.network.folder else _api.Network.read_gmns(folder)
        scen = _api.Scenario(net, demand=self._demand, settings=settings)
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

    # ---- OD skim service (the Choice Graph / ABM interface) ----
    def observe_skims(self, variables=None):
        """[Cat 2] OD skims for external choice / ABM / RL update: per (o,d,mode)
        congested travel time + distance + free-flow time. Backed by
        od_performance.csv (every listed OD has a path, so path_available=True).
        The Choice Graph sends (o,d,mode,period,demand); this returns the skim it
        needs to update alternative costs externally."""
        rows = self._read_output("od_performance.csv", "no od_performance.csv in the run")
        out = []
        for r in rows:
            out.append({
                "o_zone_id": r.get("o_zone_id"), "d_zone_id": r.get("d_zone_id"),
                "mode": r.get("mode"),
                "skim_time": _f(r.get("total_congestion_travel_time")),
                "skim_distance": _f(r.get("total_distance_mile")),
                "free_flow_time": _f(r.get("total_free_flow_travel_time")),
                "generalized_cost": _f(r.get("total_congestion_travel_time")),  # time proxy
                "path_available": True})
        if variables:
            base = ["o_zone_id", "d_zone_id", "mode"]
            out = [{k: rec.get(k) for k in base + list(variables)} for rec in out]
        return out

    def query_skim(self, o_zone, d_zone, mode=None):
        """[Cat 2] Single-OD skim (Choice Graph point query). Returns the skim dict
        with ``path_available=True``, or ``path_available=False`` (null skims) if the
        OD is absent from od_performance -- i.e. no feasible path this run."""
        o, d = str(o_zone), str(d_zone)
        for rec in self.observe_skims():
            if str(rec["o_zone_id"]) == o and str(rec["d_zone_id"]) == d \
                    and (mode is None or str(rec["mode"]) == str(mode)):
                return rec
        return {"o_zone_id": o, "d_zone_id": d, "mode": mode, "skim_time": None,
                "skim_distance": None, "generalized_cost": None, "path_available": False}

    def save_skims(self, path):
        """[Cat 2] Save the OD skim table to ``path`` (.json portable, else CSV)."""
        skims = self.observe_skims()
        if path.lower().endswith(".json"):
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"format": "tapci.skims.v1", "n": len(skims), "skims": skims},
                          f, indent=1)
        else:
            hdr = list(skims[0].keys()) if skims else ["o_zone_id", "d_zone_id", "mode"]
            _csvio.write(path, hdr, skims)
        return path

    # ---- next-run scenario edits (real: mutate the working copy, not live) ----
    def set_link_capacity(self, link_ids, factor=None, value=None):
        """[Cat 2] Scale (``factor``) or set (``value``) the capacity of ``link_ids``
        on the NEXT run. Edits the ``capacity`` column of a working copy; the source
        network is untouched. Exactly one of factor/value must be given."""
        if (factor is None) == (value is None):
            raise ValueError("give exactly one of factor= or value=")
        self._edits.append({"op": "capacity", "links": _idset(link_ids),
                            "factor": factor, "value": value})
        return self

    def set_link_closure(self, link_ids):
        """[Cat 2] Close ``link_ids`` on the next run by banning all modes
        (``allowed_uses='closed'``). Uses the mode filter, NOT capacity=0 (the kernel
        treats capacity<=0 as free-flow, not closed)."""
        self._edits.append({"op": "closure", "links": _idset(link_ids)})
        return self

    def set_toll(self, link_ids, toll):
        """[Cat 2] Set the ``vdf_toll`` of ``link_ids`` on the next run. The kernel
        folds toll into generalized cost as (toll + dist*op_cost)/VOT (minutes)."""
        self._edits.append({"op": "toll", "links": _idset(link_ids), "toll": float(toll)})
        return self

    def set_od_multiplier(self, factor, o_zones=None, d_zones=None):
        """[Cat 2] Scale demand ``volume`` by ``factor`` on the next run, optionally
        restricted to origins in ``o_zones`` and/or destinations in ``d_zones``.
        Edits the demand file(s) in the working copy."""
        self._edits.append({"op": "od_mult", "factor": float(factor),
                            "o": _idset(o_zones) if o_zones else None,
                            "d": _idset(d_zones) if d_zones else None})
        return self

    def clear_edits(self):
        """[Cat 2] Drop all pending scenario edits (back to the base network)."""
        self._edits = []
        return self

    # scenario-edit materialization -------------------------------------
    def _run_folder(self):
        """The folder the next run assigns on: the source network if there are no
        edits, else a persistent working copy with the edits applied fresh from
        source (so edits are declarative vs base, never compounding across runs)."""
        if not self._edits:
            return self.network.folder
        src = self.network.folder
        if self._work is None:
            self._work = tempfile.mkdtemp(prefix="tapci_edit_")
            _copytree(src, self._work)
        # restore the editable files from source, then apply the full edit set
        editable = ["link.csv"] + self._demand_basenames()
        for f in editable:
            sp = os.path.join(src, f)
            if os.path.exists(sp):
                shutil.copy(sp, os.path.join(self._work, f))
        self._apply_edits(self._work)
        return self._work

    def _demand_basenames(self):
        return [os.path.basename(f) for f in _api.Demand(self.network).files]

    def _apply_edits(self, folder):
        link_ops = [e for e in self._edits if e["op"] in ("capacity", "closure", "toll")]
        od_ops = [e for e in self._edits if e["op"] == "od_mult"]
        if link_ops:
            self._apply_link_edits(folder, link_ops)
        if od_ops:
            self._apply_od_edits(folder, od_ops)

    @staticmethod
    def _apply_link_edits(folder, ops):
        p = os.path.join(folder, "link.csv")
        header, rows = _csvio.read(p)
        if "vdf_toll" not in header and any(e["op"] == "toll" for e in ops):
            header.append("vdf_toll")
        # closure bans all modes via the kernel's `allowed_use` field (singular -- the
        # exact name TAPLite reads); "closed" contains no mode_type so every mode's
        # allowed-mask goes to 0. capacity=0 would NOT close (kernel treats it as
        # free-flow), which is why closure uses the mode filter.
        if any(e["op"] == "closure" for e in ops):
            if "allowed_use" not in header:
                header.append("allowed_use")
            for r in rows:                       # default: keep every link open
                r.setdefault("allowed_use", r.get("allowed_use", "") or "")
        for r in rows:
            lid = str(r.get("link_id"))
            for e in ops:
                if lid not in e["links"]:
                    continue
                if e["op"] == "capacity":
                    cap = _f(r.get("capacity")) or 0.0
                    r["capacity"] = repr(e["value"] if e["value"] is not None
                                         else cap * e["factor"])
                elif e["op"] == "closure":
                    r["allowed_use"] = "closed"
                elif e["op"] == "toll":
                    r["vdf_toll"] = repr(e["toll"])
        _csvio.write(p, header, rows)

    def _apply_od_edits(self, folder, ops):
        for df in self._demand_basenames():
            p = os.path.join(folder, df)
            if not os.path.exists(p):
                continue
            header, rows = _csvio.read(p)
            for r in rows:
                o, d = str(r.get("o_zone_id")), str(r.get("d_zone_id"))
                mult = 1.0
                for e in ops:
                    if (e["o"] is None or o in e["o"]) and (e["d"] is None or d in e["d"]):
                        mult *= e["factor"]
                if mult != 1.0:
                    r["volume"] = repr((_f(r.get("volume")) or 0.0) * mult)
            _csvio.write(p, header, rows)

    def run_day_to_day(self, days, policy_fn=None, carry_policy=False,
                       max_iter=20, gap=0.001, override="tapci-d2d", exe=None,
                       record=("vmt", "vht", "mean_speed_mph", "loaded_links")):
        """[Cat 2] Offline day-to-day loop -- the one-period ENVIRONMENT driven for
        ``days`` days. Each day, optionally call ``policy_fn(day, self)`` (the EXTERNAL
        information-provision / choice / RL logic, free to read observe_skims()/
        observe_links() and apply set_toll/set_od_multiplier/... edits), optionally
        carry yesterday's routing policy (DTAC) forward as today's warm start
        (``carry_policy`` -- day-to-day route learning), run one-period assignment, and
        record the chosen MOEs. Returns the day-by-day history (list of dicts).

        The day-to-day / information-provision LOGIC lives in ``policy_fn`` (external);
        TAPCI just orchestrates: hand today's state to the policy, apply its edits, run,
        observe. This is offline (repeated one-period), not a resident dynamic loading.
        """
        prev_policy = None
        history = []
        for day in range(int(days)):
            if policy_fn is not None:
                policy_fn(day, self)
            if carry_policy:
                self._settings["column_output"] = 2       # write today's DTAC
                if prev_policy:
                    self.load_routing_policy(prev_policy)  # seed from yesterday
            self.run_until_converged(max_iter=max_iter, gap=gap,
                                     override=override, exe=exe)
            moe = self.moe()
            row = {"day": day}
            row.update({k: moe.get(k) for k in record})
            try:
                row["final_gap_pct"] = self.observe_convergence()[-1]["gap_pct"]
            except (IndexError, KeyError, RuntimeError):
                row["final_gap_pct"] = None
            history.append(row)
            if carry_policy:
                prev_policy = os.path.join(
                    self._result.run_dir, "route_columns.bin")
                if not os.path.exists(prev_policy):
                    prev_policy = None
        return history

    def close(self):
        """Remove the scenario-edit working copy, if any."""
        if self._work and os.path.isdir(self._work):
            shutil.rmtree(self._work, ignore_errors=True)
        self._work = None

    # =====================================================================
    # Category 3 -- DYNAMIC / LIVE CONTROL / STEP (roadmap)
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

    def set_information_provision(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(
            what="information-provision control (message -> path-response experiment)"))

    def set_loading_policy(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(what="network-loading policy control"))

    def set_vdf_parameters(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(
            what="per-link VDF alpha/beta edits (next-run; tractable next, not yet wired)"))

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
                "query_paths", "save_paths", "save_routing_policy", "load_routing_policy",
                "observe_skims", "query_skim", "save_skims",
                "set_link_capacity", "set_link_closure", "set_toll", "set_od_multiplier",
                "clear_edits", "run_day_to_day", "close"],
            3: ["run_iteration", "load_paths", "set_routing_policy_from_paths",
                "set_information_provision", "set_loading_policy", "set_vdf_parameters"],
        }

    def __repr__(self):
        state = "no-run" if self._result is None else (
            "ok" if self._result.ok else "failed")
        return f"<TAPCI {self.network!r} settings={self._settings} [{state}]>"
