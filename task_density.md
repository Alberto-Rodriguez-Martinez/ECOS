## Task: density_archimedes.py

Create acquisition/density_archimedes.py for density measurement via Archimedes method.

### Setup
- Cylindrical vessel (~20cm diameter, configurable via r_vessel parameter)
- Single-element unfocused transducer at base, pointing up (5 or 10 MHz)
- Precision balance for mass measurement

### Two independent functions

#### 1. calibrate_vessel(V_cal, temperature=None, transducer_freq=10, channel=2, Smin=0, Smax=4096, N_cal=3)
- V_cal (cm³): known volume of calibration object, mandatory
- Acquire sW1 (no object) and sW2 (with object) N_cal times
- Compute r_vessel = mean(sqrt(V_cal / (pi * delta_h))) over N_cal repetitions
- Returns r_vessel (cm)

#### 2. measure_density(r_vessel, mass=None, temperature=None, transducer_freq=10, channel=2, Smin=0, Smax=4096, specimen_name=None)
- r_vessel: float, mandatory (use result from calibrate_vessel or known value)
- mass (g): optional, if provided density is computed
- If specimen_name is None → prompt at runtime

### Input parameters
- transducer_freq: int, 5 or 10 MHz (default 10)
- channel: int, default 2
- Smin: int, default 0 (configurable)
- Smax: int, mandatory, depends on water level in vessel
- temperature: float or None → if None, read from Arduino

### Excitation pulse
- Generate with MakeGenCode using transducer_freq
- Upload to device with appropriate ACQ_ToolBox function before any acquisition

### Temperature
- Primary source: Arduino (use existing hardware module)
- If temperature is passed as parameter, skip Arduino read

### Real-time visualization before each acquisition
- Show live A-scan in matplotlib window, updating continuously
- Include Acquire button in the window to confirm when signal is stable
- Allow user to adjust channel gain by typing a number
- Used before acquiring both sW1 and sW2

### TOF extraction
- Cross-correlation via CalcToFAscanCosine_XCRFFT from ECOS_US_ToolBox
- delta_h = cw(T) * delta_TOF / 2

### Output (measure_density only)
- Print results to console
- Save JSON file: data/density_<specimen_name>_<datetime>.json
  - specimen_name
  - date and time
  - temperature (°C)
  - transducer_freq (MHz)
  - r_vessel (cm)
  - delta_TOF (s)
  - delta_h (cm)
  - displaced_volume (cm³)
  - mass (g), if provided
  - density (g/cm³), if mass provided

### Requirements
- Use existing functions from ECOS_US_ToolBox and ACQ_ToolBox
- After MakeGenCode, upload pulse to device before acquisition
- Python 32-bit compatible
- Comment code thoroughly for students
- Show implementation plan before writing code