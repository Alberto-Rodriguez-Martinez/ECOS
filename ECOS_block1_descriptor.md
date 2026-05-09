# ECOS Notebook — Block 1: Static Characterization (per cycle)

## Objective

Characterize the effect of PVA% and PG% on Cl and density at each
fixed cycle. This is the foundational analysis: before studying
evolution (Block 2), we must understand the cross-sectional picture.

## Prerequisites

- `ecos_loader.py` produces a merged DataFrame with US and DENS data
- `pva_real` column created (125 → 12.5)
- Numeric conversion of `pva_pct`, `pg_pct`, `cycle` done

## User controls

The notebook should include a **cycle selector** at the top of Block 1.
All plots and statistics in this block are computed for the selected
cycle. This allows repeating the entire analysis for each cycle
independently, and visually comparing outputs.

Implementation: a simple variable `CYCLE = 3` at the top of the block,
with a markdown cell explaining that the user should change this value
and re-run the block. (Interactive widget optional; simple variable is
more robust and reproducible.)

```python
# ========== USER: select cycle to analyze ==========
CYCLE = 3
df_cycle = df[df["cycle"] == CYCLE].copy()
print(f"Block 1: analyzing cycle {CYCLE}")
print(f"  Specimens: {len(df_cycle)}")
print(f"  Conditions: {df_cycle[['pva_real','pg_pct']].drop_duplicates().shape[0]}")
```

---

## Cell 1.1 — Summary statistics table

### What it shows
A table with one row per condition (PVA% × PG%), reporting mean ± SD
and n for Cl, density, thickness, impedance Z, and modulus M.

### How to read it
- Compare means across rows to see the effect of composition
- SD tells you within-condition variability (reproducibility)
- n should be 5 for every condition; if not, data is missing

### What to compute
- `df_cycle.groupby(['pva_real', 'pg_pct']).agg(...)` for:
  - US_Cl: mean, std, count
  - DENS_density_gcm3: mean, std, count
  - US_d: mean, std
  - Z: mean, std
  - M_GPa: mean, std
- Format as mean ± SD with 2 decimal places for Cl, 4 for density

### Why it matters
This table will appear in the paper. Reviewers expect it. It is also
the quickest way to spot anomalies (unexpected values, missing data,
high SD).

### Red flags
- n < 5 → missing data, investigate
- SD(Cl) > 15 m/s within a condition → poor reproducibility or outlier
- SD(density) > 0.03 → fabrication inconsistency
- density < 1.0 → measurement problem (see Study Rules §4)

### Pedagogical note for students
The **coefficient of variation** (CV = SD/mean × 100%) is more
informative than SD alone for comparing reproducibility across
quantities with different scales. A CV < 1% for Cl is excellent.
Include a CV column.

---

## Cell 1.2 — Grouped boxplots: Cl by condition

### What it shows
Boxplots of Cl, one per condition (PVA% × PG%), with individual
data points overlaid as jittered dots.

### How to read it
- Box = IQR (25th to 75th percentile); line = median
- Whiskers extend to 1.5×IQR; points outside = potential outliers
- Compare medians across conditions for effect of composition
- Box width reflects variability

### Implementation
Same as current boxplot, but with individual points overlaid (scatter
with small jitter). This is critical with n=5: the box alone can be
misleading, the actual data points tell the real story.

### Why it matters
Boxplots with n=5 are at the limit of usefulness. Showing individual
points is essential — it lets you see if the "distribution" is real or
an artifact of small n.

### Pedagogical note
Explain to students: with n=5, the median can be any of the 5 values.
The box boundaries are computed from 5 numbers. Do not over-interpret
the box shape. The individual points ARE the data.

---

## Cell 1.3 — Grouped boxplots: Density by condition

### What it shows
Same as 1.2 but for density. Include a horizontal reference line at
ρ = 1.0 g/cm³ (physical lower bound for PVA hydrogels).

### Red flags
Any points below the 1.0 line need investigation (see Study Rules).

---

## Cell 1.4 — Scatter: Cl vs PVA%, colored by PG% (jittered)

### What it shows
Individual Cl measurements on y-axis, PVA% on x-axis, color = PG%.
Groups are horizontally jittered to avoid overlap.

### How to read it
- Vertical trend within a color → PVA effect for that PG level
- Separation between colors at same PVA% → PG effect
- Spread within a cluster → within-condition variability

### Why it matters
This separates the two factors visually. If all colors follow the
same upward trend, PVA is the dominant factor and PG is secondary.
If colors are interleaved, PG has a comparable effect.

---

## Cell 1.5 — Scatter: Cl vs PG%, colored by PVA% (jittered)

### What it shows
Same as 1.4 with axes swapped. Complementary view.

---

## Cell 1.6 — 3D surface / scatter: Cl = f(PVA%, PG%)

### What it shows
A 3D scatter plot with PVA% on x-axis, PG% on y-axis, Cl on z-axis.
Individual points colored by Cl (colormap). Optionally, overlay a
fitted surface (planar or quadratic).

### How to read it
- Tilt of surface in PVA direction → PVA effect
- Tilt in PG direction → PG effect
- Twist → interaction effect (PVA effect changes with PG level)
- Points far from surface → residuals / poor fit

### Implementation
Use `matplotlib` 3D projection. Include rotation controls in the
notebook (elevation and azimuth as variables). Also provide a 2D
contour/heatmap version (top-down view of the surface) for the paper,
since 3D plots are hard to read in print.

### Pedagogical note
3D plots are seductive but often misleading. The 2D contour plot
carries the same information and is easier to read. Show both and
discuss the tradeoffs with students.

---

## Cell 1.7 — Heatmap: mean Cl by (PVA%, PG%)

### What it shows
A 3×4 heatmap grid. Rows = PVA%, columns = PG%. Color = mean Cl.
Annotate each cell with the mean ± SD value.

### How to read it
- Color gradient along rows → PVA effect
- Color gradient along columns → PG effect
- Diagonal gradient → interaction

### Why it matters
This is the most compact representation of the full factorial design.
It will likely be a key figure in the paper.

### Implementation
Use `seaborn.heatmap` or `matplotlib.imshow` with annotations.

---

## Cell 1.8 — Heatmap: mean density by (PVA%, PG%)

Same as 1.7 but for density.

---

## Cell 1.9 — Scatter: Cl vs density (all conditions)

### What it shows
Each point is one specimen. x = density, y = Cl. Color = PVA%.
Marker shape = PG%.

### How to read it
- Strong positive correlation → Cl and ρ are coupled; you cannot
  tune one without moving the other. This limits the phantom's
  usefulness (tissue matching requires independent control).
- Weak or no correlation → Good news: Cl and ρ can be adjusted
  somewhat independently.
- Distinct clusters → compositions produce clearly different
  property combinations.

### What to compute
- Pearson r and p-value
- Report on the plot as annotation

### Why it matters
This is a fundamental result for tissue mimicking. If Cl and ρ are
strongly coupled, you need a third degree of freedom (e.g., dopants,
different polymer) to match both properties simultaneously.

### Overlay: tissue reference regions
Add shaded rectangles or ellipses for:
- Liver: Cl ≈ 1540–1590 m/s, ρ ≈ 1.06 g/cm³
- Breast: Cl ≈ 1430–1570 m/s, ρ ≈ 0.99–1.06 g/cm³
- Muscle: Cl ≈ 1545–1630 m/s, ρ ≈ 1.04–1.06 g/cm³
(Values from Zell 2007, Duck 1990 — verify with project literature)

---

## Cell 1.10 — Two-way ANOVA: Cl = f(PVA%, PG%)

### What it computes
- Main effect of PVA% on Cl
- Main effect of PG% on Cl
- Interaction effect PVA% × PG%
- For each: F statistic, p-value, η² (effect size)

### How to interpret
- Significant main effect (p < 0.05) + large η² → this factor
  matters practically
- Significant interaction → the effect of PVA depends on PG level
  (or vice versa). This complicates interpretation but is common.
- Non-significant with n=5 → inconclusive (low power), not "no effect"

### Post-hoc: Tukey HSD
Pairwise comparisons between all PVA levels (at each PG) and all PG
levels (at each PVA). Report which pairs are significantly different.

### Assumptions to check
1. **Normality** within each group — Shapiro-Wilk test (but with n=5,
   this test has very low power; visual inspection via Q-Q plot is
   equally valid)
2. **Homogeneity of variance** — Levene's test. If violated, use
   Welch's ANOVA.
3. **Independence** — satisfied by design (different pieces)

### Pedagogical note
ANOVA tells you IF there is a difference somewhere. Post-hoc tells
you WHERE. Effect size tells you if it MATTERS. You need all three.

### Implementation
Use `scipy.stats.f_oneway` for one-way, or `statsmodels` for two-way
ANOVA with interaction. If `statsmodels` is not available, compute
manually or use `pingouin` library.

Display results as a formatted table:

| Source | SS | df | F | p | η² | Interpretation |
|--------|----|----|---|---|----|----------------|

---

## Cell 1.11 — Two-way ANOVA: density = f(PVA%, PG%)

Same as 1.10 but for density.

---

## Cell 1.12 — Summary and interpretation (Markdown cell)

A markdown cell at the end of Block 1 with a template for the student
to fill in:

```markdown
### Block 1 — Summary (Cycle X)

**Effect of PVA%:**
- On Cl: [describe direction, magnitude, significance]
- On density: [...]

**Effect of PG%:**
- On Cl: [...]
- On density: [...]

**Interaction PVA × PG:**
- [describe if present]

**Reproducibility:**
- CV for Cl: [range across conditions]
- CV for density: [range]

**Anomalies or concerns:**
- [list any unexpected observations]

**Tissue matching (preliminary):**
- Best match for liver: [condition]
- Best match for breast: [condition]
```

---

## Visual style rules (for all Block 1 cells)

- Figure size: (7, 5) for single plots, (14, 5) for side-by-side
- Color palette: `tab10` — consistent mapping across all plots
- Individual data points always shown (n=5 is too small for boxes alone)
- Grid: alpha=0.3
- Font sizes: xlabel/ylabel 12, title 13, legend 8-9
- Error bars: always SD (not SEM) — state in caption
- Save all figures: `fig_dir / 'B1_XX_description.png'` with dpi=150
