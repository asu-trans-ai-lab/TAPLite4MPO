"""MPO data intake — turn a raw agency hand-off into a TAPLite-ready scenario through a
*guided, auditable* process instead of guesswork.

The problem this solves: an MPO hands over a shapefile + a demand matrix and a couple of
"alpha/beta" numbers. Those files CANNOT tell you the things that actually decide whether
the assignment is right: is the capacity hourly, period, or daily? what is the peak-load
factor? are lengths miles or metres? are trips vehicles or persons? Picking an answer and
running is how you get a plausible-looking, wrong result.

`intake` reads the converted GMNS scenario together with the MPO's **declaration file**
(`submission.yml`, filled from `templates/mpo_submission_template.yml`) and produces:

  * intake_issues.json  — machine-readable issues (BLOCKER / DECISION / MISSING / INFO)
  * intake_log.md       — the conversion/validation steps + every assumption, time-ordered
  * intake_dashboard.html — a self-contained dashboard that lists the issues and GUIDES the
                            user through filling the missing declarations, then emits the
                            resolved submission.yml to paste back and re-run.

It never invents a convention. Anything the MPO did not declare becomes an issue that names
the exact field to provide and why it matters. Run it, read the report, fill the gaps,
re-run — until there are no BLOCKERs left; only then is the scenario ready to assign.

CLI:  python -m dtalite_qa intake <scenario> [--submission <file>] [--out <dir>]
"""
import json
import os
import statistics

from . import csvio

# ---- the declaration contract: things a shapefile/matrix can't carry -------------------
# sev: BLOCKER (cannot assign correctly without it) | DECISION (must choose; risky default)
#      | MISSING (default applied, but record it)
DECLARATIONS = [
    dict(key="capacity_basis", sev="BLOCKER", options=["per_lane", "per_link"],
         label="Capacity basis",
         help="Is the GMNS 'capacity' column per LANE or per LINK? DTALite expects per-lane.",
         why="Wrong basis scales every D/C by the lane count — silently."),
    dict(key="capacity_period", sev="BLOCKER", options=["hourly", "period", "daily"],
         label="Capacity time basis",
         help="Does that capacity represent one HOUR, the whole assignment PERIOD, or a DAY?",
         why="A daily capacity makes a peak run look empty (median V/C ~0); an hourly cap "
             "over a multi-hour period over-states congestion. This is the #1 hand-off error."),
    dict(key="capacity_source_field", sev="MISSING", options=None,
         label="Capacity source column",
         help="Original column used for capacity (e.g. AB_CAP_PK, AMCAPACITY).",
         why="Provenance — so a reviewer can re-derive it."),
    dict(key="peak_load_factor", sev="DECISION", options=None,
         label="Peak load factor (PLF=phi/L)",
         help="0<PLF<=1. Converts period demand to the peak-hour load the capacity is sized "
             "for. If unknown, give phi_hour_to_period instead and PLF=phi/L is computed.",
         why="Flat PLF=1 over a multi-hour period under-states peak congestion."),
    dict(key="length_unit", sev="BLOCKER", options=["mi", "m", "km"],
         label="Length unit",
         help="Unit of the GMNS 'length' column.",
         why="Mislabelled metres-as-miles inflates distance-based cost ~1609x."),
    dict(key="speed_unit", sev="DECISION", options=["mph", "kmh"],
         label="Speed unit",
         help="Unit of free_speed / vdf_free_speed.",
         why="Drives free-flow time; mph vs kmh is a 1.6x error."),
    dict(key="demand_kind", sev="DECISION", options=["vehicle_trips", "person_trips"],
         label="Demand kind",
         help="Are matrix cells vehicles or persons? If persons, give occupancy.",
         why="Person trips loaded as vehicles over-load the network by the occupancy factor."),
    dict(key="demand_period_hours", sev="DECISION", options=None,
         label="Demand period (hours)",
         help="How many hours the demand matrix spans (should match the assignment period).",
         why="Sets the hourly load the kernel compares to capacity."),
    dict(key="zone_id_basis", sev="MISSING", options=None,
         label="Zone-id basis",
         help="How matrix row/col labels map to GMNS zone_id (e.g. 'matrix label = original "
             "centroid node id -> ZONE field').",
         why="A silent off-by-mapping scrambles the whole OD table."),
    dict(key="vot", sev="DECISION", options=None,
         label="Value of time ($/hr)",
         help="Used in generalized cost; per class if multiclass.",
         why="Wrong VOT mis-weights tolls/distance vs time."),
    dict(key="vdf_source", sev="MISSING", options=None,
         label="VDF parameter source",
         help="Provenance of alpha/beta (e.g. 'HCM default', 'calibrated 2019 counts').",
         why="'alpha/beta' with no provenance can't be trusted or reproduced."),
    dict(key="count_field", sev="MISSING", options=None,
         label="Count / reference-volume field",
         help="Observed-count or model ref-volume column for validation (or 'none').",
         why="Without it the run can't be validated against reality."),
]
REQUIRED_KEYS = [d["key"] for d in DECLARATIONS]
_TODO = {"", "todo", "tbd", "?", "none-given", "fill", "fixme"}


def parse_submission(path):
    """Minimal flat 'key: value' parser (stdlib; no yaml dependency)."""
    decl = {}
    if not path or not os.path.exists(path):
        return decl
    for raw in open(path, encoding="utf-8-sig"):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or ":" not in line:
            continue
        k, v = line.split(":", 1)
        decl[k.strip()] = v.strip()
    return decl


def _declared(decl, key):
    v = decl.get(key, "")
    return v if str(v).strip().lower() not in _TODO else ""


def _stat(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return dict(n=len(vals), min=min(vals), med=statistics.median(vals), max=max(vals))


def run_intake(scenario, submission=None, out_dir=None):
    out_dir = out_dir or scenario
    log = []
    issues = []
    facts = {}

    def step(msg): log.append(("STEP", msg))
    def note(msg): log.append(("NOTE", msg))
    def issue(sev, key, msg, why="", fix=""):
        issues.append(dict(severity=sev, field=key, message=msg, why=why, resolution=fix))

    step(f"intake scenario: {scenario}")
    sub_path = submission or os.path.join(scenario, "submission.yml")
    decl = parse_submission(sub_path)
    if decl:
        step(f"read declaration: {sub_path} ({len(decl)} keys)")
    else:
        step(f"no declaration found at {sub_path} — every required field is unverified")
        issue("BLOCKER", "submission.yml",
              "No MPO declaration file. The agency must supply submission.yml "
              "(from templates/mpo_submission_template.yml) describing the data.",
              "A shapefile + matrix cannot state capacity basis, PLF, units, or trip kind.",
              "Copy templates/mpo_submission_template.yml to the scenario as submission.yml and fill it.")

    # ---- read the GMNS data we DO have, and gather evidence --------------------------
    if csvio.exists(scenario, "link.csv"):
        lhdr, links = csvio.read(csvio.path(scenario, "link.csv"))
        facts["links"] = len(links)
        step(f"read link.csv: {len(links)} links, {len(lhdr)} columns")
        cap = [csvio.fnum(r.get("capacity"), None) for r in links if csvio.is_num(r.get("capacity"))]
        cap_real = [c for c in cap if c and c < 90000]          # drop connector sentinels
        facts["capacity"] = _stat(cap_real)
        length = [csvio.fnum(r.get("length"), None) for r in links if csvio.is_num(r.get("length"))]
        facts["length"] = _stat(length)
        plf = set(round(csvio.fnum(r.get("vdf_plf", r.get("VDF_plf")), 1.0), 4) for r in links)
        facts["plf_values"] = sorted(plf)
        fs = [csvio.fnum(r.get("vdf_free_speed_mph", r.get("free_speed")), None) for r in links]
        facts["free_speed"] = _stat([s for s in fs if s])
    else:
        issue("BLOCKER", "link.csv", "No link.csv in scenario.", fix="Run the network converter first.")
        lhdr, links = [], []

    # period length from settings
    L = None
    if csvio.exists(scenario, "settings.csv"):
        _, srows = csvio.read(csvio.path(scenario, "settings.csv"))
        if srows:
            h0 = csvio.fnum(srows[0].get("demand_period_starting_hours"), None)
            h1 = csvio.fnum(srows[0].get("demand_period_ending_hours"), None)
            if h0 is not None and h1 is not None and h1 > h0:
                L = h1 - h0
                step(f"assignment period = {h0:g}..{h1:g} h  (L={L:g} hours)")
    facts["period_hours"] = L

    # ---- declaration completeness: the core of the intake ----------------------------
    for d in DECLARATIONS:
        val = _declared(decl, d["key"])
        if val:
            note(f"declared {d['key']} = {val}")
        else:
            issue(d["sev"], d["key"],
                  f"{d['label']} not declared.",
                  d["why"], f"Set `{d['key']}:` in submission.yml. {d['help']}")

    # ---- evidence-driven cross-checks (catch wrong declarations too) -----------------
    # capacity vs period sanity
    if facts.get("capacity"):
        c = facts["capacity"]
        note(f"capacity (non-connector): n={c['n']}, min={c['min']:.0f}, "
             f"median={c['med']:.0f}, max={c['max']:.0f}")
        cper = _declared(decl, "capacity_period")
        if cper == "daily" and L:
            issue("DECISION", "capacity_period",
                  "Capacity declared DAILY but used in a period assignment.",
                  "Daily capacity ~5-10x peak -> the run will look uncongested (median V/C ~0).",
                  "Provide an hourly or period capacity column, or a daily->period factor.")
        if not cper and L and L > 1 and (facts["plf_values"] == [1.0]):
            issue("BLOCKER", "capacity_period",
                  f"Capacity convention undeclared AND PLF is flat (=1) over a {L:g}-hour period.",
                  "D/C is undefined until you say whether capacity is hourly/period/daily and "
                  "give the peak-load factor.",
                  "Declare capacity_period and peak_load_factor (PLF=phi/L). See docs/peak_load_factor.md.")
    # length unit sanity
    if facts.get("length"):
        med = facts["length"]["med"]
        lu = _declared(decl, "length_unit")
        guess = "m" if med > 100 else "mi"
        note(f"length median = {med:.1f} -> looks like '{guess}'")
        if lu and lu != guess and not (lu == "km" and med > 1):
            issue("DECISION", "length_unit",
                  f"length_unit declared '{lu}' but median length {med:.1f} looks like '{guess}'.",
                  "A metres-as-miles mislabel inflates distance cost ~1609x.",
                  "Confirm the unit; the kernel divides length by 1609 when it expects metres.")
    # plf flat warning
    if L and L > 1 and facts.get("plf_values") == [1.0] and not _declared(decl, "peak_load_factor"):
        issue("DECISION", "peak_load_factor",
              f"vdf_plf is flat (=1) across a {L:g}-hour period.",
              "Peak-hour congestion is under-stated; D/C = period-average, not peak.",
              "Set peak_load_factor (=phi/L) by facility type. Run `dtalite_qa plf` for the inventory.")

    # demand zones present
    if csvio.exists(scenario, "node.csv"):
        _, nodes = csvio.read(csvio.path(scenario, "node.csv"))
        zones = set(csvio.inum(r["zone_id"]) for r in nodes
                    if csvio.is_num(r.get("zone_id")) and csvio.inum(r["zone_id"]) > 0)
        facts["zones"] = len(zones)
        step(f"read node.csv: {len(nodes)} nodes, {len(zones)} zones")

    # ---- assemble + write ------------------------------------------------------------
    order = {"BLOCKER": 0, "DECISION": 1, "MISSING": 2, "INFO": 3}
    issues.sort(key=lambda i: order.get(i["severity"], 9))
    counts = {s: sum(1 for i in issues if i["severity"] == s) for s in order}
    gate = "READY" if counts["BLOCKER"] == 0 else "BLOCKED"
    summary = dict(scenario=scenario, gate=gate, counts=counts, facts=facts,
                   declared=sorted(k for k in REQUIRED_KEYS if _declared(decl, k)),
                   issues=issues)

    os.makedirs(out_dir, exist_ok=True)
    json.dump(summary, open(os.path.join(out_dir, "intake_issues.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    open(os.path.join(out_dir, "intake_log.md"), "w", encoding="utf-8").write(_render_log(scenario, log, facts))
    open(os.path.join(out_dir, "intake_dashboard.html"), "w", encoding="utf-8").write(
        _render_html(summary, decl))
    return summary


def _render_log(scenario, log, facts):
    out = [f"# Intake log — {scenario}", "",
           "Time-ordered record of every step and assumption (the auditable trail).", ""]
    for kind, msg in log:
        out.append(f"- **{kind}** — {msg}")
    out += ["", "## Detected facts", ""]
    for k, v in facts.items():
        out.append(f"- `{k}` = {v}")
    out += ["", "_Generated by `dtalite_qa intake`. Resolve issues in intake_dashboard.html, "
            "fill submission.yml, and re-run until no BLOCKERs remain._"]
    return "\n".join(out) + "\n"


def _render_html(summary, decl):
    sev_color = {"BLOCKER": "#c0392b", "DECISION": "#d68910", "MISSING": "#2471a3", "INFO": "#555"}
    c = summary["counts"]
    gate = summary["gate"]
    gate_bg = "#1e8449" if gate == "READY" else "#c0392b"
    rows = []
    for i in summary["issues"]:
        col = sev_color.get(i["severity"], "#555")
        rows.append(f"""<tr>
          <td><span class="sev" style="background:{col}">{i['severity']}</span></td>
          <td><code>{i['field']}</code></td>
          <td><b>{i['message']}</b><div class="why">{i.get('why','')}</div>
              <div class="fix">→ {i.get('resolution','')}</div></td></tr>""")
    issue_rows = "\n".join(rows) or '<tr><td colspan="3">No issues 🎉</td></tr>'

    # guided form: one control per UNDECLARED required field
    from_decl = {d["key"]: d for d in DECLARATIONS}
    fields = []
    for d in DECLARATIONS:
        val = decl.get(d["key"], "")
        if str(val).strip().lower() in _TODO:
            val = ""
        if d["options"]:
            opts = "".join(f'<option {"selected" if val==o else ""}>{o}</option>' for o in [""] + d["options"])
            ctl = f'<select data-k="{d["key"]}">{opts}</select>'
        else:
            ctl = f'<input data-k="{d["key"]}" value="{val}" placeholder="...">'
        done = "done" if val else ""
        fields.append(f"""<div class="fld {done}">
          <label>{d['label']} <code>{d['key']}</code> <span class="sevtag" style="color:{sev_color[d['sev']]}">{d['sev']}</span></label>
          {ctl}
          <div class="help">{d['help']}<br><i>Why: {d['why']}</i></div></div>""")
    form_html = "\n".join(fields)

    facts = summary["facts"]
    ev = []
    if facts.get("capacity"):
        cc = facts["capacity"]
        ev.append(f"capacity (non-connector): median <b>{cc['med']:.0f}</b>, range {cc['min']:.0f}–{cc['max']:.0f}")
    if facts.get("length"):
        ev.append(f"length: median <b>{facts['length']['med']:.1f}</b> (>100 ⇒ likely metres)")
    if facts.get("period_hours"):
        ev.append(f"assignment period <b>{facts['period_hours']:g} h</b>")
    if facts.get("plf_values"):
        ev.append(f"vdf_plf values: {facts['plf_values']}")
    evidence = " · ".join(ev)

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>MPO intake — {summary['scenario']}</title>
<style>
 body{{font:14px/1.5 system-ui,Segoe UI,Arial;margin:0;color:#222;background:#f4f6f8}}
 header{{background:{gate_bg};color:#fff;padding:18px 26px}}
 header h1{{margin:0;font-size:20px}} header .gate{{font-size:28px;font-weight:700;letter-spacing:1px}}
 .wrap{{max-width:1080px;margin:0 auto;padding:20px 26px}}
 .pill{{display:inline-block;padding:2px 10px;border-radius:12px;color:#fff;margin-right:6px;font-size:12px}}
 table{{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px #0002}}
 td,th{{border-bottom:1px solid #eee;padding:8px 10px;vertical-align:top;text-align:left}}
 .sev{{color:#fff;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:700}}
 .why{{color:#666;font-size:12px;margin-top:3px}} .fix{{color:#1e6;color:#178a4c;font-size:12px;margin-top:3px}}
 .evidence{{background:#fff;border-left:4px solid #2471a3;padding:8px 12px;margin:14px 0;font-size:13px}}
 .fld{{background:#fff;border:1px solid #e2e6ea;border-left:4px solid #d68910;border-radius:6px;padding:10px 12px;margin:8px 0}}
 .fld.done{{border-left-color:#1e8449;opacity:.7}}
 .fld label{{font-weight:600}} .fld code{{color:#888;font-weight:400}}
 .fld input,.fld select{{margin-top:5px;width:340px;max-width:90%;padding:5px;border:1px solid #ccc;border-radius:4px}}
 .help{{color:#666;font-size:12px;margin-top:5px}}
 button{{background:#1e8449;color:#fff;border:0;padding:10px 18px;border-radius:6px;font-size:14px;cursor:pointer}}
 pre{{background:#1d2733;color:#dfe7ef;padding:14px;border-radius:6px;overflow:auto;white-space:pre-wrap}}
 h2{{margin-top:28px}} .sevtag{{font-size:11px;font-weight:700}}
</style></head><body>
<header><div class="wrap" style="max-width:1080px;padding:0">
  <h1>MPO data intake — {summary['scenario']}</h1>
  <div class="gate">{gate}</div>
  <div style="margin-top:6px">
   <span class="pill" style="background:#c0392b">{c['BLOCKER']} blocker</span>
   <span class="pill" style="background:#d68910">{c['DECISION']} decision</span>
   <span class="pill" style="background:#2471a3">{c['MISSING']} missing</span>
  </div></div></header>
<div class="wrap">
  <p>This scenario is <b>{gate}</b>. Resolve every <b>BLOCKER</b> (and ideally the
     decisions) by filling the declarations below, paste the generated block into
     <code>submission.yml</code>, and re-run <code>dtalite_qa intake</code>.</p>
  {"<div class='evidence'>Evidence from the data: " + evidence + "</div>" if evidence else ""}

  <h2>1. Issues</h2>
  <table><tr><th>Severity</th><th>Field</th><th>What & why / how to fix</th></tr>
  {issue_rows}</table>

  <h2>2. Guided declarations</h2>
  <p>Fill what you know (amber = still open, green = already declared). These are the facts
     the shapefile/matrix can't carry.</p>
  {form_html}
  <p style="margin-top:14px"><button onclick="gen()">⬇ Generate submission.yml</button></p>
  <pre id="out">// click Generate — then copy into &lt;scenario&gt;/submission.yml and re-run intake</pre>
</div>
<script>
function gen(){{
  var lines=["# resolved by intake dashboard — re-run: python -m dtalite_qa intake <scenario>"];
  document.querySelectorAll('[data-k]').forEach(function(el){{
    var v=el.value.trim(); if(v) lines.push(el.getAttribute('data-k')+": "+v);
  }});
  document.getElementById('out').textContent=lines.join("\\n");
}}
</script></body></html>"""
