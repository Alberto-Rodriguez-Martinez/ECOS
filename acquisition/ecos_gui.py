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
