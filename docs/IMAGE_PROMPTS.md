# Image-generation prompts — easy-to-follow diagrams for TAPLite4MPO

Copy-paste these into a GPT image tool (GPT-4o / DALL·E 3, Sora image, etc.) to make clean,
consistent figures for the README, the onboarding guide, and slides.

**Two tips for readable results**
1. Image models render *short* labels well and *long* text poorly. Each prompt keeps labels
   to 1–3 words. If a label comes out garbled, generate the **text-free** version (append
   *"no text labels, leave clean space for captions"*) and add captions in PowerPoint/Figma.
2. Reuse the **STYLE** block below at the start of every prompt so the set looks cohesive.

> **STYLE (prepend to each prompt):**
> Flat 2D vector infographic, clean and minimal, generous white background, soft modern
> palette of blue, teal and amber with dark slate text, rounded rectangles, simple thin-line
> icons, clear flow with thin arrows, lots of whitespace, professional, friendly. No
> photorealism, no 3D, no heavy drop shadows, no clutter. 16:9.

---

## 1. The Golden Path (overview)
*Use for: README top, onboarding guide hero, slide 1.*

> [STYLE] A horizontal left-to-right pipeline of six rounded-rectangle steps connected by
> thin arrows, each with a small line icon and a one-word label below:
> 1 a stack of map and document files — "Collect";
> 2 a network of dots and lines — "Map to GMNS";
> 3 a clipboard with checkmarks — "Declare";
> 4 a small car at a traffic signal — "Run";
> 5 a shield with a checkmark — "Validate";
> 6 a gear with a small rocket — "Advanced".
> Title across the top: "From agency files to a trusted assignment". Calm, confident, tidy.

## 2. The three gates
*Use for: the "simple first" front door, dashboard explainer.*

> [STYLE] A single straight road running left to right, passing through three tall checkpoint
> gates evenly spaced. Each gate is a rounded panel with a coloured top bar and a big number:
> gate 1 red bar — "Can I run?"; gate 2 amber bar — "Can I trust it?"; gate 3 green bar —
> "Can I improve it?". A small car waits at gate 1. Conveys: pass each gate in order.

## 3. A shapefile is not yet a model
*Use for: the core teaching idea (why declarations matter).*

> [STYLE] Three zones left to right. Left: a flat map outline (a shapefile) plus a small grid
> matrix, both sprinkled with small question marks reading "capacity?", "units?", "period?".
> Middle: a funnel labelled "Declare conventions". Right: a neat assembled road-network model
> with a green checkmark labelled "Runnable model". Thin arrows flow left to right. Conveys:
> raw data plus declared conventions equals a model.

## 4. The dataset ladder
*Use for: DATASET_LADDER.md, "which example to start with".*

> [STYLE] An ascending staircase of four rounded blocks, each larger than the last, a small
> friendly figure stepping up. Tiny icon on each step: step 1 a small grid — "Chicago Sketch";
> step 2 a bigger city grid — "Chicago Regional"; step 3 a detailed metro map — "ARC Atlanta";
> step 4 a map pin — "OSM" (slightly faded, marked "soon"). Conveys: start small, climb to
> full agency reproduction.

## 5. Super-zones — compress the response, not the data
*Use for: SUPERZONE.md, the acceleration story.*

> [STYLE] Two side-by-side panels over the SAME visible road network (thin grey lines kept in
> both). Left panel: the region covered by many small coloured zones. Arrows show clusters of
> neighbouring zones merging into a few larger "super-zones" in the right panel. The road
> network stays identical in both. A small rounded badge in the corner: "~2x faster". Conveys:
> fewer origins, same network.

## 6. The key advantage — recover the original skim
*Use for: SUPERZONE.md §4, the headline benefit.*

> [STYLE] Left: a compact network of a few big super-zones (labelled "compressed run, 2x
> faster"). A thick arrow into the middle: a full detailed road network (many thin lines,
> labelled "full link network kept"). A thick arrow to the right: a clean grid/heatmap of
> cells labelled "zone-to-zone travel time — original resolution". A small green badge:
> "R² 0.99". Conveys: a fast compressed run still yields the full-resolution travel-time skim.

---

### Optional cohesion prompt
To regenerate any image to match an existing one, append:
> *Match the style, palette, line weight and icon style of the previous image exactly.*
