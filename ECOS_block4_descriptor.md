# ECOS Notebook — Block 4: Tissue-Mimicking Comparison

## Objective

Answer the central question of the ECOS project: **which combination
of (PVA%, PG%, cycles) best mimics specific soft tissues?**

This block connects our measured properties with clinical reference
values from the literature. It is the bridge between material
characterization (Blocks 1–2) and the intended application (surgical
robotics phantom validation).

This block will likely produce the most impactful figures for the
paper — the ones that justify why this work matters.

---

## Literature reference values

Values compiled from project literature (Zell 2007, Duck 1990,
ICRU Report 61, and papers in the project knowledge base).
**These must be verified against the actual papers before publication.**

| Tissue | Cl (m/s) | ρ (g/cm³) | Z (MRayl) | α at 1 MHz (dB/cm) | Source |
|--------|----------|-----------|-----------|---------------------|--------|
| Water (37°C) | 1524 | 1.000 | 1.524 | 0.002 | Reference |
| Liver | 1540–1590 | 1.06 | 1.63–1.69 | 0.5–0.9 | Zell 2007, Duck 1990 |
| Breast (fat) | 1430–1480 | 0.93–0.99 | 1.33–1.46 | 0.5–1.5 | Duck 1990 |
| Breast (glandular) | 1510–1570 | 1.02–1.06 | 1.54–1.66 | 0.8–2.0 | Duck 1990 |
| Muscle | 1545–1630 | 1.04–1.06 | 1.61–1.73 | 0.5–1.5 | Duck 1990 |
| Kidney | 1560–1570 | 1.05 | 1.64 | 0.9–1.0 | Duck 1990 |
| Blood | 1570–1584 | 1.06 | 1.66–1.68 | 0.14–0.18 | Duck 1990 |
| Brain (grey matter) | 1530–1560 | 1.04 | 1.59–1.62 | 0.6–0.8 | Duck 1990 |

**Important**: These ranges come from multiple sources and measurement
conditions. They should be treated as approximate targets, not exact
specifications. Tissue properties vary with patient, location within
the organ, temperature, and measurement method.

---

## Cell 4.0 — Reference table (Markdown + code)

### What it shows
Display the tissue reference table above as a formatted DataFrame.
Store the reference values as a dictionary in code so they can be
used programmatically in subsequent cells.

### Implementation
```python
tissue_refs = {
    'Liver':             {'Cl_min': 1540, 'Cl_max': 1590, 'rho_min': 1.05, 'rho_max': 1.07},
    'Breast (glandular)':{'Cl_min': 1510, 'Cl_max': 1570, 'rho_min': 1.02, 'rho_max': 1.06},
    'Muscle':            {'Cl_min': 1545, 'Cl_max': 1630, 'rho_min': 1.04, 'rho_max': 1.06},
    'Kidney':            {'Cl_min': 1560, 'Cl_max': 1570, 'rho_min': 1.04, 'rho_max': 1.06},
    'Brain':             {'Cl_min': 1530, 'Cl_max': 1560, 'rho_min': 1.03, 'rho_max': 1.05},
    'Water (37°C)':      {'Cl_min': 1520, 'Cl_max': 1528, 'rho_min': 1.00, 'rho_max': 1.00},
}
```

### Pedagogical note
Explain to students that these values represent *population ranges*,
not exact targets. A phantom matching the center of the range is not
necessarily better than one matching the edge. The goal is to fall
*within* the range.

---

## Cell 4.1 — Property map: Cl vs density with tissue regions

### What it shows
THE key figure of the paper. A 2D scatter plot:
- x = density (g/cm³)
- y = Cl (m/s)
- Each point = one specimen (mean across pieces, or individual points)
- Color = PVA%, marker shape = PG%
- Shaded rectangles or ellipses for each tissue type (from tissue_refs)
- Labels on each tissue region

### How to read it
- Points falling inside a tissue rectangle → that phantom composition
  mimics that tissue
- Points between regions → intermediate properties, could mimic
  with interpolation
- Empty tissue regions → no current formulation matches, need
  different composition
- Cluster spread → reproducibility of each formulation

### Implementation
- Plot individual points (not just means) to show spread
- Use `matplotlib.patches.Rectangle` with alpha=0.15 for tissue
  regions, with text label centered
- Add a legend for PVA% (color) and PG% (marker)
- Consider connecting points of same condition across cycles with
  thin arrows to show evolution direction

### Why it matters
This single plot demonstrates the tunability of PVA+PG phantoms and
identifies which clinical applications each formulation serves. It
answers the "so what?" question.

---

## Cell 4.2 — Property map evolution: one panel per cycle

### What it shows
Same as 4.1 but as a multi-panel figure (one subplot per cycle).
Tissue regions stay fixed; data points shift between panels.

### How to read it
- Points migrating toward a tissue region with more cycles →
  cycling "tunes" the phantom closer to that tissue
- Points migrating away → overprocessing, need fewer cycles
- All points shifting in the same direction → systematic effect

### Implementation
Subplot grid: 1 row × N_cycles columns. Same axis limits across
all panels for direct comparison. Share y-axis.

---

## Cell 4.3 — Distance to tissue: quantitative matching

### What it shows
For each phantom condition and each target tissue, compute a
normalized distance metric that quantifies how close the phantom
is to the tissue.

Display as a heatmap: rows = phantom conditions (PVA% × PG% × cycle),
columns = target tissues. Color = distance (green = close, red = far).
Annotate cells with the distance value.

### How to compute
Normalized Euclidean distance:

```
d = sqrt( ((Cl_phantom - Cl_tissue_center) / Cl_tissue_range)² +
          ((ρ_phantom - ρ_tissue_center) / ρ_tissue_range)² )
```

Where:
- Cl_tissue_center = (Cl_min + Cl_max) / 2
- Cl_tissue_range = (Cl_max - Cl_min) / 2
- Same for ρ

A distance < 1 means the phantom falls within the tissue's property
ellipse. Distance > 1 means outside.

### How to read it
- Green cells (d < 1) → phantom matches tissue
- Yellow cells (d ≈ 1) → borderline match
- Red cells (d > 2) → poor match
- Row with many green cells → versatile phantom
- Column with no green cells → that tissue cannot be matched with
  current formulations

### Why it matters
This is a quantitative answer to "which phantom for which tissue?"
It converts a visual inspection (Cell 4.1) into a number that can
be tabulated, compared, and optimized.

### Pedagogical note
The normalization is critical. Without it, Cl (values ~1500) would
dominate the distance over density (values ~1.0). The normalization
puts both properties on the same scale relative to the tissue's
natural variability range.

---

## Cell 4.4 — Best match recommendation table

### What it shows
A summary table: for each target tissue, list the top 3 phantom
conditions ranked by distance (from Cell 4.3). Include the distance
value, Cl, and density of the phantom.

| Target tissue | Rank | PVA% | PG% | Cycle | Cl (m/s) | ρ (g/cm³) | Distance |
|---------------|------|------|-----|-------|----------|-----------|----------|

### Why it matters
This is the practical output — the recipe book. A robotics engineer
who needs a liver phantom looks at this table and knows what to
fabricate.

---

## Cell 4.5 — Impedance matching

### What it shows
Bar chart: acoustic impedance Z for each condition (PVA% × PG%),
with horizontal bands for tissue reference Z values.

### How to read it
- Bars within a tissue band → impedance match
- Impedance matching is critical for realistic ultrasound images:
  reflections at interfaces depend on Z contrast

### Implementation
- Grouped bars (by PVA%), colored by PG%
- Horizontal shaded bands for each tissue Z range
- Include water Z as reference

---

## Cell 4.6 — Spider/radar chart: multi-property matching

### What it shows
For a selected phantom condition, overlay its properties on a radar
chart alongside the target tissue. Axes: Cl, density, Z, (and
attenuation if available in future).

### How to read it
- Phantom polygon overlapping tissue polygon → good match
- Mismatch on one axis → that property needs adjustment

### Implementation
- Use matplotlib polar projection
- Normalize each axis to the tissue range (0 = tissue_min, 1 = tissue_max)
- Show one radar per target tissue, with the best-matching phantom
  overlaid

### Limitation
With only Cl and density, this is a 2-axis radar (effectively a bar
chart). It becomes truly useful when attenuation and shear velocity
are added. Include it now as a placeholder that motivates future
measurements.

---

## Cell 4.7 — Gap analysis: what tissues can we NOT match?

### What it shows
A markdown cell + supporting plot identifying which tissue types
fall outside the reachable property space of our current phantoms.

### What to compute
- Convex hull of all measured (Cl, ρ) points
- Which tissue reference rectangles fall entirely outside this hull?
- Which are partially inside?

### Why it matters
This identifies the limitations of PVA+PG and motivates:
- Additional dopants (e.g., nanoparticles, cellulose)
- Different PVA concentrations
- Alternative base materials (agar, gelatin)
It also sets up future work in the paper's discussion section.

---

## Cell 4.8 — Literature comparison plot

### What it shows
Overlay our data on published Cl vs PVA% curves from the project
literature. This validates our measurements against independent
results.

### Implementation
- Plot our mean Cl vs PVA% (at PG=0, to isolate the PVA effect)
- Overlay data points or curves from:
  - Zell 2007
  - Surry 2004
  - Fromageau 2007
  - Other papers in the project knowledge base
- Include error bars for both our data and literature values

### How to read it
- Our data within literature scatter → measurements are consistent
  with published work. Strong validation.
- Systematic offset → possible methodological difference (temperature,
  PVA molecular weight, number of cycles, measurement technique)
- Similar slope, different intercept → offset is additive (e.g.,
  temperature difference)

### Why it matters
Reviewers will compare your results with existing literature. Showing
this comparison proactively, with discussion of any differences,
demonstrates rigor and saves review cycles.

### Data extraction from literature
Values from papers must be extracted carefully:
- Use the project PDFs and extract data from tables or figures
- Document which paper, which table/figure, which conditions
- Note differences in methodology (temperature, PVA type, cycle
  protocol, measurement method)

---

## Cell 4.9 — Summary and interpretation (Markdown cell)

```markdown
### Block 4 — Tissue-Mimicking Summary

**Property space coverage:**
- Cl range achieved: [min]–[max] m/s
- Density range achieved: [min]–[max] g/cm³
- Z range achieved: [min]–[max] MRayl

**Best matches:**
- Liver: [condition], distance = [d]
- Muscle: [condition], distance = [d]
- Brain: [condition], distance = [d]
- Breast (glandular): [condition], distance = [d]

**Tissues NOT matchable with current formulations:**
- [list, with explanation of what property is missing]

**Comparison with literature:**
- [agreement / discrepancy, with possible explanations]

**Recommendations for phantom fabrication:**
- For [tissue]: use PVA [X]%, PG [Y]%, [N] cycles
- [repeat for each tissue]

**Limitations:**
- Only Cl and ρ used for matching (no attenuation, no shear)
- Tissue reference values have wide ranges
- Temperature differences between our measurements and literature
- [other]

**Future work needed:**
- [specific measurements or compositions to try]
```

---

## Visual style rules (consistent with Blocks 1–3)

- Figure size: (7, 5) single, (14, 5) side-by-side, (14, 10) for
  multi-panel
- Color: `tab10` for phantom conditions (consistent mapping)
- Tissue regions: use a separate muted palette (pastel) to avoid
  visual conflict with data points
- Individual points shown where n is small
- Grid: alpha=0.3
- Save: `fig_dir / 'B4_XX_description.png'` with dpi=150
