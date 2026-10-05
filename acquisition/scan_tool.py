# -*- coding: utf-8 -*-
"""
scan_tool.py — Line scan with live map, water references and saving (scanner phase 5).
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See task_scanner_phase5.md and scanner_tab_spec.md section 5.6.

A line scan moves the lateral axis or Z (never the beam axis, never R) over a
range [start, end] with a step, absolute or relative to the position at Start.
On every point, after the move and the settle time, the sequencer of phase 2
acquires both channels (averaged) and the tool keeps:
    - both channels, samples Smin..Smax-1 (the Acquisition window), as saved
      by every ECOS experiment;
    - the REAL position read back from the scanner after the move (the worker
      re-reads every axis: panel.current_coords()), not the requested one;
    - the front-face echo found by echo_tracking.FrontEchoTracker (beam axis
      still: prediction t_prev), for the ToF and for the point flags;
    - every map magnitude (MAGNITUDES, extensible: register_magnitude).
Points where the echo is lost (the beam leaves the sample) are marked and the
scan goes on: it never aborts for that.

Optional water references at the start and at the end (spec 5.6), with the
reference gains (Gain2 always set again after Gain1: known pulser fault) and
their own averages. The order in which the user moves the axes to take the
sample out is recorded; the way back is one move per axis in reverse order.

Temperature: read at the start, at each reference and at the end, never per
point; ONE Arduino instance for the whole scan session, closed at the end.
Without PT100: NaN and a warning at the start, never the (modal) manual dialog.

Saving: one folder per scan, database/<PVA_..._SCAN_<ts>>/ meta.json + scan.npz
(BD_Experimentos_PVA.save_scan_raw_32, schema scan-32-2.0), automatically at
the end, or on demand after a STOP. "Save to another folder…" writes a copy.
No results: they are computed later, in the analysis. The signals are stored as
the integer sums of counts of the averaged captures plus a per-point offset
(database/scan_counts.py): the host hands them over with counts_fn() after
every acquisition, and the floats every tool sees are computed from them with
scan_counts.counts_to_float, so the file rebuilds them bit for bit.

Reference drift: with both water references, the final one is compared with
the initial one on Ch1, the through-transmission channel (the ECOS s_W):
amplitude difference in dB and ToF difference by cross-correlation
(ECOS_US_ToolBox.CalcToFAscanCosine_XCRFFT). Shown on screen, saved in
meta.json, and warned about above configurable thresholds: it measures the
drift of the transmission path during the scan (temperature, gain, coupling).
Ch2 (pulse-echo) is saved in every reference but not compared, so a drift of
the pulse-echo channel alone is not covered by this metric.

Settle and averages are the scan's own, NOT the focus ones (5000 ms / 100 were
measured with 1 mm steps): defaults DEFAULT_SCAN_SETTLE_MS / DEFAULT_SCAN_AVG_N,
PENDIENTES DE CARACTERIZAR en función del paso.
"""
from __future__ import annotations

import math
import os
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np

from echo_tracking import (
    ACQ_FS, DEFAULT_BAND_SAMPLES, DEFAULT_BAND_US, DEFAULT_EDGE_MARGIN, DEFAULT_THRESHOLD,
    MIN_WINDOW_SAMPLES, FrontEchoTracker, band_samples,
)
from flatness_tool import line_flags
from ECOS_US_ToolBox import CalcToFAscanCosine_XCRFFT, Envelope
from echo_tracking import CONFIDENT_CONTRAST
from focus_tool import (
    DEFAULT_EMISSION_SAMPLE, MOVE_MM_S, POSITION_DECIMALS, FocusDebugDump, acq_time,
    format_duration, resolve_cw,
)

_DB_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                        'database'))
if _DB_DIR not in sys.path:
    sys.path.insert(0, _DB_DIR)
from scan_counts import ADC_BITS_DEFAULT, counts_to_float  # noqa: E402

PE_CHANNEL = 2
# PENDIENTES DE CARACTERIZAR en función del paso (task_scanner_phase5.md 1):
# scan steps are far smaller than the 1 mm focus steps that gave 5000 ms / 100.
DEFAULT_SCAN_SETTLE_MS = 500
DEFAULT_SCAN_AVG_N = 20
DEFAULT_SCAN_STEP_MM = 0.5
DEFAULT_REF_AVG_N = 100
LONG_SCAN_S = 30 * 60          # warn above half an hour
DEFAULT_DRIFT_DB = 0.5         # reference drift warnings: amplitude [dB] …
DEFAULT_DRIFT_NS = 20.0        # … and ToF [ns] (~0.1 °C of water over a 60 mm path)
DEFAULT_DUMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'data', 'scan_debug')
AXES4 = ('X', 'Y', 'Z', 'R')


# ===========================================================================
#  Map magnitudes (extensible without touching the scan)
# ===========================================================================
@dataclass
class PointContext:
    """What a magnitude can use on one point."""
    measure: object              # echo_tracking.PeakMeasure of the front echo
    seg: np.ndarray              # PE (Ch2) samples Smin..Smax-1
    env: np.ndarray              # its Hilbert envelope
    seg_ch1: np.ndarray          # Ch1 samples Smin..Smax-1
    fs: float
    emission_sample: int


@dataclass
class Magnitude:
    label: str
    unit: str
    fn: Callable[[PointContext], float]
    uses_echo: bool = False      # depends on the tracked front echo (lost echo → NaN)


MAGNITUDES = OrderedDict()


def register_magnitude(name, label, unit, fn, uses_echo=False):
    """Add a map magnitude: fn(PointContext) -> float. The scan computes all of them."""
    MAGNITUDES[name] = Magnitude(label, unit, fn, uses_echo)


register_magnitude('amplitude', 'Max. envelope in the window (PE)', '',
                   lambda c: float(np.max(c.env)))
register_magnitude('tof', 'Front-echo time of flight', 'µs',
                   lambda c: (c.measure.index_frac - c.emission_sample) / c.fs * 1e6,
                   uses_echo=True)
register_magnitude('energy', 'Energy in the window (PE)', 'a.u.·µs',
                   lambda c: float(np.sum(c.seg * c.seg)) / c.fs * 1e6)


def compute_magnitudes(ctx, lost=False):
    out = {}
    for name, mag in MAGNITUDES.items():
        if mag.uses_echo and lost:
            out[name] = float('nan')
            continue
        try:
            out[name] = float(mag.fn(ctx))
        except Exception:
            out[name] = float('nan')
    return out


# ===========================================================================
#  Pure part: positions, estimate, data
# ===========================================================================
def line_positions(start, end, step, limit):
    """
    start, start ± step, ... up to end (inclusive within rounding), in the
    direction of end. Points outside [0, limit] are dropped. Returns
    (positions, clipped).
    """
    if not (step > 0):
        raise ValueError('the step must be positive')
    span = end - start
    n = int(math.floor(abs(span) / step + 1e-9)) + 1
    sign = 1.0 if span >= 0 else -1.0
    xs, clipped = [], False
    for k in range(n):
        x = round(start + sign * k * step, POSITION_DECIMALS)
        if x < 0.0 or x > limit:
            clipped = True
            continue
        xs.append(x)
    return xs, clipped


@dataclass
class ScanParams:
    axis_role: str = 'lateral'           # 'lateral' or 'z'
    mode: str = 'relative'               # 'relative' (to the position at Start) or 'absolute'
    start: float = -5.0
    end: float = 5.0
    step: float = DEFAULT_SCAN_STEP_MM
    settle_ms: int = DEFAULT_SCAN_SETTLE_MS
    avg_n: int = DEFAULT_SCAN_AVG_N
    references: bool = False
    ref_gain1: float = 0.0
    ref_gain2: float = 0.0
    ref_avg_n: int = DEFAULT_REF_AVG_N
    operator: str = 'Sebas'
    comment: str = ''
    edge_margin: float = DEFAULT_EDGE_MARGIN
    band_us: float = DEFAULT_BAND_US
    threshold: float = DEFAULT_THRESHOLD
    emission_sample: int = DEFAULT_EMISSION_SAMPLE
    debug_dump: bool = False
    drift_tol_db: float = DEFAULT_DRIFT_DB
    drift_tol_ns: float = DEFAULT_DRIFT_NS


class ScanPlan:
    """Positions of a line scan from the start coordinates (no Qt, no hardware)."""

    def __init__(self, params, start_coords, lat_axis, beam_axis, limits):
        if params.axis_role not in ('lateral', 'z'):
            raise ValueError("axis must be 'lateral' or 'z'")
        self.params = params
        self.axis = lat_axis if params.axis_role == 'lateral' else 'Z'
        self.beam_axis = beam_axis
        self.start_coords = {a: float(v) for a, v in start_coords.items()}
        self.beam_x = self.start_coords.get(beam_axis, 0.0)
        limit = limits.get(self.axis)
        if limit is None or limit <= 0:
            raise ValueError(f'{self.axis} limit unknown')
        origin = self.start_coords[self.axis] if params.mode == 'relative' else 0.0
        self.first, self.last = origin + params.start, origin + params.end
        self.xs, clipped = line_positions(self.first, self.last, params.step, limit)
        self.notices = []
        if clipped:
            self.notices.append(f'Scan range clipped to the session limits of {self.axis} '
                                f'[0, {limit:g}] mm: {len(self.xs)} points left.')
        if len(self.xs) < 2:
            raise ValueError('fewer than 2 scan points inside the session limits')

    def positions(self):
        return [{self.axis: x} for x in self.xs]

    @property
    def home(self):
        """The scanned axis back at the start point."""
        return {self.axis: self.start_coords[self.axis]}


def estimate_scan_s(plan, acq_s, move_mm_s=MOVE_MM_S):
    """Seconds: travel to and along the line and back, settle + averages per point,
    and the two reference acquisitions (the manual steps are not included)."""
    p = plan.params
    total, cur = 0.0, plan.start_coords[plan.axis]
    for x in plan.xs:
        total += abs(x - cur) / move_mm_s + p.settle_ms / 1000.0 + p.avg_n * acq_s
        cur = x
    total += abs(cur - plan.start_coords[plan.axis]) / move_mm_s
    if p.references:
        total += 2 * p.ref_avg_n * acq_s
    return total


@dataclass
class ScanData:
    """Everything acquired in one scan session (one line)."""
    sum1: List[np.ndarray] = field(default_factory=list)    # Σ(raw − midpoint), window, Ch1
    sum2: List[np.ndarray] = field(default_factory=list)    # same, Ch2
    off1: List[float] = field(default_factory=list)         # whole-record offset, Ch1
    off2: List[float] = field(default_factory=list)
    coords: List[List[float]] = field(default_factory=list)      # real X, Y, Z, R
    times: List[float] = field(default_factory=list)
    requested: List[float] = field(default_factory=list)
    measures: list = field(default_factory=list)
    magnitudes: List[Dict[str, float]] = field(default_factory=list)
    flags: List[List[str]] = field(default_factory=list)
    temperatures: List[dict] = field(default_factory=list)
    references: Dict[str, dict] = field(default_factory=dict)
    axis_order: List[str] = field(default_factory=list)
    manual_log: List[tuple] = field(default_factory=list)
    reference_position: Optional[dict] = None
    drift: Optional[dict] = None

    @property
    def n(self):
        return len(self.coords)


DRIFT_CHANNEL = 'ch1'          # through-transmission, the ECOS s_W (Ch2 is pulse-echo)


def reference_drift(initial, final, fs=ACQ_FS, tol_db=DEFAULT_DRIFT_DB, tol_ns=DEFAULT_DRIFT_NS):
    """
    Final vs initial water reference on Ch1 (through-transmission, s_W): envelope
    maximum of each, the difference in dB (final − initial) and the ToF difference
    by cross-correlation (positive: the final one arrives later). Without a clear
    signal in both references (contrast < CONFIDENT_CONTRAST) it is reported as
    not measured. Ch2 (pulse-echo) is not compared: a drift of its own is not
    covered. initial/final: {'ch1', 'ch2'} float arrays (the Smin–Smax window).
    Returns {'channel': 'ch1', 'ch1': {...}, 'exceeds': [...], 'tol_db', 'tol_ns'}.
    """
    out = {'channel': DRIFT_CHANNEL, 'path': 'through-transmission (Ch1, s_W)',
           'tol_db': float(tol_db), 'tol_ns': float(tol_ns), 'exceeds': []}
    for ch in (DRIFT_CHANNEL,):
        a, b = np.asarray(initial[ch], dtype=float), np.asarray(final[ch], dtype=float)
        ea, eb = Envelope(a), Envelope(b)
        ca = float(np.max(ea) / np.median(ea)) if np.median(ea) > 0 else float('inf')
        cb = float(np.max(eb) / np.median(eb)) if np.median(eb) > 0 else float('inf')
        r = {'amp_initial': float(np.max(ea)), 'amp_final': float(np.max(eb)),
             'clear': bool(ca >= CONFIDENT_CONTRAST and cb >= CONFIDENT_CONTRAST)}
        if r['clear']:
            r['d_db'] = 20.0 * math.log10(r['amp_final'] / r['amp_initial'])
            dtof, _, _ = CalcToFAscanCosine_XCRFFT(b, a)
            r['d_tof_samples'] = float(dtof)
            r['d_tof_ns'] = float(dtof) / fs * 1e9
            if abs(r['d_db']) > tol_db:
                out['exceeds'].append(f'{ch} amplitude')
            if abs(r['d_tof_ns']) > tol_ns:
                out['exceeds'].append(f'{ch} ToF')
        out[ch] = r
    return out


def drift_lines(drift):
    lines = []
    r = drift[DRIFT_CHANNEL]
    if not r['clear']:
        lines.append('Reference drift (Ch1, transmission): no clear signal in the references: '
                     'drift NOT measured.')
    else:
        lines.append(f'Reference drift (Ch1, transmission): {r["d_db"]:+.2f} dB, ToF '
                     f'{r["d_tof_ns"]:+.1f} ns (final − initial; limits ±{drift["tol_db"]:g} dB, '
                     f'±{drift["tol_ns"]:g} ns). Pulse-echo (Ch2) drift not covered.')
    if drift['exceeds']:
        lines.append('⚠ Drift above the limits (' + ', '.join(drift['exceeds']) + '): temperature, '
                     'gain or coupling changed during the scan; check before trusting it.')
    return lines


def scan_messages(xs, flags, measures):
    """Narrow window vs lost tracking vs saturation, as in focus and flatness."""
    msgs = []
    edge = [x for x, f in zip(xs, flags) if 'edge' in f]
    lost = [k for k, f in enumerate(flags) if 'weak' in f or 'outside' in f]
    sat = [x for x, f in zip(xs, flags) if 'saturated' in f]
    if edge:
        msgs.append(f'Echo pinned at an edge of Smin–Smax at {_pts(edge)} mm: the window is too '
                    'narrow, widen Smin–Smax on the Acquisition tab.')
    if lost:
        elsewhere = any(measures[k].echo_elsewhere for k in lost)
        why = ('a clear echo lies outside the tracking band (the echo jumps more than the band '
               'between points: smaller step or wider band)' if elsewhere else
               'no clear front echo (the beam is probably off the sample there)')
        msgs.append(f'Front-echo tracking lost at {_pts([xs[k] for k in lost])} mm: {why}. '
                    'Marked; the scan goes on (ToF = NaN there).')
    if sat:
        msgs.append(f'Signal saturated at {_pts(sat)} mm: lower the gain.')
    return msgs


def _pts(xs):
    if len(xs) > 8:
        return ', '.join(f'{x:g}' for x in xs[:4]) + f' … {xs[-1]:g} ({len(xs)} points)'
    return ', '.join(f'{x:g}' for x in xs)


# ===========================================================================
#  Qt part
# ===========================================================================
import pyqtgraph as pg  # noqa: E402
from PyQt5.QtCore import QObject, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QWidget,
)

_COL_MAP = (80, 160, 255)
_COL_FLAG = (235, 60, 60)
_COL_CH1 = (255, 80, 80)
_COL_CH2 = (255, 220, 0)


class ScanPlot:
    """Live map of the chosen magnitude vs position; also shows the water references."""

    def __init__(self, plot_widget):
        self._pw = plot_widget
        self._curve = None

    def reset(self, axis, magnitude):
        pw = self._pw
        pw.clear()
        mag = MAGNITUDES[magnitude]
        pw.setTitle(f'Line scan: {mag.label}')
        pw.setLabel('bottom', f'{axis}', units='mm')
        pw.setLabel('left', mag.label, units=mag.unit or None)
        pw.getAxis('bottom').enableAutoSIPrefix(False)
        pw.getAxis('left').enableAutoSIPrefix(False)
        pw.enableAutoRange()
        self._curve = pw.plot(pen=pg.mkPen(_COL_MAP, width=1), symbol='o', symbolSize=5,
                              symbolBrush=_COL_MAP, symbolPen=None, connect='finite')
        self._flag = pw.plot(pen=None, symbol='x', symbolSize=11,
                             symbolBrush=_COL_FLAG, symbolPen=pg.mkPen(_COL_FLAG, width=2))

    def set_data(self, xs, values, flagged):
        if self._curve is None:
            return
        v = np.asarray(values, dtype=float)
        self._curve.setData(np.asarray(xs, dtype=float), v)
        fx = [x for x, f, y in zip(xs, flagged, v) if f and np.isfinite(y)]
        fy = [y for f, y in zip(flagged, v) if f and np.isfinite(y)]
        self._flag.setData(fx, fy)

    def show_reference(self, which, ch1, ch2, smin, fs):
        pw = self._pw
        pw.clear()
        self._curve = None
        pw.setTitle(f'Water reference ({which}): Ch1 red, Ch2 (PE) yellow — OK, Repeat or Cancel')
        pw.setLabel('bottom', 'Time', units='µs')
        pw.setLabel('left', 'Amplitude', units=None)
        pw.getAxis('bottom').enableAutoSIPrefix(False)
        t = (smin + np.arange(len(ch1))) / fs * 1e6
        pw.plot(t, ch1, pen=pg.mkPen(_COL_CH1, width=1))
        pw.plot(t, ch2, pen=pg.mkPen(_COL_CH2, width=1))
        pw.enableAutoRange()


class ScanTool(QObject):
    """
    Line scan session (see the module docstring). States:
        'idle'         nothing running
        'ref_out'      initial/final reference: take the sample out by hand, Continue
        'ref_review'   reference acquired: accept / repeat / cancel
        'to_start'     back to the start point, one move per axis in reverse order
        'scan'         the line (pause / resume / STOP)
        'to_ref'       scanned axis home, then to the reference position (recorded order)
        'back'         back to the start point (reverse order)
        'stopped'      after a STOP or a fault: nothing moves; save / final ref / discard
    Signals: status(str), warning(str), state_changed(str), echo_used(PeakMeasure),
    reference_ready(str which), saved(str path), done(str how).
    """
    status = pyqtSignal(str)
    warning = pyqtSignal(str)
    state_changed = pyqtSignal(str)
    echo_used = pyqtSignal(object)
    reference_ready = pyqtSignal(str)
    saved = pyqtSignal(str)
    done = pyqtSignal(str)

    drift = pyqtSignal(object)

    def __init__(self, sequencer, panel, window_fn, plot_widget, acquire_fn, gains_fn,
                 set_gains_fn, counts_fn=None, temp_factory=None, sos_fn=None, cw_fn=None,
                 info_fn=None, base_dir=None, show_plot_fn=None, acq_time_fn=None, lock_fn=None,
                 dump_dir=None, adc_bits=ADC_BITS_DEFAULT, parent=None):
        """
        acquire_fn(avg_n) -> (ch1, ch2) full averaged records (references)
        counts_fn() -> {'sum': (s1, s2), 'offset': (o1, o2), 'n': avg_n} of the LAST
                     acquisition (the sequencer's or acquire_fn's): integer sums of
                     (raw − midpoint) over the whole record, as scan_counts defines
        adc_bits: ADC resolution assumed for the conversion (written in every file)
        gains_fn() -> (gain1, gain2) of the Acquisition tab (the scan gains)
        set_gains_fn(g1, g2): Gain1 then Gain2, always both (pulser fault)
        temp_factory() -> Arduino-like (getTemperatures, close) or None: opened ONCE
        sos_fn(T) -> c_w from the water temperature (ECOS: water_temp2sos)
        cw_fn() -> (c_w, source) WITHOUT opening the Arduino, when there is no PT100
        info_fn() -> {specimen, protocol, equipment1, equipment2, name_parts}
        base_dir: automatic save folder (default ../database)
        lock_fn(bool): host locks/unlocks the Acquisition tab for the whole session
        """
        super().__init__(parent)
        self._seq = sequencer
        self._panel = panel
        self._window_fn = window_fn
        self._plot = ScanPlot(plot_widget)
        self._acquire = acquire_fn
        self._counts_fn = counts_fn
        self.adc_bits = int(adc_bits)
        self._gains_fn = gains_fn
        self._set_gains = set_gains_fn
        self._temp_factory = temp_factory
        self._sos_fn = sos_fn
        self._cw_fn = cw_fn
        self._info_fn = info_fn
        self.base_dir = base_dir or _DB_DIR
        self._show_plot = show_plot_fn
        self._acq_time_fn = acq_time_fn
        self._lock_fn = lock_fn
        self._dump_dir = dump_dir or DEFAULT_DUMP_DIR
        self.state = 'idle'
        self.magnitude = 'amplitude'
        self.data = None
        self.plan = None
        self.params = None
        self._dump = None
        self.last_saved_path = None
        self.last_dump_path = None
        self._arduino = None
        self._phase = None
        self._pending_ref = None
        self._review = None
        self._watching = False
        sequencer.point_done.connect(self._on_point)
        sequencer.finished.connect(self._on_finished)

    # -- helpers ---------------------------------------------------------------
    def _set_state(self, state):
        self.state = state
        self.state_changed.emit(state)

    def _plan_for(self, params):
        lat = self._panel.role_axis('lateral')
        beam = self._panel.role_axis('beam')
        coords = self._panel.current_coords()
        limits = {a: self._panel.axis_limit(a) for a in (lat, 'Z')}
        return ScanPlan(params, coords, lat, beam, limits)

    def estimate(self, params):
        """(seconds, text, long) before starting; (None, reason, False) if not possible."""
        try:
            plan = self._plan_for(params)
        except Exception as e:
            return None, f'Estimate not available ({e}).', False
        acq_s, timed = acq_time(self._acq_time_fn)
        total = estimate_scan_s(plan, acq_s)
        long_ = total > LONG_SCAN_S
        refs = ' + two water references (manual steps not included)' if params.references else ''
        text = (f'Estimated time ≈ {format_duration(total)}: {len(plan.xs)} points along '
                f'{plan.axis} ({plan.xs[0]:g} → {plan.xs[-1]:g} mm){refs}; per point '
                f'{params.settle_ms / 1000.0:g} s settle + {params.avg_n} × {acq_s * 1e3:.0f} ms '
                f'({"timed" if timed else "assumed"}).')
        if long_:
            text += ' ⚠ Longer than half an hour.'
        return total, text, long_

    # -- start -----------------------------------------------------------------
    def start(self, params):
        """Start a scan session. None if started, else the reason it could not."""
        if self.state != 'idle':
            return 'A scan session is already in progress.'
        if self._seq.active:
            return 'A sequence is already running.'
        reason = self._seq.reserved_reason(self) or self._panel.sequence_blocker()
        if reason:
            return reason
        smin, smax = self._window_fn()
        if smax - smin < MIN_WINDOW_SAMPLES:
            return f'Acquisition window Smin–Smax too short ({smin}–{smax}).'
        try:
            plan = self._plan_for(params)
        except ValueError as e:
            return str(e)
        self.plan, self.params = plan, params
        self.window = (int(smin), int(smax))
        self.data = ScanData()
        self.last_saved_path = None
        self.last_dump_path = None
        self._t_start = time.time()
        self._ts = time.strftime('%Y%m%d_%H%M%S')
        self._warned_kinds = set()
        self._scan_gains = tuple(float(g) for g in self._gains_fn())
        self._tracker = FrontEchoTracker(self.window, 0.0, band_samples(params.band_us),
                                         params.threshold, params.edge_margin)
        self._dump = FocusDebugDump(dict(tool='scan', started=time.strftime('%Y-%m-%dT%H:%M:%S'),
                                         axis=plan.axis, xs=plan.xs, smin=smin, smax=smax),
                                    prefix='scan_debug') if params.debug_dump else None
        self._seq.reserve(self, 'A scan session is in progress (scanner tab).')
        if self._lock_fn:
            self._lock_fn(True)
        self._open_temperature()
        self._read_temperature('start', -1)
        self._resolve_cw()
        for text in plan.notices:
            self.warning.emit(text)
        self._plot.reset(plan.axis, self.magnitude)
        if self._show_plot is not None:
            self._show_plot()
        if params.references:
            self._enter_ref_out('initial')
        else:
            self._start_scan()
        return None

    def _open_temperature(self):
        self._arduino = None
        if self._temp_factory is not None:
            try:
                self._arduino = self._temp_factory()
            except Exception as e:
                self.warning.emit(f'PT100 could not be opened ({e}).')
                self._arduino = None
        if self._arduino is None:
            self.warning.emit('PT100 not available: the temperatures of this scan are stored '
                              'as NaN (not available).')

    def _read_temperature(self, label, point):
        t1 = t2 = float('nan')
        if self._arduino is not None:
            try:
                r1, r2 = self._arduino.getTemperatures()
                t1 = float('nan') if r1 is None else float(r1)
                t2 = float('nan') if r2 is None else float(r2)
            except Exception as e:
                self.warning.emit(f'Temperature read failed ({e}): stored as NaN.')
        entry = {'label': label, 'point': int(point), 'time': time.time(), 'T1': t1, 'T2': t2}
        self.data.temperatures.append(entry)
        return entry

    def _resolve_cw(self):
        t = self.data.temperatures[-1]
        temps = [v for v in (t['T1'], t['T2']) if v == v]
        if temps and self._sos_fn is not None:
            self.c_w = float(np.mean([self._sos_fn(v) for v in temps]))
            self.cw_source = 'PT100 ' + ', '.join(f'{v:.2f} °C' for v in temps)
        else:
            self.c_w, self.cw_source = resolve_cw(self._cw_fn)

    def _coords4(self):
        c = self._panel.current_coords()
        return [float(c.get(a, float('nan'))) for a in AXES4]

    # -- water references ------------------------------------------------------
    def _enter_ref_out(self, which):
        self._ref_which = which
        self._snapshot = self._panel.current_coords()
        if which == 'initial':
            self.data.axis_order = []
            self.data.manual_log = []
        if not self._watching and hasattr(self._panel, 'scanner_state_changed'):
            self._panel.scanner_state_changed.connect(self._on_manual_move)
            self._watching = True
        self._set_state('ref_out')
        self.status.emit('Water reference: take the sample out of the beam with the manual '
                         'controls (the order of the axes is recorded), then press Continue.')

    def _stop_watching(self):
        if self._watching:
            try:
                self._panel.scanner_state_changed.disconnect(self._on_manual_move)
            except (TypeError, RuntimeError):
                pass
            self._watching = False

    def _on_manual_move(self):
        if self.state != 'ref_out':
            return
        now = self._panel.current_coords()
        for a in AXES4:
            if abs(now.get(a, 0.0) - self._snapshot.get(a, 0.0)) > 1e-6:
                self.data.manual_log.append((a, float(now[a]), time.time()))
                if a not in self.data.axis_order:
                    self.data.axis_order.append(a)
        self._snapshot = now

    def continue_reference(self):
        """'Continue' after taking the sample out: acquire the initial reference."""
        if self.state != 'ref_out':
            return 'Not waiting for a reference.'
        if getattr(self._panel, 'is_busy', False):
            return 'The scanner is still moving.'
        self._stop_watching()
        if 'R' in self.data.axis_order:
            self.warning.emit('R was moved: it is not moved back automatically (the scan '
                              'never moves R). Bring it back by hand.')
        if not [a for a in self.data.axis_order if a != 'R']:
            self.warning.emit('No axis was moved: the reference is taken where the scan starts.')
        self.data.reference_position = self._panel.current_coords()
        self._take_reference('initial')
        return None

    def _last_counts(self, smin, smax):
        """Window of the integer sums of the last acquisition, and the offsets."""
        lc = self._counts_fn()
        if int(lc['n']) <= 0:
            raise ValueError('no counts for the last acquisition')
        s1, s2 = (np.array(np.asarray(s)[smin:smax], dtype=np.int64) for s in lc['sum'])
        return (s1, s2), (float(lc['offset'][0]), float(lc['offset'][1]))

    def _take_reference(self, which):
        p = self.params
        self._set_gains(p.ref_gain1, p.ref_gain2)          # Gain1, then Gain2 again
        self._acquire(p.ref_avg_n)
        smin, smax = self.window
        (s1, s2), (o1, o2) = self._last_counts(smin, smax)
        n = int(p.ref_avg_n)
        self._pending_ref = {
            'sum1': s1, 'sum2': s2, 'offset1': o1, 'offset2': o2, 'avg_n': n,
            'ch1': counts_to_float(s1, n, self.adc_bits, o1)[0],
            'ch2': counts_to_float(s2, n, self.adc_bits, o2)[0],
            'gains': [float(p.ref_gain1), float(p.ref_gain2)], 'coords': self._coords4(),
            'time': time.time(),
        }
        self._review = which
        self._plot.show_reference(which, self._pending_ref['ch1'], self._pending_ref['ch2'],
                                  smin, ACQ_FS)
        self._set_state('ref_review')
        self.reference_ready.emit(which)
        self.status.emit(f'Water reference ({which}) acquired at gains '
                         f'{p.ref_gain1:g}/{p.ref_gain2:g} dB: OK, Repeat or Cancel.')

    def repeat_reference(self):
        if self.state != 'ref_review':
            return 'No reference to repeat.'
        self._take_reference(self._review)
        return None

    def accept_reference(self):
        if self.state != 'ref_review':
            return 'No reference to accept.'
        which, ref = self._review, self._pending_ref
        t = self._read_temperature(f'ref_{which}', self.data.n - 1 if which == 'final' else -1)
        ref['T1'], ref['T2'] = t['T1'], t['T2']
        self.data.references[which] = ref
        self._restore_gains()
        self._pending_ref = None
        if which == 'final' and 'initial' in self.data.references:
            self._compare_references()
        self._plot.reset(self.plan.axis, self.magnitude)
        self._redraw()
        if which == 'initial':
            self._move('to_start', self._return_path(), 'Back to the start point (one move '
                       'per axis, reverse order)…')
        else:
            self._move('back', self._return_path(), 'Back to the start point…')
        return None

    def _compare_references(self):
        p = self.params
        d = reference_drift(self.data.references['initial'], self.data.references['final'],
                            ACQ_FS, p.drift_tol_db, p.drift_tol_ns)
        self.data.drift = d
        self.drift.emit(d)
        lines = drift_lines(d)
        if d['exceeds']:
            self.warning.emit(lines[-1])
        self.status.emit('\n'.join(lines))

    def cancel_reference(self):
        """Initial: cancel the session (nothing moves). Final: skip it and go back."""
        if self.state not in ('ref_out', 'ref_review'):
            return 'Not in a reference step.'
        self._stop_watching()
        self._restore_gains()
        self._pending_ref = None
        if self._ref_which == 'initial':
            self._end('cancelled', 'Scan cancelled before starting: nothing scanned. The '
                                   'scanner is where it was left (bring the sample back by hand).')
        else:
            self.warning.emit('Final water reference skipped.')
            self._move('back', self._return_path(), 'Back to the start point…')
        return None

    def _restore_gains(self):
        self._set_gains(*self._scan_gains)

    def _return_path(self):
        """One move per manually moved axis (not R), reverse order, to the start point."""
        start = self.plan.start_coords
        return [{a: start[a]} for a in reversed(self.data.axis_order) if a in ('X', 'Y', 'Z')]

    def _to_reference_path(self):
        """Scanned axis home first (the path just scanned), then the recorded order."""
        ref = self.data.reference_position or {}
        path = [self.plan.home]
        path += [{a: ref[a]} for a in self.data.axis_order if a in ('X', 'Y', 'Z')]
        return path

    # -- sequences -------------------------------------------------------------
    def _move(self, phase, path, text):
        """Travel-only sequence (one point per move, nothing kept)."""
        if not path:
            self._phase = phase
            QTimer.singleShot(0, lambda: self._phase_done(phase))
            return
        self._phase = phase
        self._set_state(phase)
        self.status.emit(text)
        reason = self._seq.start(path, self.params.settle_ms, 1, lambda ch1, ch2: None,
                                 validate_fn=self._panel.validate_position,
                                 record_temperature=False, owner=self)
        if reason:
            self._stopped(f'Could not move: {reason}')

    def _start_scan(self):
        self._phase = 'scan'
        self._set_state('scan')
        self._tracker.new_sweep()
        n = len(self.plan.xs)
        self.status.emit(f'Scanning {n} points along {self.plan.axis} (c_w = {self.c_w:.1f} m/s, '
                         f'{self.cw_source})…')
        reason = self._seq.start(self.plan.positions(), self.params.settle_ms, self.params.avg_n,
                                 self._measure, validate_fn=self._panel.validate_position,
                                 record_temperature=False, owner=self)
        if reason:
            self._stopped(f'The scan could not start: {reason}')

    def _measure(self, ch1, ch2):
        if self._phase != 'scan':
            return None
        smin, smax = self.window
        sig = ch2 if PE_CHANNEL == 2 else ch1
        m = self._tracker.measure(sig, self.plan.beam_x)
        seg, env = self._tracker.point_signals(-1)
        (s1, s2), (o1, o2) = self._last_counts(smin, smax)
        self.data.sum1.append(s1)
        self.data.sum2.append(s2)
        self.data.off1.append(o1)
        self.data.off2.append(o2)
        self._last = (seg, env, np.array(ch1[smin:smax], dtype=float),
                      np.array(sig, dtype=float) if self._dump is not None else None)
        return m

    def _on_point(self, i, coords, value):
        if self._phase != 'scan':
            return
        d = self.data
        d.coords.append([float(coords.get(a, float('nan'))) for a in AXES4])
        d.times.append(time.time())
        d.requested.append(self.plan.xs[i] if i < len(self.plan.xs) else float('nan'))
        d.measures = list(self._tracker.measures)        # a re-lock revises earlier points
        xs = self.positions_read()
        d.flags = line_flags(xs, d.measures, self.window, self.params.edge_margin)
        seg, env, seg1, record = self._last
        ctx = PointContext(value, seg, env, seg1, ACQ_FS, self.params.emission_sample)
        lost = 'weak' in d.flags[-1] or 'outside' in d.flags[-1]
        d.magnitudes.append(compute_magnitudes(ctx, lost))
        # ToF depends on the (possibly revised) measures: refresh it on every point
        for k, (m, f) in enumerate(zip(d.measures, d.flags)):
            gone = 'weak' in f or 'outside' in f
            d.magnitudes[k]['tof'] = (float('nan') if gone else
                                      (m.index_frac - self.params.emission_sample) / ACQ_FS * 1e6)
        if self._dump is not None:
            self._dump.add('scan', self.plan.beam_x, value, seg, env, record, self.window,
                           extra=dict(line_position=xs[-1], **d.magnitudes[-1]))
            self._dump.revise(0, d.measures, d.flags)
        self.echo_used.emit(value)
        self._redraw()
        f = d.flags[-1]
        if f and not self._warned_kinds >= set(f):
            self._warned_kinds |= set(f)
            self.warning.emit(' '.join(scan_messages([xs[-1]], [f], [d.measures[-1]])))

    def positions_read(self):
        """Real positions along the scanned axis of the points acquired so far."""
        k = AXES4.index(self.plan.axis)
        return [c[k] for c in self.data.coords]

    def set_magnitude(self, name):
        self.magnitude = name
        if self.plan is not None and self.state not in ('ref_review',):
            self._plot.reset(self.plan.axis, name)
            self._redraw()

    def _redraw(self):
        d = self.data
        if d is None or not d.coords:
            return
        mag = MAGNITUDES[self.magnitude]
        flagged = [bool(f) if mag.uses_echo else ('saturated' in f or 'edge' in f)
                   for f in d.flags]
        self._plot.set_data(self.positions_read(), [m[self.magnitude] for m in d.magnitudes],
                            flagged)

    def _on_finished(self, status, text):
        if self._phase is None or self.state == 'idle':
            return
        if status != 'done':
            self._stopped(f'{status.capitalize()} during the {self._phase} phase: {text}')
            return
        phase = self._phase
        QTimer.singleShot(0, lambda: self._phase_done(phase))

    def _phase_done(self, phase):
        if self._phase != phase or self.state == 'idle':
            return
        if phase == 'to_start':
            self._start_scan()
        elif phase == 'scan':
            if self.params.references:
                self._move('to_ref', self._to_reference_path(),
                           'Scan done. To the water reference position (recorded order)…')
            else:
                self._move('back', [self.plan.home], 'Scan done. Back to the start point…')
        elif phase == 'to_ref':
            self._ref_which = 'final'
            self._take_reference('final')
        elif phase == 'back':
            self._finish_and_save('completed' if self.data.n == len(self.plan.xs) else 'stopped')

    # -- STOP, pause -----------------------------------------------------------
    def pause(self):
        if self.state == 'scan':
            self._seq.pause()

    def resume(self):
        if self.state == 'scan':
            self._seq.resume()

    def stop(self):
        """Same as the panel STOP: the sequence ends and nothing else moves."""
        self._seq.abort()

    def _stopped(self, text):
        self._phase = None
        self._stop_watching()
        self._restore_gains()
        if self.data is None or self.data.n == 0:
            self._end('stopped', f'{text} Nothing was acquired; nothing saved. Not moved.')
            return
        self._set_state('stopped')
        can_ref = self.params.references and 'final' not in self.data.references
        self.status.emit(f'{text} Not moved. {self.data.n} of {len(self.plan.xs)} points acquired: '
                         'save them' + (', take the final reference first' if can_ref else '')
                         + ' or discard.')

    def save_acquired(self, final_reference=False):
        """After a STOP: save what was acquired, optionally after the final reference."""
        if self.state != 'stopped':
            return 'Nothing stopped to save.'
        if final_reference and self.params.references and 'final' not in self.data.references:
            self._move('to_ref', self._to_reference_path(), 'To the water reference position…')
            return None
        self._finish_and_save('stopped')
        return None

    def discard(self):
        if self.state != 'stopped':
            return 'Nothing to discard.'
        self._end('discarded', 'Acquired data discarded; nothing saved.')
        return None

    # -- saving ----------------------------------------------------------------
    def _finish_and_save(self, how):
        self._read_temperature('end', self.data.n - 1)
        self._completion = how
        try:
            path = self.save(self.base_dir)
            text = f'Scan {how}: {self.data.n} points. Saved to {path}'
        except Exception as e:
            self.warning.emit(f'Automatic save failed ({e}): use "Save to another folder…".')
            text = f'Scan {how}: {self.data.n} points. NOT saved.'
        msgs = scan_messages(self.positions_read(), self.data.flags, self.data.measures)
        if self.data.drift is not None:
            msgs = drift_lines(self.data.drift) + msgs
        self._end(how, '\n'.join([text] + msgs))

    def exp_name(self):
        if _DB_DIR not in sys.path:
            sys.path.insert(0, _DB_DIR)
        from BD_Experimentos_PVA import experiment_name
        parts = (self._info_fn() or {}).get('name_parts', {}) if self._info_fn else {}
        return experiment_name(parts.get('pva', ''), parts.get('additive', ''),
                               parts.get('sample_id', ''), parts.get('cycles', ''),
                               exp_type='SCAN', ts=self._ts)

    def save(self, base_dir):
        """Write the session's data to base_dir/<name>/ (meta.json + scan.npz)."""
        if _DB_DIR not in sys.path:
            sys.path.insert(0, _DB_DIR)
        from BD_Experimentos_PVA import save_scan_raw_32
        d, p, plan = self.data, self.params, self.plan
        info = (self._info_fn() if self._info_fn else None) or {}
        smin, smax = self.window
        n = d.n
        n_samp = smax - smin
        sum1 = np.array(d.sum1[:n], dtype=np.int64).reshape(1, n, n_samp)
        sum2 = np.array(d.sum2[:n], dtype=np.int64).reshape(1, n, n_samp)
        equipment1 = dict(info.get('equipment1', {'nombre': 'SEDAQ'}))
        params = dict(equipment1.get('params', {}))
        params.update(Gain_Ch1=self._scan_gains[0], Gain_Ch2=self._scan_gains[1],
                      F_muestreo=ACQ_FS, Smin=smin, Smax=smax, Slen=n_samp,
                      AvgSamplesNum=p.avg_n)
        equipment1['params'] = params
        scan = {
            'type': 'line', 'timestamp_start': time.strftime('%Y-%m-%dT%H:%M:%S',
                                                             time.localtime(self._t_start)),
            'axis_role': p.axis_role, 'axis': plan.axis, 'beam_axis': plan.beam_axis,
            'range_mode': p.mode, 'start_mm': p.start, 'end_mm': p.end, 'step_mm': p.step,
            'first_mm': plan.first, 'last_mm': plan.last, 'positions_requested': plan.xs,
            'n_points': len(plan.xs), 'n_acquired': n,
            'status': getattr(self, '_completion', 'completed'),
            'completed': n == len(plan.xs),
            'start_point': plan.start_coords,
            'settle_ms': p.settle_ms, 'avg_n': p.avg_n,
            'settle_avg_note': 'scan defaults pending characterization vs step (phase 5)',
            'c_w': self.c_w, 'c_w_source': self.cw_source,
            'references': p.references, 'ref_gains': [p.ref_gain1, p.ref_gain2],
            'ref_avg_n': p.ref_avg_n, 'reference_position': d.reference_position,
            'manual_axis_order': d.axis_order,
            'manual_moves': [{'axis': a, 'value': v, 'time': t} for a, v, t in d.manual_log],
            'tracking': {'band_us': p.band_us, 'threshold': p.threshold,
                         'edge_margin': p.edge_margin, 'emission_sample': p.emission_sample},
            'flags': {str(k): f for k, f in enumerate(d.flags) if f},
            'reference_drift': d.drift,
        }
        refs = {w: {k: r[k] for k in ('sum1', 'sum2', 'offset1', 'offset2', 'avg_n', 'gains',
                                      'coords', 'time', 'T1', 'T2')}
                for w, r in d.references.items()}
        name = self.exp_name()
        path = save_scan_raw_32(
            specimen=info.get('specimen', {}), protocol=info.get('protocol', {}),
            equipment1=equipment1, equipment2=info.get('equipment2', {}),
            scanner_session=(self._panel.session_dict() if hasattr(self._panel, 'session_dict')
                             else {}),
            scan=scan, signals_ch1=sum1, signals_ch2=sum2,
            offsets_ch1=np.array(d.off1[:n], dtype=float).reshape(1, n),
            offsets_ch2=np.array(d.off2[:n], dtype=float).reshape(1, n),
            n_avg=p.avg_n, gains=self._scan_gains, adc_bits=self.adc_bits,
            coords=np.array(d.coords, dtype=float).reshape(1, n, 4),
            point_time=np.array(d.times, dtype=float).reshape(1, n),
            temperatures=d.temperatures, references=refs,
            operator=p.operator, comment=p.comment, base_dir=base_dir, exp_name=name,
            extra_arrays={'positions_requested': np.array(d.requested, dtype=float).reshape(1, n)})
        if os.path.abspath(base_dir) == os.path.abspath(self.base_dir) or self.last_saved_path is None:
            self.last_saved_path = path
        self.saved.emit(path)
        return path

    def save_copy(self, base_dir):
        """'Save to another folder…': the same data, written again under base_dir."""
        if self.data is None or self.data.n == 0 or self.state != 'idle':
            return None, 'Nothing to save (or a session is still in progress).'
        try:
            return self.save(base_dir), None
        except Exception as e:
            return None, str(e)

    # -- end -------------------------------------------------------------------
    def _end(self, how, text):
        self._phase = None
        self._stop_watching()
        try:
            if self._arduino is not None:
                self._arduino.close()
        except Exception:
            pass
        self._arduino = None
        if self._dump is not None and len(self._dump):
            self._dump.meta.update(result=text)
            try:
                self.last_dump_path = self._dump.save(self._dump_dir)
                text += f'\nDebug dump: {self.last_dump_path}'
            except Exception as e:
                self.warning.emit(f'Scan debug dump not saved: {e}')
        self._dump = None
        self._seq.release(self)
        if self._lock_fn:
            self._lock_fn(False)
        self._set_state('idle')
        self.status.emit(text)
        self.done.emit(how)


class ScanGroup(QGroupBox):
    """Line-scan controls for the Scanner tab (spec 5.6, phase 5)."""

    def __init__(self, tool, sequencer, parent=None):
        super().__init__('Line scan', parent)
        self._tool = tool
        self._seq = sequencer
        form = QFormLayout(self)

        def dspin(lo, hi, val, dec, step, suffix):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setSingleStep(step)
            s.setValue(val)
            s.setSuffix(suffix)
            return s

        self._cmb_axis = QComboBox()
        self._cmb_axis.addItem('Lateral', 'lateral')
        self._cmb_axis.addItem('Z', 'z')
        self._cmb_mode = QComboBox()
        self._cmb_mode.addItem('Relative to the current position', 'relative')
        self._cmb_mode.addItem('Absolute', 'absolute')
        self._spin_start = dspin(-500.0, 500.0, -5.0, 2, 0.5, ' mm')
        self._spin_end = dspin(-500.0, 500.0, 5.0, 2, 0.5, ' mm')
        self._spin_step = dspin(0.01, 50.0, DEFAULT_SCAN_STEP_MM, 2, 0.05, ' mm')
        self._spin_settle = QSpinBox()
        self._spin_settle.setRange(0, 60000)
        self._spin_settle.setValue(DEFAULT_SCAN_SETTLE_MS)
        self._spin_settle.setSuffix(' ms')
        self._spin_settle.setToolTip('Scan default, NOT the focus one: pending characterization '
                                     'as a function of the step.')
        self._spin_avg = QSpinBox()
        self._spin_avg.setRange(1, 10000)
        self._spin_avg.setValue(DEFAULT_SCAN_AVG_N)
        self._spin_avg.setToolTip(self._spin_settle.toolTip())
        self._cmb_mag = QComboBox()
        for name, mag in MAGNITUDES.items():
            self._cmb_mag.addItem(mag.label, name)
        form.addRow('Axis:', self._cmb_axis)
        form.addRow('Range:', self._cmb_mode)
        form.addRow('Start:', self._spin_start)
        form.addRow('End:', self._spin_end)
        form.addRow('Step:', self._spin_step)
        form.addRow('Settle (scan):', self._spin_settle)
        form.addRow('Averages (scan):', self._spin_avg)
        form.addRow('Map:', self._cmb_mag)

        self._chk_refs = QCheckBox('Take water references at the start and at the end')
        self._spin_rg1 = dspin(0.0, 100.0, 0.0, 1, 1.0, ' dB')
        self._spin_rg2 = dspin(0.0, 100.0, 0.0, 1, 1.0, ' dB')
        self._spin_ravg = QSpinBox()
        self._spin_ravg.setRange(1, 10000)
        self._spin_ravg.setValue(DEFAULT_REF_AVG_N)
        form.addRow(self._chk_refs)
        form.addRow('Reference gain Ch1:', self._spin_rg1)
        form.addRow('Reference gain Ch2:', self._spin_rg2)
        form.addRow('Reference averages:', self._spin_ravg)
        self._txt_operator = QLineEdit('Sebas')
        self._txt_comment = QLineEdit('')
        form.addRow('Operator:', self._txt_operator)
        form.addRow('Comment:', self._txt_comment)
        self._spin_drift_db = dspin(0.01, 20.0, DEFAULT_DRIFT_DB, 2, 0.1, ' dB')
        self._spin_drift_ns = dspin(0.1, 10000.0, DEFAULT_DRIFT_NS, 1, 5.0, ' ns')
        self._spin_drift_db.setToolTip('Warn when the final water reference differs from the '
                                       'initial one by more than this in amplitude.')
        self._spin_drift_ns.setToolTip('… or by more than this in time of flight.')
        form.addRow('Drift limit, amplitude:', self._spin_drift_db)
        form.addRow('Drift limit, ToF:', self._spin_drift_ns)
        self._chk_dump = QCheckBox('Save debug dump (large: full records; data/scan_debug)')
        form.addRow(self._chk_dump)

        self._lbl_estimate = QLabel()
        self._lbl_estimate.setWordWrap(True)
        form.addRow(self._lbl_estimate)

        def row(*buttons):
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            for b in buttons:
                lay.addWidget(b)
            form.addRow(w)

        self._btn_start = QPushButton('Start scan')
        self._btn_pause = QPushButton('Pause')
        self._btn_stop = QPushButton('Stop')
        row(self._btn_start, self._btn_pause, self._btn_stop)
        self._btn_continue = QPushButton('Continue (sample out)')
        self._btn_ok = QPushButton('OK')
        self._btn_repeat = QPushButton('Repeat')
        self._btn_cancel = QPushButton('Cancel')
        row(self._btn_continue, self._btn_ok, self._btn_repeat, self._btn_cancel)
        self._btn_save = QPushButton('Save acquired')
        self._btn_save_ref = QPushButton('Final reference, then save')
        self._btn_discard = QPushButton('Discard')
        row(self._btn_save, self._btn_save_ref, self._btn_discard)
        self._btn_copy = QPushButton('Save to another folder…')
        row(self._btn_copy)

        self._lbl_drift = QLabel('Reference drift: —')
        self._lbl_drift.setWordWrap(True)
        form.addRow(self._lbl_drift)
        self._lbl_warn = QLabel()
        self._lbl_warn.setWordWrap(True)
        self._lbl_warn.setStyleSheet('color: rgb(230, 120, 0);')
        form.addRow(self._lbl_warn)
        self._lbl_status = QLabel('Idle.')
        self._lbl_status.setWordWrap(True)
        form.addRow(self._lbl_status)

        self._btn_start.clicked.connect(self._on_start)
        self._btn_pause.clicked.connect(self._on_pause)
        self._btn_stop.clicked.connect(tool.stop)
        self._btn_continue.clicked.connect(lambda: self._report(tool.continue_reference()))
        self._btn_ok.clicked.connect(lambda: self._report(tool.accept_reference()))
        self._btn_repeat.clicked.connect(lambda: self._report(tool.repeat_reference()))
        self._btn_cancel.clicked.connect(lambda: self._report(tool.cancel_reference()))
        self._btn_save.clicked.connect(lambda: self._report(tool.save_acquired(False)))
        self._btn_save_ref.clicked.connect(lambda: self._report(tool.save_acquired(True)))
        self._btn_discard.clicked.connect(lambda: self._report(tool.discard()))
        self._btn_copy.clicked.connect(self._on_copy)
        self._cmb_mag.currentIndexChanged.connect(
            lambda _i: tool.set_magnitude(self._cmb_mag.currentData()))
        tool.status.connect(self._lbl_status.setText)
        tool.warning.connect(self._lbl_warn.setText)
        tool.state_changed.connect(self._on_state)
        tool.drift.connect(self._on_drift)
        sequencer.state_changed.connect(lambda st: self._on_state(tool.state, st))
        for w in (self._spin_start, self._spin_end, self._spin_step, self._spin_settle,
                  self._spin_avg, self._spin_ravg):
            w.valueChanged.connect(self._refresh_estimate)
        for c in (self._cmb_axis, self._cmb_mode):
            c.currentIndexChanged.connect(self._refresh_estimate)
        self._chk_refs.toggled.connect(self._refresh_estimate)
        self._on_state('idle')
        self._refresh_estimate()

    def params(self):
        return ScanParams(
            axis_role=self._cmb_axis.currentData(), mode=self._cmb_mode.currentData(),
            start=self._spin_start.value(), end=self._spin_end.value(),
            step=self._spin_step.value(), settle_ms=self._spin_settle.value(),
            avg_n=self._spin_avg.value(), references=self._chk_refs.isChecked(),
            ref_gain1=self._spin_rg1.value(), ref_gain2=self._spin_rg2.value(),
            ref_avg_n=self._spin_ravg.value(), operator=self._txt_operator.text().strip(),
            comment=self._txt_comment.text(), debug_dump=self._chk_dump.isChecked(),
            drift_tol_db=self._spin_drift_db.value(), drift_tol_ns=self._spin_drift_ns.value())

    def _refresh_estimate(self, *_):
        _, text, long_ = self._tool.estimate(self.params())
        self._lbl_estimate.setText(text)
        self._lbl_estimate.setStyleSheet('color: rgb(200, 40, 40); font-weight: bold;' if long_
                                         else 'font-weight: bold;')

    def showEvent(self, event):
        self._refresh_estimate()
        super().showEvent(event)

    def _report(self, reason):
        if reason:
            self._lbl_status.setText(reason)

    def _on_start(self):
        self._refresh_estimate()
        self._lbl_warn.setText('')
        self._tool.set_magnitude(self._cmb_mag.currentData())
        self._report(self._tool.start(self.params()))

    def _on_pause(self):
        if self._seq.state == 'paused':
            self._tool.resume()
        else:
            self._tool.pause()

    def _on_drift(self, drift):
        self._lbl_drift.setText('\n'.join(drift_lines(drift)))
        if drift['exceeds']:
            style = 'background: rgb(200, 40, 40); color: white;'
        elif not drift[DRIFT_CHANNEL]['clear']:
            style = 'background: gray; color: white;'
        else:
            style = 'background: rgb(40, 160, 70); color: white;'
        self._lbl_drift.setStyleSheet(style)

    def _on_copy(self):
        folder = QFileDialog.getExistingDirectory(self, 'Save the scan to another folder')
        if not folder:
            return
        path, err = self._tool.save_copy(folder)
        self._lbl_status.setText(f'Copy saved to {path}' if path else f'Not saved: {err}')

    def _on_state(self, state, seq_state=None):
        seq_state = seq_state or self._seq.state
        idle = state == 'idle'
        self._btn_start.setEnabled(idle and seq_state == 'idle')
        self._btn_pause.setEnabled(state == 'scan')
        self._btn_pause.setText('Resume' if seq_state == 'paused' else 'Pause')
        self._btn_stop.setEnabled(state in ('scan', 'to_start', 'to_ref', 'back'))
        self._btn_continue.setEnabled(state == 'ref_out')
        for b in (self._btn_ok, self._btn_repeat):
            b.setEnabled(state == 'ref_review')
        self._btn_cancel.setEnabled(state in ('ref_out', 'ref_review'))
        stopped = state == 'stopped'
        self._btn_save.setEnabled(stopped)
        self._btn_discard.setEnabled(stopped)
        self._btn_save_ref.setEnabled(
            stopped and self._tool.params.references
            and 'final' not in self._tool.data.references if stopped else False)
        self._btn_copy.setEnabled(idle and self._tool.last_saved_path is not None)
