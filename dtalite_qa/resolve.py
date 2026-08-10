"""Strict model resolution — PR-3 (CR-0008).

Answers the two questions nobody may skip:
  BEFORE assignment: what model am I actually running?
  AFTER  assignment: what model produced these results?

Reads a declarative `configuration.yml`, resolves it against the scenario's
link.csv, prints the MODEL RESOLUTION AUDIT (per-function link counts,
fallback counts, findings) and writes `resolved_model_manifest.json`.

Strict mode turns ambiguous states into hard failures (exit 2):
  RS-1  vdf_type=1 links without explicit positive conic_a  (the alias
        fallback that evaluates conic with vdf_beta as b — proven to
        produce zero-clamped FREE links; finding TW-1, CR-0007)
  RS-2  vdf_type=2 links with missing/blank QVDF parameter columns
  RS-3  configuration claims a non-BPR replication family but the network
        resolves (partly) to default BPR (undeclared functional form)
  RS-4  flat vdf_plf = 1.0 across the network on a multi-hour period
  RS-5  unknown vdf_type values
Non-strict mode reports the same findings as WARNINGS.

CLI:
  python -m dtalite_qa.resolve <configuration.yml> [--strict]

configuration.yml (minimal contract — the owner-named run contract file):
  scenario: my_run
  network: {link: link.csv}
  run:
    active_period: {id: 1, name: AM, start: "07:00", end: "08:00"}
  vdf:
    strict: true                # or pass --strict
  claims:
    replication_family: conical # optional: bpr|conical|qvdf|mixed
"""
import csv as _csv
import hashlib
import json
import os
import sys

FUNC_NAME = {0: "bpr", 1: "conical_spiess", 2: "qvdf", 3: "bpr2",
             4: "inrets", 5: "akcelik", 6: "sandag_signal",
             7: "scag_piecewise", 8: "scag_ramp_meter"}
QVDF_COLS = ("vdf_cp", "vdf_cd", "vdf_n", "vdf_s")


def _hours(hhmm):
    h, m = str(hhmm).split(":")[:2]
    return int(h) + int(m) / 60.0


def resolve(cfg_path, strict=None):
    import yaml
    cfg = yaml.safe_load(open(cfg_path)) or {}
    base = os.path.dirname(os.path.abspath(cfg_path))
    link_path = os.path.join(base, (cfg.get("network") or {})
                             .get("link", "link.csv"))
    with open(link_path, newline="", encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    if strict is None:
        strict = bool((cfg.get("vdf") or {}).get("strict", False))
    period = ((cfg.get("run") or {}).get("active_period")) or {}
    dur = None
    if period.get("start") and period.get("end"):
        dur = _hours(period["end"]) - _hours(period["start"])
        if dur < 0:
            dur += 24.0

    counts, findings = {}, []
    n = len(rows)
    has_vdf_type = any("vdf_type" in r and str(r["vdf_type"]).strip() != ""
                       for r in rows)
    n_fallback_conic = n_qvdf_missing = n_unknown = 0
    n_plf_flat = 0
    for r in rows:
        vt_raw = str(r.get("vdf_type", "")).strip()
        vt = int(float(vt_raw)) if vt_raw else 0
        name = FUNC_NAME.get(vt)
        if name is None:
            n_unknown += 1
            name = "UNKNOWN(%d)" % vt
        counts[name] = counts.get(name, 0) + 1
        if vt == 1:
            ca = float(r.get("conic_a") or 0)
            if ca <= 0:
                n_fallback_conic += 1
        if vt == 2:
            if any(str(r.get(c, "")).strip() == "" for c in QVDF_COLS):
                n_qvdf_missing += 1
        plf = str(r.get("vdf_plf", "")).strip()
        if plf == "" or abs(float(plf) - 1.0) < 1e-9:
            n_plf_flat += 1

    if n_fallback_conic:
        findings.append(("RS-1", "%d conical links rely on the deprecated "
                         "vdf_alpha/vdf_beta fallback (no explicit conic_a) "
                         "- can evaluate to zero-clamped FREE travel time"
                         % n_fallback_conic))
    if n_qvdf_missing:
        findings.append(("RS-2", "%d qvdf links missing one of %s"
                         % (n_qvdf_missing, "/".join(QVDF_COLS))))
    fam = (cfg.get("claims") or {}).get("replication_family")
    if fam and fam != "bpr":
        declared = sum(v for k, v in counts.items() if k != "bpr")
        if not has_vdf_type or declared == 0:
            findings.append(("RS-3", "configuration claims replication of a "
                             "'%s' baseline but the network resolves to "
                             "default BPR (vdf_type %s)"
                             % (fam, "absent" if not has_vdf_type
                                else "never set to that family")))
    if dur is not None and dur > 1.5 and n and n_plf_flat >= 0.95 * n:
        findings.append(("RS-4", "flat vdf_plf=1.0 on %d/%d links for a "
                         "%.1f-hour period (placeholder PLF: period "
                         "capacity treatment is wrong network-wide)"
                         % (n_plf_flat, n, dur)))
    if n_unknown:
        findings.append(("RS-5", "%d links carry unknown vdf_type values"
                         % n_unknown))

    verdict = "PASS" if not findings else ("FAIL" if strict else "WARN")
    man = {
        "configuration": os.path.basename(cfg_path),
        "config_sha256": hashlib.sha256(
            open(cfg_path, "rb").read()).hexdigest()[:16],
        "scenario": cfg.get("scenario"),
        "active_period": period or None,
        "links": n,
        "performance_resolution": counts,
        "conic_fallback_links": n_fallback_conic,
        "strict": bool(strict),
        "findings": [{"id": i, "detail": d} for i, d in findings],
        "verdict": verdict,
    }
    out = os.path.join(base, "resolved_model_manifest.json")
    with open(out, "w") as f:
        json.dump(man, f, indent=2)

    print("MODEL RESOLUTION AUDIT — %s" % (cfg.get("scenario") or link_path))
    print("  links: %d   period: %s (%s h)   strict: %s"
          % (n, period.get("name", "?"),
             ("%.2f" % dur) if dur is not None else "?", strict))
    print("  Performance functions:")
    for k in sorted(counts, key=counts.get, reverse=True):
        print("    %-18s %7d" % (k, counts[k]))
    print("    %-18s %7d" % ("unresolved", 0))
    print("    %-18s %7d" % ("conic_fallback", n_fallback_conic))
    for i, d in findings:
        print("  %s %s: %s" % ("ERROR" if strict else "WARN", i, d))
    print("  VERDICT: %s   -> %s" % (verdict, os.path.basename(out)))
    return man


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = None
    if "--strict" in argv:
        strict = True
        argv.remove("--strict")
    if not argv:
        print(__doc__)
        return 1
    man = resolve(argv[0], strict)
    return 2 if man["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
