# -*- coding: utf-8 -*-
"""
ECOS — Elastic Characterization Of Soft-tissue phantoms
========================================================
Acquisition and processing script for PVA phantom ultrasonic characterization.

Measured quantities:
    Cl   : Longitudinal speed of sound (m/s)
    L    : Sample thickness (m)

Three-signal acquisition scheme:
    s_PE  (Ch2)  — Pulse-echo:           transducer transmits and receives (sample present)
    s_TT  (Ch1)  — Through-transmission: separate Tx/Rx pair (sample present)
    s_WP  (Ch1)  — Water-path reference: same path as TT, but NO sample

Workflow (sections):
    [0]  Imports
    [1]  Configuration
    [2]  Utility functions
    [3]  Acquisition state container
    [4]  Hardware initialization
    [5]  Quick signal check
    [6]  Real-time acquisition GUI
    [7]  Windowing GUI
    [8]  Signal inspection
    [9]  Velocity and thickness computation
    [10] Save experiment

Author: Alberto
"""

# ==============================================================================
# [0] IMPORTS
# ==============================================================================

import sys
import os
import time
from pathlib import Path                         # Required for path verification at [10]

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider, RadioButtons, Button, TextBox
from matplotlib.animation import FuncAnimation

# --- Project toolboxes (adjust paths to your installation) ---
sys.path.insert(0, r"D:\ECOS\tools")
sys.path.insert(0, r"D:\ECOS\tools\ultrasound_velocity_tools")
sys.path.append(r"D:\ECOS\database")
sys.path.append(r"D:\ECOS\hardware")

import SeDaq as SD
import ACQ_ToolBox as ACQ
import US_ToolBox_2025 as US
import ultrasound_velocity_tools as UVT
import GenCode_ToolBox as gc
from temperature_Alberto_temporal import Arduino
from BD_Experimentos_PVA import (
    save_experiment_raw_32,
    plot_signals        as bd_plot_signals,   # Renamed: avoids shadowing the local preview function
    append_experiment_to_xlsx,
    quick_stats,
    plot_signals_stacked,
    export_results_catalog_csv,
)

#%%
# ==============================================================================
# [1] CONFIGURATION
# All hardware parameters and file paths in one place.
# Edit this section when changing equipment or directory layout.
# ==============================================================================

# --- Hardware paths ---
RUTA_DLL = r"D:\ECOS\tools\SeDaqDLL.dll"
ARDUINO_PORT   = 'COM4'
ARDUINO_BAUD   = 115200

# --- Signal generation ---
PROG_GEN_CLK   = 200.0e6        # Internal clock of the waveform generator (Hz)
Fp             = 5.0e6          # Central frequency of the US excitation pulse (Hz)

# --- Digitizer ---
Fs                  = 100.0e6        # ADC sampling frequency (Hz)
RecLen              = 16 * 1024      # Acquisition record length (samples)
AvgSamplesNum_live  = 1          # Averaging for the real-time display loop (speed over quality)
AvgSamplesNum       = 25         # Averaging for PE/TT/WP captures (quality)
Gain_Ch1_init       = 65             # Initial gain, channel 1 — pulse-echo receiver (dB)
Gain_Ch2_init       = 35             # Initial gain, channel 2 — TT receiver (dB)

# --- Windowing ---
MyWinLen       = 200            # Initial Tukey window length (samples)

# --- Working directory (for organized file system; raw data goes to data_32/) ---
CurrentDir     = r'D:\Prueba\MEDIDAS'
RootDir        = "PVA_Characterization"
Experiment     = "Thin_PVA"
SaveDir        = "Prueba_" + time.strftime("%Y_%m_%d") + "_" + time.strftime("%H_%M_%S")
MyDir          = os.path.join(CurrentDir, RootDir, Experiment, SaveDir)
os.makedirs(MyDir, exist_ok=True)
print(f"Working directory: {MyDir}")

#%%
# ==============================================================================
# [2] UTILITY FUNCTIONS
# ==============================================================================

def water_temp2sos(T):
    """
    Speed of sound in water as a function of temperature T (°C).
    Double-Gaussian empirical fit, valid approximately 10–60 °C.

    Parameters
    ----------
    T : float or array-like — Temperature (°C)

    Returns
    -------
    c : float or array — Speed of sound (m/s)
    """
    c = (1.569678141e3 * np.exp(-((T - 5.907868678e1) / (-3.443078912e2))**2)
       - 2.574064370e4 * np.exp(-((T + 3.705052160e2) / (-1.601257116e2))**2))
    return c


def read_temperatures(port=ARDUINO_PORT, baudrate=ARDUINO_BAUD, n_avg=3):
    """
    Connect to Arduino, read both temperature sensors, compute water speed
    of sound from each, then disconnect.

    Returns
    -------
    T1, T2   : float — Temperature at sensor 1 and 2 (°C)
    Cw1, Cw2 : float — Corresponding water speed of sound (m/s)
    """
    arduino = Arduino(port=port, baudrate=baudrate, N_avg=n_avg)
    T1, T2  = arduino.getTemperatures()
    arduino.close()
    Cw1, Cw2 = water_temp2sos(T1), water_temp2sos(T2)
    print(f"  T1 = {T1:.2f} °C → Cw1 = {Cw1:.3f} m/s")
    print(f"  T2 = {T2:.2f} °C → Cw2 = {Cw2:.3f} m/s")
    return T1, T2, Cw1, Cw2


def monitor_temperature(port=ARDUINO_PORT, baudrate=ARDUINO_BAUD, interval_s=10):
    """
    Optional diagnostic tool — real-time plot of temperature and derived
    water speed of sound from both sensors.

    IMPORTANT: blocks execution until the window is closed.
    Call manually only when needed; NOT part of the normal acquisition flow.

    Parameters
    ----------
    interval_s : float — Update interval (seconds)
    """
    arduino = Arduino(port=port, baudrate=baudrate, N_avg=3)
    t0 = time.time()
    times, T1_list, T2_list, c1_list, c2_list = [], [], [], [], []

    fig_mon, (axT, axC) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)

    line_T1, = axT.plot([], [], label="T1 (°C)", color="tab:blue")
    line_T2, = axT.plot([], [], label="T2 (°C)", color="tab:orange")
    axT.set_ylabel("Temperature [°C]"); axT.legend(); axT.grid(True)

    line_c1, = axC.plot([], [], label="c(T1)", color="tab:blue")
    line_c2, = axC.plot([], [], label="c(T2)", color="tab:orange")
    axC.set_ylabel("Speed of sound [m/s]"); axC.set_xlabel("Time [s]")
    axC.legend(); axC.grid(True)

    def _update(frame):
        T1, T2 = arduino.getTemperatures()
        if T1 is None or T2 is None:
            return line_T1, line_T2, line_c1, line_c2
        t = time.time() - t0
        c1, c2 = water_temp2sos(T1), water_temp2sos(T2)
        for lst, val in zip(
            [times, T1_list, T2_list, c1_list, c2_list], [t, T1, T2, c1, c2]
        ):
            lst.append(val)
        line_T1.set_data(times, T1_list); line_T2.set_data(times, T2_list)
        line_c1.set_data(times, c1_list); line_c2.set_data(times, c2_list)
        axT.relim(); axT.autoscale_view()
        axC.relim(); axC.autoscale_view()
        return line_T1, line_T2, line_c1, line_c2

    def _on_close(event):
        print("Closing serial port (temperature monitor)...")
        arduino.close()

    ani_mon = FuncAnimation(fig_mon, _update, interval=int(interval_s * 1000), blit=False)
    fig_mon.canvas.mpl_connect('close_event', _on_close)
    plt.show()

#%%
# ==============================================================================
# [3] ACQUISITION STATE
# All mutable state shared between GUI callbacks lives here.
# Using a class avoids scattering globals across functions.
# ==============================================================================

class AcqState:
    """Container for all mutable acquisition state."""

    # --- Raw captured A-scans (set by GUI buttons) ---
    PE_Ascan     = None   # Pulse-echo (Ch2), sample present
    TT_Ascan     = None   # Through-transmission (Ch1), sample present
    WP_Ascan     = None   # Water-path reference (Ch1), NO sample

    # --- Windowed signals (set by windowing GUI) ---
    PE_Ascan_win = None
    TT_Ascan_win = None
    WP_Ascan_win = None

    # --- Window delays in samples (stored for traceability in metadata) ---
    Delay_PE = 0
    Delay_TT = 0
    Delay_WP = 0

    # --- Temperature and water speed at time of water-path capture ---
    T1 = T2 = None
    Cw1 = Cw2 = Cw_mean = None

    # --- Gains (mirrored from sliders so they can be saved in metadata) ---
    Gain_Ch1 = Gain_Ch1_init
    Gain_Ch2 = Gain_Ch2_init

    # --- Acquisition range used for PE/TT/WP captures (samples) ---
    Smin = 0
    Smax = RecLen

state = AcqState()

#%%
# ==============================================================================
# [4] HARDWARE INITIALIZATION
# Connect to SeDaq digitizer, upload excitation waveform, set initial gains.
# NOTE: requires 32-bit Python environment to load the DLL.
# ==============================================================================

SeDaq = SD.SeDaqDLL(RUTA_DLL)
time.sleep(1)                    # Allow firmware to finish initializing
print("SeDaq connected.")

SeDaq.SetRecLen(RecLen)
print(f"Record length set: {RecLen} samples ({RecLen / Fs * 1e6:.1f} µs)")

# Build excitation waveform: 5 MHz pulse, bipolar
GenCode = gc.MakeGenCode(
    Excitation='Pulse',
    Param='frequency',
    ParamVal=Fp,
    SignalPolarity=2,
    Fs=PROG_GEN_CLK,
    DeadTime_Samples=0,
    CancelDuration=0,
    AddZerosInFront_Samples=0,
)
SeDaq.UpdateGenCode(GenCode)
print(f"Excitation waveform uploaded: {Fp / 1e6:.1f} MHz pulse.")

# Set gains.
# FIRMWARE BUG: Ch1 must always be set before Ch2, otherwise Ch2 resets to default.
SeDaq.SetGain1(state.Gain_Ch1)
SeDaq.SetGain2(state.Gain_Ch2)
print(f"Gains — Ch1: {state.Gain_Ch1} dB  |  Ch2: {state.Gain_Ch2} dB")
print("=" * 70)

#%%
# ==============================================================================
# [5] QUICK SIGNAL CHECK
# Acquire both channels over the full record and display the time-frequency
# plot. Used to verify connectivity and signal quality before the main GUI.
# ==============================================================================

Ascan_Ch1 = ACQ.GetAscan_Ch1(0, RecLen, AvgSamplesNumber=AvgSamplesNum, Quantiz_Levels=1024)
Ascan_Ch2 = ACQ.GetAscan_Ch2(0, RecLen, AvgSamplesNumber=AvgSamplesNum, Quantiz_Levels=1024)

# FFT length: next power of 2 above signal length, with one extra octave of padding
nfft = 2 ** (int(np.ceil(np.log2(len(Ascan_Ch1)))) + 2)

US.Plot2Ascans_TimeFreq(
    Ascan_Ch2, Ascan_Ch1,
    nfft=nfft, FreqScale=1e6, TimeScale=1, Fmax=15, Fs=Fs, FigNum=2
)
plt.show()


# ==============================================================================
# [6] REAL-TIME ACQUISITION GUI
#
# Layout:
#   Top panel    — live zoomed A-scan (both channels)
#   Bottom panel — static overview of the full record (context)
#   Sliders      — set acquisition window start/end
#   Radio buttons— switch x-axis units: samples / µs / mm
#   Gain sliders — adjust Ch1 and Ch2 gain on the fly
#   [PE-TT] btn  — capture pulse-echo + through-transmission (sample present)
#   [WaterPath]  — capture water-path reference (no sample) + re-read temperature
# ==============================================================================

# --- Read temperature immediately before opening the GUI ---
print("Reading temperature...")
T1, T2, Cw1, Cw2 = read_temperatures()
state.T1, state.T2 = T1, T2
state.Cw1, state.Cw2 = Cw1, Cw2
state.Cw_mean = (Cw1 + Cw2) / 2   # Average used for the distance axis conversion

# ---- Axis unit helpers -------------------------------------------------------
# TipoEje is a dict (not a plain variable) so callbacks can mutate it in place
TipoEje       = {'value': 'mus'}   # options: 'samples', 'mus', 'mm'
Label_x_axis  = 'Time [μs]'
N_SAMPLES_TOTAL   = RecLen - 1
MIN_RANGE_SAMPLES = 100            # Minimum allowed window width (samples)

def units_to_samples(val):
    """Convert from the current display unit to a sample index (integer)."""
    if TipoEje['value'] == 'mus':
        return int(round(val * 1e-6 * Fs))
    elif TipoEje['value'] == 'mm':
        # One-way distance: d = c·t/2  →  t = 2d/c  →  n = 2d·Fs/c
        return int(round(val * 2.0 / (state.Cw_mean * 1e-3) * Fs))
    else:
        return int(round(val))

def samples_to_units(samples):
    """Convert from sample index to the current display unit (float)."""
    if TipoEje['value'] == 'mus':
        return samples / Fs * 1e6
    elif TipoEje['value'] == 'mm':
        return samples / Fs * state.Cw_mean / 2.0 * 1e3
    else:
        return float(samples)

# ---- Static overview acquisition (background context) -----------------------
Smin_init = 4600
Smax_init = 8000
FullData_Ch1 = ACQ.GetAscan_Ch1(0, N_SAMPLES_TOTAL, AvgSamplesNumber=AvgSamplesNum, Quantiz_Levels=1024)
FullData_Ch2 = ACQ.GetAscan_Ch2(0, N_SAMPLES_TOTAL, AvgSamplesNumber=AvgSamplesNum, Quantiz_Levels=1024)
x_full_unit  = samples_to_units(np.arange(len(FullData_Ch1)))
FullMin = min(np.min(FullData_Ch1), np.min(FullData_Ch2))
FullMax = max(np.max(FullData_Ch1), np.max(FullData_Ch2))

# ---- Build figure layout ----------------------------------------------------
fig_rt = plt.figure(figsize=(14, 7))
gs     = gridspec.GridSpec(3, 1, height_ratios=[6, 0.8, 1])
plt.subplots_adjust(bottom=0.18, left=0.08, right=0.85, hspace=0.35)

ax_main     = fig_rt.add_subplot(gs[0])   # Live zoomed view
ax_overview = fig_rt.add_subplot(gs[1])   # Full-record static overview

# Main panel: live signal lines (data updated by animation)
ArrayLen_init = Smax_init - Smin_init
x_init        = samples_to_units(np.arange(ArrayLen_init) + Smin_init)
line_Ch1, = ax_main.plot(x_init, np.zeros(ArrayLen_init), label='Ch1 (TT)', color='coral')
line_Ch2, = ax_main.plot(x_init, np.zeros(ArrayLen_init), label='Ch2 (PE)', color='blue')
ax_main.set_ylim(-0.5, 0.5)
ax_main.set_xlim(x_init[0], x_init[-1])
ax_main.set_xlabel(Label_x_axis)
ax_main.set_ylabel("Amplitude")
ax_main.set_title("Real-Time Signal Acquisition")
ax_main.legend()

# Overview panel: static snapshot of the full record for context
ax_overview.plot(x_full_unit, FullData_Ch1, color='coral', alpha=0.3, label='Ch1')
ax_overview.plot(x_full_unit, FullData_Ch2, color='blue',  alpha=0.3, label='Ch2')
ax_overview.set_xlim(x_full_unit[0], x_full_unit[-1])
ax_overview.set_ylim(FullMin, FullMax)
ax_overview.set_ylabel("Overview")
ax_overview.set_xlabel(Label_x_axis)
ax_overview.set_yticks([])
ax_overview.legend(loc='upper right', fontsize='small')
# Red dashed lines mark the current zoomed window on the overview
line_vmin = ax_overview.axvline(samples_to_units(Smin_init), color='red', linestyle='--')
line_vmax = ax_overview.axvline(samples_to_units(Smax_init), color='red', linestyle='--')
# Gray shading on the main panel indicates the captured range
shade_range = ax_main.axvspan(
    samples_to_units(Smin_init), samples_to_units(Smax_init), color='gray', alpha=0.1
)

def update_shade():
    """Redraw the gray shaded region to match the current slider values."""
    ymin, ymax = ax_main.get_ylim()
    shade_range.set_xy([
        [slider_smin.val, ymin], [slider_smin.val, ymax],
        [slider_smax.val, ymax], [slider_smax.val, ymin],
        [slider_smin.val, ymin],
    ])

# ---- Horizontal sliders: acquisition window ---------------------------------
MIN_RANGE_UNITS = samples_to_units(MIN_RANGE_SAMPLES)
unit_min = samples_to_units(0)
unit_max = samples_to_units(N_SAMPLES_TOTAL)

ax_smin    = plt.axes([0.08, 0.10, 0.77, 0.03])
ax_smax    = plt.axes([0.08, 0.05, 0.77, 0.03])
slider_smin = Slider(ax_smin, f'Start ({Label_x_axis})',
                     unit_min, unit_max - MIN_RANGE_UNITS,
                     valinit=samples_to_units(Smin_init), valstep=1)
slider_smax = Slider(ax_smax, f'End ({Label_x_axis})',
                     unit_min + MIN_RANGE_UNITS, unit_max,
                     valinit=samples_to_units(Smax_init), valstep=1)

def validate_slider_range(val):
    """
    Prevent start and end sliders from crossing or getting too close.
    Also keeps the overview markers (red dashed lines) synchronized.
    """
    smin, smax = slider_smin.val, slider_smax.val
    if smin >= smax - MIN_RANGE_UNITS:
        if val == smin:
            slider_smin.set_val(smax - MIN_RANGE_UNITS)
        else:
            slider_smax.set_val(smin + MIN_RANGE_UNITS)
    line_vmin.set_xdata(samples_to_units(units_to_samples(slider_smin.val)))
    line_vmax.set_xdata(samples_to_units(units_to_samples(slider_smax.val)))
    update_shade()

slider_smin.on_changed(validate_slider_range)
slider_smax.on_changed(validate_slider_range)

# ---- Axis unit radio buttons ------------------------------------------------
ax_radio     = plt.axes([0.92, 0.12, 0.07, 0.1])
radio_buttons = RadioButtons(ax_radio, ('samples', 'mus', 'mm'), active=1)

def on_axis_change(label):
    """
    Switch display units. Converts current slider positions to samples first,
    then re-expresses them in the new unit to preserve the visible window.
    """
    global Label_x_axis, MIN_RANGE_UNITS
    # Save current window in samples before switching
    Smin_s = units_to_samples(slider_smin.val)
    Smax_s = units_to_samples(slider_smax.val)

    TipoEje['value'] = label
    Label_x_axis = {'mus': 'Time [μs]', 'mm': 'Distance [mm]', 'samples': 'Samples'}[label]

    MIN_RANGE_UNITS = samples_to_units(MIN_RANGE_SAMPLES)
    unit_min = samples_to_units(0)
    unit_max = samples_to_units(N_SAMPLES_TOTAL)

    slider_smin.valmin = unit_min
    slider_smin.valmax = unit_max - MIN_RANGE_UNITS
    slider_smax.valmin = unit_min + MIN_RANGE_UNITS
    slider_smax.valmax = unit_max

    slider_smin.set_val(samples_to_units(Smin_s))
    slider_smax.set_val(samples_to_units(Smax_s))
    slider_smin.label.set_text(f'Start ({Label_x_axis})')
    slider_smax.label.set_text(f'End ({Label_x_axis})')
    ax_main.set_xlabel(Label_x_axis)
    ax_overview.set_xlabel(Label_x_axis)
    ax_main.set_xlim(samples_to_units(Smin_s), samples_to_units(Smax_s))
    fig_rt.canvas.draw_idle()

radio_buttons.on_clicked(on_axis_change)

# ---- Vertical gain sliders --------------------------------------------------
ax_gain1    = plt.axes([0.920, 0.38, 0.015, 0.5])
ax_gain2    = plt.axes([0.945, 0.38, 0.015, 0.5])
slider_gain1 = Slider(ax_gain1, "Ch1\nGain", 20, 90, valinit=state.Gain_Ch1, orientation='vertical')
slider_gain2 = Slider(ax_gain2, "Ch2\nGain", 20, 90, valinit=state.Gain_Ch2, orientation='vertical')

def update_gain1(val):
    """
    Update Ch1 gain.
    FIRMWARE BUG: Ch1 must be set first, then Ch2 must be re-applied immediately.
    """
    state.Gain_Ch1 = int(val)
    SeDaq.SetGain1(state.Gain_Ch1)
    SeDaq.SetGain2(state.Gain_Ch2)   # Re-apply Ch2 to prevent it resetting

def update_gain2(val):
    """Update Ch2 gain only."""
    state.Gain_Ch2 = int(val)
    SeDaq.SetGain2(state.Gain_Ch2)

slider_gain1.on_changed(update_gain1)
slider_gain2.on_changed(update_gain2)

# ---- Capture buttons --------------------------------------------------------
ax_btn_pett = plt.axes([0.92, 0.28, 0.07, 0.045])
ax_btn_wp   = plt.axes([0.92, 0.22, 0.07, 0.045])
btn_pett    = Button(ax_btn_pett, 'PE-TT')
btn_wp      = Button(ax_btn_wp,   'WaterPath')

def on_click_pett(event):
    """
    Capture pulse-echo (Ch2) and through-transmission (Ch1) with the sample
    in the water path. Saves to state.PE_Ascan and state.TT_Ascan.
    """
    Smin = units_to_samples(slider_smin.val)
    Smax = units_to_samples(slider_smax.val)
    state.PE_Ascan = np.array(ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber=AvgSamplesNum, Quantiz_Levels=1024))
    state.TT_Ascan = np.array(ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber=AvgSamplesNum, Quantiz_Levels=1024))
    state.Smin, state.Smax = Smin, Smax
    print(f"PE + TT captured: {len(state.PE_Ascan)} samples  (range {Smin}–{Smax})")

def on_click_wp(event):
    """
    Capture water-path reference (Ch1) WITHOUT the sample.
    Also re-reads temperature: Cw must correspond to the moment of reference
    capture, since it enters directly into the velocity computation.
    """
    Smin = units_to_samples(slider_smin.val)
    Smax = units_to_samples(slider_smax.val)
    state.WP_Ascan = np.array(ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber=AvgSamplesNum, Quantiz_Levels=1024))
    print("Reading temperature for water-path reference...")
    T1, T2, Cw1, Cw2 = read_temperatures()
    state.T1, state.T2   = T1, T2
    state.Cw1, state.Cw2 = Cw1, Cw2
    state.Cw_mean = (Cw1 + Cw2) / 2
    state.Smin, state.Smax = Smin, Smax
    print(f"WaterPath captured: {len(state.WP_Ascan)} samples  |  Cw = {state.Cw_mean:.3f} m/s")

btn_pett.on_clicked(on_click_pett)
btn_wp.on_clicked(on_click_wp)

# ---- Real-time animation loop -----------------------------------------------
def update_rt(frame):
    """
    Called periodically by FuncAnimation. Acquires a new A-scan pair and
    updates the main plot. The acquisition window follows the sliders live.
    """
    Smin     = units_to_samples(slider_smin.val)
    Smax     = units_to_samples(slider_smax.val)
    ArrayLen = Smax - Smin
    if ArrayLen <= 0 or ArrayLen > 50000:
        return line_Ch1, line_Ch2

    x_unit  = samples_to_units(Smin) + samples_to_units(np.arange(ArrayLen))
    # Acquire with reduced averaging for smooth real-time display
    buf_Ch1 = np.array(ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber=AvgSamplesNum_live, Quantiz_Levels=1024))
    buf_Ch2 = np.array(ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber=AvgSamplesNum_live, Quantiz_Levels=1024))

    line_Ch1.set_xdata(x_unit); line_Ch1.set_ydata(buf_Ch1)
    line_Ch2.set_xdata(x_unit); line_Ch2.set_ydata(buf_Ch2)
    ax_main.set_xlim(x_unit[0], x_unit[-1])
    ax_main.set_xlabel(Label_x_axis)
    line_vmin.set_xdata(x_unit[0])
    line_vmax.set_xdata(x_unit[-1])
    update_shade()
    return line_Ch1, line_Ch2

# Animation interval: approximate real-time rate based on initial window size
interval_ms = int(1000 * (Smax_init - Smin_init) / Fs)
ani_rt = animation.FuncAnimation(fig_rt, update_rt, interval=interval_ms, blit=False)

# ---- Hover cursor -----------------------------------------------------------
cursor_line = ax_main.axvline(x=0, color='gray', linestyle='--', linewidth=0.8, alpha=0.6)
cursor_text = ax_main.text(
    0.02, 0.95, '', transform=ax_main.transAxes, fontsize=9,
    verticalalignment='top', bbox=dict(facecolor='white', edgecolor='gray', alpha=0.6)
)

def on_mouse_move(event):
    """Display a cursor and coordinate label when hovering over the main plot."""
    if event.inaxes != ax_main or event.xdata is None:
        cursor_line.set_visible(False)
        cursor_text.set_visible(False)
        fig_rt.canvas.draw_idle()
        return
    x = event.xdata
    cursor_line.set_xdata(x); cursor_line.set_visible(True)
    label = {'mus': f"t = {x:.1f} μs", 'mm': f"d = {x:.2f} mm"}.get(TipoEje['value'], f"s = {x:.0f}")
    cursor_text.set_text(label); cursor_text.set_visible(True)
    fig_rt.canvas.draw_idle()

fig_rt.canvas.mpl_connect('motion_notify_event', on_mouse_move)
plt.show()


# ==============================================================================
# [7] WINDOWING GUI
#
# A Tukey window is applied around the main echo of each signal to isolate
# the relevant waveform before velocity/thickness computation.
# The window is centered on the peak of the Hilbert envelope.
# The student adjusts the window length and clicks "Apply window" to confirm.
# ==============================================================================

fig_win, axs_win = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
plt.subplots_adjust(left=0.1, bottom=0.35, hspace=0.35)

def draw_windowing_preview(win_len):
    """
    Preview the Tukey window superimposed on each signal (both normalised).
    The envelope peak position is shown in the subplot title.

    Parameters
    ----------
    win_len : int — Window length in samples
    """
    signals = [state.TT_Ascan, state.PE_Ascan, state.WP_Ascan]
    titles  = ['TT (Ch1, sample)', 'PE (Ch2, sample)', 'WP (Ch1, reference, no sample)']
    for ax, sig, title in zip(axs_win, signals, titles):
        ax.cla()
        env   = UVT.Envelope(sig)
        peak  = np.argmax(env)
        delay = peak - win_len // 2           # Center the window on the peak
        win   = UVT.MakeWindow('Tukey', WinLen=win_len, param1=0.2, param2=1,
                               Span=len(sig), Delay=delay)
        ax.plot(sig / np.max(np.abs(sig)), label='Normalised signal', alpha=0.6)
        ax.plot(win / np.max(win),          label='Tukey window',     linestyle='--')
        ax.set_title(f'{title}  (envelope peak @ sample {peak})')
        ax.set_ylabel('Amplitude'); ax.legend(); ax.grid(True)
    axs_win[2].set_xlabel('Samples')
    fig_win.canvas.draw_idle()

def submit_winlen(text):
    """Called when the student types a new window length and presses Enter."""
    global MyWinLen
    try:
        val = int(text)
        if val > 0:
            MyWinLen = val
            draw_windowing_preview(MyWinLen)
    except ValueError:
        pass   # Ignore non-integer input silently

def on_click_apply_window(event):
    """
    Apply the current Tukey window to TT, PE, and WP signals.
    Windowed signals and delays are stored in state for the computation step.
    """
    for attr_raw, attr_win, attr_delay in [
        ('TT_Ascan', 'TT_Ascan_win', 'Delay_TT'),
        ('PE_Ascan', 'PE_Ascan_win', 'Delay_PE'),
        ('WP_Ascan', 'WP_Ascan_win', 'Delay_WP'),
    ]:
        sig   = getattr(state, attr_raw)
        peak  = np.argmax(UVT.Envelope(sig))
        delay = peak - MyWinLen // 2
        win   = UVT.MakeWindow('Tukey', WinLen=MyWinLen, param1=0.2, param2=1,
                               Span=len(sig), Delay=delay)
        setattr(state, attr_win,   sig * win)
        setattr(state, attr_delay, delay)
    print(f"Window applied — length: {MyWinLen} samples.")

# TextBox: type a new window length and press Enter
axbox    = plt.axes([0.10, 0.22, 0.30, 0.05])
text_box = TextBox(axbox, 'Window length (samples):', initial=str(MyWinLen))
text_box.on_submit(submit_winlen)

# Button: apply the window and store results
ax_btn_win = plt.axes([0.45, 0.22, 0.15, 0.05])
btn_apply  = Button(ax_btn_win, 'Apply window')
btn_apply.on_clicked(on_click_apply_window)

draw_windowing_preview(MyWinLen)
plt.show()


# ==============================================================================
# [8] SIGNAL INSPECTION
# Visual sanity check of raw and windowed signals before computation.
# ==============================================================================

fig_chk, axs_chk = plt.subplots(4, 1, figsize=(10, 8))
axs_chk[0].plot(UVT.NormSig(state.PE_Ascan));     axs_chk[0].set_title('PE raw (Ch2, sample)')
axs_chk[1].plot(UVT.NormSig(state.TT_Ascan_win)); axs_chk[1].set_title('TT windowed (Ch1, sample)')
axs_chk[2].plot(UVT.NormSig(state.WP_Ascan_win)); axs_chk[2].set_title('WP windowed (Ch1, reference)')
axs_chk[3].plot(UVT.NormSig(state.PE_Ascan_win)); axs_chk[3].set_title('PE windowed (Ch2, sample)')
for ax in axs_chk:
    ax.set_ylabel('Norm. amplitude'); ax.grid(True)
axs_chk[3].set_xlabel('Samples')
plt.tight_layout()
plt.show()


# ==============================================================================
# [9] VELOCITY AND THICKNESS COMPUTATION
#
# Three-signal method (simultaneous Cl and L):
#   - The TOF difference between TT_win and WP_win gives the delay introduced
#     by the sample relative to the water path of the same length.
#   - The PE round-trip TOF combined with Cl gives the thickness L.
#   - Cw_mean (from temperature sensors) is the reference speed in water.
#   - UseHilbEnv=True: Hilbert envelope is used for TOF peak detection.
# ==============================================================================

Cl, L = UVT.LongVelocity_Thickness(
    state.PE_Ascan,       # Raw PE signal (used for initial TOF estimate)
    state.TT_Ascan_win,   # Windowed TT signal
    state.WP_Ascan_win,   # Windowed water-path reference
    state.PE_Ascan_win,   # Windowed PE signal
    Fs,
    state.Cw_mean,
    UseHilbEnv=True,
)

print("=" * 55)
print(f"  Water speed      Cw  = {state.Cw_mean:.3f} m/s")
print(f"  Temperature      T1  = {state.T1:.2f} °C  |  T2 = {state.T2:.2f} °C")
print("-" * 55)
print(f"  Longitudinal     Cl  = {Cl:.3f} m/s")
print(f"  Thickness         L  = {L * 1000:.3f} mm")
print("=" * 55)


# ==============================================================================
# [10] SAVE EXPERIMENT
#
# All raw signals (PE, TT, WP) and full metadata are saved to a structured
# directory under "data_32/" via the BD_Experimentos_PVA module.
# Edit the specimen dict for each new sample/session.
# ==============================================================================

# --- Specimen descriptor (edit per experiment) ---
specimen = {
    "fecha_fabricacion":   "2026-17-02",
    "base":                "agua",
    "porcentaje_pva":      "10%",
    "aditivo1":            "Propenglicol",
    "porcentaje_aditivo1": "10%",
    "ciclos":              3,
    "pieza":               "I",
    "otros":               "Segunda prueba con la pieza I",
}

# --- Acquisition equipment descriptor ---
equipment1 = {
    "nombre":          "SEDAQ",
    "transductor_pe":  "Enfocado 5MHz XXX",
    "transductor_tt":  "No enfocado 5MHz XXX",
    "params": {
        "Gain_Ch1":           state.Gain_Ch1,
        "Gain_Ch2":           state.Gain_Ch2,
        "Voltaje":            50,
        "F_muestreo":         Fs,
        "Fc_pulso":           Fp,
        "Tipo_excitacion":    "Pulso",
        "QuantizationLevels": 1024,
        "AverageSamples":     AvgSamplesNum,
        "RecLen":             RecLen,
        "Smin":               state.Smin,
        "Smax":               state.Smax,
        "Slen":               len(state.PE_Ascan),
        "WindowLen":          MyWinLen,
    },
}
equipment2 = {
    "nombre":             "Arduino",
    "transductor_temp_1": "XYZ",
    "transductor_temp_2": "",
    "otros":              "",
}
protocol = {
    "description": "Ensayo ultrasónico de caracterización longitudinal",
    "notes":       "",
}

# --- Computed results ---
results = {
    "T1": state.T1,    "T2": state.T2,
    "C1": state.Cw1,   "C2": state.Cw2,
    "Cw": state.Cw_mean,
    "Cl": Cl,
    "L":  L,
}

# Save to the experiment database (creates a timestamped subdirectory)
exp_dir = save_experiment_raw_32(
    specimen=specimen,
    equipment1=equipment1,
    equipment2=equipment2,
    protocol=protocol,
    results=results,
    Signal_PE=state.PE_Ascan,
    Signal_TT=state.TT_Ascan,
    Signal_Ref=state.WP_Ascan,
    base_dir="data_32",
)
print(f"Experiment saved to: {exp_dir}")

# --- Verify the saved directory exists and list its contents ---
p = Path(exp_dir).resolve()    # Path is now properly imported at [0]
print(f"Absolute path : {p}")
print(f"Exists        : {p.exists()}")
if p.exists():
    print("Contents:")
    for name in os.listdir(p):
        print(f"  - {name}")
