"""LRS -> GMNS conflation (WP_LRS2GMNS, P1: harvest + anchors + AZGeo client).

Adds route_id / corridor_name / milepost attribution to a GMNS (or AZTDM) network
so scenarios can be defined by the agency's own referencing ("I-17 SB MP 298-314").

P1 scope (no geometry matching yet):
  * fetch_azgeo()   -- paginated, disk-cached client for the AZGeo REST layers
                       (ATIS Roads PolylineM via returnM, Mileposts points).
  * decode_name()   -- ADOT naming convention: '008100E' = route 008 (I-8),
                       MP 100, direction/ramp letter E. Free route+MP anchors.
  * tier0()         -- harvest route identity + name-decoded MP anchors from the
                       network's own attribute table (no LRS data needed).
  * validate_anchors() -- ground-truth check vs hand-coded TIP MILESTART/MILEEND.

Tier 1 (endpoint projection onto measured routes) and Tier 2 (HMM route-trace
matching) build on these anchors -- see docs/WP_LRS2GMNS.md.
"""
import json
import os
import re
import urllib.parse
import urllib.request

AZGEO = "https://azgeo.az.gov/arcgis/rest/services/adot"
LAYERS = {
    "atis_roads": f"{AZGEO}/ATIS_Roads/MapServer/0",
    "mileposts": f"{AZGEO}/Mileposts/MapServer/0",
}
_ROUTE_PREFIX = {"I": "I", "U": "US", "S": "SR", "B": "BUS", "L": "SR"}  # AZ Loops are SR
# Arizona route systems are number-unambiguous statewide (an interstate number is
# never also a US/SR number). Static inventory for prefixing decoded numbers.
AZ_INTERSTATES = {8, 10, 11, 15, 17, 19, 40}
AZ_US_ROUTES = {60, 64, 70, 89, 91, 93, 95, 160, 163, 180, 191}


def az_prefix(num):
    return "I" if num in AZ_INTERSTATES else ("US" if num in AZ_US_ROUTES else "SR")


def fetch_azgeo(layer, where="1=1", out_fields="*", cache_dir="azgeo_cache",
                return_m=True, out_sr=4326, page=1000, max_records=200000):
    """Download a full AZGeo layer via paginated REST queries; cache to disk so the
    pipeline is reproducible offline. Returns the list of esriJSON features."""
    url = LAYERS.get(layer, layer)
    os.makedirs(cache_dir, exist_ok=True)
    key = re.sub(r"\W+", "_", f"{layer}_{where}_{out_fields}_{out_sr}_{return_m}")[:120]
    cpath = os.path.join(cache_dir, key + ".json")
    if os.path.exists(cpath):
        return json.load(open(cpath, encoding="utf-8"))
    feats, offset = [], 0
    while offset < max_records:
        q = urllib.parse.urlencode({
            "where": where, "outFields": out_fields, "f": "json",
            "returnGeometry": "true", "returnM": "true" if return_m else "false",
            "outSR": out_sr, "resultOffset": offset, "resultRecordCount": page})
        with urllib.request.urlopen(f"{url}/query?{q}", timeout=120) as r:
            data = json.loads(r.read().decode("utf-8"))
        got = data.get("features", [])
        feats.extend(got)
        if len(got) < page or not data.get("exceededTransferLimit", len(got) == page):
            if len(got) < page:
                break
        offset += page
    json.dump(feats, open(cpath, "w", encoding="utf-8"))
    return feats


# ---- ADOT naming convention decoders ----------------------------------------
# mainline/ramp segment name: RRRMMM[L]  e.g. 008100E -> route 008, MP 100, E
_SEG = re.compile(r"^\s*(\d{3})(\d{3})([A-Z]{1,2})\s*$")
# free text: 'WB US60 EX 176A ON' -> route US-60, exit(~MP) 176, WB, on-ramp
_FREE = re.compile(r"\b(?:(WB|EB|NB|SB)\s+)?(I|US|SR|L(?:OOP)?)\s*-?\s*(\d{1,3})"
                   r"(?:.*?\bEX(?:IT)?\s*(\d{1,3}))?", re.I)


def decode_name(name, staterts=None):
    """Decode a link name to (route_id, mp, direction) or None.
    route number alone is ambiguous between I/US/SR; disambiguate with the
    known state-route inventory when provided (dict num -> prefix)."""
    if not name:
        return None
    m = _SEG.match(str(name))
    if m:
        num = int(m.group(1))
        mp = float(m.group(2))
        letter = m.group(3)
        pre = (staterts or {}).get(num) or az_prefix(num)
        rid = f"{pre}-{num}"
        d = letter if letter in ("N", "S", "E", "W") else ""
        return {"route_id": rid, "mp": mp, "dir": d, "kind": "segment_name"}
    m = _FREE.search(str(name))
    if m and m.group(4):        # only trust free text when an exit number exists
        pre = {"I": "I", "US": "US", "SR": "SR", "L": "SR", "LOOP": "SR"}[m.group(2).upper()]
        return {"route_id": f"{pre}-{int(m.group(3))}", "mp": float(m.group(4)),
                "dir": (m.group(1) or "").upper(), "kind": "free_text"}
    return None


def norm_arnold_route(route_id_field):
    """'  I 008   ' / '  I 008  0 ' (non-cardinal) -> ('I-8', cardinal_bool)."""
    s = str(route_id_field).strip()
    m = re.match(r"^(I|U S|US|S R|SR|B)\s*0*(\d+)\s*(\S*)$", s)
    if not m:
        return None, None
    pre = {"I": "I", "US": "US", "U S": "US", "SR": "SR", "S R": "SR", "B": "BUS"}[m.group(1)]
    return f"{pre}-{int(m.group(2))}", (m.group(3) == "")


def tier0(rows, name_col="ROAD_01", statert_col="AZ_STATERT"):
    """Harvest route identity + name-decoded MP anchors from a link table
    (list of dicts). Returns (anchors, stats). Non-destructive."""
    # build the route-number -> prefix inventory from links that carry STATERT
    staterts = {}
    num_re = re.compile(r"^\s*0*(\d{1,3})\s*$")
    for r in rows:
        st = (r.get(statert_col) or "").strip() if statert_col else ""
        nm = num_re.match(str(r.get(name_col) or ""))
        if st in _ROUTE_PREFIX and nm:
            staterts[int(nm.group(1))] = _ROUTE_PREFIX[st]
    anchors, n_seg, n_free = [], 0, 0
    for i, r in enumerate(rows):
        d = decode_name(r.get(name_col), staterts)
        if d:
            d["row"] = i
            anchors.append(d)
            if d["kind"] == "segment_name":
                n_seg += 1
            else:
                n_free += 1
    stats = {"rows": len(rows), "anchors": len(anchors),
             "segment_name": n_seg, "free_text": n_free,
             "route_inventory": {k: v for k, v in sorted(staterts.items())}}
    return anchors, stats


def validate_anchors(anchors, rows, mp_lo_col="MILESTART", mp_hi_col="MILEEND",
                     tol=1.0):
    """Ground truth: rows that carry hand-coded milepost ranges (TIP rows) must
    agree with the name-decoded MP within tol. Returns (n_checked, n_pass, fails)."""
    checked = passed = 0
    fails = []
    by_row = {a["row"]: a for a in anchors}
    for i, r in enumerate(rows):
        try:
            lo, hi = float(r.get(mp_lo_col) or 0), float(r.get(mp_hi_col) or 0)
        except (TypeError, ValueError):
            continue
        if hi <= 0 or i not in by_row:
            continue
        checked += 1
        mp = by_row[i]["mp"]
        if lo - tol <= mp <= hi + tol:
            passed += 1
        else:
            fails.append({"row": i, "decoded_mp": mp, "tip_range": (lo, hi),
                          "name": r.get("ROAD_01")})
    return checked, passed, fails
