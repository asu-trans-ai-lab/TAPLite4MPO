# Peak Load Factor (PLF) — methodology & planning guideline

**Canonical reference:** ADOT VDF Calibration Project internal memo, *"Update the
ultimate capacity using Load Factor"* (ADOT VDF calibration project, 2022). This page is
the authoritative methodology for how the DTALite/TAPLite kernel and the
`dtalite_qa` preparation packages convert **hourly capacity** to **period capacity**
in static traffic assignment. **Read this before preparing any multi-period
network.**

---

## 1. Why PLF matters

A static assignment loads a whole **period** of demand (e.g. AM = 3 h) onto the
network at once, but capacity and the volume–delay function (VDF) are defined per
**hour**. The bridge between them is the **Peak Load Factor (PLF)**. Getting it
wrong silently mis-states congestion — almost always **under**-stating it.

## 2. Definitions (memo §1, §4)

- **PHF** (Peak Hour Factor) — within-hour peaking: `PHF = V / (4·V₁₅)`. HCM typical
  values: 0.88 rural, 0.92 urban, 0.95 congested.
- **PLF** (Peak Load Factor) — within-period peaking (memo Eq. 8):

  ```
  PLF = (average hourly volume of a period) / (maximum hourly volume)
      = v̄_period / v_max = v_period / (L · v_max)
  ```
  with **L = period length in hours**. **PLF ∈ (0, 1]; PLF = 1 ⟺ perfectly flat
  demand** across the whole period.

- **Peak hourly demand** used for D/C (memo Eq. 9):

  ```
  D = v_max = v_period / (L · PLF)
  ```

## 3. Hour → period capacity expansion (memo §5)

To keep one consistent D/C definition, convert the ultimate **hourly** capacity
`c_h` to a **period** capacity `c_period` with the expansion factor **φ** (Eq. 10):

```
c_period = φ · c_h
```

Requiring the period V/C to equal the peak-hour D/C (Eq. 11–12):

```
v_period / c_period = D / c_h = v_period / (L · PLF · c_h)
```

gives the central identity (memo Eq. 13):

```
        φ = L · PLF
```

So the period capacity is **`c_period = L · PLF · c_h`**, and the period V/C is
`v_period / (L · PLF · c_h)`.

## 4. Mapping to the kernel

The kernel computes `DOC = (V / lanes / H / plf) / lane_cap`. To realise the memo
exactly, feed it:

| kernel input | set to | meaning |
|---|---|---|
| `lane_cap` (`capacity` col) | **hourly** per-lane capacity `c_h` | not period capacity |
| `vdf_plf` | **the real PLF** (memo table) | not `1`, not `1/H` |
| `H` (period hrs) | **L** | from settings start/end |

Then `DOC = (v_period/lanes/L/PLF)/c_h = D/c_h` — the memo's peak-hour D/C.

> **Common error (do not do this):** setting `vdf_plf = 1` (flat) or, equivalently,
> using the **period** capacity with `vdf_plf = 1/H`. Both hard-code PLF = 1 and
> under-load congestion by a factor **1/PLF** — ~6 % at AM, but **~2.5× at night**
> (NT PLF ≈ 0.40). If your `VDF_cap` scales exactly with period length
> (e.g. 3:6:3:12 across AM:MD:PM:NT) it was built flat (φ = L) and needs the real PLF.

## 5. Bounds (enforced by `dtalite_qa/plf.py:bound_plf`)

| bound | rule | source |
|---|---|---|
| **hard** | `0 < PLF ≤ 1` (1 = flat) | memo §5 |
| **physical** | `φ = L·PLF ≥ 1` ⇒ `PLF ≥ 1/L` (a multi-hour period cannot carry *less* capacity than one hour) | derived |
| **advisory floor** | `PLF ≥ 0.25` (Lan-Abia `LF = 0.25 + α(V/C)^β`) | memo App. 1 |

`bound_plf(plf, L)` clamps to these and reports any adjustment; `plf check`
flags every link/value that violates them (`n_gt1`, `n_le0`, `n_subphi`,
`n_below_floor`).

## 6. Recommended PLF (MAG back-calculated table, memo §6 — internal reference)

By VDF_TYPE class and period (`AM 0600-0900, MD 0900-1400, PM 1400-1800,
NT 1800-0600`):

| VDF_TYPE class | AM | MD | PM | NT |
|---|--:|--:|--:|--:|
| most types | 0.94 | 0.96 | 0.98 | **0.40** |
| major arterials (x06) | 0.83 | 0.93 | 0.91 | 0.39 |

These are the defaults in `plf.MEMO_LOAD_FACTOR` / `nexta.MEMO_PLF`. Override with
agency-specific back-calculated factors when available.

## 7. Preparation workflow

1. **Inventory:** `python -m dtalite_qa plf <scenario> --period AM` — shows the
   `vdf_plf` distribution, the bounds (min/max, `1/L`, min φ), and flags flat or
   out-of-bound PLF.
2. **Convert (NeXTA/AZTDM):** `nexta.convert(..., plf=…, plf_arterial=…)` recovers
   `lane_cap = VDF_cap/(lanes·L)` and writes the bounded real PLF.
3. **Or set on an existing network:** `plf.apply(scenario, out, phi_profile, L)`
   writes `vdf_plf = φ/L` per facility type, clamped to the bounds.

## Motivating open questions (memo, for the final report)
1. Derivation of the load factor (this document).
2. How to treat the **shoulder** of the long NT period.
3. Whether `v_max` should be the **cumulative** or **instantaneous** peak demand.

## References
HCM 2010; Mannering & Washburn (2020); Horowitz et al. (2014, NCHRP 765);
Tarko & Perez-Cartagena (2005); NCHRP 716 (2012); Lan & Abia (2011);
Pan, Guo, Chen, Abbasi, List & Zhou — *A Review of Volume-Delay Functions*.
Original memo: `private/AZTDM GMNS Network/final_version_clean_Apr25/Memo_peak_Load Factor.tex`.
