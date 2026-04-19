# density_gui.py — Specification

**File:** `acquisition/density_gui.py`  
**Purpose:** PyQt5 GUI for the Archimedes ultrasonic density measurement workflow  
**Based on:** `acquisition/pulser_gui.py` (structure) + `acquisition/density_archimedes.py` (logic)

---

## Layout

Widescreen splitter 70/30.

### Left panel (70%)
- Single channel display — **Ch2 only**
- Zoom plot + overview with region selector
- No spectrum plot
- Ch2 visibility checkbox

### Right panel (30%) — scrollable

Blocks in order:

#### 1. Pulser Control
- Gain Ch2 — QLineEdit, default `35`
- Voltage — QLineEdit, default `100`
- RecLen — QLineEdit, default `16384` — editingFinished updates hardware and plot limits
- Relay — toggle button ON/OFF
- Excitation type — QComboBox (Pulse / Chirp / Burst) + QStackedWidget with parameters (same as `pulser_gui.py`)
- "Generate & Upload" button

#### 2. Temperature
- Manual temperature input — QLineEdit [°C]
- Arduino COM port — QLineEdit, default `COM4`
- "Read from Arduino" button — calls `get_Cw_from_arduino`, updates fields
- QLabel showing current T and cw values
- On manual entry: compute cw with `water_temp2sos`, update label

#### 3. Calibration
- V_cal — QLineEdit [cm³]
- N_cal — QLineEdit, default `3`
- "Calibrate vessel" button — acquires sW1 (reference) then sW2 (calibration object submerged), computes r_vessel from V_cal and delta_h, shows result in label
- QLabel showing calibrated r_vessel result
- "Use this value →" button — copies r_vessel to Vessel & Sample field

#### 4. Vessel & Sample
- r_vessel — QLineEdit [cm]
- Mass — QLineEdit [g] (optional)
- Specimen name — QLineEdit

#### 5. Acquisition
- "Acquire sW1 (reference)" button
- "Acquire sW2 (sample submerged)" button
- "Compute & Save" button — disabled until both sW1 and sW2 acquired
- Status label showing current step

#### 6. Results
- QLabel fields: delta_TOF (µs), delta_h (cm), V_displaced (cm³), density (g/cm³)

---

## Path Setup & Environment

Identical to `pulser_gui.py`:

```python
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_SCALE_FACTOR"] = "1"

_TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
os.chdir(_TOOLS_DIR)
os.add_dll_directory(_TOOLS_DIR)

if sys.maxsize <= 2**32:
    _anaconda32_bin = r"C:\ProgramData\Anaconda32\Library\bin"
    if os.path.isdir(_anaconda32_bin):
        os.add_dll_directory(_anaconda32_bin)

sys.path.insert(0, _TOOLS_DIR)
```

---

## Hardware

**Imports:**
- `SeDaqDLL` from `tools/SeDaq.py`
- `MakeGenCode` from `tools/GenCode_ToolBox.py`
- `water_temp2sos`, `get_Cw_from_arduino` from `hardware/SpeedsoundWater.py`
- `CalcToFAscanCosine_XCRFFT` from `tools/ECOS_US_ToolBox.py`

**Init sequence:**
```python
sedaq = SeDaqDLL()
time.sleep(0.5)
sedaq.SetRecLen(DEFAULT_RECLEN)
sedaq.SetRelay(1);  time.sleep(0.2);  sedaq.SetRelay(0)   # relay quirk
sedaq.SetGain2(DEFAULT_GAIN)
sedaq.SetExtVoltage(DEFAULT_VOLTAGE)
```

**Demo mode:** `--demo` flag, same as `pulser_gui.py`

**Real-time timer:** 100 ms, Ch2 only

**Normalisation:** `(raw - quant/2) / quant`, subtract mean

**RecLen change:** updates hardware + plot limits (same logic as `pulser_gui.py`)

---

## Acquisition Workflow

- `sW1` and `sW2` stored as numpy arrays (instance variables), initially `None`
- **AVG_N = 20** averaged A-scans per acquisition

**Acquire sW1:**
1. Stop timer
2. Acquire AVG_N A-scans from Ch2, average
3. Store as `self._sW1`
4. Restart timer
5. Update status label

**Acquire sW2:** same → `self._sW2`

**Compute & Save:**
1. Cross-correlate sW2 vs sW1 → delta_TOF
2. Compute delta_h = cw × delta_TOF / 2
3. Compute V_displaced = π × r² × delta_h
4. Compute density = mass / V_displaced (if mass provided)
5. Update Results group
6. Save JSON to `data/` folder with timestamp

---

## Calibration Workflow

**Calibrate vessel:**
1. Show message: "Vessel empty of sample — click OK when ready"
2. Acquire sW1 (reference)
3. Show message: "Submerge calibration object — click OK when ready"
4. Acquire sW2
5. Compute delta_TOF → delta_h
6. r_vessel = sqrt(V_cal / (π × delta_h))
7. Show result in Calibration label

**"Use this value →":** copies computed r_vessel to r_vessel field in Vessel & Sample

---

## Style & Behaviour

- Fusion style: `app.setStyle("Fusion")`
- DPI fix: `QT_AUTO_SCREEN_SCALE_FACTOR=1`, `QT_SCALE_FACTOR=1`
- `closeEvent`: stop timer, call `sedaq.Close()`
- `--demo` flag: skip hardware import, use simulated Ch2 signal (Gaussian noise)
- GenCode stack: same Pulse/Chirp/Burst pages as `pulser_gui.py`
