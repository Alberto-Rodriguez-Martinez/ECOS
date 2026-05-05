# Task: analysis/ecos_loader.py

Create a Python module for loading and cataloguing ECOS experiment data.
This module will be used from Jupyter notebooks and scripts running on
**Python 64-bit** (not the 32-bit acquisition environment).

## Context

The ECOS project stores experiments in `database/` with two types of folders:

- **US (ultrasound):** `PVA_{XX}_PG_{YY}_{LETTER}_C{NNN}_US_{YYYYMMDD_HHMMSS}/`
  - `meta.json` — specimen descriptor + equipment params
  - `results.json` — computed results (Cl, d, temperatures, Cw)
  - `signals/signals.npz` — three raw signals (Signal_PE, Signal_TT, Signal_Ref)

- **DENS (density):** `PVA_{XX}_PG_{YY}_{LETTER}_C{NNN}_DENS_{YYYYMMDD_HHMMSS}/`
  - `density.json` — specimen descriptor + results in a single flat file
  - `sW1.npy`, `sW2.npy` — reference and sample signals

Field names differ between the two formats and must be unified:

| Unified name | US (meta.json → specimen) | DENS (density.json) |
|--------------|---------------------------|---------------------|
| pva_pct      | porcentaje_pva            | pva_pct             |
| pg_pct       | porcentaje_aditivo1       | additive_pct        |
| piece        | pieza                     | sample_id           |
| cycle        | ciclos                    | cycles              |
| fab_date     | fecha_fabricacion         | fab_date            |
| dopants      | dopantes                  | dopants             |
| notes        | otros                     | notes               |

Numeric string fields must be converted to float where appropriate
(density, mass, r_vessel, temperatures, velocities, etc.).
Specimen descriptor fields (pva_pct, pg_pct, cycle) should remain as
strings in the catalog because they are categorical labels (e.g. "125"
means 12.5% PVA — interpretation is left to the user/notebook).

## Example data files

### meta.json (US experiment)

```json
{
  "schema_version": "raw-32-1.0",
  "experiment": {
    "id": "EXPID-73C6A269",
    "timestamp_start": "2026-05-04T11:48:34.967288",
    "timestamp_end": "2026-05-04T11:48:34.967288",
    "operator": "Sebas"
  },
  "specimen": {
    "fecha_fabricacion": "04/05/2026",
    "base": "agua",
    "porcentaje_pva": "10",
    "aditivo1": "PG",
    "porcentaje_aditivo1": "15",
    "ciclos": "3",
    "pieza": "A",
    "otros": "",
    "dopantes": "-"
  },
  "protocol": {
    "description": "Ensayo ultrasónico longitudinal ECOS",
    "notes": ""
  },
  "equipment": {
    "device_1_ultrasound": {
      "nombre": "SEDAQ",
      "transductor_pe": "No enfocado 10MHz",
      "transductor_tt": "No enfocado 10MHz",
      "params": {
        "Gain_Ch1": 37,
        "Gain_Ch2": 37,
        "Voltaje": 60,
        "Fp": 5000000.0,
        "F_muestreo": 100000000.0,
        "AvgSamplesNum": 25,
        "RecLen": 16384,
        "Smin": 4081,
        "Smax": 8000,
        "Slen": 3919,
        "WindowLen": 300
      }
    },
    "device_2_aux": {
      "nombre": "Arduino",
      "puerto": "COM4"
    }
  },
  "notes": ""
}
```

### results.json (US experiment)

```json
{
  "T1": 35.72,
  "T2": 35.68,
  "Cw1": 1523.4,
  "Cw2": 1523.1,
  "Cw_mean": 1523.25,
  "Cl": 1548.3,
  "d": 0.0198
}
```

### density.json (DENS experiment)

```json
{
  "datetime": "2026-04-30T11:28:57.080766",
  "sample_id": "A",
  "pva_pct": "10",
  "additive": "PG",
  "additive_pct": "0",
  "cycles": "3",
  "fab_date": "30/04/2026",
  "dopants": "-",
  "notes": "-",
  "T_C": 21.954,
  "cw_ms": 1488.18,
  "r_vessel_cm": "9.43",
  "mass_g": "6.936",
  "delta_tof_s": 3.533e-07,
  "delta_h_cm": 0.02629,
  "V_disp_cm3": 7.3447,
  "density_gcm3": 0.9444,
  "reclen": 16384,
  "avg_n": 20
}
```

## Functions to implement

### [0] parse_folder_name(name) -> dict | None

Parse an experiment folder name using regex.
Pattern: `PVA_(\w+)_PG_(\w+)_([A-Z])_C(\d+)_(US|DENS)_(\d{8}_\d{6})`

Return dict with keys: `pva`, `pg`, `piece`, `cycle`, `exp_type`, `timestamp`
Return None if the name does not match.

### [1] load_us(folder_path) -> dict

Read `meta.json` and `results.json` from a US experiment folder.
Return a flat dict with unified field names:
- From specimen: pva_pct, pg_pct, piece, cycle, fab_date, dopants, notes
- From results: T1, T2, Cw1, Cw2, Cw_mean, Cl, d
- From equipment params: Fs, Fp, Gain_Ch1, Gain_Ch2, Voltaje, AvgSamplesNum,
  RecLen, Smin, Smax, Slen, WindowLen
- experiment_id, operator, timestamp_start
- folder (str, the folder path for reference)

Convert numeric values in results to float.
Raise FileNotFoundError if meta.json or results.json missing.

### [2] load_density(folder_path) -> dict

Read `density.json` from a DENS experiment folder.
Return a flat dict with unified field names:
- Specimen: pva_pct, pg_pct, piece, cycle, fab_date, dopants, notes
- Results: T_C, cw_ms, r_vessel_cm, mass_g, delta_tof_s, delta_h_cm,
  V_disp_cm3, density_gcm3
- Acquisition: reclen, avg_n
- datetime
- folder (str)

Convert r_vessel_cm and mass_g from string to float.
Raise FileNotFoundError if density.json missing.

### [3] load_signals(folder_path) -> dict

Load signals from a US experiment folder (signals/signals.npz).
Also read Fs and Smin from meta.json for time axis reconstruction.
Return dict with keys: Signal_PE, Signal_TT, Signal_Ref (np.ndarray),
Fs (float), Smin (int).

### [4] load_density_signals(folder_path) -> dict

Load signals from a DENS experiment folder (sW1.npy, sW2.npy).
Return dict with keys: sW1, sW2 (np.ndarray or None if file missing).

### [5] scan_database(base_dir) -> list[dict]

Scan `base_dir` for folders matching PVA_*_US_* and PVA_*_DENS_*.
For each folder:
1. Parse the folder name with parse_folder_name()
2. Load the corresponding JSON (load_us or load_density)
3. Add a "type" field ("US" or "DENS")

Return a list of flat dicts, one per experiment.
Print a summary: number of US experiments, DENS experiments, any
folders that failed to load (with error message).
Skip folders that fail to load (print warning, continue).

### [6] build_catalog(base_dir) -> pandas.DataFrame

Call scan_database(), convert to DataFrame.
Sort by: type, pva_pct, pg_pct, cycle, piece.
Return the DataFrame.

### [7] export_catalog(df, path, fmt="csv")

Export DataFrame to file.
- fmt="csv": semicolon separator, UTF-8
- fmt="xlsx": single sheet named "Catalog"

### [8] __main__ block

When run as `python ecos_loader.py`:
1. Determine base_dir: use ../database relative to this script's location
2. Call build_catalog(base_dir)
3. Print summary: shape, columns, value_counts for type/pva_pct/pg_pct/cycle
4. Export to analysis/catalog.csv
5. Print "Done."

## Code style

- English comments throughout
- Section headers with numbered blocks: `# [0] ...`, `# [1] ...`
- Docstrings for every public function
- No dependencies beyond stdlib + numpy + pandas
- Handle missing files gracefully (warn and skip, don't crash)
- Type hints on function signatures
