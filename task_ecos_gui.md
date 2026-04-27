# task_ecos_gui.py — Specification

**File:** `acquisition/ecos_gui.py`  
**Purpose:** PyQt5 GUI for the full ECOS longitudinal characterization workflow  
**Based on:** `acquisition/density_gui.py` (structure and style — read it carefully before starting)  
**Logic from:** `acquisition/ECOS_acquisition.py` (signal acquisition and computation)

---

## General notes

- Use `density_gui.py` as the primary reference for layout, coding style, session save/load, and PyQt5 patterns. It works well — replicate its structure.
- Python 32-bit environment. Same DLL initialization order as `density_archimedes.py [0] PATH SETUP` (three steps before `import SeDaq`).
- All comments in English.
- Numbered sections: `[0] PATH SETUP`, `[1] IMPORTS`, `[2] CONFIG`, etc.
- GUI state in a single dataclass/state object (like `AcqState` in `ECOS_acquisition.py`).
- Session save/load as JSON (same pattern as `density_gui_session.json`).

---

## Layout

Widescreen splitter **70 / 30**.

### Left panel (70%)
- **Zoom plot** (top): live real-time A-scan, Ch1 and Ch2 superimposed, with checkboxes for channel visibility.
- **Overview plot** (bottom): static full-record view with draggable region selector controlling the zoom window.
- **X-axis unit radio buttons**: samples / µs / mm (same logic as `ECOS_acquisition.py`).
- **Hover cursor** with coordinate label (same as `ECOS_acquisition.py`).

### Right panel (30%) — scrollable QScrollArea

Blocks in order:

---

### Block 1 — Pulser Control

- Gain Ch1 — QLineEdit, default `65`
- Gain Ch2 — QLineEdit, default `35`
- Voltage — QLineEdit, default `100`
- RecLen — QLineEdit, default `16384` — `editingFinished` updates hardware and plot limits
- Relay — toggle button ON/OFF
- Excitation type — QComboBox (Pulse / Chirp / Burst) + QStackedWidget with parameters (same as `density_gui.py`)
- "Generate & Upload" button

---

### Block 2 — Temperature

- Arduino COM port — QLineEdit, default `COM3`
- "Read from Arduino" button (manual trigger)
- QLabel showing T1, T2, Cw1, Cw2

**Temperature is read automatically** on every acquisition button press (PE+TT, WaterPath, Angular). The manual button is for diagnostics only.

**Arduino fallback:** if the Arduino does not respond (SerialException or timeout), show a QDialog asking the user to enter temperature manually [°C]. Use that value as T1=T2, compute Cw via `water_temp2sos`. The temperature label shows "Manual: T=XX.X °C" to make it visible.

---

### Block 3 — Signal Acquisition

**Acquisition window (Smin / Smax):**
- Two QLineEdit fields: Smin [samples] and Smax [samples].
- Automatically updated when the user drags the region selector in the overview plot.
- Also editable by hand for fine adjustment.
- These define the capture range for all acquisition buttons.

**Buttons in operational order:**

1. **"Acquire s_PE + s_TT (sample, 0°)"**
   - Condition: sample in position, normal incidence (0°).
   - Acquires Ch2 (PE) and Ch1 (TT) simultaneously over Smin:Smax.
   - Reads temperature automatically before capture.
   - Stores as `state.PE_Ascan`, `state.TT_Ascan`, `state.T1`, `state.T2`, `state.Cw_mean`.
   - Status label updates: "s_PE + s_TT acquired ✓"

2. **"Acquire s_W (WaterPath)"**
   - Condition: sample removed from tank.
   - Acquires Ch1 over Smin:Smax.
   - Reads temperature automatically before capture.
   - Stores as `state.WP_Ascan`, updates `state.T1`, `state.T2`, `state.Cw_mean`.
   - Status label updates: "s_W acquired ✓"

3. **"Acquire s_G (Angular / Shear)"** — **DISABLED** (grayed out) in this phase
   - QDoubleSpinBox for angle θ_i [degrees], default `0.0`
   - Acquires Ch1 at the set angle over Smin:Smax.
   - Reads temperature automatically.
   - Stores as `state.SH_Ascan`, `state.theta_i`.
   - Add a visible note: "Not used in this phase — implement for future shear velocity measurement."
   - Button is present in the UI but `setEnabled(False)`.

Status label below the buttons shows which signals have been acquired (✓ / pending).

---

### Block 4 — Windowing

- QLineEdit: window length in samples, default `200`
- **"Preview window"** button:
  - Stops the real-time animation.
  - The zoom plot switches to **inspection mode**: shows WP, PE, TT signals with the Tukey window overlaid on each.
  - The plot title makes clear it is no longer live.
- **"Apply window"** button:
  - Applies Tukey window to TT, PE, WP (peak-centered, same logic as `ECOS_acquisition.py`).
  - Stores windowed signals in state.
  - Triggers velocity computation automatically -> updates Block 5 (Results).
- **"Back to live"** button:
  - Restarts the real-time animation, returns zoom plot to live mode.

Same Tukey window logic as `ECOS_acquisition.py` (`US.MakeWindow`, `US.Envelope`, peak-centered).
---

### Block 5 — Results

QLabel fields (read-only, updated after "Apply window"):

- Cw [m/s] (mean water speed used)
- T1 / T2 [°C]
- **Cl [m/s]** — longitudinal velocity
- **d [mm]** — sample thickness

Computed via `US.LongVelocity_Thickness(...)` same as `ECOS_acquisition.py [8]`.

---

### Block 6 — Sample Descriptor

Editable QLineEdit fields for each sample:

| Field | Label | Example |
|---|---|---|
| Sample ID | "Sample ID" | `PVA_10_PG_05_A` |
| PVA concentration | "PVA [%]" | `10` |
| Additive | "Additive" | `Propylene glycol` |
| Additive concentration | "Additive [%]" | `5` |
| Freeze-thaw cycles | "Cycles" | `3` |
| Fabrication date | "Fab. date (DD/MM/YYYY)" | `17/02/2026` |
| Dopants | "Dopants" | `` |
| Notes | "Notes" | `` |

---

### Block 7 — Save

- QLineEdit: Experiment name — pre-filled automatically from Sample ID + cycles + date + time following the naming convention:
  `PVA_{XX}_PG_{YY}_{LETRA}_C{NNN}_US_{YYYYMMDD_HHMMSS}`
  User can edit before saving.

- "Compute & Save" button — disabled until s_W, s_PE, s_TT acquired and window applied.
  - Calls `save_experiment_raw_32` from `BD_Experimentos_PVA` (same as `ECOS_acquisition.py [9]`).
  - Saves signals (PE, TT, WP), metadata (specimen dict, equipment dict, protocol dict, results dict).
  - Results dict contains: T1, T2, Cw1, Cw2, Cw_mean, Cl, d.
  - Specimen dict populated from Block 7 fields.
  - Equipment dict populated from Block 1 fields (Gain Ch1, Gain Ch2, Voltage, RecLen, Fp, Fs, AvgSamplesNum, Smin, Smax, WindowLen).
  - After save: print path to console, show confirmation in status label.

---

## File naming convention

```
PVA_{XX}_PG_{YY}_{LETRA}_C{NNN}_US_{YYYYMMDD_HHMMSS}
```

- `XX`  — PVA concentration (2 digits, e.g. `10`)
- `YY`  — Additive concentration (2 digits, e.g. `05`)
- `LETRA` — Individual piece ID (e.g. `A`)
- `NNN` — Freeze-thaw cycles (3 digits, e.g. `003`)
- `US`  — measurement type (fixed for this tool)
- Timestamp — from `time.strftime("%Y%m%d_%H%M%S")`

The experiment name field in Block 8 is auto-generated from Block 7 fields but editable.

---

## Session save / load

Same pattern as `density_gui.py`:
- Menu bar: File → Save Session / Load Session
- Saves all Block 1 + Block 7 + Block 8 fields to JSON
- Restores on load
- Default session file: `acquisition/ecos_gui_session.json`

---

## Real-time animation

- `FuncAnimation` assigned to a persistent attribute (not a local variable) to prevent garbage collection — same fix as in `density_gui.py`.
- `AvgSamplesNum_live = 1` for real-time display.
- `AvgSamplesNum = 25` for PE/TT/WP captures.
- Animation interval: ~34 ms (≈30 fps) or based on window size like `ECOS_acquisition.py`.

---

## Hardware initialization

Identical to `ECOS_acquisition.py [4]`:
- Connect SeDaq DLL.
- SetRecLen.
- Build and upload GenCode (default: 5 MHz pulse, bipolar).
- SetGain1 then SetGain2 (Ch1 before Ch2 — firmware bug workaround).

---

## Key imports and paths

```python
# [0] PATH SETUP — must be before any other imports
import sys, os
os.chdir(r"D:\ECOS\tools")
os.add_dll_directory(r"D:\ECOS\tools")
if sys.maxsize <= 2**32:
    os.add_dll_directory(r"C:\ProgramData\Anaconda32\Library\bin")

# Then normal imports
sys.path.insert(0, r"D:\ECOS\tools")
sys.path.append(r"D:\ECOS\database")
sys.path.append(r"D:\ECOS\hardware")

import SeDaq as SD
import ACQ_ToolBox as ACQ
import ECOS_US_ToolBox as US
import GenCode_ToolBox as gc
from temperature_Alberto_temporal import Arduino
from BD_Experimentos_PVA import save_experiment_raw_32
```

---

## What NOT to implement (out of scope for this phase)

- s_G (angular/shear) acquisition — button present but disabled
- s_RUS (frequency sweep) — not in GUI
- Z_PVA, ρ_US, elastic moduli — computed offline, not in this GUI
- Velocity dispersion and attenuation curves — offline analysis
