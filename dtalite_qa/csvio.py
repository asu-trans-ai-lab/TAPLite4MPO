"""Minimal CSV helpers (stdlib only) — read as list-of-dicts, write back
preserving column order, with light numeric coercion."""
import csv
import os


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        rows = list(r)
        header = r.fieldnames or []
    return header, rows


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def is_num(x):
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def fnum(x, default=0.0):
    return float(x) if is_num(x) else default


def inum(x, default=0):
    return int(float(x)) if is_num(x) else default


def exists(scenario, name):
    return os.path.exists(os.path.join(scenario, name))


def path(scenario, name):
    return os.path.join(scenario, name)
