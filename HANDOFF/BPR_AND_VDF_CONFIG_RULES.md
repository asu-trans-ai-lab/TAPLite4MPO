# BPR / VDF / capacity — configuration rules & conditions

**A one-page decision card for setting up the volume-delay + capacity block of any MPO
hand-off.** It condenses [`USER_GUIDE_VOL2_MPO.md`](../USER_GUIDE_VOL2_MPO.md) §3–§6,
[`docs/peak_load_factor.md`](../docs/peak_load_factor.md), and
[Conversion Error Catalog](../docs/CONVERSION_ERRORS_CATALOG.md) §1–§2 & §6 into the rules you
apply on *every* model. When in doubt, the catalog is the authority; this is the checklist.

> **Golden rule:** the VDF, capacity, PLF and units are **declared from the agency's own
> assignment documentation** — never defaulted. BPR `α=0.15, β=4` for every facility is a
> *sketch* setting, not an agency model.

---

## A. Pick the VDF form (`vdf_type`)

`x = v/c` per lane. Every form shares the cost-based Frank-Wolfe line search, so any monotone
VDF is solved exactly — you only choose the *shape*, from the agency's docs.

| `vdf_type` | form | choose it when the agency uses… |
|---|---|---|
| **0** BPR | `t0(1 + α·x^β)` | plain BPR (TRPA, ODOT, VDOT, MTC). |
| **0 + `vdf_A`** modified BPR | `t0(1 + A·x + α·x^β)` | a BPR with a **linear term** (**ARC**). |
| **1** conical (Spiess) | smooth, bounded derivative | MWCOG, VDOT — conical delay. |
| **2** QVDF (queue) | queue VDF (`vdf_cp/cd/n/s`, `cutoff_speed`) | you need **congestion duration / queue speeds** (CBI-calibrated). |
| **3** BPR2 | exponent doubles for `x>1` | AequilibraE-style oversaturation. |
| **4** INRETS | `t0(1.1−α·x)/(1.1−x)` | AequilibraE INRETS. |
| **5** Akcelik | time-dependent delay form | VDOT-allowed Akcelik. |
| **6** SANDAG-signal | BPR + Webster delay (`cycle_length`,`green_ratio`) | signalized arterial delay (SANDAG). |
| **7 / 8** piecewise BPR + ramp meter *(extension)* | β switches at capacity; freeway on-ramp meter fn | **SCAG** Validation-Report Table 16-2 (see catalog §6). |

**Rule:** per-facility `α / β / A` come from the agency's **FACTYPE × area-type × posted-speed**
table and are written **into `link.csv` by the converter** — they are *not* one global setting.

## B. BPR α/β — the conditions

- **Default `0.15 / 4`** → only for sketch/teaching or a first connectivity pass. It is
  *gentle*: it will **hide** a capacity-basis error (§C) because low V/C never bites.
- **Agency table** → the real setting. Examples that shipped:
  - **ARC** modified BPR, per-FACTYPE (freeway ≈ `A`-term + `0.60 / 6.0`, etc.). Flat 0.15/4
    gave region %RMSE **88%**; the Section-7 table brought it to **23%**.
  - **SCAG** piecewise: `β=4` below capacity, calibrated **β=5/6/8 above** by facility ×
    posted speed × area type; `α=1.0` freeway / `0.8` others; plus a separate freeway on-ramp
    meter function (fac 82/84).
- **Steep β is stiff.** β≥6–8 makes Frank-Wolfe converge slowly — plain FW left a ~6% gap at
  20 iters on SCAG. **Condition:** if any `β ≥ 6`, set `assignment_method = 2` (bi-conjugate
  FW) and run **≥ 40 iterations**. *A loose gap looks like over-diversion — don't mistake it
  for a routing bug.*

## C. Capacity — two independent axes, both silent when wrong

| axis | wrong looks like | the rule |
|---|---|---|
| **Basis** (per-lane vs total) | V/C 2–4× low, freeway speeds too high, VHT low | kernel `capacity` is **per-lane**: `Link_Capacity = lanes × capacity`. Commercial exports give **total** → set `capacity = total_hourly / lanes`. |
| **Period** (hourly vs period vs daily) | daily-as-hourly ⇒ median V/C ≈ 0.007; hourly-as-period ⇒ over-congested | declare `capacity_period` **and the exact source column**; convert to hourly per-lane `c_h`. |

**Sanity check (do this every time):** per-lane hourly capacity should be **freeway ≈
1800–2000, arterial ≈ 600–900**. A freeway "per-lane" capacity of 7200 is the tell that a
total was written into the per-lane field (this was the **SCAG** bug).

## D. Peak Load Factor — the #1 pitfall

A static run loads a whole **period**; capacity and the VDF are per **hour**. The bridge is PLF.

- **Identity:** `φ = L·PLF` (L = period length in hours); `c_period = φ·c_h`;
  `DOC = (V/lanes/H/plf)/c_h`.
- **Agencies state φ (a "period factor"), not PLF.** So `PLF = φ / L`. ARC AM φ=3.66 over
  L=4 h ⇒ **PLF = 0.915** (*not* flat).
- **Kernel mapping (do exactly this):** `capacity = c_h` (hourly per-lane), `vdf_plf = φ/L`,
  `demand_period_*_hours = the window`.
- **Never** leave `vdf_plf = 1`, and never feed *period* capacity with `plf = 1/H` — both
  hard-code PLF = 1 and over-state capacity (worst error at **night**, PLF ≈ 0.40 → ~2.5×).
- **Red flag:** if `VDF_cap` scales *exactly* with period length (3:6:3:12 across AM:MD:PM:NT)
  it was built flat (φ = L) and needs the real PLF.
- **Bounds (enforced by `dtalite_qa/plf.py`):** `0 < PLF ≤ 1`, `φ = L·PLF ≥ 1`, floor 0.25.
  Reference φ/L: ARC EA .417 / AM .915 / MD .94 / PM .915 / EV .489; MAG AM .94 / MD .96 /
  PM .98 / NT .40. Inventory: `python -m dtalite_qa plf <scenario> --period AM`.

## E. Units — emit both, declare both

| quantity | GMNS field | VDF field | error if confused |
|---|---|---|---|
| length | `length` (metres) | `vdf_length_mi` (miles) | distance-cost ×1609 (m) or ×1.6 (km) |
| speed | `free_speed` (km/h) | `vdf_free_speed_mph` (mph) | free-flow time ×1.6 |
| free-flow time | — | `vdf_fftt` (min) | guard `AB_TIME ≤ 0` → `60·length_mi/speed_mph` |

MAG / ARC / GSATS / SCAG all emit `vdf_free_speed_mph` and `vdf_length_mi` **explicitly** so
the kernel cannot misread a unit. Do the same.

## F. Generalized cost — access vs cost (don't conflate)

- Per-mode minutes: `cost = travel_time + (toll + distance·operating_cost)/VOT·60`.
- **`allowed_use`** = *feasibility* (which classes may use the link: HOV-only, truck-only).
- **`toll_<mode>`** = *cost* (a managed lane still **allows** the tolled class, just costs more).
- The toll penalty needs the **VOT** — **find it, don't assume** (SCAG per-class:
  SOV $20.9 / HOV2 $18.5 / HOV3 $11.6). `pce` (truck 1.3–2.5) is separate from `occupancy`.

---

## The 8-line setup checklist

```
[ ] vdf_type       = agency's form (0/0+A/1/2/6/7…), NOT default BPR unless sketch
[ ] vdf_alpha/beta = per-facility from the agency FACTYPE×ATYPE table (into link.csv)
[ ] capacity       = total_hourly / lanes         (per-lane; freeway ≈1800–2000)
[ ] capacity_period declared + exact source column (hourly, not daily)
[ ] vdf_plf        = φ/L  (real PLF; never 1; never 1/H on period capacity)
[ ] vdf_length_mi + vdf_free_speed_mph emitted     (units cannot be misread)
[ ] allowed_use (access)  and  toll_<mode>+VOT (cost)  kept separate
[ ] assignment_method = 2 (BFW) + ≥40 iters  IF any β ≥ 6
```

**Verify it caught everything:** `python -m dtalite_qa intake <scenario>` — anything you did
not declare becomes a **BLOCKER** that names the field and why it matters.
