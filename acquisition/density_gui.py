"""
density_gui.py  —  GUI for Archimedes ultrasonic density measurement
ECOS project · Universidad Miguel Hernández · Dpto. Ingeniería de Comunicaciones
Author: A. Rodríguez-Martínez

Requires (Python 32-bit): PyQt5, pyqtgraph, numpy
Hardware: KTU SeDaq digitizer (SeDaqDLL.dll)

Window layout — widescreen 70/30:
  ┌──────────────────────────────┬──────────────────┐
  │   Left 70% — Ch2 signal      │  Right 30%        │
  │  ┌────────────────────────┐  │  [Pulser Control] │
  │  │  Zoom plot (large)     │  │  [Temperature]    │
  │  └────────────────────────┘  │  [Calibration]    │
  │  ┌────────────────────────┐  │  [Vessel/Sample]  │
  │  │  Overview + region     │  │  [Acquisition]    │
  │  └────────────────────────┘  │  [Results]        │
  └──────────────────────────────┴──────────────────┘
"""

import sys
import os
import json
import math
import datetime
import argparse
import time

os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_SCALE_FACTOR"] = "1"

_TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
os.chdir(_TOOLS_DIR)
os.add_dll_directory(_TOOLS_DIR)

if sys.maxsize <= 2**32:
    _anaconda32_bin = r"C:\ProgramData\Anaconda32\Library\bin"
    if os.path.isdir(_anaconda32_bin):
        os.add_dll_directory(_anaconda32_bin)

_HW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'hardware')

import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QComboBox,
    QCheckBox, QPushButton,
    QStackedWidget, QMessageBox,
    QSplitter, QScrollArea, QFileDialog,
)
from PyQt5.QtCore import QTimer, Qt

import pyqtgraph as pg

sys.path.insert(0, _TOOLS_DIR)
sys.path.insert(0, _HW_DIR)

# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------
_arg_parser = argparse.ArgumentParser(description="ECOS Density GUI")
_arg_parser.add_argument(
    "--demo", action="store_true",
    help="Run in demo mode — skip hardware import, use simulated signals."
)
_ARGS = _arg_parser.parse_args()

# ---------------------------------------------------------------------------
# Hardware import
# ---------------------------------------------------------------------------
if _ARGS.demo:
    _HW_AVAILABLE = False
    print("[density_gui] Demo mode — hardware import skipped (--demo flag).")
else:
    try:
        from SeDaq import SeDaqDLL
        from GenCode_ToolBox import MakeGenCode
        from SpeedsoundWater import water_temp2sos, get_Cw_from_arduino
        from ECOS_US_ToolBox import CalcToFAscanCosine_XCRFFT
        _HW_AVAILABLE = True
        print("[density_gui] Hardware modules loaded OK.")
    except Exception as _hw_err:
        _HW_AVAILABLE = False
        print(f"[density_gui] Demo mode — hardware not available: {_hw_err}")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_RECLEN    = 16384
DEFAULT_GAIN      = 0
DEFAULT_VOLTAGE   = 20
DEFAULT_GEN_FS    = 200e6
DEFAULT_ACQ_FS    = 100e6
REALTIME_INTERVAL = 100      # ms
AVG_N             = 20       # A-scans averaged per acquisition

_DB_DIR      = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database')
DATA_DIR     = r"D:\ECOS\data"

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'density_gui_session.json')

SIGNAL_YMIN = -0.5
SIGNAL_YMAX =  0.5

BITS_OPTIONS = {
    "8 bit":  256,
    "10 bit": 1024,
    "12 bit": 4096,
}


# ===========================================================================
#  _DemoSeDaq
# ===========================================================================
class _DemoSeDaq:
    def __init__(self):
        self.RecLen   = DEFAULT_RECLEN
        self.DataADC1 = [512] * DEFAULT_RECLEN
        self.DataADC2 = [512] * DEFAULT_RECLEN

    def GetAScan(self):
        noise2 = np.random.normal(512, 20, self.RecLen).astype(int)
        self.DataADC1 = [512] * self.RecLen
        self.DataADC2 = list(noise2)

    def SetRecLen(self, reclen):
        self.RecLen   = reclen
        self.DataADC1 = [512] * reclen
        self.DataADC2 = [512] * reclen

    def UpdateGenCode(self, gencode):
        print(f"[Demo] UpdateGenCode — length = {len(gencode)} bytes")

    def SetGain2(self, gain):
        print(f"[Demo] SetGain2 = {gain}")

    def SetExtVoltage(self, voltage):
        print(f"[Demo] SetExtVoltage = {voltage}")

    def SetRelay(self, mode):
        print(f"[Demo] SetRelay = {mode}")

    def Close(self):
        print("[Demo] Close")


# ===========================================================================
#  DensityGUI — main window
# ===========================================================================
class DensityGUI(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECOS Density GUI")
        self.resize(1400, 800)

        # ── Hardware connection ───────────────────────────────────────────
        if _HW_AVAILABLE:
            try:
                self._sedaq = SeDaqDLL()
                time.sleep(0.5)
                self._sedaq.SetRelay(1)
                time.sleep(0.2)
                self._sedaq.SetRelay(0)  # then ON — required by hardware quirk
                self._sedaq.SetRecLen(DEFAULT_RECLEN)
                self._sedaq.SetGain2(DEFAULT_GAIN)
                self._sedaq.SetExtVoltage(DEFAULT_VOLTAGE)
                self._demo = False
            except Exception as e:
                QMessageBox.warning(
                    self, "Hardware warning",
                    f"DLL found but initialisation failed:\n{e}\n\nRunning in demo mode."
                )
                self._sedaq = _DemoSeDaq()
                self._demo = True
        else:
            self._sedaq = _DemoSeDaq()
            self._demo = True

        self._reclen  = DEFAULT_RECLEN
        self._running = True
        self._cw      = 1480.0   # m/s — speed of sound in water, updated from T
        self._T       = 20.0     # °C

        # Acquisition state
        self._sW1 = None
        self._sW2 = None
        self._r_vessel_cal = None   # calibrated vessel radius [cm]

        # ── Build UI ─────────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([1080, 320])
        main_layout.addWidget(splitter)

        self._btn_relay.setChecked(True)

        self._syncing = False

        # ── Restore previous session ──────────────────────────────────────
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE) as f:
                    self._restore_session(json.load(f))
                # Apply restored hardware values
                try:
                    self._sedaq.SetGain2(int(self._txt_gain_ch2.text()))
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
            except Exception:
                pass

        # ── Real-time acquisition timer ───────────────────────────────────
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_plots)
        self._timer.start(REALTIME_INTERVAL)

    # =======================================================================
    #  Session save / restore
    # =======================================================================
    def _collect_session(self):
        rmin, rmax = self._region.getRegion()
        return {
            "gain_ch2":            self._txt_gain_ch2.text(),
            "voltage":             self._txt_voltage.text(),
            "reclen":              self._txt_reclen.text(),
            "relay":               self._btn_relay.isChecked(),
            "region":              [rmin, rmax],
            "excitation_index":    self._cmb_excitation.currentIndex(),
            "gen_fs":              self._txt_gen_fs.text(),
            "pulse_param_index":   self._cmb_pulse_param.currentIndex(),
            "pulse_paramval":      self._txt_pulse_paramval.text(),
            "pulse_polarity_index": self._cmb_pulse_polarity.currentIndex(),
            "chirp_fstart":        self._txt_chirp_fstart.text(),
            "chirp_fend":          self._txt_chirp_fend.text(),
            "chirp_dur":           self._txt_chirp_dur.text(),
            "chirp_method_index":  self._cmb_chirp_method.currentIndex(),
            "chirp_phase":         self._txt_chirp_phase.text(),
            "chirp_polarity_index": self._cmb_chirp_polarity.currentIndex(),
            "burst_fo":            self._txt_burst_fo.text(),
            "burst_cycles":        self._txt_burst_cycles.text(),
            "burst_polarity_index": self._cmb_burst_polarity.currentIndex(),
            "arduino_port":        self._txt_arduino_port.text(),
            "temp_manual":         self._txt_temp_manual.text(),
            "r_vessel":            self._txt_r_vessel.text(),
            "mass":                self._txt_mass.text(),
            "vcal":                self._txt_vcal.text(),
            "ncal":                self._txt_ncal.text(),
            "n_avg":               self._txt_n_avg.text(),
            "sample_id":           self._txt_sample_id.text(),
            "pva_pct":             self._txt_pva_pct.text(),
            "additive":            self._txt_additive.text(),
            "additive_pct":        self._txt_additive_pct.text(),
            "cycles":              self._txt_cycles.text(),
            "fab_date":            self._txt_fab_date.text(),
            "dopants":             self._txt_dopants.text(),
            "notes":               self._txt_notes.text(),
            "save_filename":       self._txt_save_filename.text(),
        }

    def _restore_session(self, d):
        self._txt_gain_ch2.setText(d.get("gain_ch2", str(DEFAULT_GAIN)))
        self._txt_voltage.setText(d.get("voltage", str(DEFAULT_VOLTAGE)))
        self._txt_reclen.setText(d.get("reclen", str(DEFAULT_RECLEN)))
        self._btn_relay.setChecked(d.get("relay", True))
        region = d.get("region")
        if region:
            self._region.setRegion(region)
        self._cmb_excitation.setCurrentIndex(d.get("excitation_index", 0))
        self._txt_gen_fs.setText(d.get("gen_fs", "200e6"))
        self._cmb_pulse_param.setCurrentIndex(d.get("pulse_param_index", 0))
        self._txt_pulse_paramval.setText(d.get("pulse_paramval", "10e6"))
        self._cmb_pulse_polarity.setCurrentIndex(d.get("pulse_polarity_index", 0))
        self._txt_chirp_fstart.setText(d.get("chirp_fstart", "2e6"))
        self._txt_chirp_fend.setText(d.get("chirp_fend", "15e6"))
        self._txt_chirp_dur.setText(d.get("chirp_dur", "3e-6"))
        self._cmb_chirp_method.setCurrentIndex(d.get("chirp_method_index", 0))
        self._txt_chirp_phase.setText(d.get("chirp_phase", "270"))
        self._cmb_chirp_polarity.setCurrentIndex(d.get("chirp_polarity_index", 0))
        self._txt_burst_fo.setText(d.get("burst_fo", "10e6"))
        self._txt_burst_cycles.setText(d.get("burst_cycles", "5"))
        self._cmb_burst_polarity.setCurrentIndex(d.get("burst_polarity_index", 0))
        self._txt_arduino_port.setText(d.get("arduino_port", "COM4"))
        self._txt_temp_manual.setText(d.get("temp_manual", "20.0"))
        self._txt_r_vessel.setText(d.get("r_vessel", ""))
        self._txt_mass.setText(d.get("mass", ""))
        self._txt_vcal.setText(d.get("vcal", ""))
        self._txt_ncal.setText(d.get("ncal", "3"))
        self._txt_n_avg.setText(d.get("n_avg", str(AVG_N)))
        self._txt_sample_id.setText(d.get("sample_id", ""))
        self._txt_pva_pct.setText(d.get("pva_pct", ""))
        self._txt_additive.setText(d.get("additive", "PG"))
        self._txt_additive_pct.setText(d.get("additive_pct", ""))
        self._txt_cycles.setText(d.get("cycles", ""))
        self._txt_fab_date.setText(d.get("fab_date", ""))
        self._txt_dopants.setText(d.get("dopants", ""))
        self._txt_notes.setText(d.get("notes", ""))
        if d.get("save_filename"):
            self._txt_save_filename.setText(d["save_filename"])

    # =======================================================================
    #  Window close
    # =======================================================================
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

    # =======================================================================
    #  Left panel — Ch2 signal only
    # =======================================================================
    def _build_left_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Ch2 visibility toggle
        chk_row = QHBoxLayout()
        chk_row.addWidget(QLabel("Show:"))
        self._chk_ch2_vis = QCheckBox("Ch2")
        self._chk_ch2_vis.setChecked(True)
        self._chk_ch2_vis.toggled.connect(self._toggle_ch2_vis)
        chk_row.addWidget(self._chk_ch2_vis)
        chk_row.addStretch()
        layout.addLayout(chk_row)

        # Zoom plot
        self._plot_zoom = pg.PlotWidget(title="Ch2 — zoom region")
        self._plot_zoom.setLabel('left', 'Amplitude', units='a.u.')
        self._plot_zoom.getAxis('left').enableAutoSIPrefix(False)
        self._plot_zoom.setLabel('bottom', 'Sample')
        self._plot_zoom.showGrid(x=True, y=True, alpha=0.3)
        self._plot_zoom.enableAutoRange(axis='y', enable=False)
        self._plot_zoom.setYRange(-0.5, 0.5, padding=0)
        self._plot_zoom.getViewBox().setMouseEnabled(x=False, y=False)
        self._plot_zoom.enableAutoRange(axis='x', enable=False)

        self._curve_zoom_ch2 = self._plot_zoom.plot(
            pen=pg.mkPen('y', width=1), name="Ch2"
        )

        self._vline_time = pg.InfiniteLine(angle=90, movable=False, pen='w')
        self._vline_time.setVisible(False)
        self._plot_zoom.addItem(self._vline_time)
        self._cursor_text = pg.TextItem(anchor=(0, 1), color=(255, 255, 255))
        self._plot_zoom.addItem(self._cursor_text)
        self._cursor_text.hide()

        self._clip_text = pg.TextItem(
            text=u'\u26a0 CLIPPING', color=(255, 255, 255), anchor=(1, 0)
        )
        self._clip_text.setPos(self._reclen, 0.45)
        self._clip_text.hide()
        self._clip_text.setHtml(
            '<div style="background-color:red; padding:3px;">\u26a0 CLIPPING</div>'
        )
        self._plot_zoom.addItem(self._clip_text)

        self._plot_zoom.scene().sigMouseMoved.connect(self._on_mouse_moved)

        layout.addWidget(self._plot_zoom, stretch=3)

        # Overview plot
        self._plot_overview = pg.PlotWidget(title="Overview — full record")
        self._plot_overview.setLabel('bottom', 'Sample')
        self._plot_overview.setMaximumHeight(180)
        self._plot_overview.getViewBox().enableAutoRange(axis='x', enable=False)
        self._plot_overview.setXRange(0, self._reclen - 1, padding=0)
        self._plot_overview.setYRange(SIGNAL_YMIN, SIGNAL_YMAX, padding=0)
        self._plot_overview.setLimits(xMin=0, xMax=self._reclen - 1,
                                      yMin=SIGNAL_YMIN, yMax=SIGNAL_YMAX)
        self._plot_overview.getViewBox().setMouseEnabled(x=False, y=False)

        self._curve_ov_ch2 = self._plot_overview.plot(pen=pg.mkPen('y', width=1))

        self._region = pg.LinearRegionItem(
            values=[0, self._reclen // 4],
            bounds=[0, self._reclen]
        )
        self._region.setZValue(10)
        self._plot_overview.addItem(self._region)

        self._region.sigRegionChanged.connect(self._on_region_changed)
        self._plot_zoom.sigXRangeChanged.connect(self._on_zoom_xrange_changed)

        layout.addWidget(self._plot_overview, stretch=1)
        return widget

    # =======================================================================
    #  Right panel — scrollable control blocks
    # =======================================================================
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
        layout.addWidget(self._build_block_calibration())
        layout.addWidget(self._build_block_vessel())
        layout.addWidget(self._build_block_sample_descriptor())
        layout.addWidget(self._build_block_acquisition())
        layout.addWidget(self._build_block_results())
        layout.addStretch()
        return scroll

    # =======================================================================
    #  Block 1 — Pulser Control
    # =======================================================================
    def _build_block_pulser(self):
        box = QGroupBox("Pulser Control")
        form = QFormLayout(box)

        self._txt_gain_ch2 = QLineEdit(str(DEFAULT_GAIN))
        self._txt_voltage  = QLineEdit(str(DEFAULT_VOLTAGE))
        self._txt_reclen   = QLineEdit(str(DEFAULT_RECLEN))

        self._txt_gain_ch2.editingFinished.connect(self._on_gain_ch2_changed)
        self._txt_voltage.editingFinished.connect(self._on_voltage_changed)
        self._txt_reclen.editingFinished.connect(self._on_reclen_changed)

        self._cmb_bits = QComboBox()
        for label in BITS_OPTIONS:
            self._cmb_bits.addItem(label)
        self._cmb_bits.setCurrentText("10 bit")

        self._btn_relay = QPushButton("RELAY: OFF")
        self._btn_relay.setCheckable(True)
        self._btn_relay.setChecked(False)
        self._btn_relay.toggled.connect(self._on_relay_toggled)

        # GenCode sub-section
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Excitation:"))
        self._cmb_excitation = QComboBox()
        self._cmb_excitation.addItems(["Pulse", "Chirp", "Burst"])
        self._cmb_excitation.currentIndexChanged.connect(self._on_excitation_changed)
        type_row.addWidget(self._cmb_excitation)

        self._txt_gen_fs = QLineEdit("200e6")

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(
            self._stack.sizePolicy().horizontalPolicy(),
            __import__('PyQt5.QtWidgets', fromlist=['QSizePolicy']).QSizePolicy.Minimum
        )
        self._stack.addWidget(self._build_pulse_page())
        self._stack.addWidget(self._build_chirp_page())
        self._stack.addWidget(self._build_burst_page())

        btn_gen = QPushButton("Generate && Upload")
        btn_gen.setStyleSheet("font-weight: bold;")
        btn_gen.clicked.connect(self._generate_upload)

        form.addRow("Gain Ch2:",    self._txt_gain_ch2)
        form.addRow("Voltage:",     self._txt_voltage)
        form.addRow("RecLen:",      self._txt_reclen)
        form.addRow("Bits/sample:", self._cmb_bits)
        form.addRow("",             self._btn_relay)
        form.addRow(type_row)
        form.addRow("Generator Fs:", self._txt_gen_fs)
        form.addRow(self._stack)
        form.addRow("",              btn_gen)
        return box

    def _build_pulse_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self._cmb_pulse_param    = QComboBox()
        self._cmb_pulse_param.addItems(["frequency", "duration", "samples"])
        self._txt_pulse_paramval = QLineEdit("10e6")
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

    # =======================================================================
    #  Block 2 — Temperature
    # =======================================================================
    def _build_block_temperature(self):
        box = QGroupBox("Temperature")
        layout = QVBoxLayout(box)

        form = QFormLayout()
        self._txt_temp_manual = QLineEdit("20.0")
        self._txt_arduino_port = QLineEdit("COM4")
        self._txt_temp_manual.editingFinished.connect(self._on_temp_manual_changed)
        form.addRow("T manual (°C):", self._txt_temp_manual)
        form.addRow("Arduino port:",  self._txt_arduino_port)
        layout.addLayout(form)

        btn_read = QPushButton("Read from Arduino")
        btn_read.clicked.connect(self._on_read_arduino)
        layout.addWidget(btn_read)

        self._lbl_cw = QLabel(f"T = {self._T:.1f} °C   cw = {self._cw:.1f} m/s")
        layout.addWidget(self._lbl_cw)
        return box

    # =======================================================================
    #  Block 3 — Calibration
    # =======================================================================
    def _build_block_calibration(self):
        box = QGroupBox("Calibration")
        layout = QVBoxLayout(box)

        form = QFormLayout()
        self._txt_vcal = QLineEdit("")
        self._txt_ncal = QLineEdit("3")
        form.addRow("V_cal (cm³):", self._txt_vcal)
        form.addRow("N_cal:",       self._txt_ncal)
        layout.addLayout(form)

        btn_cal = QPushButton("Calibrate vessel")
        btn_cal.clicked.connect(self._on_calibrate)
        layout.addWidget(btn_cal)

        self._lbl_cal_result = QLabel("r_vessel: —")
        layout.addWidget(self._lbl_cal_result)

        btn_use = QPushButton("Use this value →")
        btn_use.clicked.connect(self._on_use_cal_value)
        layout.addWidget(btn_use)
        return box

    # =======================================================================
    #  Block 4 — Vessel & Sample
    # =======================================================================
    def _build_block_vessel(self):
        box = QGroupBox("Vessel & Sample")
        form = QFormLayout(box)

        self._txt_r_vessel = QLineEdit("")
        self._txt_mass     = QLineEdit("")

        form.addRow("r_vessel (cm):", self._txt_r_vessel)
        form.addRow("Mass (g):",      self._txt_mass)
        return box

    # =======================================================================
    #  Block 5 — Sample Descriptor
    # =======================================================================
    def _build_block_sample_descriptor(self):
        box = QGroupBox("Sample Descriptor")
        form = QFormLayout(box)

        self._txt_sample_id    = QLineEdit("")
        self._txt_pva_pct      = QLineEdit("")
        self._txt_additive     = QLineEdit("PG")
        self._txt_additive_pct = QLineEdit("")
        self._txt_cycles       = QLineEdit("")
        self._txt_fab_date     = QLineEdit("")
        self._txt_dopants      = QLineEdit("")
        self._txt_notes        = QLineEdit("")

        for w in (self._txt_sample_id, self._txt_pva_pct,
                  self._txt_additive, self._txt_additive_pct,
                  self._txt_cycles):
            w.editingFinished.connect(self._refresh_filename)

        form.addRow("Sample ID:",              self._txt_sample_id)
        form.addRow("PVA [%]:",               self._txt_pva_pct)
        form.addRow("Additive:",              self._txt_additive)
        form.addRow("Additive [%]:",          self._txt_additive_pct)
        form.addRow("Cycles:",                self._txt_cycles)
        form.addRow("Fab. date (DD/MM/YYYY):", self._txt_fab_date)
        form.addRow("Dopants:",               self._txt_dopants)
        form.addRow("Notes:",                 self._txt_notes)

        fname_row = QHBoxLayout()
        self._txt_save_filename = QLineEdit("")
        btn_refresh = QPushButton("\u21ba")
        btn_refresh.setFixedWidth(28)
        btn_refresh.setToolTip("Regenerate filename from fields")
        btn_refresh.clicked.connect(self._refresh_filename)
        fname_row.addWidget(self._txt_save_filename)
        fname_row.addWidget(btn_refresh)
        form.addRow("Filename:", fname_row)

        self._refresh_filename()
        return box

    def _refresh_filename(self):
        pva     = self._txt_pva_pct.text().strip()      or "XX"
        add     = self._txt_additive.text().strip()     or "ADD"
        add_pct = self._txt_additive_pct.text().strip() or "YY"
        letra   = self._txt_sample_id.text().strip()    or "X"
        try:
            cyc = f"{int(self._txt_cycles.text().strip()):03d}"
        except (ValueError, AttributeError):
            cyc = "NNN"
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._txt_save_filename.setText(
            f"PVA_{pva}_{add}_{add_pct}_{letra}_C{cyc}_DENS_{ts}"
        )

    # =======================================================================
    #  Block 6 — Acquisition
    # =======================================================================
    def _build_block_acquisition(self):
        box = QGroupBox("Acquisition")
        layout = QVBoxLayout(box)

        btn_sw1 = QPushButton("Acquire sW1 (reference)")
        btn_sw1.clicked.connect(self._on_acquire_sw1)
        layout.addWidget(btn_sw1)

        btn_sw2 = QPushButton("Acquire sW2 (sample submerged)")
        btn_sw2.clicked.connect(self._on_acquire_sw2)
        layout.addWidget(btn_sw2)

        self._btn_compute = QPushButton("Compute && Save")
        self._btn_compute.setStyleSheet("font-weight: bold;")
        self._btn_compute.setEnabled(False)
        self._btn_compute.clicked.connect(self._on_compute_save)
        layout.addWidget(self._btn_compute)

        row = QHBoxLayout()
        row.addWidget(QLabel("N avg:"))
        self._txt_n_avg = QLineEdit(str(AVG_N))
        self._txt_n_avg.setFixedWidth(60)
        row.addWidget(self._txt_n_avg)
        row.addStretch()
        layout.addLayout(row)

        self._lbl_acq_status = QLabel("Status: waiting for sW1")
        layout.addWidget(self._lbl_acq_status)
        return box

    # =======================================================================
    #  Block 7 — Results
    # =======================================================================
    def _build_block_results(self):
        box = QGroupBox("Results")
        form = QFormLayout(box)

        self._lbl_delta_tof = QLabel("—")
        self._lbl_delta_h   = QLabel("—")
        self._lbl_v_disp    = QLabel("—")
        self._lbl_density   = QLabel("—")

        form.addRow("ΔToF (µs):",        self._lbl_delta_tof)
        form.addRow("Δh (cm):",          self._lbl_delta_h)
        form.addRow("V_displaced (cm³):", self._lbl_v_disp)
        form.addRow("Density (g/cm³):",   self._lbl_density)
        return box

    # =======================================================================
    #  Real-time plot update
    # =======================================================================
    def _update_plots(self):
        if not self._running:
            return
        try:
            quant = BITS_OPTIONS[self._cmb_bits.currentText()]
            self._sedaq.GetAScan()

            ch2 = self._raw_to_float(self._sedaq.DataADC2, self._reclen, quant)

            rmin, rmax = self._region.getRegion()
            smin = max(0, int(rmin))
            smax = min(self._reclen, int(rmax))

            x_full = np.arange(self._reclen)
            x_zoom = np.arange(smin, smax)

            self._curve_ov_ch2.setData(x_full, ch2) if self._chk_ch2_vis.isChecked() \
                else self._curve_ov_ch2.setData([], [])

            if smax > smin:
                self._curve_zoom_ch2.setData(x_zoom, ch2[smin:smax]) \
                    if self._chk_ch2_vis.isChecked() \
                    else self._curve_zoom_ch2.setData([], [])

            visible = ch2[smin:smax] if self._chk_ch2_vis.isChecked() else np.array([])
            if len(visible) > 0 and np.abs(visible).max() >= 0.45:
                self._clip_text.setPos(rmax, 0.45)
                self._clip_text.show()
            else:
                self._clip_text.hide()

        except Exception as e:
            print(f"[_update_plots] {e}")

    @staticmethod
    def _raw_to_float(data_buffer, reclen, quant):
        arr = np.array(list(data_buffer[:reclen]), dtype=float)
        arr = (arr - quant / 2.0) / quant
        arr = arr - np.mean(arr)
        return arr

    # =======================================================================
    #  Zoom / region synchronisation
    # =======================================================================
    def _on_region_changed(self):
        if self._syncing:
            return
        self._syncing = True
        rmin, rmax = self._region.getRegion()
        self._plot_zoom.setXRange(rmin, rmax, padding=0)
        self._syncing = False

    def _on_zoom_xrange_changed(self, _vb, x_range):
        if self._syncing:
            return
        self._syncing = True
        xmin = max(0, x_range[0])
        xmax = min(self._reclen, x_range[1])
        self._region.setRegion([xmin, xmax])
        self._syncing = False

    def _toggle_ch2_vis(self, checked):
        if not checked:
            self._curve_zoom_ch2.setData([], [])
            self._curve_ov_ch2.setData([], [])

    # =======================================================================
    #  Crosshair cursor
    # =======================================================================
    def _on_mouse_moved(self, pos):
        vb = self._plot_zoom.getViewBox()
        if not self._plot_zoom.sceneBoundingRect().contains(pos):
            self._vline_time.hide()
            self._cursor_text.hide()
            return
        mp = vb.mapSceneToView(pos)
        x = mp.x()
        self._vline_time.setPos(x)
        self._vline_time.show()
        xs, ys = self._curve_zoom_ch2.getData()
        val = "---"
        if xs is not None and len(xs) > 0:
            i = int(np.clip(np.searchsorted(xs, x), 0, len(ys) - 1))
            val = f"{ys[i]:.4f}"
        self._cursor_text.setPos(x, mp.y())
        self._cursor_text.setText(f"Sample: {int(x)}\nCh2: {val}")
        self._cursor_text.show()

    # =======================================================================
    #  RecLen change
    # =======================================================================
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

        self._plot_overview.setXRange(0, reclen - 1, padding=0)
        self._plot_overview.setLimits(xMin=0, xMax=reclen - 1)
        self._region.setBounds([0, reclen])
        rmin, rmax = self._region.getRegion()
        self._region.setRegion([max(0, rmin), min(reclen, rmax)])

    # =======================================================================
    #  Relay toggle
    # =======================================================================
    def _on_relay_toggled(self, checked):
        state = 0 if checked else 1  # Hardware encoding: ON=0, OFF=1
        self._btn_relay.setText(f"RELAY: {'ON' if checked else 'OFF'}")
        try:
            self._sedaq.SetRelay(state)
        except Exception as e:
            print(f"[Relay] {e}")

    # =======================================================================
    #  Gain / voltage
    # =======================================================================
    def _on_gain_ch2_changed(self):
        try:
            self._sedaq.SetGain2(float(self._txt_gain_ch2.text()))
        except ValueError:
            pass
        except Exception as e:
            print(f"[SetGain2] {e}")

    def _on_voltage_changed(self):
        try:
            self._sedaq.SetExtVoltage(int(float(self._txt_voltage.text())))
        except ValueError:
            pass
        except Exception as e:
            print(f"[SetExtVoltage] {e}")

    # =======================================================================
    #  Temperature
    # =======================================================================
    def _on_temp_manual_changed(self):
        try:
            T = float(self._txt_temp_manual.text())
            self._T = T
            if _HW_AVAILABLE:
                self._cw = water_temp2sos(T)
            else:
                self._cw = 1402.7 + 4.88 * T - 0.0482 * T ** 2  # Marczak approximation
            self._lbl_cw.setText(f"T = {self._T:.1f} °C   cw = {self._cw:.1f} m/s")
        except ValueError:
            pass

    def _on_read_arduino(self):
        if not _HW_AVAILABLE:
            QMessageBox.information(self, "Demo mode", "Arduino read not available in demo mode.")
            return
        try:
            port = self._txt_arduino_port.text().strip()
            T1, T2, Cw1, Cw2 = get_Cw_from_arduino(port=port)
            if T1 is not None and T2 is not None:
                T = (T1 + T2) / 2.0
                cw = (Cw1 + Cw2) / 2.0
            elif T1 is not None:
                T, cw = T1, Cw1
            elif T2 is not None:
                T, cw = T2, Cw2
            else:
                raise ValueError("Could not read temperature from Arduino")
            self._T  = T
            self._cw = cw
            self._txt_temp_manual.setText(f"{T:.2f}")
            self._lbl_cw.setText(f"T = {self._T:.1f} °C   cw = {self._cw:.1f} m/s")
        except Exception as e:
            QMessageBox.warning(self, "Arduino error", str(e))

    # =======================================================================
    #  Excitation type selector + Generate & Upload
    # =======================================================================
    def _on_excitation_changed(self, index):
        self._stack.setCurrentIndex(index)

    def _generate_upload(self):
        excitation = self._cmb_excitation.currentText()
        try:
            gen_fs = float(self._txt_gen_fs.text())
        except ValueError:
            QMessageBox.warning(self, "Input error", "Generator Fs is not a valid number.")
            return

        try:
            params = self._collect_excitation_params()
            if excitation == "Pulse":
                gencode = MakeGenCode(
                    Excitation    = "Pulse",
                    Param         = params["param"],
                    ParamVal      = params["paramval"],
                    SignalPolarity = params["polarity"],
                    Fs            = gen_fs,
                )
            elif excitation == "Chirp":
                gencode = MakeGenCode(
                    Excitation    = "Chirp",
                    ParamVal      = [
                        params["fstart"], params["fend"],
                        params["duration"], params["method"], params["phase"],
                    ],
                    SignalPolarity = params["polarity"],
                    Fs            = gen_fs,
                )
            else:
                gencode = MakeGenCode(
                    Excitation    = "Burst",
                    ParamVal      = [params["fo"], params["nocycles"]],
                    SignalPolarity = params["polarity"],
                    Fs            = gen_fs,
                )
        except Exception as e:
            QMessageBox.critical(self, "GenCode error", f"Failed to build GenCode:\n{e}")
            return

        try:
            self._sedaq.UpdateGenCode(gencode)
            QMessageBox.information(self, "GenCode", "Waveform generated and uploaded successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Upload error", f"Upload failed:\n{e}")

    def _collect_excitation_params(self):
        excitation = self._cmb_excitation.currentText()

        def _polarity(cmb):
            return int(cmb.currentText().split()[0])

        if excitation == "Pulse":
            return {
                "param":    self._cmb_pulse_param.currentText(),
                "paramval": float(self._txt_pulse_paramval.text()),
                "polarity": _polarity(self._cmb_pulse_polarity),
            }
        elif excitation == "Chirp":
            return {
                "fstart":   float(self._txt_chirp_fstart.text()),
                "fend":     float(self._txt_chirp_fend.text()),
                "duration": float(self._txt_chirp_dur.text()),
                "method":   self._cmb_chirp_method.currentText(),
                "phase":    float(self._txt_chirp_phase.text()),
                "polarity": _polarity(self._cmb_chirp_polarity),
            }
        else:
            return {
                "fo":       float(self._txt_burst_fo.text()),
                "nocycles": int(self._txt_burst_cycles.text()),
                "polarity": _polarity(self._cmb_burst_polarity),
            }

    # =======================================================================
    #  Internal: acquire AVG_N A-scans from Ch2, return averaged signal
    # =======================================================================
    def _acquire_ch2_avg(self):
        quant = BITS_OPTIONS[self._cmb_bits.currentText()]
        acc   = np.zeros(self._reclen)
        n     = 0
        n_avg = int(self._txt_n_avg.text())
        while n < n_avg:
            self._sedaq.GetAScan()
            sig = self._raw_to_float(self._sedaq.DataADC2, self._reclen, quant)
            if np.all(sig == 0.0):
                continue
            acc += sig
            n   += 1
        rmin, rmax = self._region.getRegion()
        smin = max(0, int(rmin))
        smax = min(self._reclen, int(rmax))
        return (acc / n_avg)[smin:smax]

    # =======================================================================
    #  Acquisition buttons
    # =======================================================================
    def _on_acquire_sw1(self):
        self._timer.stop()
        try:
            self._sW1 = self._acquire_ch2_avg()
            self._lbl_acq_status.setText("sW1 acquired — ready for sW2")
            self._btn_compute.setEnabled(self._sW1 is not None and self._sW2 is not None)
        except Exception as e:
            QMessageBox.critical(self, "Acquisition error", str(e))
        finally:
            self._timer.start(REALTIME_INTERVAL)

    def _on_acquire_sw2(self):
        self._timer.stop()
        try:
            self._sW2 = self._acquire_ch2_avg()
            self._lbl_acq_status.setText("sW2 acquired — ready to compute")
            self._btn_compute.setEnabled(self._sW1 is not None and self._sW2 is not None)
        except Exception as e:
            QMessageBox.critical(self, "Acquisition error", str(e))
        finally:
            self._timer.start(REALTIME_INTERVAL)

    # =======================================================================
    #  Compute & Save
    # =======================================================================
    def _on_compute_save(self):
        try:
            r = float(self._txt_r_vessel.text())
        except ValueError:
            QMessageBox.warning(self, "Input error", "r_vessel is required.")
            return

        try:
            delta_tof = self._compute_delta_tof(self._sW2, self._sW1)
        except Exception as e:
            QMessageBox.critical(self, "ToF error", str(e))
            return

        delta_h   = self._cw * delta_tof / 2.0 * 100.0   # m/s × s / 2 → m → cm
        v_disp    = math.pi * r ** 2 * delta_h            # cm³

        mass_str  = self._txt_mass.text().strip()
        density   = None
        if mass_str:
            try:
                density = float(mass_str) / v_disp
            except (ValueError, ZeroDivisionError):
                pass

        self._lbl_delta_tof.setText(f"{delta_tof * 1e6:.4f}")
        self._lbl_delta_h.setText(f"{delta_h:.4f}")
        self._lbl_v_disp.setText(f"{v_disp:.4f}")
        self._lbl_density.setText(f"{density:.4f}" if density is not None else "— (no mass)")
        self._lbl_acq_status.setText("Done.")

        self._save_results(delta_tof, delta_h, v_disp, density)

    def _compute_delta_tof(self, sig, ref):
        if _HW_AVAILABLE:
            delta_tof_samples, xcorr, aligned = CalcToFAscanCosine_XCRFFT(sig, ref)
            return delta_tof_samples / DEFAULT_ACQ_FS
        else:
            return 1.5e-6   # demo: 1.5 µs

    def _save_results(self, delta_tof, delta_h, v_disp, density):
        self._refresh_filename()

        _start = DATA_DIR if os.path.isdir(DATA_DIR) \
            else (_DB_DIR if os.path.isdir(_DB_DIR) else os.path.expanduser("~"))
        save_dir = QFileDialog.getExistingDirectory(self, "Choose save folder", _start)
        if not save_dir:
            return

        base_name = self._txt_save_filename.text().strip() \
            or f"density_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        base = os.path.join(save_dir, base_name)

        result = {
            "datetime":      datetime.datetime.now().isoformat(),
            "sample_id":     self._txt_sample_id.text().strip(),
            "pva_pct":       self._txt_pva_pct.text().strip(),
            "additive":      self._txt_additive.text().strip(),
            "additive_pct":  self._txt_additive_pct.text().strip(),
            "cycles":        self._txt_cycles.text().strip(),
            "fab_date":      self._txt_fab_date.text().strip(),
            "dopants":       self._txt_dopants.text().strip(),
            "notes":         self._txt_notes.text().strip(),
            "T_C":           self._T,
            "cw_ms":         self._cw,
            "r_vessel_cm":   self._txt_r_vessel.text(),
            "mass_g":        self._txt_mass.text(),
            "delta_tof_s":   delta_tof,
            "delta_h_cm":    delta_h,
            "V_disp_cm3":    v_disp,
            "density_gcm3":  density,
            "reclen":        self._reclen,
            "avg_n":         int(self._txt_n_avg.text()),
        }
        with open(base + ".json", "w") as f:
            json.dump(result, f, indent=2)
        if self._sW1 is not None:
            np.save(base + "_sW1.npy", self._sW1)
        if self._sW2 is not None:
            np.save(base + "_sW2.npy", self._sW2)
        QMessageBox.information(self, "Saved", f"Results saved to:\n  {base}.json")

    # =======================================================================
    #  Calibration workflow
    # =======================================================================
    def _on_calibrate(self):
        try:
            v_cal = float(self._txt_vcal.text())
        except ValueError:
            QMessageBox.warning(self, "Input error", "V_cal is required.")
            return

        try:
            n_cal = int(self._txt_ncal.text())
        except ValueError:
            n_cal = 3

        ret = QMessageBox.information(
            self, "Calibration",
            "Vessel empty of sample.\nClick OK when ready to acquire reference.",
            QMessageBox.Ok | QMessageBox.Cancel
        )
        if ret != QMessageBox.Ok:
            return

        self._timer.stop()
        try:
            quant = BITS_OPTIONS[self._cmb_bits.currentText()]
            acc = np.zeros(self._reclen)
            for _ in range(n_cal):
                self._sedaq.GetAScan()
                acc += self._raw_to_float(self._sedaq.DataADC2, self._reclen, quant)
            sw1_cal = acc / n_cal
            rmin, rmax = self._region.getRegion()
            smin = max(0, int(rmin))
            smax = min(self._reclen, int(rmax))
            sw1_cal = sw1_cal[smin:smax]
        except Exception as e:
            QMessageBox.critical(self, "Calibration error", str(e))
            self._timer.start(REALTIME_INTERVAL)
            return
        finally:
            self._timer.start(REALTIME_INTERVAL)

        ret = QMessageBox.information(
            self, "Calibration",
            "Submerge calibration object.\nClick OK when ready.",
            QMessageBox.Ok | QMessageBox.Cancel
        )
        if ret != QMessageBox.Ok:
            return

        self._timer.stop()
        try:
            quant = BITS_OPTIONS[self._cmb_bits.currentText()]
            acc = np.zeros(self._reclen)
            for _ in range(n_cal):
                self._sedaq.GetAScan()
                acc += self._raw_to_float(self._sedaq.DataADC2, self._reclen, quant)
            sw2_cal = acc / n_cal
            rmin, rmax = self._region.getRegion()
            smin = max(0, int(rmin))
            smax = min(self._reclen, int(rmax))
            sw2_cal = sw2_cal[smin:smax]

            delta_tof = self._compute_delta_tof(sw2_cal, sw1_cal)
            delta_h   = self._cw * delta_tof / 2.0 * 100.0   # cm
            if delta_h <= 0:
                raise ValueError(f"delta_h = {delta_h:.4f} cm — non-positive, check signal")
            r_vessel  = math.sqrt(v_cal / (math.pi * delta_h))
            self._r_vessel_cal = r_vessel
            self._lbl_cal_result.setText(f"r_vessel = {r_vessel:.4f} cm  (Δh={delta_h:.4f} cm)")
        except Exception as e:
            QMessageBox.critical(self, "Calibration error", str(e))
        finally:
            self._timer.start(REALTIME_INTERVAL)

    def _on_use_cal_value(self):
        if self._r_vessel_cal is None:
            QMessageBox.information(self, "Calibration", "No calibrated value available yet.")
            return
        self._txt_r_vessel.setText(f"{self._r_vessel_cal:.4f}")


# ===========================================================================
#  Entry point
# ===========================================================================
if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = DensityGUI()
    win.show()
    sys.exit(app.exec_())
