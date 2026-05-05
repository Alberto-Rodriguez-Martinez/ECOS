# Task: Modify analysis/ecos_loader.py — merge US + DENS

## Changes required

### 1. Merge US and DENS into one row per specimen

In `build_catalog()`, after creating the DataFrame, merge US and DENS rows
by key `(pva_pct, pg_pct, piece, cycle)`.

Prefix result columns with `US_` or `DENS_`:
- US: `US_Cl, US_d, US_T1, US_T2, US_Cw_mean, US_folder, US_timestamp`
- DENS: `DENS_density_gcm3, DENS_T_C, DENS_delta_h_cm, DENS_V_disp_cm3, DENS_mass_g, DENS_cw_ms, DENS_r_vessel_cm, DENS_datetime, DENS_folder`

Keep common columns unprefixed: `pva_pct, pg_pct, piece, cycle, fab_date, dopants, notes`.

If a specimen has only US or only DENS, keep the row with NaN for missing columns.

### 2. Round floats

- Temperatures (T1, T2, T_C): 2 decimals
- Velocities (Cl, Cw_mean, cw_ms): 2 decimals
- Thickness (d), delta_h: 6 decimals
- Density: 4 decimals
- V_disp, mass: 4 decimals

### 3. Remove duplicates

If multiple entries exist for same `(pva_pct, pg_pct, piece, cycle, type)`,
keep only the latest by datetime/timestamp. Print warning.

### 4. Add computed columns after merge

```python
Z = DENS_density_gcm3 * 1000 * US_Cl    # acoustic impedance (kg/m²s)
M = DENS_density_gcm3 * 1000 * US_Cl**2  # longitudinal modulus (Pa)
```

### 5. Sort by pva_pct, pg_pct, cycle, piece
