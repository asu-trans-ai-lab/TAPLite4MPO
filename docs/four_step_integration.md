# Super-zone assignment in a 4-step feedback loop — the skim is the decoder

The 4-step model alternates **demand** (trip generation → distribution → mode choice,
all at original zone resolution) with **supply** (assignment), iterating to a
demand–supply equilibrium. The interface in each direction is a different operator:

| direction | object passed | operator |
|---|---|---|
| demand → supply | OD demand `d` loaded onto the network | **loading decoder** `U_C` (`superzone_hier.py`) |
| **supply → demand** | **zone-to-zone congested impedance** | **the skim** (`skim.py`) ← the key output |

**The skim is the decoder the loop feeds on.** Distribution (gravity) and mode choice
are functions of zone-to-zone time/cost, so they need an **N×N skim at original zone
resolution** every outer iteration. Super-zoning the *assignment* does not remove that
need — and it must not, or the demand model loses its zonal response.

## Architecture

```
 original zones (N):  gen → distribution → mode choice → OD d (N×N)
        │
        │  ENCODE   d̄ = Qᵀ d           (superzone_encoders.demand_kmeans → S)
        ▼
   FAST ASSIGNMENT on super-zones (K≪N)  →  congested link times τ(v)
        │
        │  SKIM at ORIGINAL resolution  (skim.py: shortest path between all N
        ▼   zone centroids over τ — one-shot, NOT iterated → cheap)
   N×N skim  ──────────────►  back to distribution / mode choice
        └──────────── outer demand–supply feedback loop ────────────┘
```

- **Assignment** is the iterated, expensive part — that is what super-zoning speeds up
  (Chicago Regional: 5–14×).
- **Skim** is one shortest-path tree per original zone over the *converged* link times —
  cheap (Chicago Regional 1,790² in ~5 s) and full-resolution.

## Why this is safe — validation

The skim is **zone-to-zone time, dominated by corridor travel** — and corridors are
exactly what super-zoning preserves (freeway R²≈0.97). So even though local link
*flows* degrade (R²~0.85), the *impedance* the demand model sees barely moves.

Measured on Chicago Regional — full-assignment skim vs super-zone-assignment skim,
both at original 1,790-zone resolution:

| | R² | %RMSE | level (super/full) |
|---|--:|--:|--:|
| all 3.2M OD pairs | **0.987** | 14.7% | 0.879 |
| demand-weighted | **0.978** | 18.5% | 0.875 |

**Pattern: excellent (R²=0.98).** The feedback signal survives super-zoning.

## The one caveat — a *level* bias the decoder causes

Super-zone skim times run **~12% low** (ratio 0.875): the loading decoder `U_C` drops
intra-super demand and loads each super-zone at a single representative, so the network
is **under-loaded → less congestion → faster times**. In a feedback loop this would
over-state accessibility and over-distribute trips. Two fixes, in order of value:

1. **Demand-spread decoder `U_C`** — split each super-zone's demand across its member
   access nodes by demand share, and keep intra-super trips (load them between member
   nodes). This restores the dropped congestion and removes most of the level bias; at
   the 1:1 corner case it becomes the identity (`e_v=0`). *This is the recommended next
   step.*
2. **Global level correction** — calibrate a per-class scalar so super skim level
   matches a one-time full reference; cheap but only a patch.

## Usage

```python
from dtalite_qa import skim
# full assignment:
t = skim.read_link_times("run/link_performance.csv")          # congested times
zones, M = skim.skim("run", t)                                 # N×N skim
skim.write_skim(zones, M, "run/od_skim.csv")

# super-zone assignment, skimmed at ORIGINAL resolution:
remap = skim.superzone_remap("original_scenario", S=178)       # super-id → original-id
t = skim.read_link_times("super_run/link_performance.csv", remap=remap)
zones, M = skim.skim("original_scenario", t)                   # original N×N skim
```

See `docs/od_compression_operators.tex` for the encoder/decoder formalism and
`docs/superzone_design_principles.md` (P0–P10) for the construction rules.
