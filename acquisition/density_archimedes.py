# -*- coding: utf-8 -*-
"""
density_archimedes.py
=====================
Density measurement of soft-tissue phantoms (PVA hydrogels) using the
Archimedes (water-displacement) method combined with ultrasonic TOF sensing.

PHYSICAL PRINCIPLE
------------------
A cylindrical vessel filled with water sits above a single-element unfocused
transducer (pointing upward). The transducer fires an ultrasonic pulse that
travels through the water, reflects off the free surface, and returns to the
transducer. The round-trip travel time is proportional to the water depth.

When a sample is submerged, the water level rises by delta_h (the sample
displaces its own volume of water). The transducer detects this rise as a
time-of-flight increase delta_TOF. From the speed of sound in water cw(T):

    delta_h = cw(T) * delta_TOF / 2        [m]
              (factor 2: round-trip path)

The displaced volume equals the cross-section of the vessel times the rise:

    V_displaced = pi * r^2 * delta_h       [m^3]

And density (if mass m is known):

    rho = m / V_displaced                  [kg/m^3]

WORKFLOW
--------
Two independent functions are provided:

    1. calibrate_vessel(V_cal, ...)
       Estimates the vessel inner radius r by submerging an object of known
       volume V_cal and measuring the TOF shift. Repeat N_cal times and
       average. Returns r in cm.

    2. measure_density(r_vessel, ...)
       Performs the actual density measurement using a known vessel radius.
       Saves results to a JSON file.

USAGE EXAMPLE
-------------
    # Step 1 (only needed if vessel radius is unknown):
    r = calibrate_vessel(V_cal=12.5, N_cal=3)

    # Step 2:
    measure_density(r_vessel=r, mass=24.3)

HARDWARE REQUIREMENTS
---------------------
- SeDaq digitizer (KTU), connected via USB — requires 32-bit Python
- Single-element unfocused transducer (5 or 10 MHz) at vessel base
- Arduino with MAX31865 temperature sensor (optional: temperature can be
  passed manually)

AUTHORS
-------
A. Rodríguez-Martínez — Universidad Miguel Hernández (UMH)
"""

# ==============================================================================
# [0] PATH SETUP
# Must be done before importing SeDaq — the DLL loader uses the working
# directory at import time to resolve dependencies (USB2.dll, etc.)
# ==============================================================================

import sys
import os

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tools_dir = os.path.join(_repo_root, 'tools')

os.chdir(_tools_dir)                  # DLL search path: must be tools/
os.add_dll_directory(_tools_dir)      # Explicit DLL directory (Python 3.8+)

# Guard against 64-bit conda DLLs leaking in via PATH (Anaconda3 base env).
# Explicitly registering the 32-bit runtime directory ensures the correct
# python3x.dll, libffi.dll, etc. are resolved first.
if sys.maxsize <= 2**32:
    _anaconda32_bin = r"C:\ProgramData\Anaconda32\Library\bin"
    if os.path.isdir(_anaconda32_bin):
        os.add_dll_directory(_anaconda32_bin)

sys.path.insert(0, _tools_dir)
sys.path.insert(0, os.path.join(_repo_root, 'hardware'))

# ==============================================================================
# [1] IMPORTS
# ==============================================================================

import json
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, TextBox
from datetime import datetime

from SeDaq import SeDaqDLL
import GenCode_ToolBox as gc
from ECOS_US_ToolBox import CalcToFAscanCosine_XCRFFT
from SpeedsoundWater import water_temp2sos, get_Cw_from_arduino

# ==============================================================================
# [2] CONFIGURATION
# Edit these values to match your hardware setup before running.
# ==============================================================================

PROG_GEN_CLK = 200e6   # Waveform generator internal clock frequency [Hz]
                        # (fixed hardware parameter of the KTU pulser)
Fs           = 100e6   # Digitizer (ADC) sampling frequency [Hz]
RecLen       = 16384   # Default acquisition record length [samples]
                        # (16384 = 16 * 1024; covers ~164 µs at 100 MHz)

AVG_N_LIVE   = 1       # Averages per frame in the live display
                        # (keep at 1 for smooth real-time update)
AVG_N        = 20      # Averages for the final stored acquisition
                        # (more averages → less noise, but slower)

GAIN_INIT    = 35      # Initial receiver gain [dB]
                        # Typical range: 20–90 dB. Adjust so the echo
                        # fills ~50–80% of the display without clipping.

# ==============================================================================
# [3] HARDWARE INITIALISATION
# ==============================================================================

def _init_hardware(transducer_freq, channel, Smax, gain=35.0, voltage=None):
    """
    Connect to the SeDaq digitizer, upload the excitation waveform, and
    set the initial receiver gain.

    The excitation is a bipolar rectangular pulse at the transducer centre
    frequency. The pulse is generated digitally and uploaded to the
    waveform generator inside the SeDaq unit via UpdateGenCode().

    Parameters
    ----------
    transducer_freq : int
        Transducer centre frequency in MHz (5 or 10).
    channel : int
        Receiver channel to use (1 or 2).
    Smax : int
        Record length (number of samples to acquire).
    gain : float
        Receiver gain [dB]. Default: 35.0.
    voltage : float or None
        Excitation voltage [V]. If None, the hardware default is used.

    Returns
    -------
    SeDaq : SeDaqDLL
        Initialised hardware object.
    """
    print("Connecting to SeDaq digitizer...")
    SeDaq = SeDaqDLL()
    time.sleep(0.5)   # Allow firmware to stabilise after connection
    SeDaq.SetRelay(1)  # force OFF first
    time.sleep(0.2)
    SeDaq.SetRelay(0)  # then ON — required by hardware quirk

    # Set how many samples the digitizer stores per trigger event
    SeDaq.SetRecLen(Smax)
    print(f"  Record length : {Smax} samples  ({Smax / Fs * 1e6:.1f} µs)")

    # Build a rectangular bipolar pulse at the requested frequency.
    # PROG_GEN_CLK is the internal clock of the waveform generator (200 MHz),
    # not the ADC sampling rate — do not confuse the two.
    GenCode = gc.MakeGenCode(
        Excitation='Pulse',
        Param='frequency',
        ParamVal=transducer_freq * 1e6,   # convert MHz → Hz
        SignalPolarity=2,                  # 2 = bipolar (standard)
        Fs=PROG_GEN_CLK,
    )
    SeDaq.UpdateGenCode(GenCode)
    print(f"  Excitation    : {transducer_freq} MHz rectangular pulse uploaded.")

    # Apply initial gain to the active channel.
    # NOTE (firmware bug): when setting Ch1, Ch2 also resets to its default.
    # Since we use only one channel here this is not an issue, but it is
    # good practice to always set gains in the order Ch1 → Ch2.
    if channel == 1:
        SeDaq.SetGain1(gain)
    else:
        SeDaq.SetGain2(gain)
    print(f"  Channel       : {channel}   |   Initial gain: {gain} dB")
    if voltage is not None:
        SeDaq.SetExtVoltage(int(voltage))
        print(f"  Excitation voltage: {int(voltage)} V")
    print("SeDaq ready.\n")

    return SeDaq

# ==============================================================================
# [4] TEMPERATURE AND SPEED OF SOUND
# ==============================================================================

def _get_temperature_and_cw(temperature, arduino_port='COM4'):
    """
    Return water temperature [°C] and the corresponding speed of sound [m/s].

    The speed of sound in water depends strongly on temperature (~3 m/s per °C
    near room temperature), so accurate temperature measurement is important
    for a correct TOF-to-distance conversion.

    Parameters
    ----------
    temperature : float or None
        If a float is provided, it is used directly (Arduino is skipped).
        If None, the value is read from the Arduino (average of two sensors).
    arduino_port : str
        Serial port of the Arduino (e.g. 'COM4', 'COM5'). Only used when
        temperature is None.

    Returns
    -------
    T : float — Water temperature [°C]
    cw : float — Speed of sound in water at T [m/s]
    """
    if temperature is not None:
        T  = float(temperature)
        cw = water_temp2sos(T)
        print(f"[Temperature] User-supplied: T = {T:.2f} °C  →  cw = {cw:.2f} m/s")
        return T, cw

    # Read from Arduino
    print(f"[Temperature] Reading from Arduino on {arduino_port}...")
    T1, T2, Cw1, Cw2 = get_Cw_from_arduino(port=arduino_port)

    if T1 is None and T2 is None:
        print(
            f"[WARNING] Could not read temperature from Arduino on {arduino_port}. "
            "Check the USB connection and port."
        )
        while True:
            try:
                raw = input("Enter water temperature manually [°C]: ").strip()
                T  = float(raw)
                cw = water_temp2sos(T)
                print(f"[Temperature] Manual input: T = {T:.2f} °C  →  cw = {cw:.2f} m/s")
                return T, cw
            except ValueError:
                print("  Invalid value — please enter a number (e.g. 22.5).")

    elif T2 is None:
        T, cw = T1, Cw1
        print(f"  Sensor 1 only: T = {T:.2f} °C  →  cw = {cw:.2f} m/s")
    elif T1 is None:
        T, cw = T2, Cw2
        print(f"  Sensor 2 only: T = {T:.2f} °C  →  cw = {cw:.2f} m/s")
    else:
        # Average both sensors — reduces the effect of sensor-to-sensor offset
        T  = (T1 + T2) / 2.0
        cw = (Cw1 + Cw2) / 2.0
        print(f"  Sensor 1: T = {T1:.2f} °C  →  cw = {Cw1:.2f} m/s")
        print(f"  Sensor 2: T = {T2:.2f} °C  →  cw = {Cw2:.2f} m/s")
        print(f"  Average : T = {T:.2f} °C  →  cw = {cw:.2f} m/s")

    return T, cw

# ==============================================================================
# [5] SINGLE A-SCAN (low-level helper)
# ==============================================================================

def _get_ascan(SeDaq, channel, Smin, Smax, avg=1):
    """
    Acquire and return one averaged A-scan from the digitizer.

    Parameters
    ----------
    SeDaq : SeDaqDLL
        Initialised hardware object.
    channel : int
        Receiver channel (1 or 2).
    Smin, Smax : int
        Sample window [Smin, Smax) to extract from the full record.
    avg : int
        Number of A-scans to average (1 for live display, AVG_N for storage).

    Returns
    -------
    ascan : ndarray, shape (Smax-Smin,)
        Normalised, averaged A-scan.
    """
    quant   = 1024   # 10-bit digitizer: 2^10 quantisation levels
    acc     = np.zeros(Smax - Smin)
    n_done  = 0

    while n_done < avg:
        SeDaq.GetAScan()

        if channel == 2:
            raw = np.array(list(SeDaq.DataADC2[Smin:Smax]), dtype=float)
        else:
            raw = np.array(list(SeDaq.DataADC1[Smin:Smax]), dtype=float)

        # Normalise to [-0.5, +0.5] and remove DC offset
        raw = (raw - quant / 2.0) / quant
        raw = raw - np.mean(raw)

        # Skip blank frames (occasional hardware glitch)
        if np.all(raw == 0.0):
            continue

        acc   += raw
        n_done += 1

    ascan = acc / avg
    ascan = ascan - np.mean(ascan)
    return ascan

# ==============================================================================
# [6] LIVE A-SCAN GUI
# ==============================================================================

def _live_acquire(SeDaq, channel, Smin, Smax, title):
    """
    Open an interactive matplotlib window showing a continuously updating
    A-scan. The user can adjust the receiver gain and press [Acquire] when
    the signal looks stable.

    HOW IT WORKS
    ------------
    The main loop calls _get_ascan() with avg=1 (single shot, fast) and
    updates the plot. This gives a real-time view of the signal. When the
    user clicks [Acquire], the loop exits and a final high-quality acquisition
    (AVG_N averages) is captured and returned.

    Gain adjustment:
    - The TextBox shows the current gain in dB.
    - Type a new integer value and press Enter to apply it to the hardware.

    Parameters
    ----------
    SeDaq : SeDaqDLL
        Initialised hardware object.
    channel : int
        Receiver channel (1 or 2).
    Smin, Smax : int
        Acquisition window in samples.
    title : str
        Window title — use it to tell the user what to do
        (e.g. "Acquire sW1 — remove sample from vessel").

    Returns
    -------
    ascan : ndarray
        Final averaged A-scan (AVG_N averages).
    gain : int
        Gain value [dB] applied at the moment of acquisition.
    """
    # Mutable container shared between the loop and the button callback.
    # Using a dict instead of a plain variable so the callback can modify it
    # (Python closures cannot rebind variables in an enclosing scope).
    state = {
        'stop'  : False,   # set to True when [Acquire] is clicked
        'gain'  : GAIN_INIT,
    }

    # Time axis in microseconds (used for the x-axis label)
    n_samples = Smax - Smin
    t_us = (np.arange(n_samples) + Smin) / Fs * 1e6

    # ---- Build figure --------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 4))
    plt.subplots_adjust(bottom=0.25)   # leave room for widgets below the plot

    line, = ax.plot(t_us, np.zeros(n_samples), color='steelblue', linewidth=0.8)
    ax.set_xlim(t_us[0], t_us[-1])
    ax.set_ylim(-0.6, 0.6)
    ax.set_xlabel('Time (µs)')
    ax.set_ylabel('Amplitude (normalised)')
    ax.set_title(title)
    ax.grid(True, alpha=0.3)

    # ---- Clipping indicator --------------------------------------------------
    clip_text = ax.text(
        0.98, 0.95, u'\u26a0 CLIPPING',
        transform=ax.transAxes,
        ha='right', va='top',
        color='white', fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.3', facecolor='red', edgecolor='none'),
        visible=False,
    )

    # ---- Gain TextBox --------------------------------------------------------
    # Positioned below the plot (axes coordinates [left, bottom, width, height])
    ax_tb = plt.axes([0.15, 0.08, 0.15, 0.06])
    tb_gain = TextBox(ax_tb, 'Gain (dB) ', initial=str(state['gain']))

    def on_gain_submit(text):
        """Called when the user presses Enter after typing a gain value."""
        try:
            new_gain = int(float(text))
            state['gain'] = new_gain
            # Apply new gain to the active channel on the hardware
            if channel == 1:
                SeDaq.SetGain1(new_gain)
            else:
                SeDaq.SetGain2(new_gain)
            print(f"  Gain updated: {new_gain} dB (Ch{channel})")
        except ValueError:
            print(f"  [WARNING] Invalid gain value: '{text}'. Enter an integer.")

    tb_gain.on_submit(on_gain_submit)

    # ---- Acquire button ------------------------------------------------------
    ax_btn = plt.axes([0.75, 0.08, 0.12, 0.06])
    btn = Button(ax_btn, 'Acquire', color='lightgreen', hovercolor='green')

    def on_acquire(event):
        """Called when the user clicks [Acquire]."""
        state['stop'] = True

    btn.on_clicked(on_acquire)

    # ---- Live update loop ----------------------------------------------------
    plt.ion()
    plt.show()

    while not state['stop']:
        # Single-shot acquisition for live display (fast, no averaging)
        ascan_live = _get_ascan(SeDaq, channel, Smin, Smax, avg=AVG_N_LIVE)

        # Update plot data — do not re-draw axes, only the signal line
        line.set_ydata(ascan_live)

        # Auto-scale y-axis with 20% headroom so the signal fits neatly
        peak = max(np.abs(ascan_live).max(), 1e-6)   # avoid zero division
        ax.set_ylim(-peak * 1.2, peak * 1.2)

        # Clipping indicator — show when signal approaches ±0.5 normalised limit
        clip_text.set_visible(np.abs(ascan_live).max() >= 0.45)

        fig.canvas.draw()
        fig.canvas.flush_events()
        plt.pause(0.05)   # ~20 fps; increase if CPU load is too high

    # ---- Final high-quality acquisition --------------------------------------
    print(f"  Acquiring final A-scan ({AVG_N} averages)...")
    ascan_final = _get_ascan(SeDaq, channel, Smin, Smax, avg=AVG_N)

    plt.close(fig)
    return ascan_final, state['gain']

# ==============================================================================
# [7] TOF EXTRACTION
# ==============================================================================

def _calc_delta_tof(sW1, sW2):
    """
    Compute the time-of-flight difference between two A-scans using
    FFT-based cross-correlation with subsample cosine interpolation.

    sW1 : reference A-scan (vessel without sample).
    sW2 : A-scan with sample submerged.

    A positive delta_TOF means the echo in sW2 arrives later than in sW1,
    i.e. the water surface has risen — the sample is displacing water.

    Parameters
    ----------
    sW1 : ndarray — Reference A-scan.
    sW2 : ndarray — A-scan with sample.

    Returns
    -------
    delta_TOF_s : float — TOF difference [s].
    xcorr       : ndarray — Cross-correlation vector (for quality inspection).
    """
    # CalcToFAscanCosine_XCRFFT returns (delta_TOF in samples, xcorr, aligned_signal)
    delta_TOF_samples, xcorr, _ = CalcToFAscanCosine_XCRFFT(sW2, sW1)

    # Convert from samples to seconds using the digitizer sampling rate
    delta_TOF_s = delta_TOF_samples / Fs

    return delta_TOF_s, xcorr

# ==============================================================================
# [8] CALIBRATION
# ==============================================================================

def calibrate_vessel(V_cal, temperature=None, transducer_freq=10,
                     channel=2, Smin=0, Smax=None, N_cal=3, arduino_port='COM4',
                     gain=35.0, voltage=None):
    """
    Estimate the effective inner radius of the cylindrical vessel by
    submerging a calibration object of known volume and measuring the
    resulting water-level rise via ultrasonic TOF.

    PRINCIPLE
    ---------
    If the vessel radius is r and the water rises by delta_h when a volume
    V_cal is submerged:

        V_cal = pi * r^2 * delta_h
        r     = sqrt(V_cal / (pi * delta_h))

    The measurement is repeated N_cal times and averaged to reduce noise.

    Parameters
    ----------
    V_cal : float
        Known volume of the calibration object [cm^3].
        Measure it externally (graduated cylinder, balance + density, etc.)
        before running this function.
    temperature : float or None
        Water temperature [°C]. If None, read from Arduino.
    transducer_freq : int
        Transducer centre frequency in MHz (5 or 10). Default: 10.
    channel : int
        Digitizer channel connected to the transducer (1 or 2). Default: 2.
    Smin : int
        First sample index of the acquisition window. Default: 0.
    Smax : int or None
        Last sample index. Default: None → use full record length (RecLen).
    N_cal : int
        Number of calibration repetitions to average. Default: 3.
    arduino_port : str
        Serial port of the Arduino (e.g. 'COM3'). Used only when temperature
        is None.
    gain : float
        Receiver gain [dB]. Default: 35.0.
    voltage : float or None
        Excitation voltage [V]. If None, the hardware default is used.

    Returns
    -------
    r_mean : float
        Estimated vessel inner radius [cm], averaged over valid repetitions.
    """

    # ---- Hardware init -------------------------------------------------------
    SeDaq = _init_hardware(transducer_freq, channel, RecLen if Smax is None else Smax,
                           gain=gain, voltage=voltage)
    if Smax is None:
        Smax = SeDaq.RecLen   # use the record length just set

    # ---- Temperature ---------------------------------------------------------
    T, cw = _get_temperature_and_cw(temperature, arduino_port)

    # Convert V_cal from cm^3 to m^3 for SI-consistent computation
    V_cal_m3 = V_cal * 1e-6

    print("\n" + "=" * 60)
    print("  VESSEL CALIBRATION")
    print(f"  Calibration volume : {V_cal:.4f} cm^3")
    print(f"  Repetitions        : {N_cal}")
    print(f"  cw(T={T:.1f} °C)    : {cw:.2f} m/s")
    print("=" * 60)

    r_estimates = []

    for i in range(N_cal):
        print(f"\n  --- Repetition {i + 1} of {N_cal} ---")

        # -- sW1: reference (empty vessel, no calibration object) --------------
        print("  Remove the calibration object from the vessel.")
        sW1, gain1 = _live_acquire(
            SeDaq, channel, Smin, Smax,
            title=f"sW1 — Calibration {i+1}/{N_cal}: vessel EMPTY. Click [Acquire] when stable."
        )
        print("  sW1 acquired.")

        # -- sW2: with calibration object submerged ----------------------------
        print("  Introduce the calibration object and wait for the surface to stabilise.")
        sW2, gain2 = _live_acquire(
            SeDaq, channel, Smin, Smax,
            title=f"sW2 — Calibration {i+1}/{N_cal}: object SUBMERGED. Click [Acquire] when stable."
        )
        print("  sW2 acquired.")

        # -- TOF → delta_h → r -------------------------------------------------
        delta_TOF_s, _ = _calc_delta_tof(sW1, sW2)

        if delta_TOF_s <= 0:
            print(f"  [WARNING] delta_TOF = {delta_TOF_s*1e6:.3f} µs is non-positive.")
            print("  This means the echo arrived earlier with the object submerged,")
            print("  which is physically wrong. Check that the object is fully submerged")
            print("  and that the correct channel is selected. Skipping this repetition.")
            continue

        # Height rise of the water surface [m]
        delta_h_m  = cw * delta_TOF_s / 2.0
        delta_h_cm = delta_h_m * 100.0

        # Vessel radius from inverted volume formula
        r_i_m  = np.sqrt(V_cal_m3 / (np.pi * delta_h_m))
        r_i_cm = r_i_m * 100.0
        r_estimates.append(r_i_cm)

        print(f"  delta_TOF = {delta_TOF_s * 1e6:.4f} µs")
        print(f"  delta_h   = {delta_h_cm:.4f} cm")
        print(f"  r         = {r_i_cm:.4f} cm")

    if len(r_estimates) == 0:
        raise RuntimeError(
            "All calibration repetitions produced invalid results. "
            "Check hardware connections, transducer alignment, and water level."
        )

    r_mean = float(np.mean(r_estimates))
    r_std  = float(np.std(r_estimates))

    print("\n  --- Calibration result ---")
    print(f"  r_vessel = {r_mean:.4f} ± {r_std:.4f} cm")
    print(f"  (mean ± std over {len(r_estimates)} valid repetitions)")
    print("  Pass this value as r_vessel to measure_density().\n")

    return r_mean

# ==============================================================================
# [9] DENSITY MEASUREMENT
# ==============================================================================

def measure_density(r_vessel, mass=None, temperature=None, transducer_freq=10,
                    channel=2, Smin=0, Smax=None, specimen_name=None,
                    arduino_port='COM4', gain=35.0, voltage=None):
    """
    Measure the density of a specimen using the Archimedes water-displacement
    method with ultrasonic TOF detection.

    Parameters
    ----------
    r_vessel : float
        Inner radius of the cylindrical vessel [cm].
        Use the value returned by calibrate_vessel(), or a known value.
    mass : float or None
        Mass of the specimen [g], measured on a precision balance.
        If None, displaced volume is still computed but density is not.
    temperature : float or None
        Water temperature [°C]. If None, read from Arduino.
    transducer_freq : int
        Transducer centre frequency in MHz (5 or 10). Default: 10.
    channel : int
        Digitizer channel connected to the transducer (1 or 2). Default: 2.
    Smin : int
        First sample index of the acquisition window. Default: 0.
    Smax : int or None
        Last sample index. Default: None → use full record length (RecLen).
    specimen_name : str or None
        Label for the specimen (e.g. 'PVA_10pct_FT3').
        If None, the user is prompted at runtime.
    arduino_port : str
        Serial port of the Arduino (e.g. 'COM4'). Used only when temperature
        is None. If the connection fails, the user is prompted to enter the
        temperature manually.
    gain : float
        Receiver gain [dB]. Default: 35.0.
    voltage : float or None
        Excitation voltage [V]. If None, the hardware default is used.

    Returns
    -------
    results : dict
        All measured and derived quantities. Also saved as a JSON file in
        the data/ directory.
    """

    print("\n" + "=" * 60)
    print("  ECOS — Archimedes Density Measurement")
    print("=" * 60)

    # ---- Specimen name -------------------------------------------------------
    if specimen_name is None:
        specimen_name = input("Enter specimen name (e.g. PVA_10pct_FT3): ").strip()
        if not specimen_name:
            specimen_name = "unknown"
    print(f"Specimen: {specimen_name}\n")

    # ---- Hardware init -------------------------------------------------------
    SeDaq = _init_hardware(transducer_freq, channel, RecLen if Smax is None else Smax,
                           gain=gain, voltage=voltage)
    if Smax is None:
        Smax = SeDaq.RecLen

    # ---- Temperature and speed of sound in water -----------------------------
    T, cw = _get_temperature_and_cw(temperature, arduino_port)

    # Convert vessel radius to metres for intermediate SI calculations
    r_vessel_m = r_vessel * 1e-2

    # ---- Acquire sW1: reference, no sample -----------------------------------
    print("\n" + "-" * 60)
    print("  ACQUISITION")
    print("-" * 60)
    print("Remove the sample from the vessel.")
    sW1, gain_sW1 = _live_acquire(
        SeDaq, channel, Smin, Smax,
        title="sW1 — Reference: vessel WITHOUT sample. Click [Acquire] when stable."
    )
    print("sW1 (reference) acquired.\n")

    # ---- Acquire sW2: sample submerged ---------------------------------------
    print("Submerge the sample and wait for the water surface to stabilise.")
    sW2, gain_sW2 = _live_acquire(
        SeDaq, channel, Smin, Smax,
        title="sW2 — Measurement: sample SUBMERGED. Click [Acquire] when stable."
    )
    print("sW2 (with sample) acquired.\n")

    # ---- TOF difference → delta_h → displaced volume ------------------------
    delta_TOF_s, xcorr = _calc_delta_tof(sW1, sW2)

    # Water-surface rise [m]: round-trip path → divide by 2
    delta_h_m  = cw * delta_TOF_s / 2.0
    delta_h_cm = delta_h_m * 100.0

    # Displaced volume = vessel cross-section × surface rise
    V_disp_m3  = np.pi * r_vessel_m**2 * delta_h_m   # [m^3]
    V_disp_cm3 = V_disp_m3 * 1e6                      # [cm^3]

    # ---- Density (only if mass is provided) ----------------------------------
    if mass is not None:
        mass_g   = float(mass)
        rho_gcc  = mass_g / V_disp_cm3    # [g/cm^3]
    else:
        mass_g  = None
        rho_gcc = None

    # ---- Print results -------------------------------------------------------
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Specimen         : {specimen_name}")
    print(f"  Temperature      : {T:.2f} °C")
    print(f"  cw(T)            : {cw:.2f} m/s")
    print(f"  Transducer       : {transducer_freq} MHz")
    print(f"  r_vessel         : {r_vessel:.4f} cm")
    print(f"  delta_TOF        : {delta_TOF_s * 1e6:.4f} µs")
    print(f"  delta_h          : {delta_h_cm:.4f} cm")
    print(f"  V_displaced      : {V_disp_cm3:.4f} cm^3")
    if mass is not None:
        print(f"  Mass             : {mass_g:.4f} g")
        print(f"  Density          : {rho_gcc:.4f} g/cm^3")
    else:
        print("  Density          : not computed (mass not provided)")
    print("=" * 60)

    # ---- Quick visualisation of the two A-scans and cross-correlation --------
    t_us = (np.arange(len(sW1)) + Smin) / Fs * 1e6
    fig, axes = plt.subplots(2, 1, figsize=(10, 6))

    axes[0].plot(t_us, sW1, label='sW1 (reference)', color='steelblue')
    axes[0].plot(t_us, sW2, label='sW2 (sample)', color='darkorange', alpha=0.8)
    axes[0].set_xlabel('Time (µs)')
    axes[0].set_ylabel('Amplitude')
    axes[0].legend()
    axes[0].set_title(f'A-scans — {specimen_name}')
    axes[0].grid(True, alpha=0.3)

    # Cross-correlation: shift so that zero-lag is at the centre of the x-axis
    lag_us = (np.arange(len(xcorr)) - len(xcorr) // 2) / Fs * 1e6
    axes[1].plot(lag_us, np.fft.fftshift(xcorr), color='seagreen')
    axes[1].axvline(0, color='gray', linestyle='--', linewidth=0.8)
    axes[1].set_xlabel('Lag (µs)')
    axes[1].set_ylabel('Cross-correlation')
    axes[1].set_title(f'Cross-correlation sW2 vs sW1  (peak lag = delta_TOF = {delta_TOF_s*1e6:.4f} µs)')
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    plt.show(block=False)

    # ---- Save results to JSON ------------------------------------------------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    results = {
        "specimen_name"       : specimen_name,
        "datetime"            : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "temperature_C"       : round(T, 4),
        "transducer_freq_MHz" : transducer_freq,
        "r_vessel_cm"         : round(r_vessel, 6),
        "delta_TOF_s"         : delta_TOF_s,
        "delta_h_cm"          : round(delta_h_cm, 6),
        "displaced_volume_cm3": round(V_disp_cm3, 6),
        "mass_g"              : mass_g,
        "density_g_cm3"       : round(rho_gcc, 6) if rho_gcc is not None else None,
    }

    data_dir = os.path.join(_repo_root, 'data')
    os.makedirs(data_dir, exist_ok=True)

    json_path = os.path.join(data_dir, f"density_{specimen_name}_{timestamp}.json")
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=4)

    print(f"\nResults saved to: {json_path}")

    return results

# ==============================================================================
# [10] ENTRY POINT
# Edit the calls below to match your experiment.
# ==============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog='density_archimedes',
        description='Archimedes ultrasonic density measurement — UMH ECOS',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # ---- Shared arguments (both subcommands) --------------------------------
    def _add_shared(p):
        p.add_argument('--freq',    type=int,   default=10,     metavar='MHz',
                       help='Transducer centre frequency in MHz (5 or 10). Default: 10')
        p.add_argument('--channel', type=int,   default=2,      metavar='CH',
                       help='Acquisition channel (1 or 2). Default: 2')
        p.add_argument('--port',    type=str,   default='COM4', metavar='PORT',
                       help='Arduino serial port. Default: COM4')
        p.add_argument('--smin',    type=int,   default=0,      metavar='S',
                       help='First sample of acquisition window. Default: 0')
        p.add_argument('--smax',    type=int,   default=None,   metavar='S',
                       help='Last sample of acquisition window. Default: full RecLen')

    # ---- calibrate ----------------------------------------------------------
    p_cal = sub.add_parser('calibrate',
                           help='Estimate vessel inner radius from a known-volume object')
    p_cal.add_argument('--vcal', type=float, required=True, metavar='CM3',
                       help='Known volume of the calibration object [cm^3]')
    p_cal.add_argument('--ncal', type=int,   default=3,     metavar='N',
                       help='Number of calibration repetitions to average. Default: 3')
    p_cal.add_argument('--gain',    type=float, default=35.0, metavar='DB',
                       help='Receiver gain Ch2 [dB] (default: 35)')
    p_cal.add_argument('--voltage', type=float, default=None, metavar='V',
                       help='Excitation voltage [V] (optional)')
    _add_shared(p_cal)

    # ---- measure ------------------------------------------------------------
    p_meas = sub.add_parser('measure',
                            help='Measure specimen density by water displacement')
    p_meas.add_argument('--rvessel', type=float, required=True, metavar='CM',
                        help='Inner radius of the vessel [cm]')
    p_meas.add_argument('--mass',    type=float, default=None,  metavar='G',
                        help='Specimen mass [g]. Omit to skip density computation')
    p_meas.add_argument('--temp',    type=float, default=None,  metavar='C',
                        help='Water temperature [°C]. Omit to read from Arduino')
    p_meas.add_argument('--name',    type=str,   default=None,  metavar='LABEL',
                        help='Specimen identifier. Omit to be prompted at runtime')
    p_meas.add_argument('--gain',    type=float, default=35.0,  metavar='DB',
                        help='Receiver gain Ch2 [dB] (default: 35)')
    p_meas.add_argument('--voltage', type=float, default=None,  metavar='V',
                        help='Excitation voltage [V] (optional)')
    _add_shared(p_meas)

    args = parser.parse_args()

    if args.command == "calibrate":
        r = calibrate_vessel(
            V_cal           = args.vcal,
            N_cal           = args.ncal,
            transducer_freq = args.freq,
            channel         = args.channel,
            arduino_port    = args.port,
            Smin            = args.smin,
            Smax            = args.smax,
            gain            = args.gain,
            voltage         = args.voltage,
        )
        print(f"\nr_vessel calibrado = {r:.4f} cm")

    elif args.command == "measure":
        measure_density(
            r_vessel        = args.rvessel,
            mass            = args.mass,
            temperature     = args.temp,
            transducer_freq = args.freq,
            channel         = args.channel,
            arduino_port    = args.port,
            Smin            = args.smin,
            Smax            = args.smax,
            specimen_name   = args.name,
            gain            = args.gain,
            voltage         = args.voltage,
        )
