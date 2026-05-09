# ECOS — Study Rules and Methodology Guidelines

## Purpose of this document

This document defines the methodological framework for analyzing ECOS
experimental data. It must be read and understood before performing any
analysis. Every decision — what to plot, what test to run, how to
interpret a result — should be traceable to the principles stated here.

If you find a result that contradicts your expectations, **do not discard
it**. Document it, investigate it, and discuss it. Unexpected results are
often more informative than expected ones.

---

## 1. Research questions

The ECOS project aims to characterize PVA-based tissue-mimicking phantoms
for surgical robotics applications. The core questions are:

1. **Tunability** — Can we independently control the acoustic and
   mechanical properties of phantoms by adjusting PVA concentration,
   cryoprotectant (PG) concentration, and the number of freeze-thaw
   cycles?
2. **Tissue matching** — Which combination of (PVA%, PG%, cycles)
   produces properties closest to specific soft tissues (liver, breast,
   muscle)?
3. **Stability** — Do phantom properties converge with increasing
   freeze-thaw cycles? How many cycles are needed?
4. **Reproducibility** — Given identical fabrication parameters, how
   consistent are the resulting acoustic properties across specimens?

### Hypotheses and null hypotheses

| ID | Hypothesis (H₁) | Null (H₀) |
|----|------------------|-----------|
| H1 | Increasing PVA% increases Cl | PVA% has no effect on Cl |
| H2 | Increasing PG% modifies Cl | PG% has no effect on Cl |
| H3 | Additional F/T cycles increase Cl (cross-linking) | Cycles have no effect on Cl |
| H4 | Density increases with PVA% | PVA% has no effect on density |
| H5 | Phantom properties converge after N cycles | Properties do not stabilize |
| H6 | Temperature (within our control range) does not significantly affect Cl | Temperature is a confounding variable |

**Important**: We do not assume any hypothesis is correct. The analysis
must be designed to *test* them, not to *confirm* them.

---

## 2. Experimental design

### Factors and levels

| Factor | Type | Levels | Role |
|--------|------|--------|------|
| PVA concentration (%) | Fixed, between-subjects | 10, 12.5, 15 | Primary factor |
| PG concentration (%) | Fixed, between-subjects | 0, 5, 10, 15 | Secondary factor (cryoprotectant) |
| Freeze-thaw cycle | Fixed, within-subjects (repeated measures) | 3, 4, ... (growing) | Evolution factor |
| Piece (A–E) | Random | 5 per condition | Replication unit |

### Design type

- **Mixed factorial design**: PVA and PG are between-subjects factors
  (each piece has a fixed composition); cycle is a within-subjects
  factor (each piece is measured at every cycle).
- **Repeated measures**: The same physical specimens are measured at
  successive cycles. This is powerful because each piece acts as its
  own control, eliminating inter-specimen variability when analyzing
  cycle effects.

### Sample size considerations

- 5 replicates per condition is modest. With 5 observations:
  - We can detect **large effects** (Cohen's d > 1.2) with ~80% power
  - We **cannot** reliably detect small effects (d < 0.5)
  - Outliers have disproportionate influence
  - Non-parametric tests may be more appropriate than parametric ones
- **Practical implication**: Report effect sizes alongside p-values.
  A non-significant p-value with n=5 does not mean "no effect" — it
  may mean "insufficient power to detect it."

---

## 3. Measured and derived variables

### Directly measured (US experiment)

| Variable | Symbol | Units | Source | Precision notes |
|----------|--------|-------|--------|-----------------|
| Longitudinal velocity | Cl | m/s | Cross-correlation TOF + thickness | Depends on Cw accuracy and TOF resolution |
| Specimen thickness | d | m | Three-signal scheme (sW, sT, sR) | Limited by sampling rate (10 ns resolution at 100 MHz) |
| Water temperature (2 sensors) | T1, T2 | °C | Arduino thermistors | Calibration accuracy unknown — verify |
| Speed of sound in water | Cw | m/s | Calculated from T | Uses empirical formula — check which one |
| Raw signals | PE, TT, Ref | V | SeDaq digitizer, 25 averages | Windowed and averaged |

### Directly measured (density experiment)

| Variable | Symbol | Units | Precision notes |
|----------|--------|-------|-----------------|
| Sample mass | m | g | Manual entry — human error risk |
| Water level change | Δh | cm | Derived from TOF — depends on Cw and vessel radius |
| Vessel radius | r | cm | **Critical parameter** — measured once, assumed constant |
| Water temperature | T | °C | Arduino sensor |
| Density | ρ | g/cm³ | Calculated: ρ = m / (π r² Δh) |

### Derived variables

| Variable | Formula | Units | Notes |
|----------|---------|-------|-------|
| Acoustic impedance | Z = ρ · Cl | Rayl (kg/m²s) | Requires pairing US and DENS of same piece/cycle |
| Longitudinal modulus | M = ρ · Cl² | Pa | Assumes elastic regime |
| Attenuation | α(f) = −ln|H(f)| / d | Np/m or dB/cm | Extractable from stored signals (future) |
| Phase velocity | c(f) from arg(H(f)) | m/s | Extractable from stored signals (future) |

---

## 4. Known sources of error and uncertainty

### Systematic errors (bias)

| Source | Affects | Direction | Mitigation |
|--------|---------|-----------|------------|
| Vessel radius error | Density | r too large → ρ too low | Re-measure vessel; sensitivity analysis |
| Manual mass entry | Density | Typos possible | Cross-check with expected range |
| Temperature measurement accuracy | Cl, Cw, density | Unknown | Calibrate thermistors against reference |
| Cw empirical formula | Cl, d | Depends on formula used | State which formula; compare alternatives |
| Air bubbles on specimen surface | Density (Δh), US (TT signal) | ρ too low; Cl unreliable | Degas water; inspect signals visually |
| Specimen not perfectly flat/parallel | d, Cl | Random | Check PE/TT signal quality |
| Operator variability | All | Random | Document operator; check inter-operator reproducibility |

### Random errors

| Source | Affects | Typical magnitude |
|--------|---------|-------------------|
| TOF extraction precision | Cl, d | ~1 sample = 10 ns at 100 MHz → ~0.015 mm in thickness |
| Temperature fluctuation during measurement | Cl | ~0.1°C → ~0.3 m/s in Cw |
| Phantom inhomogeneity | Cl, density | Unknown — depends on fabrication quality |
| Positioning in tank | All US measurements | Should be negligible if transducers are fixed |

### Things we cannot control or measure

- **Exact PVA molecular weight distribution** — vendor specs have a range
- **Uniformity of freezing** — temperature gradient inside the freezer
  affects cross-linking uniformity. Edge vs. center pieces may differ.
- **Water absorption/loss between cycles** — phantoms stored in water
  may swell or leach PG. Weighing before/after would help.
- **Aging effects** — are changes due to cycles or to time elapsed?
- **Exact PG distribution within the phantom** — PG may migrate during
  freeze-thaw

---

## 5. Statistical framework

### Significance level

- α = 0.05 (standard)
- Always report exact p-values, not just "p < 0.05"
- **Multiple comparisons**: when testing many conditions, apply
  Bonferroni correction or use Tukey HSD. Uncorrected p-values with
  12 conditions will produce false positives.

### Effect size

- Always report alongside p-values
- Cohen's d for pairwise comparisons: small (0.2), medium (0.5),
  large (0.8)
- η² (eta-squared) for ANOVA: small (0.01), medium (0.06), large (0.14)
- **A statistically significant result with tiny effect size is
  scientifically irrelevant.**
- **A non-significant result with large effect size and n=5 likely
  indicates insufficient power, not absence of effect.**

### Parametric vs non-parametric

- With n=5, normality is hard to verify (Shapiro-Wilk has low power)
- **Recommendation**: run both parametric (t-test, ANOVA) and
  non-parametric (Wilcoxon, Kruskal-Wallis). If they agree, report
  parametric. If they disagree, report non-parametric and discuss.
- For repeated measures (cycle comparisons): paired t-test or
  Wilcoxon signed-rank test.

### What "good" and "bad" results look like

| Indicator | Good | Concerning | Action if concerning |
|-----------|------|------------|----------------------|
| CV (coefficient of variation) within condition | < 1-2% for Cl; < 3% for density | > 5% | Investigate: fabrication problem? measurement error? outlier? |
| R² of model Cl = f(PVA, PG, cycle) | > 0.7 | < 0.3 | Factors don't explain variability — missing variable? |
| Density values | 1.00–1.15 g/cm³ | < 1.0 g/cm³ | Vessel radius error? Bubbles? Check measurement |
| Cl values | 1500–1650 m/s (typical PVA range) | < 1480 or > 1700 | Verify signals; check temperature; outlier? |
| ΔCl between consecutive cycles | Decreasing with cycle number (convergence) | Increasing or erratic | Fabrication issue? Degradation? |
| Temperature range during US | 36 ± 1°C | Spread > 2°C | Temperature not well controlled |

---

## 6. Reporting standards

### Figures

- All axes labeled with variable name, symbol, and units
- Title describes what is shown, not what is concluded
- Error bars: always state what they represent (SD, SEM, 95% CI)
- Use consistent color coding throughout the notebook
- Save all figures at 150+ dpi in `analysis/figures/`

### Tables

- Report mean ± SD (not SEM, unless justified)
- Include n for each group
- Include the statistical test used, test statistic, p-value, and
  effect size

### Text

- State the observation first, then the interpretation
- Distinguish between statistical significance and practical relevance
- Acknowledge limitations explicitly
- Never say "proves" — say "supports" or "is consistent with"

---

## 7. Color coding convention

To maintain visual consistency across all plots:

| Factor | Encoding |
|--------|----------|
| PVA concentration | Color (tab10 palette: PVA 10% = blue, 12.5% = orange, 15% = green) |
| PG concentration | Horizontal position offset (jittered) or marker shape |
| Cycle | x-axis in evolution plots; separate panels in static plots |
| Piece | Not shown individually (aggregated) unless investigating outliers |

---

## 8. Checklist before interpreting any result

Before drawing conclusions from any plot or test, verify:

- [ ] Is the sample size sufficient for this comparison?
- [ ] Have I checked for outliers? (visual inspection + IQR method)
- [ ] Are the assumptions of my statistical test met?
- [ ] Have I corrected for multiple comparisons if testing >3 hypotheses?
- [ ] Could a confounding variable (temperature, operator, day) explain this?
- [ ] Is the effect size practically relevant, not just statistically significant?
- [ ] Would I reach the same conclusion with a non-parametric test?
- [ ] Have I looked at the raw data (individual points), not just summaries?
