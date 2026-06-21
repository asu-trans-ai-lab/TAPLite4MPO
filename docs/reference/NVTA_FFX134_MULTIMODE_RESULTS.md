# NVTA Sub-area Benchmark — Conic VDF + Per-Link PLF

**Period:** AM  **Modes:** sov, hov2, hov3, com, trk, apv  **Iterations:** 20

**Engine:** `C:/t/cg_kernel_v2/Release/tap_lite_cg.exe` (v3 schema with vdf_type per link)

**Pipeline:** `docs/NVTA_SUBAREA_CONIC_PIPELINE.md`

## System-level results

| Sub-area | Mode | VOT | n_links | Engine | Cube | Match% | Bias | R² | ±10% | ±25% | ±50% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FFX134_BD | sov | $10 | 59 | 93,060 | 95,660 | 97.3% | -2.72% | 0.9987 | 64.0% | 92.0% | 98.0% |
| FFX134_BD | hov2 | $15 | 59 | 5,591 | 5,840 | 95.7% | -4.26% | 0.9364 | 27.5% | 60.8% | 76.5% |
| FFX134_BD | hov3 | $15 | 59 | 3,452 | 4,059 | 85.0% | -14.96% | 0.9771 | 13.7% | 51.0% | 68.6% |
| FFX134_BD | com | $20 | 59 | 9,577 | 10,909 | 87.8% | -12.20% | 0.9324 | 31.4% | 66.7% | 78.4% |
| FFX134_BD | trk | $30 | 59 | 8,850 | 9,257 | 95.6% | -4.40% | 0.9970 | 16.0% | 64.0% | 82.0% |
| FFX134_BD | apv | $20 | 59 | 260 | 440 | 59.1% | -40.93% | 0.7216 | 10.5% | 36.8% | 78.9% |

## Per-FT breakdown

### FFX134_BD / sov

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 20 | 5,374 | 5,735 | -6.3% |
| 1 | Freeway | 4 | 48,169 | 48,277 | -0.2% |
| 3 | MinArt | 10 | 10,319 | 10,719 | -3.7% |
| 4 | Collector | 16 | 12,861 | 12,722 | +1.1% |
| 5 | Exprw | 8 | 15,746 | 17,598 | -10.5% |
| 6 | Ramps | 1 | 592 | 609 | -2.9% |

### FFX134_BD / hov2

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 20 | 616 | 753 | -18.1% |
| 1 | Freeway | 4 | 125 | 112 | +11.6% |
| 3 | MinArt | 10 | 1,175 | 1,188 | -1.1% |
| 4 | Collector | 16 | 1,554 | 1,299 | +19.6% |
| 5 | Exprw | 8 | 2,121 | 2,488 | -14.7% |
| 6 | Ramps | 1 | 0 | 0 | +800.0% |

### FFX134_BD / hov3

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 20 | 274 | 368 | -25.5% |
| 1 | Freeway | 4 | 31 | 58 | -47.5% |
| 3 | MinArt | 10 | 587 | 636 | -7.7% |
| 4 | Collector | 16 | 843 | 1,116 | -24.4% |
| 5 | Exprw | 8 | 1,717 | 1,881 | -8.7% |
| 6 | Ramps | 1 | 0 | 0 | -90.3% |

### FFX134_BD / com

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 20 | 1,169 | 1,227 | -4.7% |
| 1 | Freeway | 4 | 2,072 | 3,153 | -34.3% |
| 3 | MinArt | 10 | 1,822 | 2,032 | -10.3% |
| 4 | Collector | 16 | 1,853 | 1,666 | +11.2% |
| 5 | Exprw | 8 | 2,646 | 2,773 | -4.6% |
| 6 | Ramps | 1 | 15 | 57 | -73.4% |

### FFX134_BD / trk

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 20 | 406 | 489 | -17.1% |
| 1 | Freeway | 4 | 5,449 | 5,272 | +3.4% |
| 3 | MinArt | 10 | 1,284 | 1,646 | -22.0% |
| 4 | Collector | 16 | 665 | 661 | +0.6% |
| 5 | Exprw | 8 | 994 | 1,127 | -11.8% |
| 6 | Ramps | 1 | 53 | 62 | -14.3% |

### FFX134_BD / apv

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 20 | 21 | 31 | -33.6% |
| 1 | Freeway | 4 | 84 | 272 | -69.0% |
| 3 | MinArt | 10 | 66 | 74 | -11.3% |
| 4 | Collector | 16 | 59 | 38 | +55.9% |
| 5 | Exprw | 8 | 30 | 25 | +22.4% |
| 6 | Ramps | 1 | 0 | 0 | +0.0% |
