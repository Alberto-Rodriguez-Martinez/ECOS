# ECOS Notebook — Block 3: Experimental Control and Validation

## Objective

Verify that our measurements are trustworthy before drawing scientific
conclusions. This block answers the question every reviewer will ask:
"Are your results real, or are they artifacts of your measurement
setup?"

Specifically:
- Is temperature well controlled? Does it affect Cl?
- Is the density measurement reliable? (vessel radius sensitivity)
- Are there outliers that distort the analysis?
- Is inter-piece variability due to fabrication or measurement noise?

This block does NOT generate results for the paper directly. It
generates **confidence** in the results of Blocks 1 and 2. It should
be run first chronologically, but is presented as Block 3 because
it requires context from the previous blocks to interpret.

---

## Cell 3.0 — Temperature control overview

### What it shows
Two subplots:
- Left: Histogram of US temperatures (mean of T1, T2) across all
  measurements. Overlay a vertical line at target = 36°C.
  Include mean ± SD annotation.
- Right: Histogram of DENS temperatures (T_C) across all measurements.
  Overlay vertical line at nominal room temperature (if known, ~22°C).

### How to read it
- Narrow distribution centered on target → good control
- Wide or bimodal distribution → temperature varied significantly
- Systematic offset from target → calibration issue

### What to compute
- US: mean, SD, min, max of T_mean = (T1+T2)/2
- DENS: mean, SD, min, max of T_C
- Percentage of measurements within ±1°C of target

### Red flags
- US temperature SD > 1°C → poor control
- Any measurement below 30°C or above 40°C → anomalous
- Systematic difference between T1 and T2 → sensor calibration issue

### Pedagogical note
Temperature affects the speed of sound in water (Cw), which is used
to calculate Cl. A 1°C error in temperature causes approximately
3 m/s error in Cw, which propagates into Cl. Students should
understand this error chain.

---

## Cell 3.1 — T1 vs T2 sensor agreement

### What it shows
Scatter plot: x = T1, y = T2. Include identity line (y = x).
Color by cycle.

### How to read it
- Points on the identity line → sensors agree
- Systematic offset → one sensor is biased (calibration needed)
- Random scatter → sensors are noisy

### What to compute
- Mean difference T1 − T2 and its SD
- Bland-Altman style analysis: plot (T1−T2) vs (T1+T2)/2
  with ±1.96 SD limits of agreement
- Paired t-test: is mean(T1−T2) significantly different from 0?

### Why it matters
If T1 and T2 disagree systematically, the temperature we use for
Cw calculation (their mean) has a known bias. This should be
quantified and reported.

### Implementation
Two subplots:
- Left: T1 vs T2 scatter with identity line
- Right: Bland-Altman plot (difference vs mean)

---

## Cell 3.2 — Cl vs temperature: is there a confounding effect?

### What it shows
Scatter: x = T_mean (US), y = Cl. Color by PVA%. Include regression
line and correlation statistics (r, p, R²) as annotation.

### How to read it
- No correlation (r ≈ 0, p > 0.05) → temperature is NOT confounding.
  This is the expected and desired result.
- Significant correlation → temperature explains part of the Cl
  variability. This is a problem — it means our Cl differences
  between conditions might partly reflect temperature differences.

### Extended analysis
If correlation is significant:
- Compute partial correlation of Cl with PVA%, controlling for T
- Compare with uncorrected correlation
- If partial r ≈ raw r → temperature is not a real confounder
  (it correlates with Cl by coincidence, not causation)

### What to compute
- Pearson r, p-value
- Linear regression slope: dCl/dT (m/s per °C)
- R² — fraction of Cl variance explained by temperature
- Text annotation on plot with these values

### Pedagogical note
Correlation ≠ causation. Even if Cl correlates with T, it might be
because both vary with measurement day, not because T causes Cl to
change. To establish causation, we would need a controlled temperature
sweep (same piece measured at multiple temperatures). That experiment
is recommended for future work.

---

## Cell 3.3 — Temperature distribution across conditions

### What it shows
Boxplot: US temperature grouped by condition (PVA% × PG%).
Points overlaid.

### How to read it
- All boxes at the same level → temperature is consistent across
  conditions. Good — temperature is not confounded with composition.
- Some conditions measured at higher T → potential confound.

### What to compute
- One-way ANOVA: does mean temperature differ across conditions?
- If significant → which conditions differ? (Tukey HSD)

### Why it matters
If PVA 15% happens to be measured at higher temperatures than
PVA 10%, any Cl difference between them could be partly due to
temperature. This would be a serious confound.

---

## Cell 3.4 — Temperature distribution across cycles

### What it shows
Boxplot: US temperature grouped by cycle. Points overlaid.

### How to read it
Same logic as 3.3 but for the evolution factor. If later cycles
were measured on warmer days, the cycle trend could be contaminated.

### What to compute
- One-way ANOVA or Kruskal-Wallis: does T differ across cycles?

---

## Cell 3.5 — Density measurement sensitivity: vessel radius

### What it shows
Reuse the vessel radius sensitivity analysis from the exploratory
notebook. Two subplots:
- Left: Density vs vessel radius — family of curves, one per
  specimen. Highlight the current r value with a vertical line.
  Add a green shaded region for expected density range (1.00–1.15).
- Right: Boxplots comparing original density vs recalculated
  density at a test radius. Include a slider variable `r_test`
  that the user can adjust.

### How to read it
- If the green region is only reached at a very different radius →
  the current radius measurement may be wrong
- If curves are steep near our r value → density is very sensitive
  to radius; small measurement error → large density error
- If curves are flat → density is robust to radius uncertainty

### What to compute
- Sensitivity: dρ/dr at the nominal radius
- Relative error: (Δρ/ρ) per (Δr/r) — the error multiplier
- Optimal r: the radius value that places mean density closest to
  expected range

### Pedagogical note
This is an excellent example of **error propagation** for students.
ρ = m / (π r² Δh). Since r appears squared, a 1% error in r causes
approximately 2% error in ρ. Derive this analytically:
dρ/ρ = −2 dr/r (for fixed m and Δh).

---

## Cell 3.6 — Density validation: mass and volume consistency

### What it shows
Two subplots:
- Left: Scatter of mass (g) vs condition — check that masses are
  physically reasonable and consistent within conditions.
  Same-composition pieces should have similar mass.
- Right: Scatter of V_disp (cm³) vs condition — same check.

### How to read it
- Tight clusters within conditions → consistent fabrication
- Outliers → possible weighing error or piece damage
- Mass increasing with PVA% → expected (denser material)

### Red flags
- Mass values suspiciously round (e.g., exactly 5.0 g) → manual
  entry, possibly approximate
- V_disp negative or zero → measurement error
- V_disp >> mass → density << 1, physically unreasonable

---

## Cell 3.7 — Outlier detection

### What it shows
For each measurement variable (Cl, density, d, T), identify outliers
using the IQR method within each condition.

Display a table listing:
| Condition | Piece | Cycle | Variable | Value | Lower/Upper fence | Flag |

### How to compute
Within each (PVA%, PG%, cycle) group:
- Q1 = 25th percentile, Q3 = 75th percentile
- IQR = Q3 − Q1
- Lower fence = Q1 − 1.5 × IQR
- Upper fence = Q3 + 1.5 × IQR
- Values outside fences → flagged

### How to interpret
With n=5, the IQR method is crude. A "flagged" point is not
necessarily wrong — it is a point worth investigating. Possible
actions:
1. Check the raw signals for that measurement (load_signals)
2. Check if the same piece is an outlier in other variables
3. Check if the same piece is an outlier at other cycles
4. If consistently anomalous → fabrication defect (document, possibly
   exclude with justification)
5. If isolated → measurement error (document, possibly remeasure)

### Pedagogical note
**Never delete data without justification.** If you exclude a point,
report the analysis both with and without it. If the conclusion
changes, the result is not robust and you must say so.

---

## Cell 3.8 — Reproducibility: coefficient of variation

### What it shows
Heatmap (3 × 4 grid: PVA% × PG%) of CV(%) for Cl, and a second
heatmap for CV(%) for density. Annotate each cell with the CV value.

### How to read it
- CV < 1% → excellent reproducibility
- CV 1–3% → acceptable
- CV > 5% → poor — either fabrication is inconsistent or
  measurement is noisy
- Systematically higher CV in certain conditions → those compositions
  are harder to fabricate reproducibly

### What to compute
CV = (SD / mean) × 100, per condition per cycle.
Average across cycles if multiple are available.

### Why it matters
This quantifies the answer to "can someone else reproduce our
phantoms?" — a question reviewers will ask. Industry standards
for tissue-mimicking phantoms (IEC 60601) typically require CV < 5%.

---

## Cell 3.9 — Residual analysis: what explains Cl variability?

### What it shows
A stacked bar chart or table showing the fraction of total Cl
variance explained by:
- PVA% (main effect)
- PG% (main effect)
- Cycle (main effect)
- PVA × PG interaction
- Temperature (covariate)
- Residual (unexplained)

### How to compute
This is essentially a breakdown of the ANOVA sum of squares.
Use the η² values from the full factorial ANOVA
(Cl ~ PVA + PG + Cycle + PVA:PG + T) to compute the proportion
of variance explained by each factor.

### How to read it
- PVA and PG should explain most variance → factors are effective
- Temperature explaining >5% → confounding concern
- Large residual → important sources of variability are missing
  (fabrication inconsistency? unmeasured factor?)

### Why it matters
This is the meta-analysis of the experiment. It tells you whether
your factors are the right ones, and whether your control is adequate.

---

## Cell 3.10 — Summary and interpretation (Markdown cell)

```markdown
### Block 3 — Experimental Control Summary

**Temperature control (US):**
- Mean ± SD: [X] ± [Y] °C (target: 36°C)
- Range: [min]–[max] °C
- % within ±1°C of target: [Z]%
- Confounding with Cl: r = [value], p = [value]
- Confounding with condition: [yes/no]
- Confounding with cycle: [yes/no]

**Sensor agreement:**
- Mean T1−T2: [X] ± [Y] °C
- Significant bias? [yes/no]

**Density measurement:**
- Sensitivity to vessel radius: dρ/ρ per dr/r = [value]
- Values below 1.0 g/cm³: [count] out of [total]
- Suspected cause: [radius error / bubbles / other]

**Outliers identified:**
- [list or "none"]

**Reproducibility (CV):**
- Cl: range [min]–[max]% across conditions
- Density: range [min]–[max]%
- Assessment: [excellent / acceptable / concerning]

**Variance decomposition:**
- PVA explains [X]% of Cl variance
- PG explains [Y]%
- Cycle explains [Z]%
- Temperature explains [W]%
- Unexplained: [R]%

**Overall assessment:**
- [Are the measurements trustworthy? What caveats should be stated?]
```

---

## Visual style rules (consistent with Blocks 1 and 2)

- Figure size: (7, 5) single, (14, 5) side-by-side
- Color: `tab10`, same mapping as previous blocks
- Individual points shown on all boxplots
- Error bars = SD
- Grid: alpha=0.3
- Save: `fig_dir / 'B3_XX_description.png'` with dpi=150
