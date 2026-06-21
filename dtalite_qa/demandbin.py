"""Convert demand CSV (o_zone_id,d_zone_id,volume) to the kernel's binary format.

Binary layout (little-endian, packed) -- must match ReadBinaryDemandFile in
TAPLite.cpp:
    header: b"DTAB", int32 version=1, int64 n_records
    record: int32 o_zone, int32 d_zone, double volume     (16 bytes each)

The kernel reads `<demand_file>.bin` instead of the CSV when settings.csv has
`demand_format=1`, skipping per-record text parsing -- the win is on large
regional models (millions of OD pairs). Volume <= 0 rows are dropped (they don't
affect assignment) to keep the file small.
"""
import csv as _csv
import os
import struct

from . import csvio

MAGIC = b"DTAB"
VERSION = 1
_HEADER = struct.Struct("<4siq")   # magic, version, n_records
_REC = struct.Struct("<iid")       # o, d, volume
_FLUSH = 1 << 22                    # flush the write buffer every ~4 MB


def convert_file(csv_path, bin_path=None, drop_nonpositive=True):
    """Convert one demand CSV to .bin, streaming (low memory, fast).
    Returns (n_written, bin_path)."""
    if bin_path is None:
        bin_path = csv_path[:-4] + ".bin" if csv_path.endswith(".csv") else csv_path + ".bin"
    pack = _REC.pack
    n = 0
    buf = bytearray()
    with open(csv_path, newline="", encoding="utf-8-sig") as fin, open(bin_path, "wb") as fout:
        r = _csv.reader(fin)
        header = next(r, [])
        try:
            oi, di, vi = (header.index("o_zone_id"), header.index("d_zone_id"),
                          header.index("volume"))
        except ValueError:
            oi, di, vi = 0, 1, 2   # positional fallback
        fout.write(_HEADER.pack(MAGIC, VERSION, 0))   # placeholder count, patched below
        for row in r:
            try:
                vol = float(row[vi])
            except (IndexError, ValueError):
                continue
            if drop_nonpositive and vol <= 0:
                continue
            buf += pack(int(float(row[oi])), int(float(row[di])), vol)
            n += 1
            if len(buf) >= _FLUSH:
                fout.write(buf)
                buf = bytearray()
        if buf:
            fout.write(buf)
        fout.seek(0)
        fout.write(_HEADER.pack(MAGIC, VERSION, n))   # patch real count
    return n, bin_path


def _demand_files(scenario):
    targets = []
    mt = os.path.join(scenario, "mode_type.csv")
    if os.path.exists(mt):
        _, rows = csvio.read(mt)
        for r in rows:
            df = (r.get("demand_file") or "").strip()
            if df:
                targets.append(df)
    if not targets and os.path.exists(os.path.join(scenario, "demand.csv")):
        targets = ["demand.csv"]
    return targets


def convert_scenario(scenario):
    """Convert all of a scenario's demand files to .bin. Returns list of results."""
    out = []
    for df in _demand_files(scenario):
        p = os.path.join(scenario, df)
        if not os.path.exists(p):
            out.append((df, None, "missing"))
            continue
        n, binp = convert_file(p)
        out.append((df, os.path.basename(binp), n))
    return out


def read_bin(bin_path):
    """Read a .bin back (for verification/tests). Returns list of (o,d,vol)."""
    with open(bin_path, "rb") as f:
        magic, version, n = _HEADER.unpack(f.read(_HEADER.size))
        assert magic == MAGIC and version == VERSION, "not a DTAB v1 file"
        data = f.read(n * _REC.size)
    return [_REC.unpack_from(data, i * _REC.size) for i in range(n)]
