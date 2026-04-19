# -*- coding: utf-8 -*-
"""
hw_test.py
==========
Minimal hardware smoke-test for the SeDaq digitizer.
No GUI — acquires one A-scan, prints min/max, and plots both channels.

Edit the constants in section [2] to match your setup, then run:
    python hw_test.py
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
if sys.maxsize <= 2**32:
    _anaconda32_bin = r"C:\ProgramData\Anaconda32\Library\bin"
    if os.path.isdir(_anaconda32_bin):
        os.add_dll_directory(_anaconda32_bin)

sys.path.insert(0, _tools_dir)

# ==============================================================================
# [1] IMPORTS
# ==============================================================================

import time
import numpy as np
import matplotlib.pyplot as plt

from SeDaq import SeDaqDLL
import GenCode_ToolBox as gc

# ==============================================================================
# [2] EDITABLE CONSTANTS
# ==============================================================================

GAIN_CH1  = 65     # Receiver gain, channel 1 [dB]
GAIN_CH2  = 35     # Receiver gain, channel 2 [dB]

VOLTAGE   = 71    # Excitation voltage [V]  — passed as int to SetExtVoltage
RECLEN    = 30000  # Acquisition record length [samples]  (16384 = 164 µs @ 100 MHz)
FREQ_MHZ  = 10     # Transducer centre frequency [MHz]

PROG_GEN_CLK = 200e6   # Waveform generator internal clock [Hz] — do not change
Fs           = 100e6   # ADC sampling frequency [Hz]           — do not change

# ==============================================================================
# [3] HARDWARE INIT
# ==============================================================================

print("=" * 56)
print("  SeDaq haPrdware test")
print(f"  FREQ={FREQ_MHZ} MHz  |  GAIN_CH1={GAIN_CH1} dB  "
      f"GAIN_CH2={GAIN_CH2} dB  |  VOLTAGE={VOLTAGE} V  |  RECLEN={RECLEN}")
print("=" * 56)

print("\nConnecting to SeDaq digitizer...")
sedaq = SeDaqDLL()
time.sleep(0.5)
print("  Connected.")

sedaq.SetRecLen(RECLEN)
print(f"  SetRecLen({RECLEN})  →  {RECLEN / Fs * 1e6:.1f} µs window")

GenCode = gc.MakeGenCode(
    Excitation='Pulse',
    Param='frequency',
    ParamVal=FREQ_MHZ * 1e6,
    SignalPolarity=2,
    Fs=PROG_GEN_CLK,
)
sedaq.UpdateGenCode(GenCode)
print(f"  UpdateGenCode()  →  {FREQ_MHZ} MHz bipolar pulse uploaded")

sedaq.SetGain1(GAIN_CH1)
print(f"  SetGain1({GAIN_CH1} dB)")

sedaq.SetGain2(GAIN_CH2)
print(f"  SetGain2({GAIN_CH2} dB)")

sedaq.SetExtVoltage(int(VOLTAGE))
print(f"  SetExtVoltage({int(VOLTAGE)} V)")

sedaq.SetRelay(1)   # 1 = OFF según protocolo KTU
print("  SetRelay(OFF)")
sedaq.SetRelay(0)   # 0 = ON según protocolo KTU
print("  SetRelay(ON)")
time.sleep(0.5)
print("\nHardware ready.\n")

# ==============================================================================
# [4] ACQUISITION
# ==============================================================================

print("Acquiring A-scan (single shot)...")
sedaq.GetAScan()
print("  Done.\n")

quant = 1024   # 10-bit digitizer: 2^10 levels

raw_ch1 = np.array(list(sedaq.DataADC1[:RECLEN]), dtype=float)
raw_ch2 = np.array(list(sedaq.DataADC2[:RECLEN]), dtype=float)

# Normalise to [-0.5, +0.5] and remove DC offset
ch1 = (raw_ch1 - quant / 2.0) / quant
ch2 = (raw_ch2 - quant / 2.0) / quant
ch1 = ch1 - np.mean(ch1)
ch2 = ch2 - np.mean(ch2)

print(f"  CH1  min={ch1.min():.4f}  max={ch1.max():.4f}")
print(f"  CH2  min={ch2.min():.4f}  max={ch2.max():.4f}")

# ==============================================================================
# [5] PLOT
# ==============================================================================

t_us = np.arange(RECLEN) / Fs * 1e6   # time axis in microseconds

title = (f"hw_test  —  {FREQ_MHZ} MHz  |  "
         f"G1={GAIN_CH1} dB  G2={GAIN_CH2} dB  |  "
         f"V={VOLTAGE} V  |  RecLen={RECLEN}")

fig, axes = plt.subplots(2, 1, figsize=(11, 5), sharex=True)
fig.suptitle(title, fontsize=9)

axes[0].plot(t_us, ch1, color='steelblue', linewidth=0.7)
axes[0].set_ylim(-0.5, 0.5)
axes[0].set_ylabel('CH1  (norm.)')
axes[0].grid(True, alpha=0.3)

axes[1].plot(t_us, ch2, color='darkorange', linewidth=0.7)
axes[1].set_ylim(-0.5, 0.5)
axes[1].set_ylabel('CH2  (norm.)')
axes[1].set_xlabel('Time (µs)')
axes[1].grid(True, alpha=0.3)

fig.tight_layout()
plt.show()

sedaq.Close()
print("USB connection closed.")
