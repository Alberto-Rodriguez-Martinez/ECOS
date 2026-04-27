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

import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning)

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


# ==============================================================================
# [5] MAIN WINDOW — EcosGUI
# ==============================================================================
class EcosGUI(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECOS — Longitudinal Characterization")
        self.resize(1400, 850)

        self._state           = AcqState()
        self._reclen          = DEFAULT_RECLEN
        self._running         = True
        self._inspection_mode = False
        self._syncing         = False
        self._unit            = 'samples'   # 'samples' | 'mus' | 'mm'
        self._Cl              = None
        self._L               = None

        # ── Hardware connection ───────────────────────────────────────────────
        if _HW_AVAILABLE:
            try:
                self._sedaq = SeDaqDLL()
                time.sleep(0.5)
                self._sedaq.SetRecLen(DEFAULT_RECLEN)
                _gencode = MakeGenCode(
                    Excitation='Pulse',
                    Param='frequency',
                    ParamVal=DEFAULT_FP,
                    SignalPolarity=2,
                    Fs=DEFAULT_GEN_FS,
                )
                self._sedaq.UpdateGenCode(_gencode)
                # FIRMWARE BUG: Ch1 must always be set before Ch2
                self._sedaq.SetGain1(DEFAULT_GAIN_CH1)
                self._sedaq.SetGain2(DEFAULT_GAIN_CH2)
                self._sedaq.SetRelay(1)
                time.sleep(0.1)
                self._sedaq.SetRelay(0)
                self._demo = False
            except Exception as e:
                QMessageBox.warning(
                    self, "Hardware warning",
                    f"DLL found but initialisation failed:\n{e}\n\nRunning in demo mode."
                )
                self._sedaq = _DemoSeDaq()
                self._demo  = True
        else:
            self._sedaq = _DemoSeDaq()
            self._demo  = True

        # ── Build UI ──────────────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([980, 420])
        main_layout.addWidget(splitter)

        self._build_menu()
        self._btn_relay.setChecked(True)
        self._syncing = False

        # ── Restore previous session ──────────────────────────────────────────
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE) as f:
                    self._restore_session(json.load(f))
                self._apply_restored_hw()
            except Exception:
                pass

        # ── Real-time acquisition timer ───────────────────────────────────────
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_plots)
        self._timer.start(REALTIME_INTERVAL)

    # ==========================================================================
    #  Menu
    # ==========================================================================
    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("File")
        act_save = QAction("Save Session", self)
        act_load = QAction("Load Session", self)
        act_save.triggered.connect(self._save_session_to_file)
        act_load.triggered.connect(self._load_session_from_file)
        file_menu.addAction(act_save)
        file_menu.addAction(act_load)

    def _save_session_to_file(self):
        try:
            with open(SESSION_FILE, 'w') as f:
                json.dump(self._collect_session(), f, indent=2)
            print(f"[ecos_gui] Session saved to {SESSION_FILE}")
        except Exception as e:
            QMessageBox.warning(self, "Save error", str(e))

    def _load_session_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Session", os.path.dirname(SESSION_FILE), "JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path) as f:
                self._restore_session(json.load(f))
            self._apply_restored_hw()
        except Exception as e:
            QMessageBox.warning(self, "Load error", str(e))

    def _apply_restored_hw(self):
        try:
            g1 = int(self._txt_gain_ch1.text())
            g2 = int(self._txt_gain_ch2.text())
            self._sedaq.SetGain1(g1)
            self._sedaq.SetGain2(g2)
        except Exception:
            pass
        try:
            self._sedaq.SetExtVoltage(int(self._txt_voltage.text()))
        except Exception:
            pass
        try:
            reclen = int(self._txt_reclen.text())
            self._reclen = reclen
            self._sedaq.SetRecLen(reclen)
        except Exception:
            pass
        self._generate_upload()

    # ==========================================================================
    #  Window close
    # ==========================================================================
    def closeEvent(self, event):
        self._timer.stop()
        try:
            with open(SESSION_FILE, 'w') as f:
                json.dump(self._collect_session(), f, indent=2)
        except Exception:
            pass
        if not self._demo:
            try:
                self._sedaq.Close()
            except Exception:
                pass
        event.accept()

    # ==========================================================================
    #  Left panel — live plots
    # ==========================================================================
    def _build_left_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Channel visibility + x-axis unit row
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Show:"))
        self._chk_ch1 = QCheckBox("Ch1 (TT)")
        self._chk_ch2 = QCheckBox("Ch2 (PE)")
        self._chk_ch1.setChecked(True)
        self._chk_ch2.setChecked(True)
        self._chk_ch1.toggled.connect(self._toggle_ch1_vis)
        self._chk_ch2.toggled.connect(self._toggle_ch2_vis)
        top_row.addWidget(self._chk_ch1)
        top_row.addWidget(self._chk_ch2)

        top_row.addSpacing(20)
        top_row.addWidget(QLabel("X-axis:"))
        self._radio_samples = QRadioButton("samples")
        self._radio_mus     = QRadioButton("µs")
        self._radio_mm      = QRadioButton("mm")
        self._radio_samples.setChecked(True)
        self._unit_grp = QButtonGroup()
        for r in (self._radio_samples, self._radio_mus, self._radio_mm):
            self._unit_grp.addButton(r)
            top_row.addWidget(r)
        self._radio_samples.toggled.connect(lambda c: c and self._on_unit_changed('samples'))
        self._radio_mus.toggled.connect(    lambda c: c and self._on_unit_changed('mus'))
        self._radio_mm.toggled.connect(     lambda c: c and self._on_unit_changed('mm'))
        top_row.addStretch()
        layout.addLayout(top_row)

        # Zoom plot
        self._plot_zoom = pg.PlotWidget(title="Live A-scan — zoom region")
        self._plot_zoom.setLabel('left', 'Amplitude', units='a.u.')
        self._plot_zoom.getAxis('left').enableAutoSIPrefix(False)
        self._plot_zoom.setLabel('bottom', 'Sample')
        self._plot_zoom.showGrid(x=True, y=True, alpha=0.3)
        self._plot_zoom.enableAutoRange(axis='y', enable=False)
        self._plot_zoom.setYRange(SIGNAL_YMIN, SIGNAL_YMAX, padding=0)
        self._plot_zoom.enableAutoRange(axis='x', enable=False)
        self._plot_zoom.getViewBox().setMouseEnabled(x=False, y=False)

        self._curve_zoom_ch1 = self._plot_zoom.plot(pen=pg.mkPen('r', width=1), name="Ch1 (TT)")
        self._curve_zoom_ch2 = self._plot_zoom.plot(pen=pg.mkPen('y', width=1), name="Ch2 (PE)")

        # Inspection-mode curves (windowing preview)
        self._curve_insp_wp  = self._plot_zoom.plot(pen=pg.mkPen('c',            width=1), name="WP")
        self._curve_insp_tt  = self._plot_zoom.plot(pen=pg.mkPen((255, 165, 0),  width=1), name="TT")
        self._curve_insp_pe  = self._plot_zoom.plot(pen=pg.mkPen('m',            width=1), name="PE")
        self._curve_insp_win = self._plot_zoom.plot(
            pen=pg.mkPen('w', width=1, style=Qt.DashLine), name="Window")
        for _c in (self._curve_insp_wp, self._curve_insp_tt,
                   self._curve_insp_pe, self._curve_insp_win):
            _c.hide()

        # Hover cursor
        self._vline_cursor = pg.InfiniteLine(angle=90, movable=False, pen='w')
        self._vline_cursor.setVisible(False)
        self._plot_zoom.addItem(self._vline_cursor)
        self._cursor_label = pg.TextItem(anchor=(0, 1), color=(255, 255, 255))
        self._plot_zoom.addItem(self._cursor_label)
        self._cursor_label.hide()
        self._plot_zoom.scene().sigMouseMoved.connect(self._on_mouse_moved)

        layout.addWidget(self._plot_zoom, stretch=3)

        # Overview plot
        self._plot_ov = pg.PlotWidget(title="Overview — full record")
        self._plot_ov.setLabel('bottom', 'Sample')
        self._plot_ov.setMaximumHeight(160)
        self._plot_ov.setYRange(SIGNAL_YMIN, SIGNAL_YMAX, padding=0)
        self._plot_ov.setXRange(0, self._reclen - 1, padding=0)
        self._plot_ov.setLimits(xMin=0, xMax=self._reclen - 1,
                                yMin=SIGNAL_YMIN, yMax=SIGNAL_YMAX)
        self._plot_ov.getViewBox().setMouseEnabled(x=False, y=False)

        self._curve_ov_ch1 = self._plot_ov.plot(pen=pg.mkPen('r', width=1))
        self._curve_ov_ch2 = self._plot_ov.plot(pen=pg.mkPen('y', width=1))

        self._region = pg.LinearRegionItem(
            values=[0, self._reclen // 4],
            bounds=[0, self._reclen]
        )
        self._region.setZValue(10)
        self._plot_ov.addItem(self._region)

        self._region.sigRegionChanged.connect(self._on_region_changed)
        self._plot_zoom.sigXRangeChanged.connect(self._on_zoom_xrange_changed)

        layout.addWidget(self._plot_ov, stretch=1)
        return widget

    # ==========================================================================
    #  Right panel — scrollable control blocks
    # ==========================================================================
    def _build_right_panel(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        layout.addWidget(self._build_block_pulser())
        layout.addWidget(self._build_block_temperature())
        layout.addWidget(self._build_block_acquisition())
        layout.addWidget(self._build_block_windowing())
        layout.addWidget(self._build_block_results())
        layout.addWidget(self._build_block_descriptor())
        layout.addWidget(self._build_block_save())
        layout.addStretch()
        return scroll

    # ==========================================================================
    #  Block 1 — Pulser Control
    # ==========================================================================
    def _build_block_pulser(self):
        box = QGroupBox("Pulser Control")
        form = QFormLayout(box)

        self._txt_gain_ch1 = QLineEdit(str(DEFAULT_GAIN_CH1))
        self._txt_gain_ch2 = QLineEdit(str(DEFAULT_GAIN_CH2))
        self._txt_voltage  = QLineEdit(str(DEFAULT_VOLTAGE))
        self._txt_reclen   = QLineEdit(str(DEFAULT_RECLEN))

        self._txt_gain_ch1.editingFinished.connect(self._on_gain_changed)
        self._txt_gain_ch2.editingFinished.connect(self._on_gain_changed)
        self._txt_voltage.editingFinished.connect(self._on_voltage_changed)
        self._txt_reclen.editingFinished.connect(self._on_reclen_changed)

        self._btn_relay = QPushButton("RELAY: OFF")
        self._btn_relay.setCheckable(True)
        self._btn_relay.setChecked(False)
        self._btn_relay.toggled.connect(self._on_relay_toggled)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Excitation:"))
        self._cmb_excitation = QComboBox()
        self._cmb_excitation.addItems(["Pulse", "Chirp", "Burst"])
        self._cmb_excitation.currentIndexChanged.connect(
            lambda i: self._stack.setCurrentIndex(i)
        )
        type_row.addWidget(self._cmb_excitation)

        self._txt_gen_fs = QLineEdit(str(DEFAULT_GEN_FS))

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(
            self._stack.sizePolicy().horizontalPolicy(),
            QSizePolicy.Minimum
        )
        self._stack.addWidget(self._build_pulse_page())
        self._stack.addWidget(self._build_chirp_page())
        self._stack.addWidget(self._build_burst_page())

        btn_gen = QPushButton("Generate && Upload")
        btn_gen.setStyleSheet("font-weight: bold;")
        btn_gen.clicked.connect(self._generate_upload)

        form.addRow("Gain Ch1 (dB):", self._txt_gain_ch1)
        form.addRow("Gain Ch2 (dB):", self._txt_gain_ch2)
        form.addRow("Voltage:",        self._txt_voltage)
        form.addRow("RecLen:",         self._txt_reclen)
        form.addRow("",                self._btn_relay)
        form.addRow(type_row)
        form.addRow("Generator Fs:",   self._txt_gen_fs)
        form.addRow(self._stack)
        form.addRow("",                btn_gen)
        return box

    def _build_pulse_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self._cmb_pulse_param    = QComboBox()
        self._cmb_pulse_param.addItems(["frequency", "duration", "samples"])
        self._txt_pulse_paramval = QLineEdit(str(DEFAULT_FP))
        self._cmb_pulse_polarity = QComboBox()
        self._cmb_pulse_polarity.addItems(["2 (bipolar)", "1 (positive)", "-1 (negative)"])
        form.addRow("Param:",    self._cmb_pulse_param)
        form.addRow("ParamVal:", self._txt_pulse_paramval)
        form.addRow("Polarity:", self._cmb_pulse_polarity)
        return page

    def _build_chirp_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self._txt_chirp_fstart   = QLineEdit("2e6")
        self._txt_chirp_fend     = QLineEdit("15e6")
        self._txt_chirp_dur      = QLineEdit("3e-6")
        self._cmb_chirp_method   = QComboBox()
        self._cmb_chirp_method.addItems(["linear", "quadratic", "logarithmic", "hyperbolic"])
        self._txt_chirp_phase    = QLineEdit("270")
        self._cmb_chirp_polarity = QComboBox()
        self._cmb_chirp_polarity.addItems(["2 (bipolar)", "1 (positive)", "-1 (negative)"])
        form.addRow("Fstart (Hz):",  self._txt_chirp_fstart)
        form.addRow("Fend (Hz):",    self._txt_chirp_fend)
        form.addRow("Duration (s):", self._txt_chirp_dur)
        form.addRow("Method:",       self._cmb_chirp_method)
        form.addRow("Phase (deg):",  self._txt_chirp_phase)
        form.addRow("Polarity:",     self._cmb_chirp_polarity)
        return page

    def _build_burst_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self._txt_burst_fo       = QLineEdit("10e6")
        self._txt_burst_cycles   = QLineEdit("5")
        self._cmb_burst_polarity = QComboBox()
        self._cmb_burst_polarity.addItems(["2 (bipolar)", "1 (positive)", "-1 (negative)"])
        form.addRow("Fo (Hz):",  self._txt_burst_fo)
        form.addRow("NoCycles:", self._txt_burst_cycles)
        form.addRow("Polarity:", self._cmb_burst_polarity)
        return page

    # ==========================================================================
    #  Block 2 — Temperature
    # ==========================================================================
    def _build_block_temperature(self):
        box = QGroupBox("Temperature")
        layout = QVBoxLayout(box)

        form = QFormLayout()
        self._txt_arduino_port = QLineEdit(DEFAULT_COM)
        form.addRow("Arduino COM:", self._txt_arduino_port)
        layout.addLayout(form)

        btn_read = QPushButton("Read from Arduino")
        btn_read.clicked.connect(self._on_read_arduino)
        layout.addWidget(btn_read)

        self._lbl_temp = QLabel("T1: — °C   T2: — °C   Cw1: — m/s   Cw2: — m/s")
        layout.addWidget(self._lbl_temp)
        return box

    # ==========================================================================
    #  Block 3 — Signal Acquisition
    # ==========================================================================
    def _build_block_acquisition(self):
        box = QGroupBox("Signal Acquisition")
        layout = QVBoxLayout(box)

        # Acquisition window fields
        win_row = QHBoxLayout()
        win_row.addWidget(QLabel("Smin:"))
        self._txt_smin = QLineEdit("0")
        self._txt_smin.setFixedWidth(72)
        win_row.addWidget(self._txt_smin)
        win_row.addWidget(QLabel("Smax:"))
        self._txt_smax = QLineEdit(str(self._reclen // 4))
        self._txt_smax.setFixedWidth(72)
        win_row.addWidget(self._txt_smax)
        win_row.addStretch()
        self._txt_smin.editingFinished.connect(self._on_smin_smax_edited)
        self._txt_smax.editingFinished.connect(self._on_smin_smax_edited)
        layout.addLayout(win_row)

        # Acquisition buttons
        self._btn_pett = QPushButton("Acquire s_PE + s_TT  (sample, 0°)")
        self._btn_pett.clicked.connect(self._on_acquire_pett)
        layout.addWidget(self._btn_pett)

        self._btn_wp = QPushButton("Acquire s_W  (WaterPath)")
        self._btn_wp.clicked.connect(self._on_acquire_wp)
        layout.addWidget(self._btn_wp)

        # Angular / shear — disabled in this phase
        ang_row = QHBoxLayout()
        self._btn_sh = QPushButton("Acquire s_G  (Angular / Shear)")
        self._btn_sh.setEnabled(False)
        self._btn_sh.setToolTip(
            "Not used in this phase — implement for future shear velocity measurement."
        )
        self._spn_theta = QDoubleSpinBox()
        self._spn_theta.setRange(0.0, 90.0)
        self._spn_theta.setValue(0.0)
        self._spn_theta.setSuffix(" °")
        self._spn_theta.setFixedWidth(80)
        self._spn_theta.setEnabled(False)
        ang_row.addWidget(self._btn_sh)
        ang_row.addWidget(QLabel("θ_i:"))
        ang_row.addWidget(self._spn_theta)
        layout.addLayout(ang_row)

        lbl_note = QLabel("(s_G disabled — future shear velocity measurement)")
        lbl_note.setStyleSheet("color: gray; font-style: italic; font-size: 10px;")
        layout.addWidget(lbl_note)

        self._lbl_acq_status = QLabel("Status: no signals acquired")
        layout.addWidget(self._lbl_acq_status)
        return box

    # ==========================================================================
    #  Block 4 — Windowing
    # ==========================================================================
    def _build_block_windowing(self):
        box = QGroupBox("Windowing")
        layout = QVBoxLayout(box)

        form = QFormLayout()
        self._txt_win_len = QLineEdit(str(DEFAULT_WIN_LEN))
        form.addRow("Window length (samples):", self._txt_win_len)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self._btn_preview = QPushButton("Preview window")
        self._btn_apply   = QPushButton("Apply window")
        self._btn_live    = QPushButton("Back to live")
        self._btn_preview.clicked.connect(self._on_preview_window)
        self._btn_apply.clicked.connect(self._on_apply_window)
        self._btn_live.clicked.connect(self._on_back_to_live)
        btn_row.addWidget(self._btn_preview)
        btn_row.addWidget(self._btn_apply)
        btn_row.addWidget(self._btn_live)
        layout.addLayout(btn_row)
        return box

    # ==========================================================================
    #  Block 5 — Results
    # ==========================================================================
    def _build_block_results(self):
        box = QGroupBox("Results")
        form = QFormLayout(box)

        self._lbl_res_cw = QLabel("—")
        self._lbl_res_t1 = QLabel("—")
        self._lbl_res_t2 = QLabel("—")
        self._lbl_res_cl = QLabel("—")
        self._lbl_res_d  = QLabel("—")

        form.addRow("Cw [m/s]:", self._lbl_res_cw)
        form.addRow("T1 [°C]:",  self._lbl_res_t1)
        form.addRow("T2 [°C]:",  self._lbl_res_t2)
        form.addRow("Cl [m/s]:", self._lbl_res_cl)
        form.addRow("d [mm]:",   self._lbl_res_d)
        return box

    # ==========================================================================
    #  Block 6 — Sample Descriptor
    # ==========================================================================
    def _build_block_descriptor(self):
        box = QGroupBox("Sample Descriptor")
        form = QFormLayout(box)

        self._txt_sample_id    = QLineEdit("")
        self._txt_pva_pct      = QLineEdit("")
        self._txt_additive     = QLineEdit("")
        self._txt_additive_pct = QLineEdit("")
        self._txt_cycles       = QLineEdit("")
        self._txt_fab_date     = QLineEdit("")
        self._txt_dopants      = QLineEdit("")
        self._txt_notes        = QLineEdit("")

        for w in (self._txt_sample_id, self._txt_pva_pct, self._txt_additive_pct,
                  self._txt_cycles):
            w.textChanged.connect(self._update_exp_name)

        form.addRow("Sample ID:",              self._txt_sample_id)
        form.addRow("PVA [%]:",                self._txt_pva_pct)
        form.addRow("Additive:",               self._txt_additive)
        form.addRow("Additive [%]:",           self._txt_additive_pct)
        form.addRow("Cycles:",                 self._txt_cycles)
        form.addRow("Fab. date (DD/MM/YYYY):", self._txt_fab_date)
        form.addRow("Dopants:",                self._txt_dopants)
        form.addRow("Notes:",                  self._txt_notes)
        return box

    # ==========================================================================
    #  Block 7 — Save
    # ==========================================================================
    def _build_block_save(self):
        box = QGroupBox("Save")
        layout = QVBoxLayout(box)

        form = QFormLayout()
        self._txt_exp_name = QLineEdit("")
        form.addRow("Experiment name:", self._txt_exp_name)
        layout.addLayout(form)

        self._btn_save = QPushButton("Compute && Save")
        self._btn_save.setStyleSheet("font-weight: bold;")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_compute_save)
        layout.addWidget(self._btn_save)

        self._lbl_save_status = QLabel("")
        layout.addWidget(self._lbl_save_status)
        return box

    # ==========================================================================
    #  [6] Unit conversion helpers
    # ==========================================================================
    def _samples_to_unit(self, n):
        cw = self._state.Cw_mean or 1480.0
        if self._unit == 'mus':
            return np.asarray(n, dtype=float) / DEFAULT_ACQ_FS * 1e6
        elif self._unit == 'mm':
            return np.asarray(n, dtype=float) / DEFAULT_ACQ_FS * cw / 2.0 * 1e3
        return np.asarray(n, dtype=float)

    def _unit_to_samples(self, val):
        cw = self._state.Cw_mean or 1480.0
        if self._unit == 'mus':
            return int(round(float(val) * 1e-6 * DEFAULT_ACQ_FS))
        elif self._unit == 'mm':
            return int(round(float(val) * 2.0 / (cw * 1e-3) * DEFAULT_ACQ_FS))
        return int(round(float(val)))

    def _unit_label(self):
        return {'samples': 'Sample', 'mus': 'Time [µs]', 'mm': 'Distance [mm]'}[self._unit]

    def _on_unit_changed(self, unit):
        self._unit = unit
        self._plot_zoom.setLabel('bottom', self._unit_label())
        self._plot_ov.setLabel('bottom', self._unit_label())

    # ==========================================================================
    #  Real-time plot update
    # ==========================================================================
    def _update_plots(self):
        if not self._running or self._inspection_mode:
            return
        try:
            quant = 1024
            self._sedaq.GetAScan()
            ch1 = self._raw_to_float(self._sedaq.DataADC1, self._reclen, quant)
            ch2 = self._raw_to_float(self._sedaq.DataADC2, self._reclen, quant)

            rmin, rmax = self._region.getRegion()
            smin = max(0, int(rmin))
            smax = min(self._reclen, int(rmax))

            x_full = self._samples_to_unit(np.arange(self._reclen))
            x_zoom = self._samples_to_unit(np.arange(smin, smax))

            if self._chk_ch1.isChecked():
                self._curve_ov_ch1.setData(x_full, ch1)
                if smax > smin:
                    self._curve_zoom_ch1.setData(x_zoom, ch1[smin:smax])
            else:
                self._curve_ov_ch1.setData([], [])
                self._curve_zoom_ch1.setData([], [])

            if self._chk_ch2.isChecked():
                self._curve_ov_ch2.setData(x_full, ch2)
                if smax > smin:
                    self._curve_zoom_ch2.setData(x_zoom, ch2[smin:smax])
            else:
                self._curve_ov_ch2.setData([], [])
                self._curve_zoom_ch2.setData([], [])

            if smax > smin:
                self._plot_zoom.setXRange(
                    self._samples_to_unit(smin),
                    self._samples_to_unit(smax), padding=0
                )
        except Exception as e:
            print(f"[_update_plots] {e}")

    @staticmethod
    def _raw_to_float(buf, reclen, quant):
        arr = np.array(list(buf[:reclen]), dtype=float)
        arr = (arr - quant / 2.0) / quant
        arr -= arr.mean()
        return arr

    # ==========================================================================
    #  Region / zoom synchronisation
    # ==========================================================================
    def _on_region_changed(self):
        rmin, rmax = self._region.getRegion()
        smin = max(0, int(rmin))
        smax = min(self._reclen, int(rmax))
        self._txt_smin.setText(str(smin))
        self._txt_smax.setText(str(smax))
        if not self._syncing:
            self._syncing = True
            self._plot_zoom.setXRange(
                self._samples_to_unit(smin), self._samples_to_unit(smax), padding=0
            )
            self._syncing = False

    def _on_zoom_xrange_changed(self, _vb, x_range):
        if self._syncing or self._inspection_mode:
            return
        self._syncing = True
        smin = max(0, self._unit_to_samples(x_range[0]))
        smax = min(self._reclen, self._unit_to_samples(x_range[1]))
        self._region.setRegion([smin, smax])
        self._syncing = False

    def _on_smin_smax_edited(self):
        try:
            smin = max(0, int(self._txt_smin.text()))
            smax = min(self._reclen, int(self._txt_smax.text()))
            self._region.setRegion([smin, smax])
        except ValueError:
            pass

    def _toggle_ch1_vis(self, checked):
        if not checked:
            self._curve_zoom_ch1.setData([], [])
            self._curve_ov_ch1.setData([], [])

    def _toggle_ch2_vis(self, checked):
        if not checked:
            self._curve_zoom_ch2.setData([], [])
            self._curve_ov_ch2.setData([], [])

    # ==========================================================================
    #  Hover cursor
    # ==========================================================================
    def _on_mouse_moved(self, pos):
        vb = self._plot_zoom.getViewBox()
        if not self._plot_zoom.sceneBoundingRect().contains(pos):
            self._vline_cursor.setVisible(False)
            self._cursor_label.hide()
            return
        mp  = vb.mapSceneToView(pos)
        x   = mp.x()
        self._vline_cursor.setPos(x)
        self._vline_cursor.setVisible(True)

        xs, ys = self._curve_zoom_ch2.getData()
        if xs is None or len(xs) == 0:
            xs, ys = self._curve_zoom_ch1.getData()
        val = "---"
        if xs is not None and len(xs) > 0:
            i   = int(np.clip(np.searchsorted(xs, x), 0, len(ys) - 1))
            val = f"{ys[i]:.4f}"

        coord = {'samples': f"s = {int(x)}",
                 'mus':     f"t = {x:.2f} µs",
                 'mm':      f"d = {x:.2f} mm"}[self._unit]
        self._cursor_label.setPos(x, mp.y())
        self._cursor_label.setText(f"{coord}\nAmp: {val}")
        self._cursor_label.show()

    # ==========================================================================
    #  RecLen change
    # ==========================================================================
    def _on_reclen_changed(self):
        try:
            reclen = int(self._txt_reclen.text())
            if reclen <= 0:
                raise ValueError("RecLen must be positive")
        except ValueError as e:
            QMessageBox.warning(self, "Input error", str(e))
            self._txt_reclen.setText(str(self._reclen))
            return
        self._reclen = reclen
        try:
            self._sedaq.SetRecLen(reclen)
        except Exception as e:
            print(f"[SetRecLen] {e}")
        self._plot_ov.setXRange(0, reclen - 1, padding=0)
        self._plot_ov.setLimits(xMin=0, xMax=reclen - 1)
        self._region.setBounds([0, reclen])
        rmin, rmax = self._region.getRegion()
        self._region.setRegion([max(0, rmin), min(reclen, rmax)])

    # ==========================================================================
    #  Relay
    # ==========================================================================
    def _on_relay_toggled(self, checked):
        self._btn_relay.setText(f"RELAY: {'ON' if checked else 'OFF'}")
        try:
            self._sedaq.SetRelay(0 if checked else 1)
        except Exception as e:
            print(f"[Relay] {e}")

    # ==========================================================================
    #  Gain / voltage
    # ==========================================================================
    def _on_gain_changed(self):
        try:
            g1 = int(float(self._txt_gain_ch1.text()))
            g2 = int(float(self._txt_gain_ch2.text()))
            # FIRMWARE BUG: Ch1 must always be set before Ch2
            self._sedaq.SetGain1(g1)
            self._sedaq.SetGain2(g2)
            self._state.Gain_Ch1 = g1
            self._state.Gain_Ch2 = g2
        except Exception as e:
            print(f"[Gain] {e}")

    def _on_voltage_changed(self):
        try:
            self._sedaq.SetExtVoltage(int(float(self._txt_voltage.text())))
        except Exception as e:
            print(f"[Voltage] {e}")

    # ==========================================================================
    #  Excitation / GenCode
    # ==========================================================================
    def _generate_upload(self):
        if not _HW_AVAILABLE:
            self._sedaq.UpdateGenCode([0] * 64)
            return
        try:
            exc    = self._cmb_excitation.currentText()
            gen_fs = float(self._txt_gen_fs.text())
            params = self._collect_excitation_params()
            if exc == "Pulse":
                gencode = MakeGenCode(
                    Excitation='Pulse',
                    Param=params["param"],
                    ParamVal=params["paramval"],
                    SignalPolarity=params["polarity"],
                    Fs=gen_fs,
                )
            elif exc == "Chirp":
                gencode = MakeGenCode(
                    Excitation='Chirp',
                    ParamVal=[params["fstart"], params["fend"],
                               params["duration"], params["method"], params["phase"]],
                    SignalPolarity=params["polarity"],
                    Fs=gen_fs,
                )
            else:
                gencode = MakeGenCode(
                    Excitation='Burst',
                    ParamVal=[params["fo"], params["nocycles"]],
                    SignalPolarity=params["polarity"],
                    Fs=gen_fs,
                )
            self._sedaq.UpdateGenCode(gencode)
            QMessageBox.information(self, "GenCode", "Waveform generated and uploaded.")
        except Exception as e:
            QMessageBox.critical(self, "GenCode error", str(e))

    def _collect_excitation_params(self):
        exc = self._cmb_excitation.currentText()

        def _pol(cmb):
            return int(cmb.currentText().split()[0])

        if exc == "Pulse":
            return {
                "param":    self._cmb_pulse_param.currentText(),
                "paramval": float(self._txt_pulse_paramval.text()),
                "polarity": _pol(self._cmb_pulse_polarity),
            }
        elif exc == "Chirp":
            return {
                "fstart":   float(self._txt_chirp_fstart.text()),
                "fend":     float(self._txt_chirp_fend.text()),
                "duration": float(self._txt_chirp_dur.text()),
                "method":   self._cmb_chirp_method.currentText(),
                "phase":    float(self._txt_chirp_phase.text()),
                "polarity": _pol(self._cmb_chirp_polarity),
            }
        else:
            return {
                "fo":       float(self._txt_burst_fo.text()),
                "nocycles": int(self._txt_burst_cycles.text()),
                "polarity": _pol(self._cmb_burst_polarity),
            }

    # ==========================================================================
    #  Temperature
    # ==========================================================================
    def _on_read_arduino(self):
        self._read_temperature()

    def _read_temperature(self):
        """Read temperature from Arduino. On failure, shows manual-entry dialog."""
        if not _HW_AVAILABLE:
            T = 20.0
            cw = self._approx_cw(T)
            self._state.T1 = self._state.T2 = T
            self._state.Cw1 = self._state.Cw2 = self._state.Cw_mean = cw
            self._update_temp_label()
            return True

        port = self._txt_arduino_port.text().strip()
        try:
            arduino = Arduino(port=port, baudrate=115200, N_avg=3)
            T1, T2  = arduino.getTemperatures()
            arduino.close()
            if T1 is None and T2 is None:
                raise ValueError("No temperature data received from Arduino")
            T1 = T1 if T1 is not None else T2
            T2 = T2 if T2 is not None else T1
            Cw1 = water_temp2sos(T1)
            Cw2 = water_temp2sos(T2)
            self._state.T1, self._state.T2   = T1, T2
            self._state.Cw1, self._state.Cw2 = Cw1, Cw2
            self._state.Cw_mean = (Cw1 + Cw2) / 2.0
            self._update_temp_label()
            return True
        except Exception as e:
            print(f"[Arduino] {e}")
            return self._ask_manual_temperature()

    def _ask_manual_temperature(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Temperature — Manual Entry")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            "Arduino did not respond (serial error or timeout).\n"
            "Enter water temperature manually [°C]:"
        ))
        txt = QLineEdit("20.0")
        layout.addWidget(txt)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec_() != QDialog.Accepted:
            return False
        try:
            T = float(txt.text())
        except ValueError:
            T = 20.0
        cw = self._approx_cw(T)
        self._state.T1 = self._state.T2 = T
        self._state.Cw1 = self._state.Cw2 = self._state.Cw_mean = cw
        self._lbl_temp.setText(f"Manual: T = {T:.1f} °C   Cw = {cw:.1f} m/s")
        return True

    def _update_temp_label(self):
        s = self._state
        if s.T1 is None:
            self._lbl_temp.setText("T1: — °C   T2: — °C   Cw1: — m/s   Cw2: — m/s")
        else:
            self._lbl_temp.setText(
                f"T1: {s.T1:.2f} °C   T2: {s.T2:.2f} °C   "
                f"Cw1: {s.Cw1:.1f} m/s   Cw2: {s.Cw2:.1f} m/s"
            )

    @staticmethod
    def _approx_cw(T):
        return 1402.7 + 4.88 * T - 0.0482 * T ** 2

    # ==========================================================================
    #  Averaged acquisition helpers
    # ==========================================================================
    def _get_smin_smax(self):
        rmin, rmax = self._region.getRegion()
        return max(0, int(rmin)), min(self._reclen, int(rmax))

    def _acquire_ch_avg(self, channel, smin, smax):
        """Average AVG_N A-scans from channel 1 or 2 and return the windowed slice."""
        quant = 1024
        acc   = np.zeros(self._reclen)
        n     = 0
        while n < AVG_N:
            self._sedaq.GetAScan()
            if channel == 1:
                sig = self._raw_to_float(self._sedaq.DataADC1, self._reclen, quant)
            else:
                sig = self._raw_to_float(self._sedaq.DataADC2, self._reclen, quant)
            if not np.all(sig == 0.0):
                acc += sig
                n   += 1
        return (acc / AVG_N)[smin:smax]

    # ==========================================================================
    #  Acquisition buttons
    # ==========================================================================
    def _on_acquire_pett(self):
        self._timer.stop()
        try:
            if not self._read_temperature():
                return
            smin, smax = self._get_smin_smax()
            self._state.PE_Ascan = self._acquire_ch_avg(2, smin, smax)
            self._state.TT_Ascan = self._acquire_ch_avg(1, smin, smax)
            self._state.Smin, self._state.Smax = smin, smax
            self._lbl_acq_status.setText("s_PE + s_TT acquired ✓")
            self._update_save_button()
        except Exception as e:
            QMessageBox.critical(self, "Acquisition error", str(e))
        finally:
            self._timer.start(REALTIME_INTERVAL)

    def _on_acquire_wp(self):
        self._timer.stop()
        try:
            if not self._read_temperature():
                return
            smin, smax = self._get_smin_smax()
            self._state.WP_Ascan = self._acquire_ch_avg(1, smin, smax)
            self._state.Smin, self._state.Smax = smin, smax
            self._lbl_acq_status.setText("s_W acquired ✓")
            self._update_save_button()
        except Exception as e:
            QMessageBox.critical(self, "Acquisition error", str(e))
        finally:
            self._timer.start(REALTIME_INTERVAL)

    # ==========================================================================
    #  Windowing
    # ==========================================================================
    def _get_win_len(self):
        try:
            return max(1, int(self._txt_win_len.text()))
        except ValueError:
            return DEFAULT_WIN_LEN

    def _make_window(self, sig, win_len):
        """Return a Tukey window centered on the envelope peak of sig."""
        if _HW_AVAILABLE:
            env   = Envelope(sig)
            peak  = int(np.argmax(env))
            delay = peak - win_len // 2
            win   = MakeWindow('Tukey', WinLen=win_len, param1=0.2, param2=1,
                                Span=len(sig), Delay=delay)
        else:
            n     = len(sig)
            peak  = n // 2
            delay = peak - win_len // 2
            win   = np.zeros(n)
            start, end = max(0, delay), min(n, delay + win_len)
            win[start:end] = 1.0
        return win

    def _on_preview_window(self):
        st = self._state
        if any(x is None for x in (st.WP_Ascan, st.TT_Ascan, st.PE_Ascan)):
            QMessageBox.warning(self, "Preview window",
                                "Acquire WP, PE, and TT signals first.")
            return

        import matplotlib.pyplot as plt

        win_len = self._get_win_len()
        self._timer.stop()
        try:
            fig, axes = plt.subplots(3, 1, figsize=(10, 7), sharex=False)
            fig.suptitle("Windowing preview — close to continue", fontsize=11)

            for ax, sig, label in zip(
                axes,
                [st.WP_Ascan, st.TT_Ascan, st.PE_Ascan],
                ["s_W  (WaterPath, Ch1)",
                 "s_TT  (Through-transmission, Ch1)",
                 "s_PE  (Pulse-echo, Ch2)"],
            ):
                win   = self._make_window(sig, win_len)
                t     = np.arange(len(sig))
                norm  = np.max(np.abs(sig)) or 1.0
                ax.plot(t, sig / norm, label="Signal (normalised)",
                        color='steelblue', lw=1)
                ax.plot(t, win / (np.max(win) or 1.0), label="Tukey window",
                        color='orange', lw=1.5, linestyle='--')
                ax.set_title(label, fontsize=9)
                ax.legend(fontsize=8)
                ax.set_xlabel("Samples")
                ax.set_ylabel("Amplitude")
                ax.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.show(block=True)
        finally:
            self._timer.start(REALTIME_INTERVAL)

    def _on_apply_window(self):
        st = self._state
        if any(x is None for x in (st.WP_Ascan, st.TT_Ascan, st.PE_Ascan)):
            QMessageBox.warning(self, "Apply window",
                                "Acquire WP, PE, and TT signals first.")
            return

        win_len = self._get_win_len()
        for attr_raw, attr_win in (
            ('TT_Ascan', 'TT_Ascan_win'),
            ('PE_Ascan', 'PE_Ascan_win'),
            ('WP_Ascan', 'WP_Ascan_win'),
        ):
            sig = getattr(st, attr_raw)
            win = self._make_window(sig, win_len)
            setattr(st, attr_win, sig * win)

        print(f"[ecos_gui] Window applied — length: {win_len} samples.")
        self._compute_results()
        self._update_save_button()

    def _on_back_to_live(self):
        self._inspection_mode = False
        self._plot_zoom.setTitle("Live A-scan — zoom region")
        for c in (self._curve_insp_wp, self._curve_insp_tt,
                  self._curve_insp_pe, self._curve_insp_win):
            c.setData([], [])
            c.hide()
        if not self._timer.isActive():
            self._timer.start(REALTIME_INTERVAL)

    # ==========================================================================
    #  [7] Results computation
    # ==========================================================================
    def _compute_results(self):
        st = self._state
        if any(x is None for x in (st.TT_Ascan_win, st.WP_Ascan_win,
                                       st.PE_Ascan_win, st.Cw_mean)):
            return
        try:
            if _HW_AVAILABLE:
                Cl, L = LongVelocity_Thickness(
                    st.PE_Ascan,
                    st.TT_Ascan_win,
                    st.WP_Ascan_win,
                    st.PE_Ascan_win,
                    DEFAULT_ACQ_FS,
                    st.Cw_mean,
                    UseHilbEnv=True,
                )
            else:
                Cl, L = 1540.0, 0.010

            self._Cl = Cl
            self._L  = L

            self._lbl_res_cw.setText(f"{st.Cw_mean:.2f}")
            self._lbl_res_t1.setText(f"{st.T1:.2f}" if st.T1 is not None else "—")
            self._lbl_res_t2.setText(f"{st.T2:.2f}" if st.T2 is not None else "—")
            self._lbl_res_cl.setText(f"{Cl:.2f}")
            self._lbl_res_d.setText(f"{L * 1e3:.3f}")
            print(f"[ecos_gui] Cl = {Cl:.2f} m/s   d = {L * 1e3:.3f} mm")
        except Exception as e:
            QMessageBox.critical(self, "Computation error", str(e))

    # ==========================================================================
    #  Save button state
    # ==========================================================================
    def _update_save_button(self):
        st    = self._state
        ready = (st.WP_Ascan is not None and
                 st.PE_Ascan is not None and
                 st.TT_Ascan is not None and
                 st.WP_Ascan_win is not None)
        self._btn_save.setEnabled(ready)

    # ==========================================================================
    #  Experiment name auto-generation
    # ==========================================================================
    def _update_exp_name(self):
        pva   = self._txt_pva_pct.text().strip()
        add   = self._txt_additive_pct.text().strip()
        sid   = self._txt_sample_id.text().strip()
        cyc   = self._txt_cycles.text().strip()
        letra = sid[-1].upper() if sid else "X"
        pva   = pva.zfill(2) if pva.isdigit() else "XX"
        add   = add.zfill(2) if add.isdigit() else "YY"
        cyc   = cyc.zfill(3) if cyc.isdigit() else "NNN"
        ts    = time.strftime("%Y%m%d_%H%M%S")
        self._txt_exp_name.setText(f"PVA_{pva}_PG_{add}_{letra}_C{cyc}_US_{ts}")

    # ==========================================================================
    #  [8] Compute & Save
    # ==========================================================================
    def _on_compute_save(self):
        if self._Cl is None:
            QMessageBox.warning(self, "Save", "Apply window first to compute results.")
            return

        st = self._state
        try:
            win_len = self._get_win_len()
        except Exception:
            win_len = DEFAULT_WIN_LEN

        specimen = {
            "fecha_fabricacion":   self._txt_fab_date.text(),
            "base":                "agua",
            "porcentaje_pva":      self._txt_pva_pct.text(),
            "aditivo1":            self._txt_additive.text(),
            "porcentaje_aditivo1": self._txt_additive_pct.text(),
            "ciclos":              self._txt_cycles.text(),
            "pieza":               self._txt_sample_id.text(),
            "otros":               self._txt_notes.text(),
            "dopantes":            self._txt_dopants.text(),
        }
        equipment1 = {
            "nombre":          "SEDAQ",
            "transductor_pe":  "No enfocado 10MHz",
            "transductor_tt":  "No enfocado 10MHz",
            "params": {
                "Gain_Ch1":        int(float(self._txt_gain_ch1.text())),
                "Gain_Ch2":        int(float(self._txt_gain_ch2.text())),
                "Voltaje":         int(float(self._txt_voltage.text())),
                "Fp":              DEFAULT_FP,
                "F_muestreo":      DEFAULT_ACQ_FS,
                "AvgSamplesNum":   AVG_N,
                "RecLen":          self._reclen,
                "Smin":            st.Smin,
                "Smax":            st.Smax,
                "WindowLen":       win_len,
            },
        }
        equipment2 = {
            "nombre":  "Arduino",
            "puerto":  self._txt_arduino_port.text(),
        }
        protocol = {
            "description": "Ensayo ultrasónico longitudinal ECOS",
            "notes":       self._txt_notes.text(),
        }
        results = {
            "T1":      st.T1,
            "T2":      st.T2,
            "Cw1":     st.Cw1,
            "Cw2":     st.Cw2,
            "Cw_mean": st.Cw_mean,
            "Cl":      self._Cl,
            "d":       self._L,
        }

        exp_name = self._txt_exp_name.text().strip()
        if not exp_name:
            exp_name = "ecos_" + time.strftime("%Y%m%d_%H%M%S")

        try:
            if _HW_AVAILABLE:
                exp_dir = save_experiment_raw_32(
                    specimen=specimen,
                    equipment1=equipment1,
                    equipment2=equipment2,
                    protocol=protocol,
                    results=results,
                    Signal_PE=st.PE_Ascan,
                    Signal_TT=st.TT_Ascan,
                    Signal_Ref=st.WP_Ascan,
                    base_dir="data_32",
                )
                print(f"[ecos_gui] Saved to: {exp_dir}")
                self._lbl_save_status.setText(f"Saved: {os.path.basename(exp_dir)}")
                QMessageBox.information(self, "Saved",
                                        f"Experiment saved to:\n  {exp_dir}")
            else:
                print(f"[ecos_gui] Demo — would save as: {exp_name}")
                self._lbl_save_status.setText(f"Demo: {exp_name}")
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))

    # ==========================================================================
    #  Session collect / restore
    # ==========================================================================
    def _collect_session(self):
        rmin, rmax = self._region.getRegion()
        return {
            "gain_ch1":              self._txt_gain_ch1.text(),
            "gain_ch2":              self._txt_gain_ch2.text(),
            "voltage":               self._txt_voltage.text(),
            "reclen":                self._txt_reclen.text(),
            "relay":                 self._btn_relay.isChecked(),
            "region":                [rmin, rmax],
            "excitation_index":      self._cmb_excitation.currentIndex(),
            "gen_fs":                self._txt_gen_fs.text(),
            "pulse_param_index":     self._cmb_pulse_param.currentIndex(),
            "pulse_paramval":        self._txt_pulse_paramval.text(),
            "pulse_polarity_index":  self._cmb_pulse_polarity.currentIndex(),
            "chirp_fstart":          self._txt_chirp_fstart.text(),
            "chirp_fend":            self._txt_chirp_fend.text(),
            "chirp_dur":             self._txt_chirp_dur.text(),
            "chirp_method_index":    self._cmb_chirp_method.currentIndex(),
            "chirp_phase":           self._txt_chirp_phase.text(),
            "chirp_polarity_index":  self._cmb_chirp_polarity.currentIndex(),
            "burst_fo":              self._txt_burst_fo.text(),
            "burst_cycles":          self._txt_burst_cycles.text(),
            "burst_polarity_index":  self._cmb_burst_polarity.currentIndex(),
            "arduino_port":          self._txt_arduino_port.text(),
            "win_len":               self._txt_win_len.text(),
            "sample_id":             self._txt_sample_id.text(),
            "pva_pct":               self._txt_pva_pct.text(),
            "additive":              self._txt_additive.text(),
            "additive_pct":          self._txt_additive_pct.text(),
            "cycles":                self._txt_cycles.text(),
            "fab_date":              self._txt_fab_date.text(),
            "dopants":               self._txt_dopants.text(),
            "notes":                 self._txt_notes.text(),
            "exp_name":              self._txt_exp_name.text(),
        }

    def _restore_session(self, d):
        self._txt_gain_ch1.setText(d.get("gain_ch1", str(DEFAULT_GAIN_CH1)))
        self._txt_gain_ch2.setText(d.get("gain_ch2", str(DEFAULT_GAIN_CH2)))
        self._txt_voltage.setText(d.get("voltage",   str(DEFAULT_VOLTAGE)))
        self._txt_reclen.setText(d.get("reclen",      str(DEFAULT_RECLEN)))
        self._btn_relay.setChecked(d.get("relay", True))
        region = d.get("region")
        if region:
            self._region.setRegion(region)
        self._cmb_excitation.setCurrentIndex(d.get("excitation_index", 0))
        self._txt_gen_fs.setText(d.get("gen_fs", str(DEFAULT_GEN_FS)))
        self._cmb_pulse_param.setCurrentIndex(d.get("pulse_param_index", 0))
        self._txt_pulse_paramval.setText(d.get("pulse_paramval", str(DEFAULT_FP)))
        self._cmb_pulse_polarity.setCurrentIndex(d.get("pulse_polarity_index", 0))
        self._txt_chirp_fstart.setText(d.get("chirp_fstart", "2e6"))
        self._txt_chirp_fend.setText(d.get("chirp_fend",     "15e6"))
        self._txt_chirp_dur.setText(d.get("chirp_dur",       "3e-6"))
        self._cmb_chirp_method.setCurrentIndex(d.get("chirp_method_index", 0))
        self._txt_chirp_phase.setText(d.get("chirp_phase",   "270"))
        self._cmb_chirp_polarity.setCurrentIndex(d.get("chirp_polarity_index", 0))
        self._txt_burst_fo.setText(d.get("burst_fo",         "10e6"))
        self._txt_burst_cycles.setText(d.get("burst_cycles", "5"))
        self._cmb_burst_polarity.setCurrentIndex(d.get("burst_polarity_index", 0))
        self._txt_arduino_port.setText(d.get("arduino_port", DEFAULT_COM))
        self._txt_win_len.setText(d.get("win_len",            str(DEFAULT_WIN_LEN)))
        self._txt_sample_id.setText(d.get("sample_id",        ""))
        self._txt_pva_pct.setText(d.get("pva_pct",            ""))
        self._txt_additive.setText(d.get("additive",          ""))
        self._txt_additive_pct.setText(d.get("additive_pct",  ""))
        self._txt_cycles.setText(d.get("cycles",              ""))
        self._txt_fab_date.setText(d.get("fab_date",          ""))
        self._txt_dopants.setText(d.get("dopants",            ""))
        self._txt_notes.setText(d.get("notes",                ""))
        self._txt_exp_name.setText(d.get("exp_name",          ""))


# ==============================================================================
# [9] ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = EcosGUI()
    win.show()
    sys.exit(app.exec_())
