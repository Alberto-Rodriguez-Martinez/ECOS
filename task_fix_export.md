# Task: Fix export format and add consistency check

## 1. Fix CSV export for Spanish locale

In `export_catalog()`:
- CSV: use `decimal=","` in `df.to_csv()` so Spanish Excel reads correctly
- Add xlsx export: always export BOTH `.csv` and `.xlsx`
- For xlsx, use `df.to_excel()` (numeric types preserved, no locale issue)
- Example: `export_catalog(df, "catalog")` should produce
  `catalog.csv` (semicolon sep, comma decimal) AND `catalog.xlsx`

## 2. Add consistency check: folder name vs JSON

Add function `check_consistency(base_dir) -> list[str]`:

For each experiment folder:
- Parse folder name with `parse_folder_name()` → get pva, pg, piece, cycle
- Load the JSON and read the specimen fields
- Compare: folder pva vs JSON pva_pct, folder pg vs JSON pg_pct,
  folder piece vs JSON piece, folder cycle vs JSON cycle
- If any mismatch: add to warnings list with details

Call this from `__main__` before building catalog.
Print all warnings clearly so the user can fix mismatches.

## 3. Round Z and M

- Z: round to 0 decimals (integer Rayl)
- M: express in GPa (divide by 1e9), round to 4 decimals
  Rename column to `M_GPa`

## 4. Update __main__ block

Run order:
1. `check_consistency(base_dir)` — print warnings
2. `build_catalog(base_dir)` — build and export
3. Print summary
