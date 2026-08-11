# Mode-Type and Pricing Specification (NORMATIVE)

**Status:** normative for all TAPLite4MPO networks · **Version:** 1.0 (2026-08-10)
**Applies to:** `mode_type.csv`, `link.csv` (`allowed_use`, `toll_<class>`),
and every network converted from an agency model.

This document exists because a real network shipped with `allowed_use`
permitting `sov` on an HOV-only facility and with all six per-class tolls set
to the same value. Both are silent defects: the kernel applies exactly what
the file says, the run completes, and the error only appears later as an
unexplained under-assignment. The rules below make that class of defect
detectable before a run, and the conformance checks make it testable.

Key words MUST / MUST NOT / SHOULD / MAY are used in the RFC 2119 sense.

---

## 1. The two instruments

There are exactly two mechanisms for controlling which vehicles use a link,
and they MUST NOT be used as substitutes for one another.

| instrument | question it answers | field |
|---|---|---|
| **Permission** | Who may physically enter this link? | `allowed_use` |
| **Price** | What does a permitted class pay? | `toll_<class>` |

**Rule 1.1** A class omitted from `allowed_use` MUST NOT be able to use the
link at any price. Permission is absolute; price is a deterrent.

**Rule 1.2** A prohibition MUST be expressed as permission, never as a
prohibitive price. Setting `toll_sov = 999` to keep SOV off an HOV lane is
non-conformant: it distorts the generalized cost of every path considered,
and it produces a small but nonzero SOV flow whenever no alternative exists.

**Rule 1.3** A price MUST NOT be expressed as a prohibition. Removing `sov`
from a HOT lane's `allowed_use` because "SOV mostly avoids it" destroys the
buy-in behaviour the facility exists to model.

## 2. Class taxonomy

`mode_type.csv` defines the classes. Each row MUST carry a distinct
`mode_type` token, a `vot` in dollars per hour, and a `pce`.

| token | meaning | typical VOT | notes |
|---|---|---|---|
| `sov` | single-occupant vehicle | lowest | the class HOV facilities exclude |
| `hov2` | 2-occupant | middle | policy may treat as HOV or as SOV |
| `hov3` | 3+-occupant | highest | the class HOV facilities exist for |
| `com` | commercial van / service | middle | often permitted on HOV lanes |
| `trk` | truck | middle | often prohibited on HOV lanes; `pce > 1` |
| `apv` | airport / public van | middle | usually permitted on HOV lanes |

**Rule 2.1** The token used in `allowed_use` MUST match the `mode_type`
token exactly, character for character. `hov2` and `hov2f` are different
classes; a mismatch silently closes the link to that class.

**Rule 2.2** VOT MUST be positive. Generalized cost divides by it.

## 3. Generalized cost

For class *k* on link *a* the kernel computes

```
cost_k(a) = travel_time(a) + toll_k(a) / VOT_k * 60        [minutes]
```

**Rule 3.1** `toll_<class>` MUST be in dollars for the whole traversal of the
link, not per mile and not in cents.

**Rule 3.2** A higher VOT makes the same toll *less* deterrent, because the
toll converts to fewer minutes. A $1.42 toll costs a VOT-$20 class 4.25
minutes and a VOT-$60 class 1.42 minutes. Any policy expressed only through
price therefore bites hardest on the lowest-VOT class — which is usually the
opposite of the intent for HOV facilities. This is the reason Rule 1.2
exists.

## 4. Facility classes and their required coding

Every link MUST be assignable to exactly one facility class per period.

### 4.1 Permission matrix

| facility class | sov | hov2 | hov3 | com | trk | apv | `allowed_use` |
|---|---|---|---|---|---|---|---|
| `HOV_only` | NO | YES | YES | YES | NO | YES | `hov2;hov3;com;apv` |
| `HOV3_only` | NO | NO | YES | NO | NO | YES | `hov3;apv` |
| `HOT` | YES | YES | YES | YES | policy | YES | `sov;hov2;hov3;com;apv` |
| `general_purpose` | YES | YES | YES | YES | YES | YES | `sov;hov2;hov3;com;trk;apv` |
| `toll_road_all` | YES | YES | YES | YES | YES | YES | `sov;hov2;hov3;com;trk;apv` |
| `closed_in_period` | NO | NO | NO | NO | NO | NO | `closed` |

### 4.2 Toll matrix

| facility class | toll_sov | toll_hov2 | toll_hov3 | toll_com | toll_trk | toll_apv |
|---|---|---|---|---|---|---|
| `HOV_only` | n/a | 0 | 0 | 0 | n/a | 0 |
| `HOV3_only` | n/a | n/a | 0 | n/a | n/a | 0 |
| `HOT` | > 0 | 0 or declared discount | **0** | > 0 per policy | > 0 if permitted | 0 |
| `general_purpose` | 0 | 0 | 0 | 0 | 0 | 0 |
| `toll_road_all` | > 0 | > 0 | > 0 | > 0 | > 0 | > 0 |
| `closed_in_period` | n/a | n/a | n/a | n/a | n/a | n/a |

**Rule 4.1** On a `HOT` facility `toll_hov3` MUST be strictly less than
`toll_sov`. If every class pays the same, the facility is `toll_road_all`,
not `HOT`, and MUST be labelled as such.

**Rule 4.2** `n/a` cells mean the class cannot enter, so the toll value is
never read. It SHOULD be written as 0 for cleanliness, and it MUST NOT be
used to encode the restriction.

**Rule 4.3** Reversible facilities MUST keep the link in the network in the
closed direction with `allowed_use = closed`, not delete it. Deleting breaks
the union link universe across periods and the GIS round trip.

## 5. Testable invariants

Each facility class implies an invariant that MUST hold in the assignment
output. These are the acceptance tests, not guidelines.

| facility class | invariant on the assignment |
|---|---|
| `HOV_only` | SOV volume = 0 |
| `HOV3_only` | SOV volume = 0 and HOV2 volume = 0 |
| `HOT` | `toll_hov3 < toll_sov` on every link |
| `general_purpose` | every class toll = 0 |
| `toll_road_all` | all classes priced; no HOV discount |
| `closed_in_period` | every class volume = 0 |

**Rule 5.1** A violated invariant is a **blocker**, not a warning. The run
may complete, but its per-class volumes MUST NOT be used for calibration,
validation, or reporting until the coding is corrected.

## 6. Cross-checking against a reference model

When a network is converted from an agency model that carries its own
per-class assignment, the facility class MUST be inferred from the
reference's behaviour and compared against the converted permission string.

| reference says | `allowed_use` says | verdict |
|---|---|---|
| class volume ≈ 0 across the facility | class permitted | **RESTRICTION_LOST** — the conversion dropped a restriction |
| class volume > 0 | class not permitted | **RESTRICTION_TOO_TIGHT** — the conversion invented a restriction |
| class volume ≈ 0 | class not permitted | consistent |
| class volume > 0 | class permitted | consistent |

**Rule 6.1** `RESTRICTION_LOST` on a tolled facility is the specific
signature of an HOV lane converted as if it were a HOT lane. It MUST be
resolved before the network is used, because the excluded class will occupy
capacity the reference reserves for others.

**Rule 6.2** The threshold for "≈ 0" MUST be declared (we use 1.0 vehicle)
and recorded in the run manifest.

## 7. How TAPLite implements this

So that the specification and the code cannot drift apart:

| rule | kernel behaviour | where |
|---|---|---|
| Permission is absolute | `allowed_use` is parsed to a per-class bitmask at load; a forbidden class never enters the shortest-path search for that link | `ReadLinks`, `mode_allowed_use` |
| Price is per class | `mode_AdditionalCost[m] = (toll_m + length × op_cost) / VOT_m × 60`, added to link travel time inside the class's own shortest path | `UpdateLinkCost` |
| Classes may share a tree | modes with `dedicated_shortest_path = 0`, or the same `g_rep_mode`, share one predecessor tree; their per-class costs still differ only if their tolls or VOTs differ | `All_or_Nothing_Assign` |
| Per-class volumes are reported | `mod_vol_<class>` in `link_performance.csv` | output writer |

**Consequence worth stating plainly:** if all six `toll_<class>` values are
equal and all six classes are permitted, then every class sees the identical
cost on that link and the model cannot express any managed-lane behaviour at
all. The kernel is not ignoring the policy — there is no policy in the file.

## 8. Conformance checklist

Run before accepting any converted network. Automated form:
`python -m dtalite_qa.check_pricing <network_dir>` (see §9).

- [ ] Every `allowed_use` token matches a `mode_type` token exactly
- [ ] Every VOT is positive; every PCE is positive
- [ ] Every link is assigned exactly one facility class per period
- [ ] Every `HOT` link satisfies `toll_hov3 < toll_sov`
- [ ] No link uses a prohibitive toll in place of a permission
- [ ] Every `general_purpose` link has all tolls = 0
- [ ] Reversible facilities use `allowed_use = closed`, not deletion
- [ ] Against a reference model: zero `RESTRICTION_LOST` on tolled links
- [ ] Post-run: every facility-class invariant in §5 holds
- [ ] The "≈ 0" threshold and the facility-class assignment rule are in the
      run manifest

## 9. Reference implementation of the checks

The audit script that produced the the agency findings is the reference
implementation of §6 and §8:

```
analysis/g1_allowed_use_audit.py     # RESTRICTION_LOST / TOO_TIGHT matrix
analysis/g1_corridor_triangulation.py # per-corridor pricing evidence
```

Outputs a matrix of link × class with `permitted`, reference volume, model
volume, and verdict — the artifact a reviewer needs in order to sign off
that mode-type and pricing handling is correct.

## 10. Worked example of the defect this specification prevents

A real facility, 23 links, PM period:

| what | value |
|---|---|
| Reference model SOV volume | **0.0** across all 23 links |
| `allowed_use` as converted | `sov;hov2;hov3;com;apv` — SOV permitted |
| `toll_sov` = `toll_hov2` = `toll_hov3` | 1.42 (identical) |
| Model SOV volume that resulted | **1,787 vehicles** |
| Model HOV2 volume vs reference | 31 % |
| Model APV volume vs reference | 18 % |

Diagnosis under this specification: the facility is `HOV_only` (Rule 6.1,
reference keeps SOV off), so `sov` MUST be removed from `allowed_use`. The
identical tolls additionally violate Rule 4.1 if the facility were in fact
`HOT`. Either way the coding is non-conformant, and the §5 invariant
"SOV volume = 0" fails — which is exactly the test that would have caught it
before anyone looked at an R².
