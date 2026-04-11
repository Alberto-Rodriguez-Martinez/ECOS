## Task: acquisition/pulser_gui.py

Real-time laboratory GUI for pulser control, signal visualization and acquisition.

### Technology
- PyQt5 + pyqtgraph for real-time plotting (Python 32-bit compatible)
- numpy for signal handling
- Save signals as .npy, metadata and sessions as .json

### Layout — widescreen 70/30
- Left (70%): signal visualization
- Right (30%): control panels stacked vertically
- Top: menu bar

### Menu bar
- File → Save Session / Load Session
  - Save Session: saves all current interface parameters to .json
  - Load Session: loads .json and restores all parameters in the interface

### Left panel — Signal visualization
- Large plot (top): Ch1 and Ch2 superimposed, shows zoom region only
  - Checkboxes to enable/disable Ch1 and Ch2
- Small plot (bottom): full RecLen overview
  - Draggable and resizable zoom region (shaded rectangle)
  - Large plot updates automatically when zoom region moves
- Real-time continuous update: 1 A-scan, no averaging, no start/stop button

### Right panel — 3 blocks always visible

#### Block 1 — Pulser Control
- Gain Ch1 (textbox, float)
- Gain Ch2 (textbox, float)
- Voltage (textbox, float)
- Relay (toggle button ON/OFF)
- Acquisition Fs (textbox, default 100 MHz)
- Bits per sample (selector)

#### Block 2 — Acquisition
- Checkboxes Ch1 / Ch2
- N Ascans to average (textbox, default 1)
- Buttons: Acquire Ch1 / Acquire Ch2 / Acquire Both
  - Acquires N Ascans, averages them, saves Smin→Smax range only
  - Opens file dialog to choose folder and filename
  - Saves <filename>.npy and <filename>.json
- Comment field (small free text box)

#### Block 3 — GenCode Waveform Generator
- Excitation type selector: Pulse / Chirp / Burst
- Generator Fs (textbox, default 200 MHz — independent from acquisition Fs)
- Dynamic parameters based on selected type:

  Pulse:
  - Param: selector (Frequency / Duration / Samples)
  - ParamVal: textbox
  - SignalPolarity: selector (2=bipolar, 1, -1)

  Chirp:
  - Fstart (Hz), Fend (Hz), Duration (s)
  - Method: selector (linear / quadratic / logarithmic / hyperbolic)
  - Phase (degrees, default 270)
  - SignalPolarity: selector

  Burst:
  - Fo (Hz), NoCycles (int)
  - SignalPolarity: selector

- Button: Generate & Upload
  - Calls MakeGenCode with selected parameters
  - Uploads to device via ACQ_ToolBox
  - Shows confirmation message

### Acquisition save format
- Signal: <filename>.npy (Smin→Smax range only, averaged over N Ascans)
- Metadata: <filename>.json
  - datetime
  - channel(s) acquired
  - gain Ch1, Ch2
  - voltage
  - acquisition Fs, bits per sample
  - generator Fs
  - excitation type and all parameters
  - Smin, Smax, RecLen
  - N Ascans averaged
  - comment

### Session save format (.json)
- All interface parameters (gains, voltage, Fs, bits, excitation type and params, Smin, Smax, N Ascans, relay state, active channels, comment)

### Notes
- Generator Fs (up to 200 MHz) and acquisition Fs (100 MHz) are independent
- Real-time display: 1 A-scan, no averaging, no start/stop button
- Acquisition for saving: N A-scans averaged
- Use MakeGenCode as unified entry point for all excitation types
- Check ACQ_ToolBox for correct upload function after MakeGenCode
- Use existing functions from ECOS_US_ToolBox and ACQ_ToolBox where possible
- Python 32-bit compatible throughout
- Comment code thoroughly for students
- Show implementation plan before writing code