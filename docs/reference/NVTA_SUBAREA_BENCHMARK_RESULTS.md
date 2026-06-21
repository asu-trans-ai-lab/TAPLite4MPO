# NVTA Sub-area Benchmark — Conic VDF + Per-Link PLF

**Period:** AM  **Mode:** sov  **VOT:** $10/hr  **Iterations:** 20

**Engine:** `C:/t/cg_kernel_v2/Release/tap_lite_cg.exe` (v3 schema with vdf_type per link)

**Pipeline:** `docs/NVTA_SUBAREA_CONIC_PIPELINE.md`

## System-level results

| Sub-area | n_links | Engine | Cube | Match% | Bias | R² | ±10% | ±25% | ±50% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FFX134_BD | 59 | 93,060 | 95,660 | 97.3% | -2.72% | 0.9987 | 64.0% | 92.0% | 98.0% |
| FFX134_NB | 59 | 93,060 | 95,660 | 97.3% | -2.72% | 0.9987 | 64.0% | 92.0% | 98.0% |
| LDN034_BD | 28 | 21,683 | 22,285 | 97.3% | -2.70% | 0.9160 | 75.0% | 82.1% | 92.9% |
| LDN034_NB | 28 | 21,683 | 22,285 | 97.3% | -2.70% | 0.9160 | 75.0% | 82.1% | 92.9% |

## Per-FT breakdown

### FFX134_BD

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 20 | 5,374 | 5,735 | -6.3% |
| 1 | Freeway | 4 | 48,169 | 48,277 | -0.2% |
| 3 | MinArt | 10 | 10,319 | 10,719 | -3.7% |
| 4 | Collector | 16 | 12,861 | 12,722 | +1.1% |
| 5 | Exprw | 8 | 15,746 | 17,598 | -10.5% |
| 6 | Ramps | 1 | 592 | 609 | -2.9% |

### FFX134_NB

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 20 | 5,374 | 5,735 | -6.3% |
| 1 | Freeway | 4 | 48,169 | 48,277 | -0.2% |
| 3 | MinArt | 10 | 10,319 | 10,719 | -3.7% |
| 4 | Collector | 16 | 12,861 | 12,722 | +1.1% |
| 5 | Exprw | 8 | 15,746 | 17,598 | -10.5% |
| 6 | Ramps | 1 | 592 | 609 | -2.9% |

### LDN034_BD

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 8 | 1,851 | 1,677 | +10.4% |
| 3 | MinArt | 6 | 7,855 | 7,847 | +0.1% |
| 4 | Collector | 14 | 11,977 | 12,762 | -6.2% |

### LDN034_NB

| FT | Name | n | Engine | Cube | Diff% |
|---:|---|---:|---:|---:|---:|
| 0 | Centroid | 8 | 1,851 | 1,677 | +10.4% |
| 3 | MinArt | 6 | 7,855 | 7,847 | +0.1% |
| 4 | Collector | 14 | 11,977 | 12,762 | -6.2% |
