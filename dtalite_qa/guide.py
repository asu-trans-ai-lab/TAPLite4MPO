"""Generate the generalized MPO onboarding guideline as a single self-contained HTML page.

This is the front door for students and MPO users: the whole staged journey from a raw
GIS hand-off to a validated, traceable assignment — what you provide, what you run, what
you get, and the gate at each stage. It is generated from the live schema (the intake
declarations, the R1-R6 workflow) so it never drifts from the tools.

CLI:  python -m dtalite_qa guide [--out onboarding_guide.html]
"""
import os
from . import intake as _intake

# NeXTA-style GIS field mapping (shapefile field -> GMNS), distilled from the classic
# import_GIS_settings.csv. "default from link_type" means the value can be filled by the
# link_type table instead of a source column.
GIS_FIELD_MAP = [
    ("link", "from_node_id", "A", "required", "or inferred from geometry"),
    ("link", "to_node_id", "B", "required", "or inferred from geometry"),
    ("link", "link_type / facility_type", "FT", "required", "default = 1"),
    ("link", "length", "DISTANCE", "desired", "unit must be declared (mi/m/km)"),
    ("link", "lanes", "LANES", "desired", "or default from link_type"),
    ("link", "capacity", "CAP1HR1LN", "desired", "per-lane vs per-link + hourly/period/daily must be declared"),
    ("link", "free_speed", "SFF", "desired", "or default from link_type; unit (mph/kmh) declared"),
    ("link", "vdf_alpha / vdf_beta", "ALPHA / BETA", "desired", "provenance must be declared"),
    ("link", "allowed_use", "(from FT / PROHIBIT)", "desired", "HOV/truck/managed-lane permissions"),
    ("node", "node_id", "N", "required", "centroid node_id must equal zone_id"),
    ("node", "zone_id / TAZ", "TAZID", "desired", "centroids only"),
    ("zone", "zone_id", "Id", "desired", "required if a zone layer is given"),
]

# the staged journey
STAGES = [
    dict(n=0, key="gis", title="GIS import & field mapping",
         icon="🗺️", gate="every required GMNS field mapped or defaulted",
         provide=["link / node / (zone) shapefiles", "a field-mapping (which source column → which GMNS field)"],
         run=["map fields one-by-one (see the reference table below)",
              "the importer writes node.csv / link.csv and a conversion_log"],
         get=["node.csv, link.csv (GMNS)", "conversion_log.json (the field mapping + steps)"],
         body="A shapefile names fields its own way (`A`,`B`,`DISTANCE`,`CAP1HR1LN`…). "
              "Map each to its GMNS field. Anything you can't map gets a default from the "
              "link_type table — and is recorded. This is the only manual-ish step; the "
              "mapping is saved so it's reproducible, not redone by hand each time."),
    dict(n=1, key="declare", title="Declare the conventions",
         icon="📝", gate="every declaration field filled (no TODO)",
         provide=["submission.yml (from templates/mpo_submission_template.yml)"],
         run=["fill capacity basis/period, PLF, units, trip kind, VOT, count field, …"],
         get=["submission.yml — the README for your data"],
         body="The files can't state whether capacity is hourly/period/daily, what the "
              "peak-load factor is, or whether trips are vehicles or persons. You declare "
              "them. The tool never guesses these. ARC's Section-7 documentation is the model."),
    dict(n=2, key="convert", title="Convert & log",
         icon="⚙️", gate="conversion_log.json emitted; outputs present",
         provide=["the field mapping + submission.yml"],
         run=["run the converter (gsats_to_gmns / nexta / …)"],
         get=["GMNS scenario", "conversion_log.json (steps, mappings, assumptions, warnings)"],
         body="Every converter emits a step log — what it read, every field mapping, every "
              "assumption/default, every warning. The next stage ingests it, so the trail "
              "from raw files to GMNS is unbroken."),
    dict(n=3, key="intake", title="Intake audit — resolve iteratively",
         icon="🔍", gate="0 BLOCKERs (GATE: READY)",
         provide=["the GMNS scenario + submission.yml + conversion_log.json"],
         run=["python -m dtalite_qa intake <scenario>",
              "open intake_dashboard.html, fill gaps, re-run — until READY"],
         get=["intake_issues.json, intake_log.md, intake_dashboard.html"],
         body="The audit blocks on anything undeclared (capacity convention, PLF, units, "
              "trip kind) and cross-checks declarations against the data (e.g. length_unit=mi "
              "but median length 710 ⇒ metres). Run → read → resolve → re-run. This is the loop."),
    dict(n=4, key="quality", title="Data-quality & validation",
         icon="✅", gate="0 errors; all zones reachable per mode",
         provide=["the READY scenario"],
         run=["python -m dtalite_qa check <scenario>"],
         get=["input validation + accessibility report"],
         body="Structural checks the audit doesn't cover: schema/field validity, "
              "node/link consistency, demand zones present, per-mode connectivity."),
    dict(n=5, key="run", title="Run the assignment",
         icon="🚦", gate="converges; link_performance.csv written",
         provide=["the validated scenario + bin/DTALite.exe"],
         run=["python -m dtalite_qa run <scenario> --exe bin/DTALite.exe"],
         get=["link_performance.csv (volumes, V/C, speed, VMT/VHT, QVDF duration)"],
         body="Static user equilibrium (Frank-Wolfe / conjugate / bi-conjugate). "
              "QVDF also yields D/C-consistent congestion duration."),
    dict(n=6, key="workflow", title="Traceable workflow R1–R6",
         icon="📊", gate="all stages pass (VMT vs reference ≤ 5%, …)",
         provide=["the run output + a reference (counts / agency volumes)"],
         run=["python -m dtalite_qa workflow <scenario> [--reference …] [--period PM]"],
         get=["traceability/reports/00_traceability.md + tables/ + figures/ + dashboard"],
         body="The full auditable record: inventory → OD/allowed-use → capacity/VDF join → "
              "PLF → consistency → VMT/VHT validation, each gated."),
]

R1_R6 = [
    ("R1", "Inventory & directionality", "directed AB/BA present; network by FT-AT"),
    ("R2", "OD & allowed-uses", "demand totals by class; allowed_use flags"),
    ("R3", "Capacity & VDF join", "100% capacity + α/β join rate"),
    ("R4", "Period & PLF", "PLF declared / not flat over a multi-hour period"),
    ("R5", "TAP consistency", "model-vs-reference volume slope ≈ 1; problem links"),
    ("R6", "VMT/VHT validation", "total VMT vs reference ≤ 5%, by FT-AT"),
]


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html():
    # field-map table
    fmrows = "".join(
        f"<tr><td><span class=lay>{lay}</span></td><td><code>{_esc(g)}</code></td>"
        f"<td><code>{_esc(src)}</code></td><td>{req}</td><td>{_esc(note)}</td></tr>"
        for lay, g, src, req, note in GIS_FIELD_MAP)

    # declaration checklist from the live intake schema
    decl_rows = ""
    for d in _intake.DECLARATIONS:
        col = {"BLOCKER": "#c0392b", "DECISION": "#d68910", "MISSING": "#2471a3"}[d["sev"]]
        opts = (" — options: " + " / ".join(d["options"])) if d["options"] else ""
        decl_rows += (f"<li><code>{d['key']}</code> "
                      f"<span class=sev style='background:{col}'>{d['sev']}</span><br>"
                      f"<span class=hint>{_esc(d['help'])}{opts}<br><i>{_esc(d['why'])}</i></span></li>")

    # stage cards
    cards = ""
    for s in STAGES:
        prov = "".join(f"<li>{_esc(x)}</li>" for x in s["provide"])
        run = "".join(f"<li>{_esc(x)}</li>" for x in s["run"])
        get = "".join(f"<li>{_esc(x)}</li>" for x in s["get"])
        extra = ""
        if s["key"] == "gis":
            extra = ("<div class=ref><b>Field-mapping reference (source → GMNS)</b>"
                     "<table><tr><th>layer</th><th>GMNS field</th><th>typical source</th>"
                     f"<th>need</th><th>note</th></tr>{fmrows}</table></div>")
        if s["key"] == "declare":
            extra = f"<div class=ref><b>Declaration checklist</b><ul class=decl>{decl_rows}</ul></div>"
        if s["key"] == "workflow":
            wf = "".join(f"<tr><td><b>{a}</b></td><td>{b}</td><td>{c}</td></tr>" for a, b, c in R1_R6)
            extra = ("<div class=ref><b>R1–R6 stages &amp; gates</b><table>"
                     f"<tr><th>stage</th><th>focus</th><th>gate</th></tr>{wf}</table></div>")
        cards += f"""
        <section class=stage id=stage{s['n']}>
          <h2><label><input type=checkbox data-n={s['n']} onchange=prog()>
              <span class=ic>{s['icon']}</span> Stage {s['n']} — {_esc(s['title'])}</label>
              <span class=gate>gate: {_esc(s['gate'])}</span></h2>
          <p class=intro>{_esc(s['body'])}</p>
          <div class=cols>
            <div><h4>You provide</h4><ul>{prov}</ul></div>
            <div><h4>You run</h4><ul>{run}</ul></div>
            <div><h4>You get</h4><ul>{get}</ul></div>
          </div>{extra}
        </section>"""

    nav = "".join(f"<a href=#stage{s['n']}>{s['n']}. {_esc(s['title'])}</a>" for s in STAGES)

    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TAPLite4MPO — MPO Onboarding Guide</title><style>
 :root{{--b:#1e5aa8;--g:#1e8449}}
 *{{box-sizing:border-box}} body{{font:15px/1.6 system-ui,Segoe UI,Arial;margin:0;color:#1d2733;background:#eef2f6}}
 header{{background:linear-gradient(135deg,#1e5aa8,#123a6b);color:#fff;padding:26px 30px}}
 header h1{{margin:0 0 4px;font-size:23px}} header p{{margin:0;opacity:.9;max-width:760px}}
 .bar{{position:sticky;top:0;background:#fff;border-bottom:1px solid #dde3ea;padding:8px 30px;z-index:5;
   display:flex;gap:14px;align-items:center;flex-wrap:wrap;font-size:12.5px}}
 .bar a{{color:#1e5aa8;text-decoration:none}} .bar a:hover{{text-decoration:underline}}
 .pb{{flex:1;min-width:120px;height:8px;background:#e2e8f0;border-radius:5px;overflow:hidden}}
 .pb i{{display:block;height:100%;width:0;background:var(--g);transition:width .3s}}
 .wrap{{max-width:980px;margin:0 auto;padding:22px 30px}}
 .stage{{background:#fff;border:1px solid #e2e8f0;border-left:5px solid var(--b);border-radius:8px;
   padding:16px 20px;margin:16px 0;box-shadow:0 1px 3px #0001}}
 .stage h2{{font-size:17px;margin:0 0 8px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}}
 .stage h2 label{{cursor:pointer;display:flex;align-items:center;gap:9px}}
 .ic{{font-size:20px}} .gate{{font-size:12px;font-weight:400;color:#fff;background:#7a8aa0;padding:3px 9px;border-radius:11px}}
 .intro{{color:#445;margin:.3em 0 1em}}
 .cols{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}}
 .cols h4{{margin:0 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#1e5aa8}}
 .cols ul{{margin:0;padding-left:17px}} .cols li{{font-size:13.5px;margin:3px 0}}
 .ref{{margin-top:14px;background:#f7f9fc;border:1px solid #e2e8f0;border-radius:6px;padding:10px 14px}}
 table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:13px}}
 th,td{{border-bottom:1px solid #e6ebf1;padding:5px 8px;text-align:left;vertical-align:top}}
 th{{color:#5a6b80;font-weight:600}}
 .lay{{font-size:11px;background:#eaf0f7;color:#1e5aa8;padding:1px 6px;border-radius:8px}}
 code{{background:#eef2f7;padding:1px 5px;border-radius:4px;font-size:12.5px}}
 ul.decl{{list-style:none;padding:0;columns:1}} ul.decl li{{margin:7px 0;font-size:13.5px}}
 .sev{{color:#fff;font-size:10px;font-weight:700;padding:1px 6px;border-radius:4px}}
 .hint{{color:#667;font-size:12px}}
 @media(max-width:740px){{.cols{{grid-template-columns:1fr}}}}
 footer{{max-width:980px;margin:0 auto;padding:8px 30px 34px;color:#778;font-size:12.5px}}
</style></head><body>
<header><h1>TAPLite4MPO — MPO Onboarding Guide</h1>
<p>From a raw agency hand-off (shapefiles + a demand matrix) to a validated, <b>traceable</b>
assignment. Seven stages, each with a clear gate. Don't hand over just a shapefile — follow
the journey, declare your conventions, and let each stage check the last.</p></header>
<div class=bar><b>Progress</b><div class=pb><i id=pbi></i></div><span id=pct>0%</span>
{nav}</div>
<div class=wrap>{cards}</div>
<footer>Generated by <code>python -m dtalite_qa guide</code>. Companion docs:
<code>MPO_ONBOARDING_GUIDE.md</code>, <code>USER_GUIDE_VOL2_MPO.md</code>,
<code>examples/arc_atlanta/</code> (the model complete submission). Progress is saved in your browser.</footer>
<script>
 var N={len(STAGES)};
 function prog(){{
   var done=0; document.querySelectorAll('[data-n]').forEach(function(c){{
     if(c.checked) done++; localStorage.setItem('tap_stage_'+c.dataset.n, c.checked?1:0);
   }});
   var p=Math.round(done/N*100);
   document.getElementById('pbi').style.width=p+'%'; document.getElementById('pct').textContent=p+'%';
 }}
 document.querySelectorAll('[data-n]').forEach(function(c){{
   c.checked = localStorage.getItem('tap_stage_'+c.dataset.n)==='1';
 }});
 prog();
</script></body></html>"""


def write(out_path):
    html = render_html()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    open(out_path, "w", encoding="utf-8").write(html)
    return out_path
