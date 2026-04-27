"""
ecos_gui.py  —  PyQt5 GUI for ECOS longitudinal characterization workflow
ECOS project · Universidad Miguel Hernández · Dpto. Ingeniería de Comunicaciones
Author: A. Rodríguez-Martínez

Requires (Python 32-bit): PyQt5, pyqtgraph, numpy
Hardware: KTU SeDaq digitizer (SeDaqDLL.dll), Arduino (MAX31865 temperature)

Acquisition scheme:
    s_PE  (Ch2) — Pulse-echo, sample present
    s_TT  (Ch1) — Through-transmission, sample present
    s_WP  (Ch1) — Water-path reference, no sample
"""

# ==============================================================================
# [0] PATH SETUP — must be before any other imports
# ==============================================================================
import sys
import os

_TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
os.chdir(_TOOLS_DIR)
os.add_dll_directory(_TOOLS_DIR)

if sys.maxsize <= 2**32:
    _anaconda32_bin = r"C:\ProgramData\Anaconda32\Library\bin"
    if os.path.isdir(_anaconda32_bin):
        os.add_dll_directory(_anaconda32_bin)

_HW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'hardware')
_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database')

# ==============================================================================
# [1] IMPORTS
# ==============================================================================
import json
import time
import argparse

import numpy as np

os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_SCALE_FACTOR"] = "1"

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QComboBox,
    QCheckBox, QPushButton, QRadioButton, QButtonGroup,
    QStackedWidget, QMessageBox, QDialog, QDialogButtonBox,
    QSplitter, QScrollArea, QDoubleSpinBox,
    QAction, QFileDialog, QSizePolicy,
)
from PyQt5.QtCore import QTimer, Qt

import pyqtgraph as pg

sys.path.insert(0, _TOOLS_DIR)
sys.path.insert(0, _HW_DIR)
sys.path.insert(0, _DB_DIR)

# ==============================================================================
# [2] CONFIG
# ==============================================================================
_arg_parser = argparse.ArgumentParser(description="ECOS GUI — longitudinal characterization")
_arg_parser.add_argument(
    "--demo", action="store_true",
    help="Run without hardware (simulated signals)."
)
_ARGS = _arg_parser.parse_args()

if _ARGS.demo:
    _HW_AVAILABLE = False
    print("[ecos_gui] Demo mode — hardware import skipped (--demo flag).")
else:
    try:
        from SeDaq import SeDaqDLL
        from GenCode_ToolBox import MakeGenCode
        from ECOS_US_ToolBox import MakeWindow, Envelope, LongVelocity_Thickness
        from temperature_Alberto_temporal import Arduino
        from BD_Experimentos_PVA import save_experiment_raw_32
        from SpeedsoundWater import water_temp2sos
        _HW_AVAILABLE = True
        print("[ecos_gui] Hardware modules loaded OK.")
    except Exception as _hw_err:
        _HW_AVAILABLE = False
        print(f"[ecos_gui] Demo mode — hardware not available: {_hw_err}")

DEFAULT_GAIN_CH1  = 65
DEFAULT_GAIN_CH2  = 35
DEFAULT_VOLTAGE   = 100
DEFAULT_RECLEN    = 16384
DEFAULT_ACQ_FS    = 100e6
DEFAULT_GEN_FS    = 200e6
DEFAULT_FP        = 5e6
DEFAULT_WIN_LEN   = 200
AVG_N_LIVE        = 1
AVG_N             = 25
REALTIME_INTERVAL = 34       # ms (~30 fps)
DEFAULT_COM       = "COM3"

BITS_OPTIONS = {
    "8 bit":  256,
    "10 bit": 1024,
    "12 bit": 4096,
}

SESSION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'ecos_gui_session.json'
)

SIGNAL_YMIN = -0.5
SIGNAL_YMAX =  0.5

# ==============================================================================
# [3] DEMO HARDWARE
# ==============================================================================
class _DemoSeDaq:
    def __init__(self):
        self.RecLen   = DEFAULT_RECLEN
        self.DataADC1 = [512] * DEFAULT_RECLEN
        self.DataADC2 = [512] * DEFAULT_RECLEN

    def GetAScan(self):
        n  = self.RecLen
        t  = np.arange(n)
        noise = np.random.normal(0, 8, n)

        def _pulse(center, amp=220, width=60, period=20):
            env = np.exp(-((t - center) ** 2) / (2 * width ** 2))
            return amp * env * np.sin(2 * np.pi * t / period)

        ch1 = np.clip(_pulse(2200) + noise + 512, 0, 1023).astype(int)
        ch2 = np.clip(_pulse(1900, amp=170) + noise + 512, 0, 1023).astype(int)
        self.DataADC1 = list(ch1)
        self.DataADC2 = list(ch2)

    def SetRecLen(self, n):
        self.RecLen   = n
        self.DataADC1 = [512] * n
        self.DataADC2 = [512] * n

    def UpdateGenCode(self, gencode):
        print(f"[Demo] UpdateGenCode — {len(gencode)} bytes")

    def SetGain1(self, g):
        print(f"[Demo] SetGain1 = {g}")

    def SetGain2(self, g):
        print(f"[Demo] SetGain2 = {g}")

    def SetExtVoltage(self, v):
        print(f"[Demo] SetExtVoltage = {v}")

    def SetRelay(self, m):
        print(f"[Demo] SetRelay = {m}")

    def Close(self):
        print("[Demo] Close")


# ==============================================================================
# [4] ACQUISITION STATE
# All mutable state shared between GUI callbacks lives here.
# ==============================================================================
class AcqState:
    # Raw captured A-scans
    PE_Ascan     = None   # Pulse-echo (Ch2), sample present
    TT_Ascan     = None   # Through-transmission (Ch1), sample present
    WP_Ascan     = None   # Water-path reference (Ch1), no sample

    # Windowed signals
    PE_Ascan_win = None
    TT_Ascan_win = None
    WP_Ascan_win = None

    # Temperature and water speed at time of capture
    T1 = T2 = None
    Cw1 = Cw2 = Cw_mean = None

    # Gains (mirrored from UI for metadata)
    Gain_Ch1 = DEFAULT_GAIN_CH1
    Gain_Ch2 = DEFAULT_GAIN_CH2

    # Acquisition window (samples)
    Smin = 0
    Smax = DEFAULT_RECLEN

    # Angular acquisition (future)
    theta_i  = 0.0
    SH_Ascan = None
