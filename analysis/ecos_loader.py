"""
ecos_loader.py — Load and catalogue ECOS experiment data.

Designed for Python 64-bit (analysis environment, not the 32-bit acquisition env).
Covers two experiment types stored under database/:
  - US  : PVA_{XX}_PG_{YY}_{LETTER}_C{NNN}_US_{YYYYMMDD_HHMMSS}/
  - DENS: PVA_{XX}_PG_{YY}_{LETTER}_C{NNN}_DENS_{YYYYMMDD_HHMMSS}/
"""

from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# [0] Folder-name parser
# ---------------------------------------------------------------------------

_FOLDER_RE = re.compile(
    r"^PVA_(\w+)_PG_(\w+)_([A-Z])_C(\d+)_(US|DENS)_(\d{8}_\d{6})$"
)


def parse_folder_name(name: str) -> Optional[dict]:
    """Parse an ECOS experiment folder name.

    Returns a dict with keys {pva, pg, piece, cycle, exp_type, timestamp},
    or None if the name does not match the expected pattern.
    """
    m = _FOLDER_RE.match(name)
    if m is None:
        return None
    return {
        "pva":      m.group(1),
        "pg":       m.group(2),
        "piece":    m.group(3),
        "cycle":    m.group(4),
        "exp_type": m.group(5),
        "timestamp": m.group(6),
    }


# ---------------------------------------------------------------------------
# [1] Load US experiment
# ---------------------------------------------------------------------------

# Mapping: unified key -> key inside meta.json["specimen"]
_US_SPECIMEN_MAP = {
    "pva_pct":  "porcentaje_pva",
    "pg_pct":   "porcentaje_aditivo1",
    "piece":    "pieza",
    "cycle":    "ciclos",
    "fab_date": "fecha_fabricacion",
    "dopants":  "dopantes",
    "notes":    "otros",
}

_US_RESULT_FIELDS = ["T1", "T2", "Cw1", "Cw2", "Cw_mean", "Cl", "d"]

_US_PARAM_MAP = {
    # unified key -> key inside equipment params
    "Fs":            "F_muestreo",
    "Fp":            "Fp",
    "Gain_Ch1":      "Gain_Ch1",
    "Gain_Ch2":      "Gain_Ch2",
    "Voltaje":       "Voltaje",
    "AvgSamplesNum": "AvgSamplesNum",
    "RecLen":        "RecLen",
    "Smin":          "Smin",
    "Smax":          "Smax",
    "Slen":          "Slen",
    "WindowLen":     "WindowLen",
}


def load_us(folder_path: str | Path) -> dict:
    """Load a US experiment folder into a flat dict with unified field names.

    Reads meta.json and results.json.
    Raises FileNotFoundError if either file is missing.
    """
    folder_path = Path(folder_path)
    meta_path    = folder_path / "meta.json"
    results_path = folder_path / "results.json"

    if not meta_path.exists():
        raise FileNotFoundError(f"meta.json not found in {folder_path}")
    if not results_path.exists():
        raise FileNotFoundError(f"results.json not found in {folder_path}")

    with meta_path.open(encoding="utf-8") as f:
        meta = json.load(f)
    with results_path.open(encoding="utf-8") as f:
        results = json.load(f)

    specimen  = meta.get("specimen", {})
    exp_info  = meta.get("experiment", {})
    params    = (
        meta.get("equipment", {})
            .get("device_1_ultrasound", {})
            .get("params", {})
    )

    record: dict = {}

    # Specimen fields (kept as strings — categorical labels)
    for unified, src in _US_SPECIMEN_MAP.items():
        record[unified] = specimen.get(src, "")

    # Result fields (float)
    for key in _US_RESULT_FIELDS:
        val = results.get(key)
        record[key] = float(val) if val is not None else None

    # Equipment params
    for unified, src in _US_PARAM_MAP.items():
        val = params.get(src)
        record[unified] = float(val) if val is not None else None

    # Experiment metadata
    record["experiment_id"]   = exp_info.get("id", "")
    record["operator"]        = exp_info.get("operator", "")
    record["timestamp_start"] = exp_info.get("timestamp_start", "")
    record["folder"]          = str(folder_path)

    return record


# ---------------------------------------------------------------------------
# [2] Load DENS experiment
# ---------------------------------------------------------------------------

# Mapping: unified key -> key inside density.json
_DENS_SPECIMEN_MAP = {
    "pva_pct":  "pva_pct",
    "pg_pct":   "additive_pct",
    "piece":    "sample_id",
    "cycle":    "cycles",
    "fab_date": "fab_date",
    "dopants":  "dopants",
    "notes":    "notes",
}

_DENS_RESULT_FIELDS = [
    "T_C", "cw_ms", "r_vessel_cm", "mass_g",
    "delta_tof_s", "delta_h_cm", "V_disp_cm3", "density_gcm3",
]

_DENS_ACQ_FIELDS = ["reclen", "avg_n"]


def load_density(folder_path: str | Path) -> dict:
    """Load a DENS experiment folder into a flat dict with unified field names.

    Reads density.json.
    Raises FileNotFoundError if density.json is missing.
    """
    folder_path  = Path(folder_path)
    density_path = folder_path / "density.json"

    if not density_path.exists():
        raise FileNotFoundError(f"density.json not found in {folder_path}")

    with density_path.open(encoding="utf-8") as f:
        data = json.load(f)

    record: dict = {}

    # Specimen fields (kept as strings)
    for unified, src in _DENS_SPECIMEN_MAP.items():
        record[unified] = str(data.get(src, ""))

    # Result fields — r_vessel_cm and mass_g may be stored as strings
    for key in _DENS_RESULT_FIELDS:
        val = data.get(key)
        try:
            record[key] = float(val) if val is not None else None
        except (ValueError, TypeError):
            record[key] = None

    # Acquisition params
    for key in _DENS_ACQ_FIELDS:
        val = data.get(key)
        record[key] = int(val) if val is not None else None

    record["datetime"] = data.get("datetime", "")
    record["folder"]   = str(folder_path)

    return record


# ---------------------------------------------------------------------------
# [3] Load US signals
# ---------------------------------------------------------------------------

def load_signals(folder_path: str | Path) -> dict:
    """Load raw signals from a US experiment folder.

    Reads signals/signals.npz and Fs/Smin from meta.json.
    Returns dict with keys: Signal_PE, Signal_TT, Signal_Ref (np.ndarray),
    Fs (float), Smin (int).
    """
    folder_path = Path(folder_path)
    npz_path    = folder_path / "signals" / "signals.npz"
    meta_path   = folder_path / "meta.json"

    if not npz_path.exists():
        raise FileNotFoundError(f"signals.npz not found in {folder_path}")

    npz = np.load(npz_path)
    result = {
        "Signal_PE":  npz["Signal_PE"],
        "Signal_TT":  npz["Signal_TT"],
        "Signal_Ref": npz["Signal_Ref"],
    }

    if meta_path.exists():
        with meta_path.open(encoding="utf-8") as f:
            meta = json.load(f)
        params = (
            meta.get("equipment", {})
                .get("device_1_ultrasound", {})
                .get("params", {})
        )
        result["Fs"]   = float(params.get("F_muestreo", 100e6))
        result["Smin"] = int(params.get("Smin", 0))
    else:
        warnings.warn(f"meta.json not found in {folder_path}; using default Fs/Smin.")
        result["Fs"]   = 100e6
        result["Smin"] = 0

    return result


# ---------------------------------------------------------------------------
# [4] Load DENS signals
# ---------------------------------------------------------------------------

def load_density_signals(folder_path: str | Path) -> dict:
    """Load reference and sample signals from a DENS experiment folder.

    Returns dict with keys sW1, sW2 (np.ndarray or None if file missing).
    """
    folder_path = Path(folder_path)
    result = {}
    for key in ("sW1", "sW2"):
        path = folder_path / f"{key}.npy"
        if path.exists():
            result[key] = np.load(path)
        else:
            warnings.warn(f"{key}.npy not found in {folder_path}.")
            result[key] = None
    return result


# ---------------------------------------------------------------------------
# [5] Scan database
# ---------------------------------------------------------------------------

def scan_database(base_dir: str | Path) -> list[dict]:
    """Scan base_dir for ECOS experiment folders and load each one.

    Returns a list of flat dicts (one per experiment) with a 'type' key added.
    Folders that fail to load are skipped with a printed warning.
    Prints a summary at the end.
    """
    base_dir = Path(base_dir)
    records: list[dict] = []
    failed: list[tuple[str, str]] = []
    counts = {"US": 0, "DENS": 0}

    try:
        entries = sorted(os.listdir(base_dir))
    except FileNotFoundError:
        print(f"[scan_database] base_dir not found: {base_dir}")
        return records

    for name in entries:
        parsed = parse_folder_name(name)
        if parsed is None:
            continue  # not an experiment folder

        folder = base_dir / name
        exp_type = parsed["exp_type"]

        try:
            if exp_type == "US":
                record = load_us(folder)
            else:
                record = load_density(folder)
            record["type"] = exp_type
            records.append(record)
            counts[exp_type] += 1
        except Exception as exc:
            failed.append((name, str(exc)))
            print(f"  [WARNING] skipping {name}: {exc}")

    print(
        f"[scan_database] loaded {counts['US']} US, {counts['DENS']} DENS"
        + (f", {len(failed)} failed" if failed else "")
    )
    return records


# ---------------------------------------------------------------------------
# [6] Build catalog — column maps and helpers
# ---------------------------------------------------------------------------

_MERGE_KEY   = ["pva_pct", "pg_pct", "piece", "cycle"]
_COMMON_COLS = ["pva_pct", "pg_pct", "piece", "cycle", "fab_date", "dopants", "notes"]

_US_COLS_RENAME = {
    "Cl":              "US_Cl",
    "d":               "US_d",
    "T1":              "US_T1",
    "T2":              "US_T2",
    "Cw_mean":         "US_Cw_mean",
    "folder":          "US_folder",
    "timestamp_start": "US_timestamp",
}
_DENS_COLS_RENAME = {
    "density_gcm3": "DENS_density_gcm3",
    "T_C":          "DENS_T_C",
    "delta_h_cm":   "DENS_delta_h_cm",
    "V_disp_cm3":   "DENS_V_disp_cm3",
    "mass_g":       "DENS_mass_g",
    "cw_ms":        "DENS_cw_ms",
    "r_vessel_cm":  "DENS_r_vessel_cm",
    "datetime":     "DENS_datetime",
    "folder":       "DENS_folder",
}

_ROUND_RULES = {
    "T1": 2, "T2": 2, "T_C": 2,
    "Cl": 2, "Cw_mean": 2, "Cw1": 2, "Cw2": 2, "cw_ms": 2,
    "d": 6, "delta_h_cm": 6,
    "density_gcm3": 4,
    "V_disp_cm3": 4, "mass_g": 4,
}


def _parse_dt(row: pd.Series) -> pd.Timestamp:
    """Extract a comparable Timestamp from a flat experiment row."""
    val = row.get("timestamp_start") if row.get("type") == "US" else row.get("datetime")
    try:
        return pd.Timestamp(val)
    except Exception:
        return pd.Timestamp.min


def _round_catalog(df: pd.DataFrame) -> pd.DataFrame:
    for col, decimals in _ROUND_RULES.items():
        if col in df.columns:
            df[col] = df[col].round(decimals)
    return df


# ---------------------------------------------------------------------------
# [6] Build catalog
# ---------------------------------------------------------------------------

def build_catalog(base_dir: str | Path) -> pd.DataFrame:
    """Scan base_dir, deduplicate, merge US+DENS per specimen, compute Z and M.

    Returns one row per (pva_pct, pg_pct, piece, cycle).
    Specimens with only one measurement type get NaN on the missing side.
    """
    records = scan_database(base_dir)
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # --- Deduplicate: per (pva_pct, pg_pct, piece, cycle, type) keep latest ---
    dup_key = ["pva_pct", "pg_pct", "piece", "cycle", "type"]
    df["_dt"] = df.apply(_parse_dt, axis=1)
    df = df.sort_values("_dt")

    dups = df[df.duplicated(subset=dup_key, keep=False)]
    if not dups.empty:
        summary = dups[dup_key + ["_dt"]].sort_values(dup_key)
        print(f"[build_catalog] WARNING: {len(dups)} duplicate entries — keeping latest:")
        print(summary.to_string(index=False))

    df = df.drop_duplicates(subset=dup_key, keep="last").drop(columns=["_dt"])

    # --- Round numeric columns ---
    df = _round_catalog(df)

    # --- Split, select, and rename columns for each type ---
    us_df   = df[df["type"] == "US"]
    dens_df = df[df["type"] == "DENS"]

    us_src   = _COMMON_COLS + [c for c in _US_COLS_RENAME   if c in us_df.columns]
    dens_src = _COMMON_COLS + [c for c in _DENS_COLS_RENAME if c in dens_df.columns]

    us_sel   = us_df[us_src].rename(columns=_US_COLS_RENAME)
    dens_sel = dens_df[dens_src].rename(columns=_DENS_COLS_RENAME)

    # Outer merge — rows with only one type get NaN on the missing side
    merged = pd.merge(
        us_sel, dens_sel,
        on=_MERGE_KEY, how="outer",
        suffixes=("_us", "_dens"),
    )

    # Coalesce fab_date / dopants / notes that appear on both sides after merge
    for col in ("fab_date", "dopants", "notes"):
        col_u, col_d = f"{col}_us", f"{col}_dens"
        if col_u in merged.columns and col_d in merged.columns:
            merged[col] = merged[col_u].combine_first(merged[col_d])
            merged = merged.drop(columns=[col_u, col_d])

    # --- Computed columns ---
    if "DENS_density_gcm3" in merged.columns and "US_Cl" in merged.columns:
        merged["Z"] = merged["DENS_density_gcm3"] * 1000.0 * merged["US_Cl"]
        merged["M"] = merged["DENS_density_gcm3"] * 1000.0 * merged["US_Cl"] ** 2

    # --- Sort ---
    sort_cols = [c for c in ["pva_pct", "pg_pct", "cycle", "piece"] if c in merged.columns]
    merged = merged.sort_values(sort_cols).reset_index(drop=True)

    return merged


# ---------------------------------------------------------------------------
# [7] Export catalog
# ---------------------------------------------------------------------------

def export_catalog(df: pd.DataFrame, path: str | Path, fmt: str = "csv") -> None:
    """Export a catalog DataFrame to CSV or XLSX.

    fmt="csv"  — semicolon-separated, UTF-8
    fmt="xlsx" — single sheet named 'Catalog'
    """
    path = Path(path)
    if fmt == "csv":
        df.to_csv(path, sep=";", encoding="utf-8", index=False)
    elif fmt == "xlsx":
        df.to_excel(path, sheet_name="Catalog", index=False)
    else:
        raise ValueError(f"Unsupported format: {fmt!r}. Use 'csv' or 'xlsx'.")
    print(f"[export_catalog] saved {len(df)} rows → {path}")


# ---------------------------------------------------------------------------
# [8] __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    base_dir = Path(__file__).parent / ".." / "database"

    print(f"Scanning: {base_dir.resolve()}\n")
    df = build_catalog(base_dir)

    if df.empty:
        print("No experiments found.")
    else:
        print(f"\nShape: {df.shape}")
        print(f"Columns: {list(df.columns)}\n")

        has_us   = df["US_Cl"].notna()             if "US_Cl"             in df.columns else pd.Series(False, index=df.index)
        has_dens = df["DENS_density_gcm3"].notna() if "DENS_density_gcm3" in df.columns else pd.Series(False, index=df.index)
        print(f"Merged (US+DENS): {(has_us & has_dens).sum()}")
        print(f"US only:          {(has_us & ~has_dens).sum()}")
        print(f"DENS only:        {(~has_us & has_dens).sum()}\n")

        for col in ["pva_pct", "pg_pct", "cycle"]:
            if col in df.columns:
                print(f"--- {col} ---")
                print(df[col].value_counts().to_string())
                print()

        out_path = Path(__file__).parent / "catalog.csv"
        export_catalog(df, out_path, fmt="csv")

    print("Done.")
