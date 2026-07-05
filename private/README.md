# `private/` — agency-restricted data & internal case studies

**Nothing in this folder except this README is committed.** The repo `.gitignore` keeps
`private/*` (and `private_docs/*`) out of Git. Agency networks and demand matrices are
distributed under data agreements and **must never be pushed to the public repo.**

## What lives here

Each agency model gets its **own subfolder** — its inputs (kept locally, git-ignored) and a
`README.md` **case study** that documents, for that model:

- the exact **conventions** it used (capacity basis/period, PLF, units, demand kind, VDF form
  + per-facility α/β, zone-id basis, count/reference field), and
- the **issues** it raised, mapped to the [Conversion Error Catalog](../docs/CONVERSION_ERRORS_CATALOG.md)
  categories, with the specific fix and the evidence.

These case studies are the *worked, real-world* companions to the public catalog — they are
how a new engineer learns "what actually happened on a real hand-off." Because they can quote
agency field names and numbers, they stay here (internal), not in the public docs.

## Subfolders

| folder | agency / model | status |
|---|---|---|
| `SCAG/` | SCAG RTP/SCS 2024, 2050 Plan (50PL) — TransCAD | network built; demand = open "missing volume" question — see `SCAG/README.md` |

## Reproducing a private run

Same pattern as `nvta_run/` (main README §6): the scripts read the data from a path you
provide (env var / `local_config.json` / a local `data/` drop), so a colleague with the data
agreement can reproduce the run without the data ever entering Git.
