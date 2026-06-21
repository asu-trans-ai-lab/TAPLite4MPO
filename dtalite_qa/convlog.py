"""Converter step-log — a shared, standardized conversion record that `intake` ingests.

Every converter (gsats_to_gmns, nexta, arc_atlanta_to_gmns, a GIS field-mapping import...)
should write one of these so the conversion is auditable: what was read, every field
mapping, every assumption/default applied, every warning. `intake` reads
`conversion_log.json` from the scenario and folds its steps + assumptions into the intake
log, so the trail is unbroken from raw agency files -> GMNS -> audit -> workflow.

Usage in a converter:
    from dtalite_qa.convlog import ConversionLog
    log = ConversionLog("gsats_to_gmns", source="2025BY_Links_v9.shp")
    log.input("2025BY_Links_v9.shp", "10,264 links")
    log.map("capacity", "AB_CAP / TOT_LANES", "per-lane")          # field mapping
    log.assume("capacity_period", "daily", "AB_CAP is the daily column; PK exists too")
    log.warn("FT 15 has metres-as-miles look")
    log.step("split two-way links into AB/BA")
    log.output("link.csv", "10,264 directed links")
    log.write(out_dir)                                             # -> conversion_log.json/.md
"""
import json
import os


class ConversionLog:
    def __init__(self, converter, source=None):
        self.converter = converter
        self.source = source
        self.entries = []          # ordered (kind, *fields)

    def _add(self, kind, **kw):
        self.entries.append(dict(kind=kind, **kw))
        return self

    def step(self, msg):                      return self._add("STEP", msg=msg)
    def note(self, msg):                      return self._add("NOTE", msg=msg)
    def input(self, path, detail=""):         return self._add("INPUT", path=path, detail=detail)
    def output(self, path, detail=""):        return self._add("OUTPUT", path=path, detail=detail)
    def warn(self, msg):                      return self._add("WARN", msg=msg)

    def map(self, gmns_field, source_expr, note=""):
        """Record a field mapping  source -> GMNS  (the 'one by one' NeXTA mapping)."""
        return self._add("MAP", field=gmns_field, source=source_expr, note=note)

    def assume(self, key, value, why=""):
        """Record an assumption/default the MPO should confirm (intake surfaces these)."""
        return self._add("ASSUME", key=key, value=value, why=why)

    def as_dict(self):
        return dict(converter=self.converter, source=self.source, entries=self.entries)

    def write(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        json.dump(self.as_dict(),
                  open(os.path.join(out_dir, "conversion_log.json"), "w", encoding="utf-8"),
                  indent=2, default=str)
        open(os.path.join(out_dir, "conversion_log.md"), "w", encoding="utf-8").write(self.render_md())
        return out_dir

    def render_md(self):
        out = [f"# Conversion log — {self.converter}", ""]
        if self.source:
            out.append(f"Source: `{self.source}`\n")
        maps = [e for e in self.entries if e["kind"] == "MAP"]
        if maps:
            out += ["## Field mapping (source -> GMNS)", "",
                    "| GMNS field | from source | note |", "|---|---|---|"]
            out += [f"| `{e['field']}` | `{e['source']}` | {e.get('note','')} |" for e in maps]
            out.append("")
        assumes = [e for e in self.entries if e["kind"] == "ASSUME"]
        if assumes:
            out += ["## Assumptions / defaults (confirm with the agency)", "",
                    "| key | value | why |", "|---|---|---|"]
            out += [f"| `{e['key']}` | {e['value']} | {e.get('why','')} |" for e in assumes]
            out.append("")
        out += ["## Steps", ""]
        for e in self.entries:
            if e["kind"] in ("STEP", "NOTE", "INPUT", "OUTPUT", "WARN"):
                txt = e.get("msg") or f"{e.get('path','')} — {e.get('detail','')}"
                out.append(f"- **{e['kind']}** — {txt}")
        return "\n".join(out) + "\n"


def load(scenario):
    """Read a conversion_log.json from a scenario dir; returns dict or None."""
    p = os.path.join(scenario, "conversion_log.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return None
    return None
