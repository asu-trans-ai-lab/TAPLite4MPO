"""Self-contained HTML assignment-result map (volume / V-over-C / speed).

Reads a run folder (node.csv + link.csv + link_performance.csv) and writes
assignment_map.html: an interactive canvas map, no external dependencies or
tiles (works offline / behind agency firewalls). Link width ~ volume, color =
V/C (green->red), connectors hidden by default. This is the M3 quick-win of
docs/NEXTA_AI_INTEGRATION_ROADMAP.md — the 'see the assignment' step.

Usage: python -m dtalite_qa.vizmap <run_folder> [out.html]
"""
import csv
import json
import os
import sys


def load(scen):
    nodes = {}
    for r in csv.DictReader(open(os.path.join(scen, "node.csv"), encoding="utf-8-sig")):
        try:
            nodes[int(float(r["node_id"]))] = (float(r["x_coord"]), float(r["y_coord"]))
        except (KeyError, ValueError):
            continue
    links = []
    ltype = {}
    for r in csv.DictReader(open(os.path.join(scen, "link.csv"), encoding="utf-8-sig")):
        lid = r.get("link_id")
        ltype[lid] = r.get("link_type") or ""
        links.append(r)
    perf = {}
    p = os.path.join(scen, "link_performance.csv")
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        try:
            perf[r["link_id"]] = (float(r.get("volume") or 0), float(r.get("doc") or 0),
                                  float(r.get("speed_mph") or r.get("speed") or 0))
        except ValueError:
            continue
    segs = []
    for r in links:
        lid = r.get("link_id")
        if lid not in perf:
            continue
        try:
            a = nodes[int(float(r["from_node_id"]))]
            b = nodes[int(float(r["to_node_id"]))]
        except (KeyError, ValueError):
            continue
        v, doc, spd = perf[lid]
        conn = str(r.get("link_type")) in ("100", "100.0", "9")
        segs.append([round(a[0], 6), round(a[1], 6), round(b[0], 6), round(b[1], 6),
                     round(v, 1), round(doc, 3), round(spd, 1), 1 if conn else 0])
    return segs


HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Assignment map</title>
<style>
 body{margin:0;font:13px sans-serif;background:#111;color:#eee}
 #bar{position:fixed;top:0;left:0;right:0;background:#222;padding:6px 12px;z-index:2}
 #bar label{margin-right:14px} canvas{display:block}
 .lg{display:inline-block;width:12px;height:12px;vertical-align:-2px;margin:0 3px 0 10px}
</style></head><body>
<div id="bar">
 <b>TAPLite assignment</b>
 <label><input type="checkbox" id="conn"> show connectors</label>
 <label>metric <select id="metric"><option value="doc">V/C</option>
   <option value="vol">volume</option><option value="spd">speed</option></select></label>
 <span class="lg" style="background:#2ecc71"></span>low
 <span class="lg" style="background:#f1c40f"></span>mid
 <span class="lg" style="background:#e74c3c"></span>high
 <span id="stat"></span>
</div>
<canvas id="cv"></canvas>
<script>
const SEGS = __SEGS__;
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
let xs=SEGS.map(s=>[s[0],s[2]]).flat(), ys=SEGS.map(s=>[s[1],s[3]]).flat();
const x0=Math.min(...xs), x1=Math.max(...xs), y0=Math.min(...ys), y1=Math.max(...ys);
const vmax = Math.max(...SEGS.map(s=>s[4]), 1);
function color(t){ t=Math.max(0,Math.min(1,t));
  return t<0.5 ? `rgb(${46+t*2*(241-46)},${204+t*2*(196-204)},${113+t*2*(15-113)})`
               : `rgb(${241+(t-0.5)*2*(231-241)},${196+(t-0.5)*2*(76-196)},${15+(t-0.5)*2*(60-15)})`; }
function draw(){
  const W=innerWidth, H=innerHeight-34; cv.width=W; cv.height=H; cv.style.marginTop='34px';
  const sc=Math.min(W/(x1-x0), H/(y1-y0))*0.97;
  const ox=(W-sc*(x1-x0))/2, oy=(H+sc*(y1-y0))/2;
  const X=x=>ox+sc*(x-x0), Y=y=>oy-sc*(y-y0);
  const showConn=document.getElementById('conn').checked;
  const m=document.getElementById('metric').value;
  ctx.clearRect(0,0,W,H); let loaded=0;
  for(const s of SEGS){
    if(s[7] && !showConn) continue;
    const [ax,ay,bx,by,v,doc,spd]=s;
    if(v>0.5) loaded++;
    let t = m==='doc'?doc : m==='vol'?v/vmax : 1-Math.min(spd/70,1);
    ctx.strokeStyle = v>0.5?color(t):'#333';
    ctx.lineWidth = v>0.5? (0.6+3.5*Math.sqrt(v/vmax)) : 0.4;
    ctx.beginPath(); ctx.moveTo(X(ax),Y(ay)); ctx.lineTo(X(bx),Y(by)); ctx.stroke();
  }
  document.getElementById('stat').textContent =
    `  ${SEGS.length} links, ${loaded} loaded, max vol ${Math.round(vmax)}`;
}
addEventListener('resize',draw);
document.getElementById('conn').onchange=draw;
document.getElementById('metric').onchange=draw;
draw();
</script></body></html>"""


def main():
    scen = sys.argv[1] if len(sys.argv) > 1 else "."
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(scen, "assignment_map.html")
    segs = load(scen)
    with open(out, "w", encoding="utf-8") as f:
        f.write(HTML.replace("__SEGS__", json.dumps(segs)))
    print(f"assignment map: {len(segs)} drawable links -> {out}")


if __name__ == "__main__":
    main()
