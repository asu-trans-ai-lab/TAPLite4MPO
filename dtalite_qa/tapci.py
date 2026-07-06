"""TAPCI -- Traffic Assignment Programming/Control Interface (PREVIEW, 0.x).

The stable "build-on-top" surface for GMNS-based traffic assignment: open a
project, validate the intake gate, run to convergence, observe link/path/gap
state, and export. Inspired by the ecosystem role of SUMO's TraCI/libsumo, but
targeted at planning-scale assignment / ODME / corridor validation rather than
vehicle-level microsimulation -- so the unit of observation is an *assignment
iteration / link-time state*, never a vehicle.

    from taplite4mpo import TAPCI            # or: from dtalite_qa.tapci import TAPCI
    sim = TAPCI.open("project.yml", exe="bin/DTALite.exe")
    sim.validate()
    sim.run_until_converged(max_iter=50, gap=0.001)
    links = sim.observe_links(["volume", "speed", "vc"])
    sim.export("outputs/")

WHAT IS REAL IN THIS PREVIEW (batch style, backed by dtalite_qa.api):
  open / validate / run_until_converged / observe_links / observe_paths /
  observe_convergence / observe_manifest / moe / set_setting / export*.

WHAT IS ROADMAP (raises NotImplementedError with a pointer, does NOT fake it):
  step style (run_iteration) and live control (set_link_capacity/toll/vdf,
  set_od_multiplier, observe_od skims). These need a stepped/resident kernel and
  demand-edit plumbing (TAPCI 1.0 / DRC R3). The names exist here so the contract
  is legible and the error is precise instead of an AttributeError.

This is a thin, honest facade -- it adds NO solving logic of its own; every real
method delegates to the audited dtalite_qa.api layer (gate + manifest included).
"""
import os

from . import api as _api
from . import runconfig as _runconfig
from . import csvio as _csvio

_ROADMAP = ("TAPCI roadmap (not in this 0.x preview): {what}. "
            "The preview is batch-style -- open/validate/run_until_converged/"
            "observe_*/export. See private_docs/TAPCI_STRATEGY.md for the R2/R3 plan.")


class TAPCI:
    """A single assignment project: network + pending demand/settings + last run.

    Construct with :meth:`open`. The object is mutable across runs -- edit pending
    settings with :meth:`set_setting`, call :meth:`run_until_converged` again, and
    re-observe. The source network folder is never modified (runs happen in an
    isolated working copy, exactly as :class:`dtalite_qa.api.AssignmentEngine`).
    """

    def __init__(self, network, exe=None, settings=None, demand=None):
        self.network = network
        self.exe = exe
        self._settings = dict(settings or {})
        self._demand = demand
        self._result = None            # dtalite_qa.api.Result of the last run

    # -- A. load ------------------------------------------------------------
    @classmethod
    def open(cls, project, exe=None):
        """Open a project.yml run-config OR a GMNS scenario folder.

        A ``.yml``/``.yaml`` path is parsed as a run-config (its ``input.scenario_folder``,
        ``assignment`` settings, and ``exe`` become the pending state). A directory is
        read as a GMNS network folder directly.
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

    # -- B. validate + run --------------------------------------------------
    def validate(self):
        """Run the intake gate + schema/accessibility checks; returns the prepare() dict."""
        from . import control as _control
        return _control.prepare(self.network.folder)

    def run_until_converged(self, max_iter=None, gap=None, exe=None,
                            override=None, timeout=1800):
        """Solve to convergence (batch). Returns self so calls can chain.

        ``max_iter`` -> ``iterations``; ``gap`` (a fraction, e.g. 0.001 = 0.1%) ->
        ``gap_tolerance`` as a percent. Other pending settings from :meth:`set_setting`
        / the opened config are carried through. The kernel exe must be given here,
        at :meth:`open`, or on the object.
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

    def run_iteration(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(
            what="step-style run_iteration (one FW iteration with hand-back) needs a "
                 "stepped/resident kernel"))

    # -- C. observe (read-only; real once a run has produced outputs) --------
    def _require_run(self):
        if self._result is None:
            raise RuntimeError("no run yet: call run_until_converged() first")
        return self._result

    def observe_links(self, variables=None):
        """link_performance rows, optionally projected to ``variables`` (aliased).

        ``variables`` accepts friendly names (volume, speed, vc, travel_time) mapped to
        the link_performance columns; unknown names pass through verbatim. Returns a
        list of dicts.
        """
        rows = self._require_run().link_volumes()
        if not variables:
            return rows
        alias = {"volume": "volume", "speed": "speed_mph", "vc": "doc",
                 "travel_time": "travel_time", "vmt": "VMT", "vht": "VHT"}
        keep = [alias.get(v, v) for v in variables]
        out = []
        for r in rows:
            o = {"link_id": r.get("link_id")}
            for want, col in zip(variables, keep):
                o[want] = r.get(col)
            out.append(o)
        return out

    def observe_paths(self, variables=None):
        """route_assignment.csv rows (requires the run to have had route_output on).

        Raises a clear message if no path file was written, rather than returning an
        empty list that reads as "no paths".
        """
        run_dir = self._require_run().run_dir
        p = os.path.join(run_dir, "route_assignment.csv")
        if not os.path.exists(p):
            raise RuntimeError(
                "no route_assignment.csv in the run -- set route_output=1 (via "
                "set_setting(route_output=1)) before run_until_converged() to observe paths")
        _, rows = _csvio.read(p)
        if not variables:
            return rows
        return [{v: r.get(v) for v in ["o_zone_id", "d_zone_id", *variables]} for r in rows]

    def observe_convergence(self):
        """Per-iteration gap trajectory (list of dicts)."""
        return self._require_run().convergence()

    def observe_manifest(self):
        """The run manifest dict (version, hashes, effective settings, MOE, gate)."""
        return self._require_run().manifest

    def moe(self):
        """System MOEs: VMT / VHT / mean speed / loaded links."""
        return self._require_run().moe()

    def observe_od(self, *a, **k):
        raise NotImplementedError(_ROADMAP.format(
            what="OD skim observation (needs the skim writer / Path4GMNS hook)"))

    # -- D. control / modify (honest: next-run scenario edits) --------------
    def set_setting(self, **kwargs):
        """Set pending kernel settings (friendly aliases OK) applied on the NEXT run.

        Real and backed today: anything the kernel reads from settings.csv
        (iterations, gap_tolerance, warm_start_columns, column_adjust_sweeps,
        route_output, vdf_* defaults, ...). Returns self.
        """
        self._settings.update(kwargs)
        return self

    def _roadmap_control(self, what):
        raise NotImplementedError(_ROADMAP.format(what=what + " (next-run scenario edit; "
                                  "planned for TAPCI R2 -- edits link.csv/demand in the "
                                  "working copy before the next run)"))

    def set_link_capacity(self, *a, **k): self._roadmap_control("set_link_capacity")
    def set_link_closure(self, *a, **k):  self._roadmap_control("set_link_closure")
    def set_toll(self, *a, **k):          self._roadmap_control("set_toll")
    def set_vdf_parameters(self, *a, **k): self._roadmap_control("set_vdf_parameters")
    def set_od_multiplier(self, *a, **k):  self._roadmap_control("set_od_multiplier")

    # -- E. export ----------------------------------------------------------
    def export(self, folder):
        """Copy the last run to a durable folder; returns the path."""
        return self._require_run().export(folder)

    def export_report(self, out_html=None):
        """Build the self-contained HTML report for the last run; returns its path."""
        from . import report_html as _rh
        run_dir = self._require_run().run_dir
        out_html = out_html or os.path.join(run_dir, "report.html")
        _rh.build_report(run_dir, out_html)
        return out_html

    def __repr__(self):
        state = "no-run" if self._result is None else (
            "ok" if self._result.ok else "failed")
        return f"<TAPCI {self.network!r} settings={self._settings} [{state}]>"
