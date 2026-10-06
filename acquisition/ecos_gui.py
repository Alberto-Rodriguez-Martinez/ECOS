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
    QApplication, QMainWindow, QWidget, QTabWidget, QSpinBox,
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
# acquisition/ itself, for scanner_panel: os.chdir(tools/) above means the
# script directory cannot be assumed to be found through the cwd.
_ACQ_DIR = os.path.dirname(os.path.abspath(__file__))
if _ACQ_DIR not in sys.path:
    sys.path.append(_ACQ_DIR)

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
_arg_parser.add_argument(
    "--scanner-sim", action="store_true",
    help="Use the scanner serial simulator and the synthetic SeDaq (implied by demo mode)."
)
_arg_parser.add_argument(
    "--session", metavar="FILE", default=None,
    help="GUI session file to restore and save (default: ecos_gui_session.json, or "
         "ecos_gui_session_sim.json in simulator mode; also the ECOS_GUI_SESSION "
         "environment variable). Tests pass a temporary one."
)
_ARGS = _arg_parser.parse_args()

# Simulator mode: synthetic SeDaq (sim_sedaq.SimSeDaq) whose echoes follow the
# simulated scanner. Also the fallback whenever the real digitizer is missing.
_SIM_MODE = _ARGS.demo or _ARGS.scanner_sim

from sim_sedaq import SimSeDaq, make_params_widget as make_sim_params_widget

try:
    from scanner_panel import ScannerPanel
    from scan_sequencer import ScanSequencer, DEFAULT_AVG_N, DEFAULT_SETTLE_MS
    from focus_tool import FocusTool, FocusGroup, window_peak
    from flatness_tool import FlatnessTool, FlatnessGroup
    from scan_tool import ScanTool, ScanGroup
    from stability_tool import StabilityTool, StabilityGroup
    _SCANNER_PANEL_ERR = None
except Exception as _sp_err:   # e.g. pyserial missing: the rest of the GUI still works
    ScannerPanel = ScanSequencer = None
    _SCANNER_PANEL_ERR = str(_sp_err)
    print(f"[ecos_gui] Scanner tab unavailable: {_sp_err}")

# Experiment folder names (ECOS convention, shared with the scans). Kept apart
# from the hardware imports: the scanner's line scan names and saves its folders
# in the simulator too.
try:
    from BD_Experimentos_PVA import experiment_name
except Exception as _bd_err:      # keep the original naming if the module cannot load
    experiment_name = None
    print(f"[ecos_gui] BD_Experimentos_PVA unavailable: {_bd_err}")

if _ARGS.demo:
    _HW_AVAILABLE = False
    print("[ecos_gui] Demo mode — hardware import skipped (--demo flag).")
else:
    try:
        if sys.maxsize > 2**32:
            # SeDaqDLL.dll is 32-bit: constructing SeDaqDLL() in a 64-bit
            # process crashes the interpreter (access violation) instead of
            # raising, so it can never be left to the except below.
            raise RuntimeError("SeDaqDLL.dll requires 32-bit Python")
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
AVG_MAX_ATTEMPTS_FACTOR = 4  # captures tried per requested average before giving up

# ADC resolution of the SeDaq. It cannot be read from the equipment (SeDaqDLL
# gives uint16 buffers and no query), so 10 bits is ASSUMED, as everywhere in
# ECOS until now (density_gui / pulser_gui let the user pick it, default 10 bit).
# It is a parameter: the quantizer midpoint and full scale come from it, and
# every scan writes it into its metadata (database/scan_counts.py).
from scan_counts import (  # noqa: E402
    ADC_BITS_DEFAULT, count_at_top, counts_to_float, default_emission_blank, top_mask,
)
ADC_BITS = ADC_BITS_DEFAULT
ADC_FULL_SCALE = 2 ** ADC_BITS          # counts; midpoint = ADC_FULL_SCALE / 2

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')

# The hardware session (Smin–Smax, gains... of the real set-up) is never touched by a
# simulator run: the simulator has its own file, and tests pass a temporary one.
SESSION_FILE = (_ARGS.session or os.environ.get('ECOS_GUI_SESSION') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'ecos_gui_session_sim.json' if _SIM_MODE else 'ecos_gui_session.json'))

SIGNAL_YMIN = -0.5
SIGNAL_YMAX =  0.5
# Quantizer full scale in the ECOS float, ±midpoint/full_scale (±0.5 at any number of
# bits). Nominal: the float has the record mean removed, so a channel with a DC offset
# clips that much off these lines (05/10, real scans: Ch2 −7 to −8 counts, ≈1.5 % of FS;
# Ch1 ≈ +1 count).
QUANT_FULL_SCALE = (ADC_FULL_SCALE // 2) / ADC_FULL_SCALE
ZOOM_Y_MARGIN = 1.1            # live plot range: the full-scale lines inside, not on the border

# ==============================================================================
# [3] ACQUISITION ERRORS (the simulated digitizer is sim_sedaq.SimSeDaq)
# ==============================================================================
class AcquisitionError(RuntimeError):
    """The digitizer did not deliver usable captures."""


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
        if _HW_AVAILABLE and not _SIM_MODE:
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
                self._sedaq = SimSeDaq(reclen=DEFAULT_RECLEN)
                self._demo  = True
        else:
            self._sedaq = SimSeDaq(reclen=DEFAULT_RECLEN)
            self._demo  = True

        # ── Scanner panel (embedded as a tab, see _build_right_panel) ─────────
        if ScannerPanel is not None:
            self._scanner_panel = ScannerPanel(use_sim=self._demo or _SIM_MODE)
        else:
            self._scanner_panel = None

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

        # Synthetic SeDaq: the default Smin–Smax holds its front echo and back wall
        # (a saved simulator session may override it below).
        if isinstance(self._sedaq, SimSeDaq):
            self._region.setRegion(list(self._sedaq.default_window()))

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

        # ── Scanner sequencer (needs the timer: it pauses the live refresh) ───
        self._sequencer = None
        if self._scanner_panel is not None:
            self._setup_sequencer()

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
        if self._sequencer is not None:
            self._sequencer.shutdown()   # its leave hook restarts the timer: stop it after
        self._timer.stop()
        if self._scanner_panel is not None:
            self._scanner_panel.shutdown()
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
        # Saturation of each channel, next to its name, only while it happens
        self._lbl_sat = {}
        for ch, chk in ((1, self._chk_ch1), (2, self._chk_ch2)):
            lbl = QLabel("")
            lbl.setStyleSheet("color: rgb(230, 30, 30); font-weight: bold;")
            lbl.setToolTip("Raw samples of the last acquisition at the top of the quantizer "
                           "(code 0 or full scale - 1) in any capture, whole record: this "
                           "channel has clipped.")
            lbl.hide()
            self._lbl_sat[ch] = lbl
            top_row.addWidget(chk)
            top_row.addWidget(lbl)

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
        top_row.addSpacing(20)
        # One control for the whole cross: both lines are shown and hidden together
        self._chk_cursor = QCheckBox("Cursor")
        self._chk_cursor.setChecked(True)
        self._chk_cursor.setToolTip("Cross-hair cursor on the live A-scan (time and amplitude)")
        self._chk_cursor.toggled.connect(lambda on: on or self._set_cursor_visible(False))
        top_row.addWidget(self._chk_cursor)
        self._chk_fullscale = QCheckBox("Full scale")
        self._chk_fullscale.setChecked(True)
        self._chk_fullscale.setToolTip(
            "Faint lines at the quantizer full scale, ± (nominal): the margin left before "
            "saturating. The signal has its mean removed, so a channel with a DC offset "
            "clips slightly off them (Ch2 ≈ 1.5 % of full scale on the real set-up).")
        self._chk_fullscale.toggled.connect(
            lambda on: [line.setVisible(on) for line in self._fullscale_lines])
        top_row.addWidget(self._chk_fullscale)
        top_row.addStretch()
        # Values under the cursor: discreet, at the right of the row, not over the trace
        self._lbl_cursor = QLabel("")
        self._lbl_cursor.setStyleSheet("color: gray;")
        top_row.addWidget(self._lbl_cursor)
        layout.addLayout(top_row)

        # Zoom plot
        self._plot_zoom = pg.PlotWidget(title="Live A-scan — zoom region")
        self._plot_zoom.setLabel('left', 'Amplitude', units='a.u.')
        self._plot_zoom.getAxis('left').enableAutoSIPrefix(False)
        self._plot_zoom.setLabel('bottom', 'Sample')
        self._plot_zoom.showGrid(x=True, y=True, alpha=0.3)
        self._plot_zoom.enableAutoRange(axis='y', enable=False)
        self._plot_zoom.setYRange(SIGNAL_YMIN * ZOOM_Y_MARGIN, SIGNAL_YMAX * ZOOM_Y_MARGIN,
                                  padding=0)
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

        # Hover cursor: a full cross (time and amplitude), both lines in the same style
        self._vline_cursor = pg.InfiniteLine(angle=90, movable=False, pen='w')
        self._hline_cursor = pg.InfiniteLine(angle=0, movable=False, pen='w')
        # Quantizer full scale, + and −: faint, dashed, behind the traces
        fs_pen = pg.mkPen((200, 200, 200, 90), width=1, style=Qt.DashLine)
        self._fullscale_lines = []
        for level in (QUANT_FULL_SCALE, -QUANT_FULL_SCALE):
            line = pg.InfiniteLine(pos=level, angle=0, movable=False, pen=fs_pen)
            line.setZValue(-10)
            self._plot_zoom.addItem(line)
            self._fullscale_lines.append(line)
        for line in (self._vline_cursor, self._hline_cursor):
            line.setVisible(False)
            self._plot_zoom.addItem(line)
        self._plot_zoom.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # The big plot lives in a tab widget: "A-scan" is the live zoom plot,
        # "Scanner" is where the scanner tools draw (focus curve, flatness
        # lines, scan map). The overview below stays outside the tabs so the
        # live A-scan is always visible.
        self._left_tabs = QTabWidget()
        self._left_tabs.addTab(self._plot_zoom, "A-scan")
        self._plot_scan = pg.PlotWidget(title="Scanner")
        self._plot_scan.showGrid(x=True, y=True, alpha=0.3)
        self._left_tabs.addTab(self._plot_scan, "Scanner")
        layout.addWidget(self._left_tabs, stretch=3)

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
        self._acq_scroll = scroll

        self._right_tabs = QTabWidget()
        self._right_tabs.addTab(scroll, "Acquisition")
        if self._scanner_panel is not None:
            self._right_tabs.addTab(self._scanner_panel, "Scanner")
        else:
            lbl = QLabel(f"Scanner unavailable:\n{_SCANNER_PANEL_ERR}")
            lbl.setAlignment(Qt.AlignCenter)
            self._right_tabs.addTab(lbl, "Scanner")
        return self._right_tabs

    def _show_scanner_plot(self):
        """Bring the big plot to the "Scanner" tab (called when a scanner tool starts)."""
        self._left_tabs.setCurrentWidget(self._plot_scan)

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
        # Live saturation indicator: blanking of the emission zone (the main bang reaches
        # the quantizer top by design and would keep the indicator always on)
        self._spin_blank = QSpinBox()
        self._spin_blank.setRange(0, DEFAULT_RECLEN)
        self._spin_blank.setSuffix(" samples")
        self._spin_blank.setToolTip(
            "Samples from the start of the record left out of the live saturation "
            "indicator (the excitation pulse clips by design). The indicator covers from "
            "here to the end of the record, so it still sees clipping outside Smin-Smax. "
            "Auto: end of the main bang in the current record + 0.5 µs.")
        self._spin_blank.valueChanged.connect(self._on_blank_changed)
        btn_blank = QPushButton("Auto")
        btn_blank.setToolTip("Estimate it from the current record")
        btn_blank.clicked.connect(self._auto_emission_blank)
        blank_row = QHBoxLayout()
        blank_row.addWidget(self._spin_blank)
        blank_row.addWidget(btn_blank)
        form.addRow("Emission blanking:", blank_row)
        self._blank_from_session = False
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

        avg_row = QHBoxLayout()
        avg_row.addWidget(QLabel("Averages (N):"))
        self._txt_avg_n = QLineEdit(str(AVG_N))
        self._txt_avg_n.setFixedWidth(60)
        avg_row.addWidget(self._txt_avg_n)
        avg_row.addStretch()
        layout.addLayout(avg_row)

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
        self._btn_preview.clicked.connect(self._on_preview_window)
        self._btn_apply.clicked.connect(self._on_apply_window)
        btn_row.addWidget(self._btn_preview)
        btn_row.addWidget(self._btn_apply)
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
            quant = ADC_FULL_SCALE
            self._timed_get_ascan()
            ch1 = self._raw_to_float(self._sedaq.DataADC1, self._reclen, quant)
            ch2 = self._raw_to_float(self._sedaq.DataADC2, self._reclen, quant)
            self._plot_ascans(ch1, ch2)
            self._last_raw = tuple(np.asarray(buf[:self._reclen])
                                   for buf in (self._sedaq.DataADC1, self._sedaq.DataADC2))
            if not self._blank_from_session:          # no saved value: from the record, once
                self._auto_emission_blank()
            self._show_saturation(tuple(top_mask(r, ADC_BITS) for r in self._last_raw))
        except Exception as e:
            print(f"[_update_plots] {e}")

    def _show_saturation(self, tops):
        """Red indicator next to each channel name, only when its last acquisition has
        raw samples at the quantizer top (scan_counts.top_mask, the one detection of
        ECOS), from the end of the emission blanking to the end of the record: any
        clipping is worth seeing, also outside Smin–Smax (the measurement flags look at
        Smin–Smax only), but not the main bang, which clips by design."""
        for ch, mask in zip((1, 2), tops):
            n = count_at_top(mask, self._indicator_span(len(mask)))
            lbl = self._lbl_sat[ch]
            lbl.setText(f"SATURATED: {n} sample{'s' if n != 1 else ''} at full scale"
                        if n else "")
            lbl.setVisible(n > 0)

    def _indicator_span(self, reclen):
        """Samples the live saturation indicator covers: blanking .. end of record."""
        return (min(self._spin_blank.value(), reclen), reclen)

    def _on_blank_changed(self, value):
        self._blank_from_session = True        # set (by hand, Auto or the session): keep it
        if getattr(self, '_sequencer', None) is not None:
            self._sequencer.emission_blank = int(value)     # into the tools' metadata

    def _auto_emission_blank(self):
        """Blanking from the current record: end of the main bang + margin."""
        raws = getattr(self, '_last_raw', None)
        if raws is None:
            return
        self._spin_blank.setValue(default_emission_blank(raws, DEFAULT_ACQ_FS))
        self._blank_from_session = True

    def _plot_ascans(self, ch1, ch2):
        """Draw one pair of full-record A-scans on the zoom and overview plots."""
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
    def _set_cursor_visible(self, visible):
        """The two lines of the cross always together, and their readout."""
        self._vline_cursor.setVisible(visible)
        self._hline_cursor.setVisible(visible)
        if not visible:
            self._lbl_cursor.setText("")

    def _unit_to_us(self, x):
        """x-axis value (current unit) to time [µs], without rounding to a sample."""
        if self._unit == 'mus':
            return float(x)
        if self._unit == 'mm':
            cw = self._state.Cw_mean or 1480.0
            return float(x) * 2.0 / (cw * 1e-3)
        return float(x) / DEFAULT_ACQ_FS * 1e6

    def _on_mouse_moved(self, pos):
        vb = self._plot_zoom.getViewBox()
        if (not self._chk_cursor.isChecked()
                or not self._plot_zoom.sceneBoundingRect().contains(pos)):
            self._set_cursor_visible(False)
            return
        mp = vb.mapSceneToView(pos)
        x, y = mp.x(), mp.y()
        self._vline_cursor.setPos(x)
        self._hline_cursor.setPos(y)
        self._set_cursor_visible(True)

        where = {'samples': f"sample {x:.0f}", 'mus': "", 'mm': f"d = {x:.2f} mm"}[self._unit]
        text = (f"t = {self._unit_to_us(x):.3f} µs" + (f" ({where})" if where else "")
                + f"   A = {y:.4f} a.u. ({y / QUANT_FULL_SCALE * 100:+.1f} % FS)")
        # The signal at that instant (Ch2, else Ch1), as the former floating label showed
        for name, curve in (("Ch2", self._curve_zoom_ch2), ("Ch1", self._curve_zoom_ch1)):
            xs, ys = curve.getData()
            if xs is not None and len(xs) > 0:
                i = int(np.clip(np.searchsorted(xs, x), 0, len(ys) - 1))
                text += f"   ·   {name} = {ys[i]:.4f} a.u."
                break
        self._lbl_cursor.setText(text)

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
        self._spin_blank.setMaximum(reclen)
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
            self._temp_note = None        # assumed, not read: not reported as a reading
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
            self._note_temperature("PT100 (Acquisition tab)")
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
        self._temp_note = None            # manual, not read: not reported as a reading
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

    def _get_avg_n(self):
        try:
            return max(1, int(self._txt_avg_n.text()))
        except ValueError:
            return AVG_N

    def _acquire_avg(self, avg_n, channels, reclen=None):
        """
        Average avg_n A-scans and return one full-record array per requested
        channel (1 and/or 2). A capture that comes out all zeros on any
        requested channel is discarded and retried, but only up to
        AVG_MAX_ATTEMPTS_FACTOR * avg_n captures in total: with the hardware
        disconnected or failing every capture is all zeros, and an unbounded
        retry would hang the GUI thread with no message.
        """
        quant = ADC_FULL_SCALE
        reclen = self._reclen if reclen is None else reclen
        accs  = {ch: np.zeros(reclen) for ch in channels}
        n     = 0
        tries = 0
        max_tries = AVG_MAX_ATTEMPTS_FACTOR * avg_n
        while n < avg_n:
            if tries >= max_tries:
                raise AcquisitionError(
                    f"Acquisition failed: only {n} of {avg_n} valid captures after "
                    f"{tries} attempts (all-zero signals; is the digitizer connected?)"
                )
            tries += 1
            self._timed_get_ascan()
            sigs = {
                ch: self._raw_to_float(
                    self._sedaq.DataADC1 if ch == 1 else self._sedaq.DataADC2,
                    reclen, quant)
                for ch in channels
            }
            if any(np.all(sig == 0.0) for sig in sigs.values()):
                continue
            for ch, sig in sigs.items():
                accs[ch] += sig
            n += 1
        return [accs[ch] / avg_n for ch in channels]

    def _timed_get_ascan(self):
        """GetAScan(), keeping a running mean of its duration (scanner time estimates)."""
        t0 = time.perf_counter()
        self._sedaq.GetAScan()
        dt = time.perf_counter() - t0
        prev = getattr(self, '_t_ascan', None)
        self._t_ascan = dt if prev is None else 0.9 * prev + 0.1 * dt

    def _acquire_ch_avg(self, channel, smin, smax):
        """Average N A-scans from channel 1 or 2 and return the windowed slice."""
        avg = self._acquire_avg(self._get_avg_n(), (channel,))[0]
        return avg[smin:smax]

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
    #  Scanner sequences (phase 2: sequencer + debug test sequence)
    # ==========================================================================
    def _setup_sequencer(self):
        panel = self._scanner_panel
        self._sequencer = ScanSequencer(
            panel.worker, self._sedaq, self._seq_acquire,
            coords_fn=panel.current_coords,
            blocker_fn=panel.sequence_blocker,
            temp_factory=self._open_seq_arduino,
            enter_exclusive=self._timer.stop,
            leave_exclusive=lambda: self._timer.start(REALTIME_INTERVAL),
            top_fn=lambda: getattr(self, '_last_top', None),
            parent=self,
        )
        self._sequencer.emission_blank = (self._spin_blank.value()
                                          if self._blank_from_session else None)
        seq = self._sequencer
        panel.stop_pressed.connect(seq.abort)
        seq.started.connect(self._on_seq_started)
        seq.progress.connect(self._on_seq_progress)
        seq.finished.connect(self._on_seq_finished)
        seq.message.connect(self._on_seq_message)
        seq.state_changed.connect(self._on_seq_state)

        # Focus (phase 3): reads Smin–Smax of the Acquisition tab, never sets it.
        self._focus_tool = FocusTool(seq, panel, self._get_smin_smax, self._plot_scan,
                                     show_plot_fn=self._show_scanner_plot,
                                     cw_fn=self._scanner_water_cw,
                                     gains_fn=self._scan_gains, temp_fn=self._latest_temperature,
                                     acq_time_fn=lambda: getattr(self, '_t_ascan', None),
                                     parent=self)
        panel.add_tool_widget(FocusGroup(self._focus_tool, seq, self._get_smin_smax),
                              tab='calibration')
        # Which echo each point measured (front-echo tracking), marked on the A-scan.
        self._echo_mark = None
        self._focus_tool.echo_used.connect(self._mark_echo)
        self._focus_tool.done.connect(lambda _moved: self._clear_echo_mark())

        # Flatness (phase 4): same sequencer, c_w and echo marking as the focus.
        self._flatness_tool = FlatnessTool(seq, panel, self._get_smin_smax, self._plot_scan,
                                           show_plot_fn=self._show_scanner_plot,
                                           cw_fn=self._scanner_water_cw,
                                           gains_fn=self._scan_gains,
                                           temp_fn=self._latest_temperature,
                                           acq_time_fn=lambda: getattr(self, '_t_ascan', None),
                                           parent=self)
        panel.add_tool_widget(FlatnessGroup(self._flatness_tool, seq), tab='calibration')

        # Stability test (diagnostic, Calibration): nothing moves; its own plot tab.
        self._plot_stability = pg.GraphicsLayoutWidget()
        self._left_tabs.addTab(self._plot_stability, "Stability")
        self._stability_tool = StabilityTool(
            seq, panel, self._get_smin_smax, self._plot_stability,
            show_plot_fn=lambda: self._left_tabs.setCurrentWidget(self._plot_stability),
            temp_factory=self._open_seq_arduino,
            sos_fn=water_temp2sos if _HW_AVAILABLE else self._approx_cw,
            cw_fn=self._scanner_cw_no_read, gains_fn=self._scan_gains,
            acq_time_fn=lambda: getattr(self, '_t_ascan', None), parent=self)
        panel.add_tool_widget(StabilityGroup(self._stability_tool, seq), tab='calibration')
        self._stability_tool.echo_used.connect(self._mark_echo)
        self._stability_tool.done.connect(lambda _how: self._clear_echo_mark())
        self._flatness_tool.echo_used.connect(self._mark_echo)
        self._flatness_tool.done.connect(lambda _ok: self._clear_echo_mark())

        # Line and surface scans (phases 5 and 6): save to ../database; references
        # with their own gains. A surface draws its 2-D maps in their own tab.
        self._scan_session_lock = False
        self._plot_scan_map = pg.GraphicsLayoutWidget()
        self._left_tabs.addTab(self._plot_scan_map, "Scan map")
        self._scan_tool = ScanTool(
            seq, panel, self._get_smin_smax, self._plot_scan,
            map_widget=self._plot_scan_map,
            show_map_fn=lambda: self._left_tabs.setCurrentWidget(self._plot_scan_map),
            acquire_fn=self._seq_acquire,
            gains_fn=self._scan_gains,
            set_gains_fn=self._scan_set_gains,
            counts_fn=self._last_counts_fn,
            adc_bits=ADC_BITS,
            temp_factory=self._open_seq_arduino,
            sos_fn=water_temp2sos if _HW_AVAILABLE else self._approx_cw,
            cw_fn=self._scanner_cw_no_read,
            info_fn=self._scan_experiment_info,
            base_dir=_DB_DIR,
            show_plot_fn=self._show_scanner_plot,
            acq_time_fn=lambda: getattr(self, '_t_ascan', None),
            lock_fn=self._scan_lock,
            hold_live_fn=self._hold_live,
            parent=self)
        panel.add_tool_widget(ScanGroup(self._scan_tool, seq), tab='scans')
        self._scan_tool.echo_used.connect(self._mark_echo)
        self._scan_tool.done.connect(lambda _how: self._clear_echo_mark())

        if isinstance(self._sedaq, SimSeDaq):
            panel.scanner_state_changed.connect(self._push_scanner_state_to_sim)
            self._push_scanner_state_to_sim()
            panel.add_tool_widget(make_sim_params_widget(self._sedaq))
        if panel.uses_simulator:
            panel.add_tool_widget(self._build_test_sequence_group())
            seq.point_done.connect(self._on_test_point)

    _ECHO_MARK_TEXT = {
        'first':   "front echo · first peak",
        'tracked': "front echo · tracked",
        'relock':  "front echo · re-locked (earlier echo found)",
        'none':    "no clear echo · window max",
        'max':     "window max",
    }

    def _mark_echo(self, m):
        """Mark on the A-scan the echo measured on the current point: dashed
        line at its envelope peak, shaded band searched around the prediction
        and a label with how it was chosen. The A-scan of the point is already
        drawn (the sequencer acquires, then measures)."""
        if self._echo_mark is None:
            col = (0, 220, 120)
            band = pg.LinearRegionItem(values=(0, 1), movable=False,
                                       brush=pg.mkBrush(0, 220, 120, 40))
            band.setZValue(-5)
            peak = pg.InfiniteLine(angle=90, movable=False,
                                   pen=pg.mkPen(col, width=2, style=Qt.DashLine))
            label = pg.TextItem(anchor=(0, 0), color=col)
            for item in (band, peak, label):
                self._plot_zoom.addItem(item)
            self._echo_mark = (band, peak, label)
        band, peak, label = self._echo_mark
        x = float(self._samples_to_unit(m.index))
        peak.setPos(x)
        if m.band is not None:
            band.setRegion((float(self._samples_to_unit(m.band[0])),
                            float(self._samples_to_unit(m.band[1]))))
            band.show()
        else:
            band.hide()
        text = self._ECHO_MARK_TEXT.get(m.mode, m.mode)
        if m.outside:
            text += " · predicted outside Smin–Smax"
        elif m.at_edge:
            text += " · at a window edge"
        if m.saturated:
            text += " · Ch2 saturated"
        label.setText(text, color=(235, 60, 60) if m.flagged else (0, 220, 120))
        label.setPos(x, SIGNAL_YMAX)
        peak.show()
        label.show()

    def _clear_echo_mark(self):
        if self._echo_mark is not None:
            for item in self._echo_mark:
                item.hide()

    def _scanner_water_cw(self):
        """
        c_w for the scanner tools, read from the PT100s when a tool starts, as
        the rest of ECOS does (water_temp2sos on T1 and T2, their mean; the
        state and the temperature label are updated too). Never the manual
        dialog: it is modal and a sequence must not block on it. Returns
        (c_w, source), or None (the tool then uses its nominal value).
        With the synthetic SeDaq the echoes follow its own c_w, so that one.
        """
        if isinstance(self._sedaq, SimSeDaq):
            return self._sedaq.params.c_w, "synthetic SeDaq"
        st = self._state
        if _HW_AVAILABLE:
            arduino = None
            try:
                arduino = self._open_seq_arduino()
                T1, T2 = arduino.getTemperatures()
                if T1 is None and T2 is None:
                    raise ValueError("no temperature data received from Arduino")
                T1 = T1 if T1 is not None else T2
                T2 = T2 if T2 is not None else T1
                st.T1, st.T2 = T1, T2
                st.Cw1, st.Cw2 = water_temp2sos(T1), water_temp2sos(T2)
                st.Cw_mean = (st.Cw1 + st.Cw2) / 2.0
                self._note_temperature("PT100 (scanner tool start)")
                self._update_temp_label()
                return st.Cw_mean, f"PT100 T1 = {T1:.2f} °C, T2 = {T2:.2f} °C"
            except Exception as e:
                print(f"[scanner c_w] PT100 read failed: {e}")
            finally:
                if arduino is not None:
                    try:
                        arduino.close()
                    except Exception:
                        pass
        if st.Cw_mean:
            return st.Cw_mean, "last temperature reading, PT100 unavailable now"
        return None

    # -- line scan host functions (phase 5) ---------------------------------------
    def _scan_gains(self):
        """Gains of the Acquisition tab: the scan gains (restored after a reference)."""
        return float(self._txt_gain_ch1.text()), float(self._txt_gain_ch2.text())

    def _scan_set_gains(self, g1, g2):
        """Gain1, then Gain2 again: the pulser loses Gain2 after any Gain1 change."""
        self._sedaq.SetGain1(g1)
        self._sedaq.SetGain2(g2)

    def _scan_lock(self, locked):
        """The Acquisition tab stays locked for the whole scan session, also between
        its sequences (water-reference steps)."""
        self._scan_session_lock = bool(locked)
        self._acq_scroll.setEnabled(not locked and not self._sequencer.active)

    def _hold_live(self, hold):
        """Hold the live A-scan refresh while a water reference is up for approval:
        the averaged reference stays on the plots instead of single live captures."""
        if hold:
            self._timer.stop()
        elif not self._sequencer.active:
            self._timer.start(REALTIME_INTERVAL)

    def _note_temperature(self, source):
        """Remember when and where the state temperatures were last read (debug dumps)."""
        self._temp_note = {"time": time.time(), "source": source}

    def _latest_temperature(self):
        """The latest PT100 reading, with its time and source, or None. Only real readings
        count: the assumed (no hardware) or manual values are not noted."""
        note = getattr(self, "_temp_note", None)
        st = self._state
        if note is None or (st.T1 is None and st.T2 is None):
            return None
        return dict(note, T1=st.T1, T2=st.T2)

    def _scanner_cw_no_read(self):
        """c_w without opening the Arduino (the scan holds its only instance)."""
        if isinstance(self._sedaq, SimSeDaq):
            return self._sedaq.params.c_w, "synthetic SeDaq"
        if self._state.Cw_mean:
            return self._state.Cw_mean, "last temperature reading, PT100 unavailable now"
        return None

    def _specimen_dict(self):
        return {
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

    def _scan_experiment_info(self):
        """Metadata of a scan, same scheme as Compute & Save (save_experiment_raw_32)."""
        try:
            excitation = dict(self._collect_excitation_params(),
                              type=self._cmb_excitation.currentText())
        except Exception as e:
            excitation = {"error": str(e)}
        return {
            "specimen": self._specimen_dict(),
            "protocol": {"description": "Barrido ultrasónico ECOS (escáner)",
                         "notes": self._txt_notes.text()},
            "equipment1": {
                "nombre": "SEDAQ" + (" (synthetic)" if isinstance(self._sedaq, SimSeDaq) else ""),
                "transductor_pe": "",
                "transductor_tt": "",
                "params": {
                    "Voltaje": self._txt_voltage.text(),
                    "Fp": DEFAULT_FP,
                    "F_muestreo": DEFAULT_ACQ_FS,
                    "RecLen": self._reclen,
                    "excitation": excitation,
                    "gen_fs": self._txt_gen_fs.text(),
                },
            },
            "equipment2": {"nombre": "Arduino", "puerto": self._txt_arduino_port.text()},
            "name_parts": {"pva": self._txt_pva_pct.text(),
                           "additive": self._txt_additive_pct.text(),
                           "sample_id": self._txt_sample_id.text(),
                           "cycles": self._txt_cycles.text()},
        }

    def _push_scanner_state_to_sim(self):
        """Synthetic SeDaq: echoes follow the (simulated) scanner position."""
        panel = self._scanner_panel
        coords = panel.current_coords() if panel.is_connected else None
        self._sedaq.set_scanner_state(coords, panel.role_axis('beam'), panel.pe_side())

    def _seq_acquire(self, avg_n):
        """
        Acquisition step of a sequence (and of the water references): averaged
        Ch1/Ch2, drawn on the live plots. Acquired as integer sums of counts
        (_acquire_counts) and turned into the ECOS float with
        scan_counts.counts_to_float, the same function that reads a saved scan,
        so the scan files rebuild these floats bit for bit. Mathematically equal
        to _acquire_avg (mean of the mean-removed captures). The sums of this
        acquisition stay available through _last_counts_fn.
        """
        reclen = self._sedaq.RecLen
        s1, s2 = self._acquire_counts(avg_n, reclen)
        ch1, o1 = counts_to_float(s1, avg_n, ADC_BITS)
        ch2, o2 = counts_to_float(s2, avg_n, ADC_BITS)
        self._last_counts = {'sum': (s1, s2), 'offset': (o1, o2), 'n': int(avg_n),
                             'top': self._last_top}
        if reclen == self._reclen:
            self._plot_ascans(ch1, ch2)
            self._show_saturation(self._last_top)
        return ch1, ch2

    def _last_counts_fn(self):
        return getattr(self, '_last_counts', {'sum': (None, None), 'offset': (0.0, 0.0), 'n': 0})

    def _acquire_counts(self, avg_n, reclen=None):
        """
        Integer sums over avg_n captures of (raw − midpoint), both channels, whole
        record (int64). Same retry rule as _acquire_avg: a constant capture on any
        channel (all zeros after the mean removal there) is discarded and retried,
        up to AVG_MAX_ATTEMPTS_FACTOR * avg_n captures. Also the samples at the
        quantizer top in ANY of the captures (scan_counts.top_mask, OR-ed), kept in
        self._last_top for the saturation indicator and the sequencer.
        """
        reclen = self._reclen if reclen is None else reclen
        mid = ADC_FULL_SCALE // 2
        sums = [np.zeros(reclen, dtype=np.int64), np.zeros(reclen, dtype=np.int64)]
        tops = [np.zeros(reclen, dtype=bool), np.zeros(reclen, dtype=bool)]
        n = tries = 0
        max_tries = AVG_MAX_ATTEMPTS_FACTOR * avg_n
        while n < avg_n:
            if tries >= max_tries:
                raise AcquisitionError(
                    f"Acquisition failed: only {n} of {avg_n} valid captures after "
                    f"{tries} attempts (constant signals; is the digitizer connected?)"
                )
            tries += 1
            self._timed_get_ascan()
            raws = [np.array(list(buf[:reclen]), dtype=np.int64)
                    for buf in (self._sedaq.DataADC1, self._sedaq.DataADC2)]
            if any(np.all(r == r[0]) for r in raws):
                continue
            for acc, top, r in zip(sums, tops, raws):
                acc += r - mid
                top |= top_mask(r, ADC_BITS)
            n += 1
        self._last_top = (tops[0], tops[1])
        return sums[0], sums[1]

    def _open_seq_arduino(self):
        """One Arduino instance per sequence (its constructor waits 2 s for the
        board to reset). None when there is no hardware: the temperature is then
        stored as NaN, never asked for in a modal dialog."""
        if not _HW_AVAILABLE:
            return None
        return Arduino(port=self._txt_arduino_port.text().strip(), baudrate=115200, N_avg=3)

    def _on_seq_started(self, n):
        self._acq_scroll.setEnabled(False)   # manual acquisition, gain, excitation...
        self._scanner_panel.set_sequence_active(True)
        self._scanner_panel.set_sequence_progress(0, n)

    def _on_seq_progress(self, done, n, remaining_s):
        self._scanner_panel.set_sequence_progress(done, n)
        eta = "" if remaining_s != remaining_s else f" · ~{remaining_s:.0f} s left"
        self._seq_status(f"Point {done}/{n}{eta}")

    def _on_seq_finished(self, status, text):
        self._acq_scroll.setEnabled(not getattr(self, '_scan_session_lock', False))
        self._scanner_panel.set_sequence_active(False)
        self._seq_status(f"{status}: {text}")
        self._test_seq_running = False

    def _on_seq_message(self, text):
        print(f"[sequencer] {text}")
        self._seq_status(text)

    def _on_seq_state(self, state):
        if hasattr(self, "_btn_test_run"):   # debug group exists in simulator mode only
            self._btn_test_pause.setText("Resume" if state == "paused" else "Pause")
            self._btn_test_run.setEnabled(state == "idle")
            self._btn_test_pause.setEnabled(state != "idle")
            self._btn_test_stop.setEnabled(state != "idle")

    def _seq_status(self, text):
        # Only the debug test sequence reports here; the focus tool has its own label.
        if getattr(self, "_test_seq_running", False):
            self._lbl_test_seq.setText(text)

    # -- debug test sequence (simulator only): validates the whole cycle ------
    def _build_test_sequence_group(self):
        box = QGroupBox("Debug: test sequence (simulator only)")
        form = QFormLayout(box)
        self._spin_test_n = QSpinBox()
        self._spin_test_n.setRange(2, 500)
        self._spin_test_n.setValue(10)
        self._spin_test_span = QDoubleSpinBox()
        self._spin_test_span.setRange(0.1, 100.0)
        self._spin_test_span.setValue(10.0)
        self._spin_test_span.setSuffix(" mm")
        self._spin_test_settle = QSpinBox()
        self._spin_test_settle.setRange(0, 60000)
        self._spin_test_settle.setValue(DEFAULT_SETTLE_MS)
        self._spin_test_settle.setSuffix(" ms")
        self._spin_test_avg = QSpinBox()
        self._spin_test_avg.setRange(1, 10000)
        self._spin_test_avg.setValue(DEFAULT_AVG_N)
        form.addRow("Points along lateral axis:", self._spin_test_n)
        form.addRow("Span (centred here):", self._spin_test_span)
        form.addRow("Settle:", self._spin_test_settle)
        form.addRow("Averages:", self._spin_test_avg)

        row = QHBoxLayout()
        self._btn_test_run = QPushButton("Run")
        self._btn_test_pause = QPushButton("Pause")
        self._btn_test_stop = QPushButton("Stop")
        self._btn_test_pause.setEnabled(False)
        self._btn_test_stop.setEnabled(False)
        self._btn_test_run.clicked.connect(self._on_test_seq_run)
        self._btn_test_pause.clicked.connect(self._on_test_seq_pause)
        self._btn_test_stop.clicked.connect(self._sequencer.stop)
        for b in (self._btn_test_run, self._btn_test_pause, self._btn_test_stop):
            row.addWidget(b)
        form.addRow(row)
        self._lbl_test_seq = QLabel("Idle.")
        self._lbl_test_seq.setWordWrap(True)
        form.addRow(self._lbl_test_seq)
        return box

    def _on_test_seq_run(self):
        panel = self._scanner_panel
        axis = panel.role_axis('lateral')
        limit = panel.axis_limit(axis)
        if limit is None or not panel.current_coords():
            self._lbl_test_seq.setText("Connect the scanner first.")
            return
        n = self._spin_test_n.value()
        span = min(self._spin_test_span.value(), limit)
        centre = panel.current_coords()[axis]
        lo = min(max(centre - span / 2.0, 0.0), limit - span)   # keep [lo, lo+span] inside [0, limit]
        positions = [{axis: round(float(x), 2)} for x in np.linspace(lo, lo + span, n)]   # 0.01 mm resolution

        # Measured inside Smin–Smax (read only), like the focus tool.
        smin, smax = self._get_smin_smax()
        if smax - smin < 16:
            self._lbl_test_seq.setText(f"Acquisition window Smin–Smax too short ({smin}–{smax}).")
            return

        self._plot_scan.clear()
        self._plot_scan.setTitle(f"Test sequence: envelope peak in Smin–Smax ({smin}–{smax})")
        self._plot_scan.setLabel('bottom', f"{axis} position", units='mm')
        self._plot_scan.setLabel('left', 'Envelope peak', units='a.u.')
        self._plot_scan.getAxis('bottom').enableAutoSIPrefix(False)
        self._plot_scan.getAxis('left').enableAutoSIPrefix(False)
        self._plot_scan.enableAutoRange()
        self._test_xs, self._test_y1, self._test_y2 = [], [], []
        self._test_curve1 = self._plot_scan.plot(
            pen=pg.mkPen((255, 0, 0), width=1), symbol='o', symbolSize=6,
            symbolBrush=(255, 0, 0))
        self._test_curve2 = self._plot_scan.plot(
            pen=pg.mkPen((255, 255, 0), width=1), symbol='o', symbolSize=6,
            symbolBrush=(255, 255, 0))
        self._test_axis = axis

        self._test_seq_running = True
        reason = self._sequencer.start(
            positions, self._spin_test_settle.value(), self._spin_test_avg.value(),
            lambda ch1, ch2: (window_peak(ch1, smin, smax).amp,
                              window_peak(ch2, smin, smax).amp),
            temp_after=[n - 1],
            validate_fn=panel.validate_position,
        )
        if reason:
            self._test_seq_running = False
            self._lbl_test_seq.setText(reason)
            return
        self._show_scanner_plot()

    def _on_test_seq_pause(self):
        if self._sequencer.state == "paused":
            self._sequencer.resume()
        else:
            self._sequencer.pause()

    def _on_test_point(self, i, coords, value):
        if not getattr(self, "_test_seq_running", False):
            return      # another tool's sequence (e.g. focus)
        try:
            self._test_xs.append(coords[self._test_axis])
            self._test_y1.append(value[0])
            self._test_y2.append(value[1])
            self._test_curve1.setData(self._test_xs, self._test_y1)
            self._test_curve2.setData(self._test_xs, self._test_y2)
        except Exception as e:
            print(f"[test sequence] {e}")

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
        if experiment_name is not None:      # same name, shared builder (also for SCAN)
            self._txt_exp_name.setText(experiment_name(
                self._txt_pva_pct.text(), self._txt_additive_pct.text(),
                self._txt_sample_id.text(), self._txt_cycles.text(), "US", ts))
            return
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

        specimen = self._specimen_dict()
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
                "AvgSamplesNum":   self._get_avg_n(),
                "RecLen":          self._reclen,
                "Smin":            st.Smin,
                "Smax":            st.Smax,
                "Slen":            st.Smax - st.Smin,
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

        _start = DATA_DIR if os.path.isdir(DATA_DIR) else os.path.expanduser("~")
        save_dir = QFileDialog.getExistingDirectory(
            self, "Choose save folder", _start
        )
        if not save_dir:
            return

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
                    base_dir=save_dir,
                    exp_name=self._txt_exp_name.text().strip() or None,
                )
                self._lbl_save_status.setText(f"Saved: {os.path.basename(exp_dir)}")
                QMessageBox.information(self, "Saved",
                                        f"Experiment saved to:\n  {exp_dir}")
            else:
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
            "cursor":                self._chk_cursor.isChecked(),
            "full_scale_lines":      self._chk_fullscale.isChecked(),
            "emission_blank":        self._spin_blank.value(),
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
            "avg_n":                 self._txt_avg_n.text(),
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
        self._chk_cursor.setChecked(d.get("cursor", True))
        self._chk_fullscale.setChecked(d.get("full_scale_lines", True))
        if d.get("emission_blank") is not None:
            self._spin_blank.setValue(int(d["emission_blank"]))
            self._blank_from_session = True
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
        self._txt_avg_n.setText(d.get("avg_n",               str(AVG_N)))
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
