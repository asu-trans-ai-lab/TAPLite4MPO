"""Public-release cleanliness gate.

The public repository must not name the client agency or the consultant, and
must not carry agency-derived network, demand or reference-volume data.
This runs in CI and fails the build rather than relying on anyone remembering.

  python scripts/check_public_clean.py
"""
from __future__ import annotations

import re
import subprocess
import sys

# Client agency and consultant identifiers. Public DOT names appearing in
# generic capability lists (VDOT, MTC, SANDAG, ...) are deliberately NOT here:
# naming a public agency's VDF convention is not disclosure of client work.
FORBIDDEN = re.compile(r"\b(nvta|mvta|aecom|ffx134)\b", re.I)

# Column names that would mean agency reference volumes shipped with the repo.
FORBIDDEN_COLS = re.compile(r"\bcube_ref_vol\w*\b", re.I)

# Explicitly authorized public datasets, with the reason recorded here rather
# than as a silent exception. LDN034_* is owner-ruled "Gold-LDN-RT-Public" and
# originates from a PUBLIC upstream repository, so its reference-volume columns
# are not client disclosure. Caveat on record: the upstream carries no license
# file (see LDN034_BD/CONSISTENCY.md) — revisit if that becomes a problem.
AUTHORIZED_PUBLIC = ("test_networks/subarea_conic/LDN034_",)

SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".gz", ".bin",
               ".exe", ".dll", ".parquet", ".omx", ".pdf", ".ico"}


def main() -> int:
    files = subprocess.run(["git", "ls-files"], capture_output=True,
                           text=True, check=True).stdout.split()
    bad_name = [f for f in files if FORBIDDEN.search(f)]
    bad_body, bad_data = [], []

    # This checker necessarily spells the forbidden terms in order to look for
    # them, so it must exempt itself or it fails on its own source.
    self_path = "scripts/check_public_clean.py"

    for f in files:
        if f == self_path or any(f.lower().endswith(s) for s in SKIP_SUFFIX):
            continue
        try:
            text = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN.search(line):
                bad_body.append(f"{f}:{n}: {line.strip()[:110]}")
            if (FORBIDDEN_COLS.search(line)
                    and not f.startswith(AUTHORIZED_PUBLIC)):
                bad_data.append(f"{f}:{n}: agency reference-volume column")

    fail = False
    for label, hits in (("filenames", bad_name),
                        ("content", bad_body),
                        ("agency reference-volume data", bad_data)):
        if hits:
            fail = True
            print(f"FAIL — client/consultant identifiers in {label} "
                  f"({len(hits)}):")
            for h in hits[:25]:
                print("   ", h)
            if len(hits) > 25:
                print(f"    ... and {len(hits) - 25} more")

    if fail:
        print("\nThis repository is public. Move the artifact to the private "
              "repo, or write it in agency-neutral terms.")
        return 1
    print(f"PASS — {len(files)} tracked files carry no client or consultant "
          f"identifier and no agency reference-volume data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
