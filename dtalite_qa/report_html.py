"""One self-contained HTML report fusing everything that already exists.

``build_report(run_dir)`` reads a finished kernel run folder and emits a single
report.html (no CDN, no external assets -- opens offline / behind an agency
firewall) that fuses:

  * network + OD summary and reproducibility metadata (from manifest.json)
  * convergence trace (report.parse_gap) as an inline SVG line
  * system MOE table (VMT / VHT / mean speed / loaded links, from the manifest)
  * V/C (doc) distribution histogram
  * the vizmap volume / V-C canvas map (inline, reuses vizmap.load + its script)
  * top loaded links table
  * volume-vs-reference scatter + %RMSE / R^2 (if ref_volume/ref_time present)

Pure stdlib. Reuses dtalite_qa.report, dtalite_qa.manifest, dtalite_qa.vizmap.

CLI: python -m dtalite_qa report-html <run_dir> [--out report.html]
     taplite report <run_dir>
"""
import html
import json
import os

from . import csvio
from . import manifest as _manifest
from . import report as _report
from . import vizmap as _vizmap


# ---------------------------------------------------------------------------
# small inline-SVG helpers (no matplotlib dependency)
# ---------------------------------------------------------------------------
def _svg_line(points, w=560, h=200, pad=34, ylabel="", color="#4aa3ff", logy=False):
    """A single-series line chart. points = [(x, y), ...]."""
    if not points:
        return "<p>(no data)</p>"
    import math
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if logy:
        ys = [math.log10(max(y, 1e-6)) for y in ys]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 == x0:
        x1 = x0 + 1
    if y1 == y0:
        y1 = y0 + 1
    def X(x): return pad + (x - x0) / (x1 - x0) * (w - pad - 8)
    def Y(y): return h - pad - (y - y0) / (y1 - y0) * (h - pad - 10)
    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
    grid = []
    for i in range(5):
        gy = y0 + (y1 - y0) * i / 4
        yy = Y(gy)
        raw = (10 ** gy) if logy else gy
        grid.append(f'<line x1="{pad}" y1="{yy:.1f}" x2="{w-8}" y2="{yy:.1f}" stroke="#2a2f38"/>'
                    f'<text x="4" y="{yy+3:.1f}" fill="#8a93a0" font-size="9">{raw:.3g}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px">'
            + "".join(grid)
            + f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/>'
            + "".join(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.4" fill="{color}"/>'
                      for x, y in zip(xs, ys))
            + f'<text x="{w/2:.0f}" y="{h-4}" fill="#8a93a0" font-size="10" '
              f'text-anchor="middle">{html.escape(ylabel)}</text></svg>')


def _svg_hist(values, bins, w=560, h=200, pad=34, color="#f1c40f", labels=None):
    if not values:
        return "<p>(no data)</p>"
    counts = [0] * (len(bins) - 1)          # one bucket per [bins[i], bins[i+1])
    for v in values:
        for i in range(len(bins) - 1):
            if bins[i] <= v < bins[i + 1]:
                counts[i] += 1
                break
        else:
            if v >= bins[-1]:
                counts[-1] += 1
    cmax = max(counts) or 1
    n = len(counts)
    bw = (w - pad - 8) / n
    bars, texts = [], []
    for i, c in enumerate(counts):
        bh = (c / cmax) * (h - pad - 12)
        x = pad + i * bw
        y = h - pad - bh
        bars.append(f'<rect x="{x+1:.1f}" y="{y:.1f}" width="{bw-2:.1f}" height="{bh:.1f}" fill="{color}"/>')
        lbl = (labels[i] if labels else f"{bins[i]:g}")
        texts.append(f'<text x="{x+bw/2:.1f}" y="{h-pad+11}" fill="#8a93a0" '
                     f'font-size="9" text-anchor="middle">{html.escape(str(lbl))}</text>')
        if c:
            texts.append(f'<text x="{x+bw/2:.1f}" y="{y-2:.1f}" fill="#c8ced6" '
                         f'font-size="9" text-anchor="middle">{c}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px">'
            + "".join(bars) + "".join(texts) + "</svg>")


def _svg_scatter(xy, w=420, h=380, pad=44, color="#2ecc71"):
    """Assigned (y) vs reference (x) scatter with a 45-degree line."""
    if not xy:
        return "<p>(no reference volumes)</p>"
    xs = [p[0] for p in xy]
    ys = [p[1] for p in xy]
    m = max(max(xs), max(ys)) or 1
    def X(x): return pad + (x / m) * (w - pad - 10)
    def Y(y): return h - pad - (y / m) * (h - pad - 10)
    dots = "".join(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2" fill="{color}" '
                   f'fill-opacity="0.5"/>' for x, y in xy)
    diag = f'<line x1="{X(0):.1f}" y1="{Y(0):.1f}" x2="{X(m):.1f}" y2="{Y(m):.1f}" stroke="#e74c3c" stroke-dasharray="4 3"/>'
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px">'
            f'<rect x="{pad}" y="8" width="{w-pad-10}" height="{h-pad-8}" fill="none" stroke="#2a2f38"/>'
            + diag + dots
            + f'<text x="{w/2:.0f}" y="{h-6}" fill="#8a93a0" font-size="10" text-anchor="middle">reference volume &#8594;</text>'
            + f'<text x="12" y="{h/2:.0f}" fill="#8a93a0" font-size="10" transform="rotate(-90 12 {h/2:.0f})" text-anchor="middle">assigned volume &#8594;</text>'
            + "</svg>")


# ---------------------------------------------------------------------------
def _gather(run_dir):
    rep = _report.build(run_dir)
    man = {}
    mp = os.path.join(run_dir, "manifest.json")
    if os.path.exists(mp):
        try:
            man = json.load(open(mp, encoding="utf-8"))
        except (ValueError, OSError):
            man = {}

    # V/C values + top loaded links from link_performance
    doc_vals, loaded = [], []
    p = os.path.join(run_dir, "link_performance.csv")
    if os.path.exists(p):
        _, rows = csvio.read(p)
        for r in rows:
            v = csvio.fnum(r.get("volume"))
            doc = csvio.fnum(r.get("doc"))
            if v > 0.5 and doc > 0:
                doc_vals.append(doc)
            loaded.append((v, r))
        loaded.sort(key=lambda t: -t[0])

    # reference scatter (assigned veh vs ref_volume) reuses report.build's join
    scatter = []
    lk_path = os.path.join(run_dir, "link.csv")
    if os.path.exists(lk_path) and os.path.exists(p):
        _, lp = csvio.read(p)
        _, lk = csvio.read(lk_path)
        tokens = _report._mode_tokens(run_dir)
        link = {(csvio.inum(r.get("from_node_id")), csvio.inum(r.get("to_node_id"))): r
                for r in lk}
        for r in lp:
            l = link.get((csvio.inum(r.get("from_node_id")), csvio.inum(r.get("to_node_id"))))
            if not l:
                continue
            rv = csvio.fnum(l.get("ref_volume"))
            if rv > 0:
                assigned = (sum(csvio.fnum(r.get(f"mod_vol_{t}")) for t in tokens)
                            if tokens else csvio.fnum(r.get("volume")))
                scatter.append((rv, assigned))
    return rep, man, doc_vals, loaded, scatter


def build_report(run_dir, out_html=None, project_name=None):
    """Write the fused report.html. Returns its path."""
    run_dir = os.path.abspath(run_dir)
    out_html = out_html or os.path.join(run_dir, "report.html")
    rep, man, doc_vals, loaded, scatter = _gather(run_dir)

    moe = (man.get("moe") if man else None) or _manifest._moe_from_link_performance(run_dir) or {}
    conv = man.get("convergence", {}) if man else {}
    files = man.get("files", {}) if man else {}
    settings = man.get("effective_settings", {}) if man else {}
    title = project_name or man.get("scenario") or os.path.basename(run_dir)

    # network / OD summary
    nodes = files.get("node.csv", {}).get("rows")
    links = files.get("link.csv", {}).get("rows", moe.get("links"))
    zones = None
    np_ = os.path.join(run_dir, "node.csv")
    if os.path.exists(np_):
        _, nr = csvio.read(np_)
        zones = len({csvio.inum(r.get("zone_id")) for r in nr
                     if csvio.is_num(r.get("zone_id")) and csvio.inum(r.get("zone_id")) > 0})
    trips = None
    dp = os.path.join(run_dir, "demand.csv")
    if os.path.exists(dp):
        _, dr = csvio.read(dp)
        trips = sum(csvio.fnum(r.get("volume")) for r in dr)

    # convergence chart
    traj = rep.get("gap_trajectory") or []
    conv_svg = _svg_line([(g["iter"], g["gap_pct"]) for g in traj if g["gap_pct"] > 0],
                         ylabel="relative gap % (log)", logy=True, color="#4aa3ff")

    # V/C histogram
    vc_bins = [0, .25, .5, .75, .9, 1.0, 1.1, 1.25, 1.5, 99]
    vc_labels = ["0", ".25", ".5", ".75", ".9", "1.0", "1.1", "1.25", ">1.5"]
    vc_svg = _svg_hist(doc_vals, vc_bins, labels=vc_labels, color="#f1c40f")
    n_over1 = sum(1 for v in doc_vals if v > 1.0)

    # scatter + validation stats
    ref_stats = (rep.get("reference_comparison") or {}).get("volume_vs_ref_volume")
    scatter_svg = _svg_scatter(scatter)

    # vizmap segments (reuse vizmap.load + its HTML canvas script)
    try:
        segs = _vizmap.load(run_dir)
    except Exception:
        segs = []

    # ---- assemble HTML ----
    def row(k, v):
        return f'<tr><td class="k">{html.escape(str(k))}</td><td>{v}</td></tr>'

    summary_rows = "".join([
        row("Project", html.escape(str(title))),
        row("Nodes", f"{nodes:,}" if nodes else "&mdash;"),
        row("Links", f"{links:,}" if links else "&mdash;"),
        row("Zones", f"{zones:,}" if zones else "&mdash;"),
        row("OD trips", f"{trips:,.0f}" if trips else "&mdash;"),
    ])
    moe_rows = "".join([
        row("System VMT", f"{moe.get('vmt', 0):,.0f}"),
        row("System VHT", f"{moe.get('vht', 0):,.0f}"),
        row("Mean speed (mph)", moe.get("mean_speed_mph") or "&mdash;"),
        row("Loaded links", f"{moe.get('loaded_links', 0):,} / {moe.get('links', 0):,}"),
        row("Final relative gap %",
            conv.get("final_gap_pct") or rep.get("final_gap_pct") or "&mdash;"),
        row("Iterations", conv.get("iterations", len(traj))),
        row("Links with V/C &gt; 1.0", f"{n_over1:,}"),
    ])

    repro_rows = "".join([
        row("Run folder", f'<code>{html.escape(run_dir)}</code>'),
        row("Schema version", man.get("schema_version", "&mdash;")),
        row("Kernel exe", html.escape(str((man.get("exe") or {}).get("path", "&mdash;")))),
        row("Kernel sha256", f'<code>{(man.get("exe") or {}).get("sha256", "")[:16]}...</code>'
            if man.get("exe") else "&mdash;"),
        row("Intake gate", f'<b>{html.escape(str(man.get("intake_gate", "?")))}</b>'),
        row("Override", html.escape(str(man.get("override"))) if man.get("override") else "none"),
        row("Created", html.escape(str(man.get("created", "&mdash;")))),
    ])
    file_rows = "".join(
        f'<tr><td class="k">{html.escape(n)}</td><td>{f.get("rows",0):,}</td>'
        f'<td><code>{f.get("sha256","")[:12]}</code></td></tr>'
        for n, f in sorted(files.items()))

    top_rows = "".join(
        f'<tr><td>{html.escape(str(r.get("link_id","")))}</td>'
        f'<td>{html.escape(str(r.get("from_node_id","")))}&#8594;{html.escape(str(r.get("to_node_id","")))}</td>'
        f'<td>{v:,.0f}</td><td>{csvio.fnum(r.get("doc")):.2f}</td>'
        f'<td>{csvio.fnum(r.get("speed_mph") or r.get("speed")):.1f}</td></tr>'
        for v, r in loaded[:20])

    ref_block = ""
    if ref_stats:
        r2 = ref_stats.get("r2")
        pr = ref_stats.get("pct_rmse")
        ref_block = f"""
      <div class="card">
        <h2>Assigned vs reference volume</h2>
        <div class="two">
          <div>{scatter_svg}</div>
          <div>
            <table>
              {row("Links compared", f"{ref_stats.get('n',0):,}")}
              {row("R&sup2;", f"{r2:.4f}" if r2 is not None else "&mdash;")}
              {row("RMSE", f"{ref_stats.get('rmse',0):,.1f}")}
              {row("%RMSE", f"{pr:.1f}%" if pr is not None else "&mdash;")}
              {row("Sum assigned", f"{ref_stats.get('sum_assigned',0):,.0f}")}
              {row("Sum reference", f"{ref_stats.get('sum_ref',0):,.0f}")}
            </table>
            <p class="note">Red dashed line = perfect fit (assigned = reference).</p>
          </div>
        </div>
      </div>"""
    else:
        ref_block = ('<div class="card"><h2>Assigned vs reference volume</h2>'
                     '<p class="note">No <code>ref_volume</code> column in link.csv &mdash; '
                     'validation deferred (never call a run &ldquo;validated&rdquo; without observed counts).</p></div>')

    # vizmap: embed its canvas script with our segments
    map_block = _MAP_TEMPLATE.replace("__SEGS__", json.dumps(segs)) if segs else \
        '<p class="note">(no drawable geometry)</p>'

    doc = _PAGE.format(
        title=html.escape(str(title)),
        summary_rows=summary_rows, moe_rows=moe_rows, repro_rows=repro_rows,
        file_rows=file_rows, top_rows=top_rows,
        conv_svg=conv_svg, vc_svg=vc_svg, ref_block=ref_block, map_block=map_block,
        n_seg=len(segs))
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_html


# vizmap canvas, trimmed to an embeddable block (no full <html> wrapper)
_MAP_TEMPLATE = """
<div class="mapbar">
  <label><input type="checkbox" id="conn"> connectors</label>
  <label>metric
    <select id="metric"><option value="doc">V/C</option>
      <option value="vol">volume</option><option value="spd">speed</option></select></label>
  <span class="lg" style="background:#2ecc71"></span>low
  <span class="lg" style="background:#f1c40f"></span>mid
  <span class="lg" style="background:#e74c3c"></span>high
  <span id="mapstat"></span>
</div>
<canvas id="cv" style="width:100%;height:520px;background:#0d0f13;border-radius:6px"></canvas>
<script>
const SEGS = __SEGS__;
const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
let xs=SEGS.map(s=>[s[0],s[2]]).flat(), ys=SEGS.map(s=>[s[1],s[3]]).flat();
const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
const vmax=Math.max(...SEGS.map(s=>s[4]),1);
function color(t){t=Math.max(0,Math.min(1,t));
 return t<0.5?`rgb(${46+t*2*(241-46)},${204+t*2*(196-204)},${113+t*2*(15-113)})`
            :`rgb(${241+(t-0.5)*2*(231-241)},${196+(t-0.5)*2*(76-196)},${15+(t-0.5)*2*(60-15)})`;}
function draw(){
 const W=cv.clientWidth,H=cv.clientHeight; cv.width=W; cv.height=H;
 const sc=Math.min(W/(x1-x0),H/(y1-y0))*0.96;
 const ox=(W-sc*(x1-x0))/2, oy=(H+sc*(y1-y0))/2;
 const X=x=>ox+sc*(x-x0), Y=y=>oy-sc*(y-y0);
 const showConn=document.getElementById('conn').checked;
 const m=document.getElementById('metric').value;
 ctx.clearRect(0,0,W,H); let loaded=0;
 for(const s of SEGS){ if(s[7]&&!showConn)continue;
  const [ax,ay,bx,by,v,doc,spd]=s; if(v>0.5)loaded++;
  let t=m==='doc'?doc:m==='vol'?v/vmax:1-Math.min(spd/70,1);
  ctx.strokeStyle=v>0.5?color(t):'#2a2f38';
  ctx.lineWidth=v>0.5?(0.6+3.5*Math.sqrt(v/vmax)):0.4;
  ctx.beginPath(); ctx.moveTo(X(ax),Y(ay)); ctx.lineTo(X(bx),Y(by)); ctx.stroke(); }
 document.getElementById('mapstat').textContent=`  ${SEGS.length} links, ${loaded} loaded, max vol ${Math.round(vmax)}`;
}
addEventListener('resize',draw);
document.getElementById('conn').onchange=draw;
document.getElementById('metric').onchange=draw;
draw();
</script>"""


_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>{title} &mdash; TAPLite4MPO report</title>
<style>
 :root{{color-scheme:dark}}
 body{{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:#0d0f13;color:#c8ced6}}
 header{{padding:18px 24px;background:#151a21;border-bottom:1px solid #232a33}}
 header h1{{margin:0;font-size:20px;color:#eef2f6}}
 header .sub{{color:#8a93a0;font-size:12px}}
 main{{max-width:1180px;margin:0 auto;padding:20px 24px 60px}}
 .grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
 .card{{background:#151a21;border:1px solid #232a33;border-radius:8px;padding:16px 18px;margin-bottom:18px}}
 .card.full{{grid-column:1/3}}
 h2{{margin:0 0 12px;font-size:15px;color:#eef2f6}}
 table{{border-collapse:collapse;width:100%}}
 td,th{{padding:4px 8px;border-bottom:1px solid #1e242c;text-align:left;font-size:13px}}
 td.k{{color:#8a93a0;white-space:nowrap}}
 td:nth-child(n+2){{font-variant-numeric:tabular-nums}}
 code{{background:#0d0f13;padding:1px 4px;border-radius:3px;color:#9ecbff;font-size:12px}}
 .note{{color:#8a93a0;font-size:12px}}
 .two{{display:grid;grid-template-columns:1fr 1fr;gap:14px;align-items:start}}
 .mapbar{{margin-bottom:8px;font-size:12px}} .mapbar label{{margin-right:14px}}
 .lg{{display:inline-block;width:11px;height:11px;vertical-align:-1px;margin:0 3px 0 10px;border-radius:2px}}
 .scroll{{overflow-x:auto}}
 @media(max-width:820px){{.grid{{grid-template-columns:1fr}}.card.full{{grid-column:1}}.two{{grid-template-columns:1fr}}}}
</style></head><body>
<header>
  <h1>{title}</h1>
  <div class="sub">TAPLite4MPO assignment report &mdash; static user equilibrium, no-guessing intake gate &amp; reproducibility manifest</div>
</header>
<main>
  <div class="grid">
    <div class="card"><h2>Network &amp; demand</h2><table>{summary_rows}</table></div>
    <div class="card"><h2>System MOE</h2><table>{moe_rows}</table></div>
  </div>

  <div class="grid">
    <div class="card"><h2>Convergence (relative gap by iteration)</h2>{conv_svg}</div>
    <div class="card"><h2>V/C distribution (loaded links)</h2>{vc_svg}</div>
  </div>

  {ref_block}

  <div class="card full"><h2>Assignment map ({n_seg} links)</h2>{map_block}</div>

  <div class="grid">
    <div class="card"><h2>Top 20 loaded links</h2>
      <div class="scroll"><table>
        <tr><th>link_id</th><th>from&#8594;to</th><th>volume</th><th>V/C</th><th>mph</th></tr>
        {top_rows}
      </table></div>
    </div>
    <div class="card"><h2>Reproducibility</h2><table>{repro_rows}</table>
      <h2 style="margin-top:14px">Input files (sha256)</h2>
      <div class="scroll"><table>
        <tr><th>file</th><th>rows</th><th>hash</th></tr>{file_rows}</table></div>
    </div>
  </div>
</main>
</body></html>"""
