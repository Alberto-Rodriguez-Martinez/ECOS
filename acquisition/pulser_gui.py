"""
pulser_gui.py  —  Real-time laboratory GUI for pulser control and signal acquisition
ECOS project · Universidad Miguel Hernández · Dpto. Ingeniería de Comunicaciones
Author: A. Rodríguez-Martínez

Requires (Python 32-bit): PyQt5, pyqtgraph, numpy
Hardware: KTU SeDaq digitizer (SeDaqDLL.dll)

Window layout — widescreen 70/30:
  ┌──────────────────────────────┬──────────────────┐
  │   Left 70% — Signal plots    │  Right 30%        │
  │  ┌────────────────────────┐  │  [Pulser Control] │
  │  │  Zoom plot (large)     │  │  [Acquisition]    │
  │  └────────────────────────┘  │  [GenCode]        │
  │  ┌────────────────────────┐  │                   │
  │  │  Overview + region     │  │                   │
  │  └────────────────────────┘  │                   │
  └──────────────────────────────┴──────────────────┘
"""

import sys
import os
import json
import datetime
import argparse
import time

_TOOLS_DIR_EARLY = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
os.chdir(_TOOLS_DIR_EARLY)
os.add_dll_directory(_TOOLS_DIR_EARLY)

if sys.maxsize <= 2**32:
    _anaconda32_bin = r"C:\ProgramData\Anaconda32\Library\bin"
    if os.path.isdir(_anaconda32_bin):
        os.add_dll_directory(_anaconda32_bin)

import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QComboBox,
    QCheckBox, QPushButton, QPlainTextEdit,
    QStackedWidget, QFileDialog, QMessageBox,
    QSplitter, QAction, QScrollArea,
)
from PyQt5.QtCore import QTimer, Qt

import pyqtgraph as pg

# ---------------------------------------------------------------------------
# Path setup — tools/ contains SeDaq.py, GenCode_ToolBox.py, etc.
# ---------------------------------------------------------------------------
_TOOLS_DIR = _TOOLS_DIR_EARLY
sys.path.insert(0, _TOOLS_DIR)

# ---------------------------------------------------------------------------
# CLI arguments — parsed early so --demo can suppress the DLL import.
# ---------------------------------------------------------------------------
_arg_parser = argparse.ArgumentParser(description="ECOS Pulser GUI")
_arg_parser.add_argument(
    "--demo", action="store_true",
    help="Run in demo mode — skip hardware import, use simulated signals."
)
_ARGS = _arg_parser.parse_args()

# ---------------------------------------------------------------------------
# Hardware import — skipped entirely when --demo is passed.
# If the DLL is absent at runtime the GUI falls back to demo mode anyway.
# ---------------------------------------------------------------------------
if _ARGS.demo:
    _HW_AVAILABLE = False
    print("[pulser_gui] Demo mode — hardware import skipped (--demo flag).")
else:
    try:
        from SeDaq import SeDaqDLL
        from GenCode_ToolBox import MakeGenCode
        _HW_AVAILABLE = True
        print("[pulser_gui] Hardware modules loaded OK.")
    except Exception as _hw_err:
        _HW_AVAILABLE = False
        print(f"[pulser_gui] Demo mode — hardware not available: {_hw_err}")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RECLEN    = 16384   # samples — default digitizer record length
DEFAULT_GAIN_CH1  = 60
DEFAULT_GAIN_CH2  = 20
DEFAULT_ACQ_FS    = 100e6   # Hz — digitizer sampling frequency
DEFAULT_GEN_FS    = 200e6   # Hz — generator (KTU pulser) clock frequency
REALTIME_INTERVAL = 100     # ms — timer period ≈ 10 fps

SIGNAL_YMIN = -0.5          # normalised signal range lower bound
SIGNAL_YMAX =  0.5          # normalised signal range upper bound

# Bits per sample → quantisation levels (2^B).
# GetAScan returns raw unsigned integers in [0, Quantiz_Levels-1].
BITS_OPTIONS = {
    "8 bit":  256,
    "10 bit": 1024,
    "12 bit": 4096,
}


# ===========================================================================
#  _DemoSeDaq — drop-in replacement when hardware is not available
# ===========================================================================
class _DemoSeDaq:
    """
    Simulates SeDaqDLL with Gaussian noise.
    DataADC1 / DataADC2 are plain Python lists so they share the same
    slice syntax as the ctypes arrays returned by the real DLL.
    """

    def __init__(self):
        self.RecLen = DEFAULT_RECLEN
        self.DataADC1 = [512] * DEFAULT_RECLEN
        self.DataADC2 = [512] * DEFAULT_RECLEN

    def GetAScan(self):
        """Fill both channels with random noise centred on mid-scale (512)."""
        noise1 = np.random.normal(512, 30, self.RecLen).astype(int)
        noise2 = np.random.normal(512, 20, self.RecLen).astype(int)
        self.DataADC1 = list(noise1)
        self.DataADC2 = list(noise2)

    def SetRecLen(self, reclen):
        self.RecLen = reclen
        self.DataADC1 = [512] * reclen
        self.DataADC2 = [512] * reclen

    def UpdateGenCode(self, gencode):
        print(f"[Demo] UpdateGenCode — length = {len(gencode)} bytes")

    # Mirror the SeDaqDLL wrapper methods used by the GUI
    def SetGain1(self, gain):
        print(f"[Demo] SetGain1 = {gain}")

    def SetGain2(self, gain):
        print(f"[Demo] SetGain2 = {gain}")

    def SetExtVoltage(self, voltage):
        print(f"[Demo] SetExtVoltage = {voltage}")

    def SetRelay(self, mode):
        print(f"[Demo] SetRelay = {mode}")


# ===========================================================================
#  PulserGUI — main window
# ===========================================================================
class PulserGUI(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECOS Pulser GUI")
        self.resize(1400, 800)

        # ── Hardware connection ───────────────────────────────────────────
        if _HW_AVAILABLE:
            try:
                self._sedaq = SeDaqDLL()  # DLL path resolved relative to SeDaq.py location
                self._sedaq.SetRecLen(DEFAULT_RECLEN)
                time.sleep(0.5)   # wait for firmware to stabilise after connection
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

        self._reclen = DEFAULT_RECLEN  # kept in sync with hardware
        self._running = True           # real-time acquisition state

        # ── Build UI ─────────────────────────────────────────────────────
        self._build_menu()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 7)   # left  70 %
        splitter.setStretchFactor(1, 3)   # right 30 %
        main_layout.addWidget(splitter)

        # ── Real-time acquisition timer ───────────────────────────────────
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_plots)
        self._timer.start(REALTIME_INTERVAL)

    # =======================================================================
    #  Window resize
    # =======================================================================
    def resizeEvent(self, event):
        self._timer.stop()
        super().resizeEvent(event)
        self._timer.start(REALTIME_INTERVAL)

    # =======================================================================
    #  Menu bar
    # =======================================================================
    def _build_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")

        act_save = QAction("Save Session", self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self._save_session)
        file_menu.addAction(act_save)

        act_load = QAction("Load Session", self)
        act_load.setShortcut("Ctrl+O")
        act_load.triggered.connect(self._load_session)
        file_menu.addAction(act_load)

    # =======================================================================
    #  Left panel — signal visualisation
    # =======================================================================
    def _build_left_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Channel visibility toggles ────────────────────────────────────
        chk_row = QHBoxLayout()
        chk_row.addWidget(QLabel("Show:"))
        self._chk_ch1_vis = QCheckBox("Ch1")
        self._chk_ch2_vis = QCheckBox("Ch2")
        self._chk_ch1_vis.setChecked(True)
        self._chk_ch2_vis.setChecked(True)
        self._chk_ch1_vis.toggled.connect(self._toggle_ch1_vis)
        self._chk_ch2_vis.toggled.connect(self._toggle_ch2_vis)
        chk_row.addWidget(self._chk_ch1_vis)
        chk_row.addWidget(self._chk_ch2_vis)
        chk_row.addStretch()
        layout.addLayout(chk_row)

        # ── Zoom plot (large, top) ────────────────────────────────────────
        self._plot_zoom = pg.PlotWidget(title="Signal — zoom region")
        self._plot_zoom.setLabel('left', 'Amplitude', units='a.u.')
        self._plot_zoom.getAxis('left').enableAutoSIPrefix(False)
        self._plot_zoom.setLabel('bottom', 'Sample')
        self._plot_zoom.showGrid(x=True, y=True, alpha=0.3)
        self._plot_zoom.addLegend()
        # Fix Y range to ±0.5 — disable auto-scale and mouse Y interaction
        self._plot_zoom.enableAutoRange(axis='y', enable=False)
        self._plot_zoom.setYRange(-0.5, 0.5, padding=0)
        self._plot_zoom.setLimits(xMin=0, xMax=self._reclen, yMin=-0.5, yMax=0.5)
        self._plot_zoom.getViewBox().setMouseEnabled(y=False)
        self._curve_zoom_ch1 = self._plot_zoom.plot(
            pen=pg.mkPen('c', width=1), name="Ch1"
        )
        self._curve_zoom_ch2 = self._plot_zoom.plot(
            pen=pg.mkPen('y', width=1), name="Ch2"
        )
        # Crosshair on zoom plot
        self._vline_time = pg.InfiniteLine(angle=90, movable=False, pen='w')
        self._vline_time.setVisible(False)
        self._plot_zoom.addItem(self._vline_time)
        self._cursor_text_time = pg.TextItem(anchor=(0, 1), color='white')
        self._plot_zoom.addItem(self._cursor_text_time)
        self._cursor_text_time.hide()

        self._clip_text = pg.TextItem(
            text=u'\u26a0 CLIPPING', color='white', anchor=(1, 0)
        )
        self._clip_text.setPos(self._reclen, 0.45)
        self._clip_text.hide()
        self._clip_text.setHtml(
            '<div style="background-color:red; padding:3px;">\u26a0 CLIPPING</div>'
        )
        self._plot_zoom.addItem(self._clip_text)

        # ── Spectrum plot ─────────────────────────────────────────────────
        self._plot_spectrum = pg.PlotWidget(title="Spectrum")
        self._plot_spectrum.setLabel('left', 'Amplitude')
        self._plot_spectrum.setLabel('bottom', 'Frequency (MHz)')
        self._plot_spectrum.showGrid(x=True, y=True, alpha=0.3)
        self._plot_spectrum.addLegend()
        self._curve_spec_ch1 = self._plot_spectrum.plot(
            pen=pg.mkPen('c', width=1), name="Ch1"
        )
        self._curve_spec_ch2 = self._plot_spectrum.plot(
            pen=pg.mkPen('y', width=1), name="Ch2"
        )
        self._vline_spec = pg.InfiniteLine(angle=90, movable=False, pen='w')
        self._vline_spec.setVisible(False)
        self._plot_spectrum.addItem(self._vline_spec)
        self._cursor_text_spec = pg.TextItem(anchor=(0, 1), color='white')
        self._plot_spectrum.addItem(self._cursor_text_spec)
        self._cursor_text_spec.hide()
        vb = self._plot_spectrum.getViewBox()
        vb.setMouseEnabled(x=False, y=False)
        vb.enableAutoRange(axis='y', enable=True)

        # ── Top area: zoom (left) | spectrum (right) ──────────────────────
        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.addWidget(self._plot_zoom)
        top_splitter.addWidget(self._plot_spectrum)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 1)
        layout.addWidget(top_splitter, stretch=3)

        # ── Overview plot (small, bottom) ─────────────────────────────────
        self._plot_overview = pg.PlotWidget(title="Overview — full record")
        self._plot_overview.setLabel('bottom', 'Sample')
        self._plot_overview.setMaximumHeight(180)
        # Fix axes: X = [0, RecLen], Y = [±0.5] — no mouse interaction
        self._plot_overview.setXRange(0, self._reclen, padding=0)
        self._plot_overview.setYRange(SIGNAL_YMIN, SIGNAL_YMAX, padding=0)
        self._plot_overview.setLimits(
            xMin=0, xMax=self._reclen,
            yMin=SIGNAL_YMIN, yMax=SIGNAL_YMAX
        )
        self._plot_overview.getViewBox().setMouseEnabled(x=False, y=False)

        self._curve_ov_ch1 = self._plot_overview.plot(pen=pg.mkPen('c', width=1))
        self._curve_ov_ch2 = self._plot_overview.plot(pen=pg.mkPen('y', width=1))

        # LinearRegionItem: clipped to [0, RecLen]
        self._region = pg.LinearRegionItem(
            values=[0, self._reclen // 4],
            bounds=[0, self._reclen]        # hard limits — cannot drag outside
        )
        self._region.setZValue(10)
        self._plot_overview.addItem(self._region)

        self._region.sigRegionChanged.connect(self._on_region_changed)
        self._plot_zoom.sigXRangeChanged.connect(self._on_zoom_xrange_changed)
        self._plot_zoom.scene().sigMouseMoved.connect(self._on_mouse_moved_time)
        self._plot_spectrum.scene().sigMouseMoved.connect(self._on_mouse_moved_spec)

        layout.addWidget(self._plot_overview, stretch=1)
        return widget

    # =======================================================================
    #  Right panel — three control blocks in a scroll area
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
        layout.addWidget(self._build_block_acq())
        layout.addWidget(self._build_block_spectrum())
        layout.addWidget(self._build_block_gencode())
        layout.addStretch()
        return scroll

    # =======================================================================
    #  Block 1 — Pulser Control
    # =======================================================================
    def _build_block_pulser(self):
        box = QGroupBox("Pulser Control")
        form = QFormLayout(box)

        self._txt_gain_ch1 = QLineEdit(str(DEFAULT_GAIN_CH1))
        self._txt_gain_ch2 = QLineEdit(str(DEFAULT_GAIN_CH2))
        self._txt_voltage  = QLineEdit("100.0")
        self._txt_acq_fs   = QLineEdit("100e6")

        self._txt_gain_ch1.editingFinished.connect(self._on_gain_ch1_changed)
        self._txt_gain_ch2.editingFinished.connect(self._on_gain_ch2_changed)
        self._txt_voltage.editingFinished.connect(self._on_voltage_changed)

        self._cmb_bits = QComboBox()
        for label in BITS_OPTIONS:
            self._cmb_bits.addItem(label)
        self._cmb_bits.setCurrentText("10 bit")

        self._btn_relay = QPushButton("RELAY: OFF")
        self._btn_relay.setCheckable(True)
        self._btn_relay.setChecked(False)
        self._btn_relay.toggled.connect(self._on_relay_toggled)

        form.addRow("Gain Ch1:",     self._txt_gain_ch1)
        form.addRow("Gain Ch2:",     self._txt_gain_ch2)
        form.addRow("Voltage:",      self._txt_voltage)
        form.addRow("Acq Fs (Hz):",  self._txt_acq_fs)
        form.addRow("Bits/sample:",  self._cmb_bits)
        form.addRow("",              self._btn_relay)
        return box

    # =======================================================================
    #  Block 2 — Acquisition
    # =======================================================================
    def _build_block_acq(self):
        box = QGroupBox("Acquisition")
        layout = QVBoxLayout(box)

        # RecLen control
        reclen_row = QHBoxLayout()
        reclen_row.addWidget(QLabel("RecLen (samples):"))
        self._txt_reclen = QLineEdit(str(DEFAULT_RECLEN))
        self._txt_reclen.setMaximumWidth(80)
        self._txt_reclen.editingFinished.connect(self._on_reclen_changed)
        reclen_row.addWidget(self._txt_reclen)
        reclen_row.addStretch()
        layout.addLayout(reclen_row)

        # Channels to save
        chk_row = QHBoxLayout()
        chk_row.addWidget(QLabel("Channels:"))
        self._chk_acq_ch1 = QCheckBox("Ch1")
        self._chk_acq_ch2 = QCheckBox("Ch2")
        self._chk_acq_ch1.setChecked(True)
        self._chk_acq_ch2.setChecked(True)
        chk_row.addWidget(self._chk_acq_ch1)
        chk_row.addWidget(self._chk_acq_ch2)
        chk_row.addStretch()
        layout.addLayout(chk_row)

        # Number of A-scans to average
        n_row = QHBoxLayout()
        n_row.addWidget(QLabel("N Ascans avg:"))
        self._txt_n_avg = QLineEdit("1")
        self._txt_n_avg.setMaximumWidth(60)
        n_row.addWidget(self._txt_n_avg)
        n_row.addStretch()
        layout.addLayout(n_row)

        # Stop / Resume real-time display button
        self._btn_stop = QPushButton("⏹  Stop")
        self._btn_stop.setCheckable(True)
        self._btn_stop.setChecked(False)
        self._btn_stop.toggled.connect(self._on_stop_toggled)
        layout.addWidget(self._btn_stop)

        # Acquire buttons
        btn_ch1  = QPushButton("Acquire Ch1")
        btn_ch2  = QPushButton("Acquire Ch2")
        btn_both = QPushButton("Acquire Both")
        btn_ch1.clicked.connect(lambda: self._acquire("ch1"))
        btn_ch2.clicked.connect(lambda: self._acquire("ch2"))
        btn_both.clicked.connect(lambda: self._acquire("both"))
        layout.addWidget(btn_ch1)
        layout.addWidget(btn_ch2)
        layout.addWidget(btn_both)

        # Comment
        layout.addWidget(QLabel("Comment:"))
        self._txt_comment = QPlainTextEdit()
        self._txt_comment.setMaximumHeight(60)
        self._txt_comment.setPlaceholderText("Free text note for this acquisition…")
        layout.addWidget(self._txt_comment)
        return box

    # =======================================================================
    #  Block 3 — Spectrum
    # =======================================================================
    def _build_block_spectrum(self):
        box = QGroupBox("Spectrum")
        form = QFormLayout(box)

        self._txt_spec_fmin  = QLineEdit("0")
        self._txt_spec_fmax  = QLineEdit("15")
        self._txt_spec_nfft  = QLineEdit("4096")
        self._cmb_spec_scale = QComboBox()
        self._cmb_spec_scale.addItems(["Linear", "dB"])
        self._cmb_spec_scale.currentIndexChanged.connect(self._on_spec_scale_changed)

        btn_compute = QPushButton("Compute Spectrum")
        btn_compute.clicked.connect(self._compute_spectrum)

        form.addRow("Fmin (MHz):",   self._txt_spec_fmin)
        form.addRow("Fmax (MHz):",   self._txt_spec_fmax)
        form.addRow("N FFT points:", self._txt_spec_nfft)
        form.addRow("Scale:",        self._cmb_spec_scale)
        form.addRow("",              btn_compute)
        return box

    # =======================================================================
    #  Spectrum scale toggle
    # =======================================================================
    def _on_spec_scale_changed(self, index):
        label = "Amplitude (dB)" if index == 1 else "Amplitude"
        self._plot_spectrum.setLabel('left', label)

    # =======================================================================
    #  Compute spectrum
    # =======================================================================
    def _compute_spectrum(self):
        """FFT of the current zoom-region data → update spectrum plot."""
        try:
            acq_fs = float(self._txt_acq_fs.text())
            nfft   = int(self._txt_spec_nfft.text())
            fmin   = float(self._txt_spec_fmin.text())
            fmax   = float(self._txt_spec_fmax.text())
        except ValueError as e:
            QMessageBox.warning(self, "Spectrum error", f"Invalid parameter: {e}")
            return

        use_db = self._cmb_spec_scale.currentText() == "dB"

        x1, y1 = self._curve_zoom_ch1.getData()
        x2, y2 = self._curve_zoom_ch2.getData()

        if (y1 is None or len(y1) == 0) and (y2 is None or len(y2) == 0):
            QMessageBox.warning(self, "Spectrum", "No data in zoom region yet.")
            return

        freq = np.fft.rfftfreq(nfft, d=1.0 / acq_fs) / 1e6  # → MHz
        mask = (freq >= fmin) & (freq <= fmax)
        freq_m = freq[mask]

        def _spectrum(y):
            if y is None or len(y) == 0:
                return None
            seg = y[:nfft] if len(y) >= nfft else np.pad(y, (0, nfft - len(y)))
            spec = np.abs(np.fft.rfft(seg, n=nfft)) / nfft
            if use_db:
                spec = 20.0 * np.log10(np.maximum(spec, 1e-12))
                spec = np.maximum(spec, -120.0)
            return spec[mask]

        s1 = _spectrum(y1)
        s2 = _spectrum(y2)

        if s1 is not None and self._chk_ch1_vis.isChecked():
            self._curve_spec_ch1.setData(freq_m, s1)
        else:
            self._curve_spec_ch1.setData([], [])

        if s2 is not None and self._chk_ch2_vis.isChecked():
            self._curve_spec_ch2.setData(freq_m, s2)
        else:
            self._curve_spec_ch2.setData([], [])

        vb = self._plot_spectrum.getViewBox()
        vb.setXRange(fmin, fmax, padding=0)
        vb.setLimits(xMin=fmin, xMax=fmax)

    # =======================================================================
    #  Crosshair cursor handlers
    # =======================================================================
    def _on_mouse_moved_time(self, pos):
        vb = self._plot_zoom.getViewBox()
        if not self._plot_zoom.sceneBoundingRect().contains(pos):
            self._vline_time.hide()
            self._cursor_text_time.hide()
            return
        mp = vb.mapSceneToView(pos)
        x = mp.x()
        self._vline_time.setPos(x)
        self._vline_time.show()

        ch1_x, ch1_y = self._curve_zoom_ch1.getData()
        ch2_x, ch2_y = self._curve_zoom_ch2.getData()

        def get_val(xs, ys):
            if xs is None or ys is None or len(xs) == 0:
                return "---"
            i = int(np.clip(np.searchsorted(xs, x), 0, len(ys) - 1))
            return f"{ys[i]:.4f}"

        v1 = get_val(ch1_x, ch1_y)
        v2 = get_val(ch2_x, ch2_y)
        self._cursor_text_time.setPos(x, mp.y())
        self._cursor_text_time.setText(f"Sample: {int(x)}\nCh1: {v1}\nCh2: {v2}")
        self._cursor_text_time.show()

    def _on_mouse_moved_spec(self, pos):
        vb = self._plot_spectrum.getViewBox()
        if not self._plot_spectrum.sceneBoundingRect().contains(pos):
            self._vline_spec.hide()
            self._cursor_text_spec.hide()
            return
        mp = vb.mapSceneToView(pos)
        x = mp.x()
        self._vline_spec.setPos(x)
        self._vline_spec.show()

        ch1_x, ch1_y = self._curve_spec_ch1.getData()
        ch2_x, ch2_y = self._curve_spec_ch2.getData()

        def get_val(xs, ys):
            if xs is None or ys is None or len(xs) == 0:
                return "---"
            i = int(np.clip(np.searchsorted(xs, x), 0, len(ys) - 1))
            return f"{ys[i]:.4f}"

        v1 = get_val(ch1_x, ch1_y)
        v2 = get_val(ch2_x, ch2_y)
        self._cursor_text_spec.setPos(x, mp.y())
        self._cursor_text_spec.setText(f"Freq: {x:.3f} MHz\nCh1: {v1}\nCh2: {v2}")
        self._cursor_text_spec.show()

    # =======================================================================
    #  Block 4 — GenCode Waveform Generator
    # =======================================================================
    def _build_block_gencode(self):
        box = QGroupBox("GenCode Waveform Generator")
        layout = QVBoxLayout(box)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Excitation:"))
        self._cmb_excitation = QComboBox()
        self._cmb_excitation.addItems(["Pulse", "Chirp", "Burst"])
        self._cmb_excitation.currentIndexChanged.connect(self._on_excitation_changed)
        type_row.addWidget(self._cmb_excitation)
        layout.addLayout(type_row)

        fs_row = QHBoxLayout()
        fs_row.addWidget(QLabel("Generator Fs (Hz):"))
        self._txt_gen_fs = QLineEdit("200e6")
        fs_row.addWidget(self._txt_gen_fs)
        layout.addLayout(fs_row)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_pulse_page())
        self._stack.addWidget(self._build_chirp_page())
        self._stack.addWidget(self._build_burst_page())
        layout.addWidget(self._stack)

        btn_gen = QPushButton("Generate && Upload")
        btn_gen.setStyleSheet("font-weight: bold;")
        btn_gen.clicked.connect(self._generate_upload)
        layout.addWidget(btn_gen)
        return box

    def _build_pulse_page(self):
        page = QWidget()
        form = QFormLayout(page)
        self._cmb_pulse_param    = QComboBox()
        self._cmb_pulse_param.addItems(["frequency", "duration", "samples"])
        self._txt_pulse_paramval = QLineEdit("5e6")
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
        self._txt_chirp_fend     = QLineEdit("8e6")
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
        self._txt_burst_fo       = QLineEdit("5e6")
        self._txt_burst_cycles   = QLineEdit("5")
        self._cmb_burst_polarity = QComboBox()
        self._cmb_burst_polarity.addItems(["2 (bipolar)", "1 (positive)", "-1 (negative)"])
        form.addRow("Fo (Hz):",   self._txt_burst_fo)
        form.addRow("NoCycles:",  self._txt_burst_cycles)
        form.addRow("Polarity:",  self._cmb_burst_polarity)
        return page

    # =======================================================================
    #  Real-time plot update  (called by QTimer)
    # =======================================================================
    def _update_plots(self):
        """
        Acquire 1 A-scan and refresh both plots.
        Skipped when _running is False (Stop button pressed).
        """
        if not self._running:
            return

        try:
            quant = BITS_OPTIONS[self._cmb_bits.currentText()]

            self._sedaq.GetAScan()

            ch1 = self._raw_to_float(self._sedaq.DataADC1, self._reclen, quant)
            ch2 = self._raw_to_float(self._sedaq.DataADC2, self._reclen, quant)

            rmin, rmax = self._region.getRegion()
            smin = max(0, int(rmin))
            smax = min(self._reclen, int(rmax))

            x_full = np.arange(self._reclen)
            x_zoom = np.arange(smin, smax)

            # Overview curves
            self._curve_ov_ch1.setData(x_full, ch1) if self._chk_ch1_vis.isChecked() \
                else self._curve_ov_ch1.setData([], [])
            self._curve_ov_ch2.setData(x_full, ch2) if self._chk_ch2_vis.isChecked() \
                else self._curve_ov_ch2.setData([], [])

            # Zoom curves
            if smax > smin:
                self._curve_zoom_ch1.setData(x_zoom, ch1[smin:smax]) \
                    if self._chk_ch1_vis.isChecked() \
                    else self._curve_zoom_ch1.setData([], [])
                self._curve_zoom_ch2.setData(x_zoom, ch2[smin:smax]) \
                    if self._chk_ch2_vis.isChecked() \
                    else self._curve_zoom_ch2.setData([], [])

            visible_ch1 = ch1[smin:smax] if self._chk_ch1_vis.isChecked() else np.array([])
            visible_ch2 = ch2[smin:smax] if self._chk_ch2_vis.isChecked() else np.array([])
            all_visible = np.concatenate([visible_ch1, visible_ch2])
            if len(all_visible) > 0 and np.abs(all_visible).max() >= 0.45:
                self._clip_text.setPos(rmax, 0.45)
                self._clip_text.show()
            else:
                self._clip_text.hide()

        except Exception as e:
            print(f"[_update_plots] {e}")

    @staticmethod
    def _raw_to_float(data_buffer, reclen, quant):
        """
        Convert raw ADC buffer to normalised, DC-free float array.
        raw counts ∈ [0, quant-1] → normalised ∈ [-0.5, +0.5] → subtract mean
        """
        arr = np.array(list(data_buffer[:reclen]), dtype=float)
        arr = (arr - quant / 2.0) / quant
        arr = arr - np.mean(arr)
        return arr

    # =======================================================================
    #  Zoom / region synchronisation
    # =======================================================================
    def _on_region_changed(self):
        rmin, rmax = self._region.getRegion()
        self._plot_zoom.blockSignals(True)
        self._plot_zoom.setXRange(rmin, rmax, padding=0)
        self._plot_zoom.blockSignals(False)

    def _on_zoom_xrange_changed(self, _vb, x_range):
        # Clip to valid range before syncing region
        xmin = max(0, x_range[0])
        xmax = min(self._reclen, x_range[1])
        self._region.blockSignals(True)
        self._region.setRegion([xmin, xmax])
        self._region.blockSignals(False)

    def _toggle_ch1_vis(self, checked):
        if not checked:
            self._curve_zoom_ch1.setData([], [])
            self._curve_ov_ch1.setData([], [])

    def _toggle_ch2_vis(self, checked):
        if not checked:
            self._curve_zoom_ch2.setData([], [])
            self._curve_ov_ch2.setData([], [])

    # =======================================================================
    #  Stop / Resume toggle
    # =======================================================================
    def _on_stop_toggled(self, checked):
        self._running = not checked
        self._btn_stop.setText("▶  Resume" if checked else "⏹  Stop")

    # =======================================================================
    #  RecLen change
    # =======================================================================
    def _on_reclen_changed(self):
        """Update RecLen on hardware and refresh plot limits."""
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

        # Update overview axis limits and region bounds
        self._plot_overview.setXRange(0, reclen, padding=0)
        self._plot_overview.setLimits(xMin=0, xMax=reclen)
        self._plot_zoom.setLimits(xMin=0, xMax=self._reclen)
        self._region.setBounds([0, reclen])
        # Clip current region to new bounds
        rmin, rmax = self._region.getRegion()
        self._region.setRegion([max(0, rmin), min(reclen, rmax)])

    # =======================================================================
    #  Relay toggle
    # =======================================================================
    def _on_relay_toggled(self, checked):
        state = 0 if checked else 1  # TODO: verify hardware encoding (KTU protocol: ON=0, OFF=1 per SeDaq.pyc)
        self._btn_relay.setText(f"RELAY: {'ON' if checked else 'OFF'}")
        try:
            self._sedaq.SetRelay(state)
        except Exception as e:
            print(f"[Relay] {e}")

    # ── Gain / voltage hardware wiring ──────────────────────────────────────

    def _on_gain_ch1_changed(self):
        try:
            gain = float(self._txt_gain_ch1.text())
            self._sedaq.SetGain1(gain)
        except ValueError:
            pass
        except Exception as e:
            print(f"[SetGain1] {e}")

    def _on_gain_ch2_changed(self):
        try:
            gain = float(self._txt_gain_ch2.text())
            self._sedaq.SetGain2(gain)
        except ValueError:
            pass
        except Exception as e:
            print(f"[SetGain2] {e}")

    def _on_voltage_changed(self):
        try:
            voltage = int(float(self._txt_voltage.text()))
            self._sedaq.SetExtVoltage(voltage)
        except ValueError:
            pass
        except Exception as e:
            print(f"[SetExtVoltage] {e}")

    # =======================================================================
    #  Excitation type selector
    # =======================================================================
    def _on_excitation_changed(self, index):
        self._stack.setCurrentIndex(index)

    # =======================================================================
    #  Acquisition and save
    # =======================================================================
    def _acquire(self, channels):
        """
        Acquire N averaged A-scans and save to .npy + .json.
        The real-time timer is paused during acquisition.
        """
        try:
            n_avg = int(self._txt_n_avg.text())
        except ValueError:
            QMessageBox.warning(self, "Input error", "N Ascans must be an integer.")
            return

        quant       = BITS_OPTIONS[self._cmb_bits.currentText()]
        rmin, rmax  = self._region.getRegion()
        smin        = max(0, int(rmin))
        smax        = min(self._reclen, int(rmax))

        if smax <= smin:
            QMessageBox.warning(self, "Zoom region",
                                "Zoom region is empty — adjust the region selector.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save acquisition", "",
            "NumPy files (*.npy);;All files (*)"
        )
        if not path:
            return
        base = path[:-4] if path.lower().endswith('.npy') else path

        self._timer.stop()
        try:
            acc_ch1 = np.zeros(smax - smin)
            acc_ch2 = np.zeros(smax - smin)
            n_done  = 0

            while n_done < n_avg:
                self._sedaq.GetAScan()
                raw1 = self._raw_to_float(self._sedaq.DataADC1, self._reclen, quant)
                raw2 = self._raw_to_float(self._sedaq.DataADC2, self._reclen, quant)

                seg1 = raw1[smin:smax]
                seg2 = raw2[smin:smax]

                if np.all(seg1 == 0.0) or np.all(seg2 == 0.0):
                    continue

                if channels in ("ch1", "both"):
                    acc_ch1 += seg1
                if channels in ("ch2", "both"):
                    acc_ch2 += seg2
                n_done += 1

            avg_ch1 = acc_ch1 / n_avg
            avg_ch2 = acc_ch2 / n_avg

        except Exception as e:
            QMessageBox.critical(self, "Acquisition error", str(e))
            self._timer.start(REALTIME_INTERVAL)
            return
        finally:
            self._timer.start(REALTIME_INTERVAL)

        if channels == "ch1":
            np.save(base + ".npy", avg_ch1)
        elif channels == "ch2":
            np.save(base + ".npy", avg_ch2)
        else:
            np.save(base + ".npy", np.vstack([avg_ch1, avg_ch2]))

        metadata = {
            "datetime":          datetime.datetime.now().isoformat(),
            "channels":          channels,
            "gain_ch1":          self._txt_gain_ch1.text(),
            "gain_ch2":          self._txt_gain_ch2.text(),
            "voltage":           self._txt_voltage.text(),
            "acq_fs_hz":         self._txt_acq_fs.text(),
            "bits_per_sample":   self._cmb_bits.currentText(),
            "quantiz_levels":    quant,
            "generator_fs_hz":   self._txt_gen_fs.text(),
            "excitation_type":   self._cmb_excitation.currentText(),
            "excitation_params": self._collect_excitation_params(),
            "smin":              smin,
            "smax":              smax,
            "reclen":            self._reclen,
            "n_avg":             n_avg,
            "comment":           self._txt_comment.toPlainText(),
        }
        with open(base + ".json", "w") as f:
            json.dump(metadata, f, indent=2)

        QMessageBox.information(self, "Saved",
                                f"Saved:\n  {base}.npy\n  {base}.json")

    # =======================================================================
    #  Generate & Upload GenCode
    # =======================================================================
    def _generate_upload(self):
        excitation = self._cmb_excitation.currentText()

        try:
            gen_fs = float(self._txt_gen_fs.text())
        except ValueError:
            QMessageBox.warning(self, "Input error",
                                "Generator Fs is not a valid number.")
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
            else:  # Burst
                gencode = MakeGenCode(
                    Excitation    = "Burst",
                    ParamVal      = [params["fo"], params["nocycles"]],
                    SignalPolarity = params["polarity"],
                    Fs            = gen_fs,
                )

        except Exception as e:
            QMessageBox.critical(self, "GenCode error",
                                 f"Failed to build GenCode:\n{e}")
            return

        try:
            self._sedaq.UpdateGenCode(gencode)
            QMessageBox.information(self, "GenCode",
                                    "Waveform generated and uploaded successfully.")
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
        else:  # Burst
            return {
                "fo":       float(self._txt_burst_fo.text()),
                "nocycles": int(self._txt_burst_cycles.text()),
                "polarity": _polarity(self._cmb_burst_polarity),
            }

    # =======================================================================
    #  Session save / load
    # =======================================================================
    def _collect_session(self):
        return {
            "gain_ch1":              self._txt_gain_ch1.text(),
            "gain_ch2":              self._txt_gain_ch2.text(),
            "voltage":               self._txt_voltage.text(),
            "acq_fs":                self._txt_acq_fs.text(),
            "bits_index":            self._cmb_bits.currentIndex(),
            "relay":                 self._btn_relay.isChecked(),
            "reclen":                self._txt_reclen.text(),
            "acq_ch1":               self._chk_acq_ch1.isChecked(),
            "acq_ch2":               self._chk_acq_ch2.isChecked(),
            "n_avg":                 self._txt_n_avg.text(),
            "comment":               self._txt_comment.toPlainText(),
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
            "vis_ch1":               self._chk_ch1_vis.isChecked(),
            "vis_ch2":               self._chk_ch2_vis.isChecked(),
            "region":                list(self._region.getRegion()),
        }

    def _restore_session(self, d):
        def _txt(widget, key):
            if key in d:
                widget.setText(str(d[key]))
        def _idx(combo, key):
            if key in d:
                combo.setCurrentIndex(int(d[key]))
        def _chk(checkbox, key):
            if key in d:
                checkbox.setChecked(bool(d[key]))

        _txt(self._txt_gain_ch1, "gain_ch1")
        _txt(self._txt_gain_ch2, "gain_ch2")
        _txt(self._txt_voltage,  "voltage")
        _txt(self._txt_acq_fs,   "acq_fs")
        _idx(self._cmb_bits,     "bits_index")
        if "relay" in d:
            self._btn_relay.setChecked(bool(d["relay"]))
        if "reclen" in d:
            self._txt_reclen.setText(str(d["reclen"]))
            self._on_reclen_changed()
        _chk(self._chk_acq_ch1, "acq_ch1")
        _chk(self._chk_acq_ch2, "acq_ch2")
        _txt(self._txt_n_avg,    "n_avg")
        if "comment" in d:
            self._txt_comment.setPlainText(d["comment"])
        _idx(self._cmb_excitation,      "excitation_index")
        _txt(self._txt_gen_fs,          "gen_fs")
        _idx(self._cmb_pulse_param,     "pulse_param_index")
        _txt(self._txt_pulse_paramval,  "pulse_paramval")
        _idx(self._cmb_pulse_polarity,  "pulse_polarity_index")
        _txt(self._txt_chirp_fstart,    "chirp_fstart")
        _txt(self._txt_chirp_fend,      "chirp_fend")
        _txt(self._txt_chirp_dur,       "chirp_dur")
        _idx(self._cmb_chirp_method,    "chirp_method_index")
        _txt(self._txt_chirp_phase,     "chirp_phase")
        _idx(self._cmb_chirp_polarity,  "chirp_polarity_index")
        _txt(self._txt_burst_fo,        "burst_fo")
        _txt(self._txt_burst_cycles,    "burst_cycles")
        _idx(self._cmb_burst_polarity,  "burst_polarity_index")
        _chk(self._chk_ch1_vis, "vis_ch1")
        _chk(self._chk_ch2_vis, "vis_ch2")
        if "region" in d:
            self._region.setRegion(d["region"])

    def _save_session(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session", "",
            "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        with open(path, "w") as f:
            json.dump(self._collect_session(), f, indent=2)
        QMessageBox.information(self, "Session saved", path)

    def _load_session(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Session", "",
            "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path) as f:
                d = json.load(f)
            self._restore_session(d)
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))


# ===========================================================================
#  Entry point
# ===========================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = PulserGUI()
    win.show()
    sys.exit(app.exec_())
