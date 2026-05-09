# ECOS Notebook — Block 2: Evolution across Freeze-Thaw Cycles

## Objective

Analyze how acoustic and physical properties evolve as phantoms undergo
successive freeze-thaw (F/T) cycles. Since the same pieces are measured
at every cycle, this is a **repeated-measures** analysis — the most
powerful design we have, because each specimen acts as its own control.

Key questions:
- Do properties change significantly between cycles?
- Do they converge (saturate) or keep changing?
- Does the rate of change depend on composition (PVA%, PG%)?
- How many cycles are needed for stable phantoms?

## Prerequisites

- Block 1 completed (we understand the cross-sectional picture)
- DataFrame `df` with multiple cycles loaded
- `pva_real` column created

## Important note on interpretation

Changes between cycles can be caused by:
1. **Cross-linking** (physical effect of freezing) — expected, desired
2. **Water loss/absorption** — confounding, check via mass/density
3. **PG migration** — cannot measure directly
4. **Aging** (time elapsed, not cycles) — cannot separate from cycle
   effect unless cycles are performed on different schedules

We cannot distinguish cause 1 from causes 2–4 with our current data.
Acknowledge this limitation in interpretation.

---

## Cell 2.0 — Cycle overview

### What it shows
A markdown cell + summary table: how many specimens and conditions
are available at each cycle. This is essential bookkeeping — if some
pieces were lost or not measured at a given cycle, it affects all
subsequent analyses.

### What to compute
```python
df.groupby('cycle')[['pva_real']].agg(['count']).T
# Also: check for missing pieces
df.pivot_table(index=['pva_real','pg_pct','piece'],
               columns='cycle', values='US_Cl', aggfunc='count')
```

### Red flags
- Any cell with count = 0 → missing measurement, investigate
- Unequal n across cycles → some paired tests will drop incomplete cases

---

## Cell 2.1 — Evolution of Cl by condition (mean ± SD)

### What it shows
Line plot: x = cycle, y = mean Cl. One line per condition (PVA% × PG%).
Error bars = SD. This is the "big picture" plot for the paper.

### How to read it
- Upward trend → cross-linking increases stiffness (expected)
- Lines converging → properties stabilize
- Lines crossing → rank order of conditions changes with cycles
- Widening error bars → reproducibility degrades with cycles
- Flat lines → no cycle effect for that condition

### Implementation
- x-axis: integer cycle numbers (3, 4, 5, ...)
- One line per condition, same color coding as Block 1
- 12 lines may be too many — consider two subplots:
  - Left: grouped by PVA% (3 panels or 3 colors, lines within = PG levels)
  - Right: grouped by PG% (4 panels or 4 colors, lines within = PVA levels)
- Error bars: SD, with caps

### Why it matters
This directly addresses H3 (cycles increase Cl) and H5 (convergence).
It will be a key figure in the paper.

---

## Cell 2.2 — Evolution of density by condition

### What it shows
Same as 2.1 but for density.

### Additional interpretation
- Density increase → water loss or polymer densification
- Density decrease → water absorption or structural degradation
- Compare the trend direction of density vs Cl: if both increase,
  the Cl increase may be partly explained by densification, not just
  stiffening.

---

## Cell 2.3 — Evolution of thickness by condition

### What it shows
Same format as 2.1 but for specimen thickness (US_d).

### Why it matters
Thickness changes indicate swelling or contraction. If a phantom
shrinks, its density increases even without compositional change.
This helps separate structural effects from density artifacts.

### Red flag
If thickness changes are large (>5%), the assumption of uniform
cross-section in the US measurement becomes questionable.

---

## Cell 2.4 — Paired differences ΔCl between consecutive cycles

### What it shows
For each piece, compute ΔCl = Cl(cycle n+1) − Cl(cycle n).
Boxplot of ΔCl grouped by condition, with individual points overlaid.
Include a horizontal reference line at ΔCl = 0.

### How to read it
- All boxes above 0 → Cl consistently increases with cycles
- Boxes shrinking toward 0 → rate of change decreases (convergence)
- Any boxes crossing 0 → change is not consistent across pieces
- Wide boxes → high variability in the change (unreliable)

### How to compute
```python
# Pivot to wide format: one column per cycle
pivot = df.pivot_table(index=['pva_real','pg_pct','piece'],
                       columns='cycle', values='US_Cl')
# ΔCl between consecutive cycles
for c1, c2 in zip(sorted_cycles[:-1], sorted_cycles[1:]):
    df_delta[f'dCl_{c1}_{c2}'] = pivot[c2] - pivot[c1]
```

### Why it matters
This is the **paired analysis** — it eliminates inter-specimen
variability and isolates the pure cycle effect. More powerful than
comparing group means. Essential for H3.

### Pedagogical note
Explain to students why paired analysis is more powerful: if piece A
is always 20 m/s faster than piece B (fabrication variability), that
difference cancels out in ΔCl. What remains is the true cycle effect.

---

## Cell 2.5 — Paired differences Δdensity between consecutive cycles

Same as 2.4 but for density. Important for understanding whether
density changes explain Cl changes.

---

## Cell 2.6 — Convergence analysis: rate of change vs cycle

### What it shows
Plot mean |ΔCl| (absolute change) vs cycle transition (3→4, 4→5, ...).
One line per condition. If the phantom stabilizes, this curve should
approach zero.

### How to read it
- Decreasing curve → convergence (good)
- Flat curve → constant rate of change (no stabilization yet)
- Increasing curve → degradation or instability (bad)

### What to compute
For each condition and cycle transition:
- mean |ΔCl|
- Also: compute the ratio ΔCl(n→n+1) / ΔCl(n-1→n) — if < 1,
  convergence; if > 1, divergence

### Why it matters
Directly addresses H5 and the practical question: "how many cycles
do I need?" This is critical for standardizing the fabrication protocol.

### Limitation
With only 2 cycles (3 and 4), we get a single transition point. This
cell becomes truly informative from 3+ cycles onward. Include it now
but note the limitation.

---

## Cell 2.7 — Interaction plot: cycle effect × composition

### What it shows
Two interaction plots side by side:
- Left: x = cycle, y = mean Cl, separate lines for each PVA%
  (averaged over PG%). Shows if the cycle effect depends on PVA%.
- Right: x = cycle, y = mean Cl, separate lines for each PG%
  (averaged over PVA%). Shows if the cycle effect depends on PG%.

### How to read it
- Parallel lines → no interaction (cycle effect is the same for
  all compositions)
- Non-parallel (diverging or crossing) → interaction exists
  (some compositions are more affected by cycling than others)

### Why it matters
If interaction exists, you cannot make general statements like
"each cycle increases Cl by X m/s" — the answer depends on
composition. This is scientifically interesting and practically
important for protocol design.

---

## Cell 2.8 — Repeated-measures statistical tests

### What it computes
For each condition (PVA% × PG%):
1. **Paired t-test** (or Wilcoxon signed-rank if n=5):
   H₀: mean ΔCl = 0. Tests if the change is significant.
2. **Effect size** (Cohen's d for paired data):
   d = mean(ΔCl) / SD(ΔCl). Indicates practical relevance.

### Display as table

| PVA% | PG% | mean ΔCl | SD ΔCl | t | p | Cohen's d | Significant? |
|------|-----|----------|--------|---|---|-----------|--------------|

### Also compute
- Overall test across all conditions: repeated-measures ANOVA
  (cycle as within-subjects factor, PVA and PG as between-subjects)
- If `pingouin` or `statsmodels` is available, use their
  repeated-measures ANOVA. Otherwise, compute manually or
  use paired tests per condition.

### Assumptions
- Paired t-test assumes ΔCl is normally distributed — check with
  Shapiro-Wilk on the differences (more valid than testing raw data)
- If normality is violated, report Wilcoxon alongside t-test

### Pedagogical note
The paired t-test on ΔCl is mathematically equivalent to a one-sample
t-test testing whether ΔCl = 0. Explain this equivalence to students.
Also explain that with n=5, p = 0.06 does not mean "no effect" — it
means "inconclusive." State the power limitation explicitly.

---

## Cell 2.9 — Correlation: ΔCl vs Δdensity (paired)

### What it shows
Scatter plot: x = Δdensity, y = ΔCl, one point per piece.
Color = PVA%, shape = PG%.

### How to read it
- Positive correlation → Cl changes are (partly) explained by
  density changes. The phantom gets denser AND stiffer.
- No correlation → Cl changes are due to stiffening (cross-linking)
  independent of densification.
- This helps disentangle the mechanisms.

### What to compute
- Pearson r and p-value
- Annotate on plot

---

## Cell 2.10 — Spaghetti plot (individual piece trajectories)

### What it shows
Cl vs cycle, one thin line per piece, colored by condition.
Unlike 2.1 (which shows means), this shows individual trajectories.

### How to read it
- Parallel trajectories → consistent behavior across pieces
- Crossing lines → some pieces behave differently (outliers?
  fabrication defect? measurement error?)
- One piece diverging → investigate that specific piece

### Why it matters
This is the diagnostic plot. It reveals problems that means and SDs
hide. A mean can be stable while individual pieces go in opposite
directions.

### Implementation
- Thin lines (linewidth=0.8, alpha=0.5) for individual pieces
- Thick line (linewidth=2.5) for condition mean overlaid
- Faceted by condition (subplot grid: 3 PVA × 4 PG = 12 panels)
  to avoid visual overload

---

## Cell 2.11 — Summary and interpretation (Markdown cell)

Template for the student:

```markdown
### Block 2 — Summary

**Cycle effect on Cl:**
- Direction: [increases / decreases / no change]
- Magnitude: mean ΔCl = [X] ± [Y] m/s per cycle
- Significant? [yes/no, with test and p-value]
- Effect size: Cohen's d = [Z]

**Cycle effect on density:**
- [same structure]

**Convergence:**
- Rate of change between cycles: [increasing / decreasing / constant]
- Estimated cycles to stabilization: [N or "not yet reached"]

**Interaction with composition:**
- Does the cycle effect depend on PVA%? [yes/no]
- Does the cycle effect depend on PG%? [yes/no]

**Correlation ΔCl vs Δdensity:**
- r = [value], p = [value]
- Interpretation: [coupled / independent]

**Limitations:**
- Number of cycle transitions available: [N-1]
- Cannot separate cycle effect from aging
- [other limitations observed]
```

---

## Visual style rules (same as Block 1)

- Figure size: (7, 5) for single, (14, 5) for side-by-side
- Color: `tab10`, consistent with Block 1 mapping
- Individual points always shown where applicable
- Error bars = SD, stated in caption
- Grid: alpha=0.3
- Save: `fig_dir / 'B2_XX_description.png'` with dpi=150
- x-axis for cycle plots: integer ticks only
