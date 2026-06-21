# I-10 Phoenix corridor — multi-lane QVDF test

Real westbound I-10 (Phoenix) geometry from
`../I10_corridor_QVDF/calibration_spreadsheet_I-10_Phoenix.xlsx` (Overview sheet),
built to test that **lane-related demand and QVDF produce a correct per-lane D/C**
when the lane count varies along the corridor.

## Network (single corridor path 1 → 12)
| link_id | from→to | length_mi | lanes | role |
|--------:|--------:|----------:|------:|------|
| 1   | 1→3  | 1.0 | 6 | mainline |
| 2   | 3→4  | 1.0 | 6 | mainline |
| 3   | 4→5  | 1.0 | 6 | mainline |
| 4   | 5→6  | 1.0 | 6 | mainline |
| 139 | 6→7  | 1.1 | 5 | loop detector |
| 84  | 7→8  | 1.1 | 4 | loop detector |
| 78  | 8→9  | 1.1 | 4 | loop detector |
| 10  | 9→10 | 4.0 | 6 | mainline |
| 137 | 10→11| 1.1 | 3 | loop detector (**bottleneck**) |
| 9   | 11→12| 1.0 | 6 | mainline |

capacity = 1800 veh/h/lane, free_speed = 75 mph, cutoff_speed = 52.5 mph,
`vdf_type=2` (QVDF) with the calibrated I-10 parameters
(alpha=0.801, beta=0.255, cp=0.451, cd=3.330, n=0.257; s=0.993 on link 139,
0.451 elsewhere). `vdf_plf=1` so D/C reads directly as V/(lanes·cap·H).

## Demand
A single through movement **1 → 12 = 10800 veh** over H = 1 h (7:00–8:00). Because
the corridor is one path, every link carries the same vehicle volume, so the
per-lane demand D and D/C depend only on the link's lane count — which is exactly
what we want to verify.

## Expected vs kernel D/C (verified)
| lanes | D = V/lanes | D/C = V/(lanes·1800) | kernel speed_mph |
|------:|------------:|---------------------:|-----------------:|
| 6 | 1800 | 1.00 | 29.15 |
| 5 | 2160 | 1.20 | 28.55 |
| 4 | 2700 | 1.50 | 27.80 |
| 3 | 3600 | 2.00 (bottleneck) | 26.84 |

The kernel reproduces these exactly, and the independent reference
`../qvdf_reference/qvdf_ref.py` agrees to < 5e-5.

## Run
```
# copy node/link/demand/settings + DTALite.exe into a working dir, then:
DTALite.exe
python ../qvdf_reference/qvdf_ref.py <working_dir>   # diff kernel vs QVDF reference
```

To turn each lane count into a stronger/weaker bottleneck, change the demand V or
the per-link `lanes`. To use the calibrated peak-load-factor instead of plf=1,
set `vdf_plf` per link (smaller plf → higher peak D/C).
