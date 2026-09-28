# -*- coding: utf-8 -*-
"""
focus_tool.py — Focus search on the beam axis (scanner phase 3).
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See task_scanner_phase3.md section 2 and scanner_tab_spec.md section 5.4.

Measure per point: peak of the envelope (ECOS_US_ToolBox.Envelope, Hilbert)
of the pulse-echo channel INSIDE the acquisition window Smin–Smax that the
user already set on the Acquisition tab. Never over the whole record: the
excitation main bang, reverberations and other echoes live outside it. The
tool only reads that window; it never changes it.

Algorithm:
    1. coarse sweep over ±range around the current beam position, clipped to
       the session limits (with a notice);
    2. fine sweep over ±coarse_step around the coarse maximum;
    3. parabola fitted to the amplitude IN dB on 3–5 points around the fine
       maximum (near the focus the axial profile is close to a Gaussian, and a
       Gaussian in log is a parabola);
    4. move to the optimum — unless the maximum sits on the edge of the range
       ("widen the range"), or the echo touched an edge of the window or
       saturated on any point used for the result. In those cases the scanner
       goes back to the beam-axis position it had before the sweep.
STOP is the exception: after a STOP nothing moves any more, the tool only
reports where the scanner is. After a fault (e.g. a rejected move) it does
not move either.
Every phase (coarse, fine, final move or return) is one run of the phase-2
ScanSequencer; there is no loop here. Nothing is saved.

The echo moves 2/c_w ≈ 1.33 µs per mm along the beam axis. If Smin–Smax is
too narrow for the range, the echo leaves the window. Checked on every point
as it arrives, reported at once and marked on the plot (point_flags):
    - 'edge': the envelope peak is pinned within the edge margin (a fraction
      of the window width) of Smin or Smax — the echo is half out. Only when
      the peak stands clearly above the noise (EDGE_MIN_CONTRAST): a noise
      peak can land on an edge by chance;
    - 'outside': the echo is predicted outside the window. Once the echo has
      left, only noise remains and its peak can fall anywhere, so the pinned
      test alone misses it. The prediction takes the strongest point with a
      clear echo as reference and moves it 2/c_w per mm, with the sign given
      by the PE side (spec section 2);
    - 'saturated': the signal reaches full scale inside the window.
A coarse curve with any marked point is incomplete (the true maximum may be
hidden where the echo was out): the tool then stops before the fine sweep and
does not move.

The pure part (window_peak, sweep_positions, FocusPlan) has no Qt dependency
and is what test_focus_tool.py exercises against sim_sedaq.SimSeDaq.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

_TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
if _TOOLS_DIR not in sys.path:
    sys.path.append(_TOOLS_DIR)
from ECOS_US_ToolBox import Envelope  # noqa: E402

from scan_sequencer import DEFAULT_AVG_N, DEFAULT_SETTLE_MS  # noqa: E402

PE_CHANNEL = 2                 # ecos_gui.py: s_PE is Ch2
DEFAULT_HALF_RANGE_MM = 5.0
DEFAULT_COARSE_MM = 1.0
DEFAULT_FINE_MM = 0.2
DEFAULT_EDGE_MARGIN = 0.05     # fraction of the window width
FIT_POINTS = 5                 # points around the maximum for the parabola (3–5)
SATURATION_LEVEL = 0.49        # |amplitude| in ecos_gui units (full scale ±0.5)
CONFIDENT_CONTRAST = 8.0       # envelope peak / median envelope: a clear echo (prediction reference)
EDGE_MIN_CONTRAST = 6.0        # below this the peak is noise and where it falls means nothing
C_W_NOMINAL = 1480.0           # m/s, when no temperature has been read
ACQ_FS = 100e6                 # Hz
MIN_WINDOW_SAMPLES = 16
POSITION_DECIMALS = 2          # X/Y resolve 0.01 mm


# ===========================================================================
#  Pure helpers
# ===========================================================================
@dataclass
class PeakMeasure:
    amp: float            # envelope peak inside the window
    index: int            # absolute sample index of the peak
    at_edge: bool         # a clear peak within the edge margin of Smin or Smax
    saturated: bool       # the raw signal reaches full scale inside the window
    contrast: float = float('inf')   # peak / median of the envelope in the window

    @property
    def flagged(self):
        return self.at_edge or self.saturated


def window_peak(sig, smin, smax, edge_margin=DEFAULT_EDGE_MARGIN):
    """Envelope peak of sig[smin:smax] (never the whole record)."""
    seg = np.asarray(sig[smin:smax], dtype=float)
    if len(seg) < MIN_WINDOW_SAMPLES:
        raise ValueError(f'window Smin–Smax too short ({len(seg)} samples)')
    env = Envelope(seg)
    k = int(np.argmax(env))
    med = float(np.median(env))
    contrast = float(env[k]) / med if med > 0 else float('inf')
    margin = max(1, int(round(edge_margin * len(seg))))
    at_edge = (k < margin or k >= len(seg) - margin) and contrast >= EDGE_MIN_CONTRAST
    saturated = bool(np.max(np.abs(seg)) >= SATURATION_LEVEL)
    return PeakMeasure(float(env[k]), smin + k, at_edge, saturated, contrast)


def echo_samples_per_mm(pe_side, c_w=C_W_NOMINAL, fs=ACQ_FS):
    """Signed shift of the front echo, in samples, per +1 mm on the beam axis."""
    sign = 1.0 if pe_side == 'origin' else -1.0
    return sign * 2e-3 / c_w * fs


def point_flags(xs, measures, window, edge_margin=DEFAULT_EDGE_MARGIN, samples_per_mm=None):
    """
    Per point, the reasons its measure cannot be trusted: a list of lists among
    'edge', 'outside', 'saturated' (empty list: fine). See the module docstring.
    samples_per_mm None: no prediction ('outside' never set).
    """
    smin, smax = window
    margin = max(1, int(round(edge_margin * (smax - smin))))
    flags = []
    for m in measures:
        f = []
        if m.at_edge:
            f.append('edge')
        if m.saturated:
            f.append('saturated')
        flags.append(f)
    if samples_per_mm is None:
        return flags
    clear = [k for k, m in enumerate(measures)
             if not m.flagged and m.contrast >= CONFIDENT_CONTRAST]
    if not clear:
        return flags
    r = max(clear, key=lambda k: measures[k].amp)
    for k, x in enumerate(xs):
        predicted = measures[r].index + samples_per_mm * (x - xs[r])
        if not (smin + margin <= predicted < smax - margin) and 'edge' not in flags[k]:
            flags[k].append('outside')
    return flags


def _upper_first(text):
    return text[:1].upper() + text[1:]


def describe_flags(flags):
    text = []
    if 'edge' in flags:
        text.append('echo at an edge of Smin–Smax')
    if 'outside' in flags:
        text.append('echo outside Smin–Smax')
    if 'saturated' in flags:
        text.append('signal saturated')
    return ', '.join(text)


def to_db(amp):
    return 20.0 * math.log10(max(float(amp), 1e-12))


def sweep_positions(center, half_range, step, limit):
    """
    Grid center + k·step inside [center − half_range, center + half_range] ∩
    [0, limit]. Returns (positions, clipped): clipped is True when the session
    limits cut the requested range.
    """
    lo, hi = center - half_range, center + half_range
    clipped = lo < 0.0 or hi > limit
    lo, hi = max(lo, 0.0), min(hi, limit)
    k0 = math.ceil((lo - center) / step - 1e-9)
    k1 = math.floor((hi - center) / step + 1e-9)
    xs = []
    for k in range(k0, k1 + 1):
        x = round(center + k * step, POSITION_DECIMALS)
        x = min(max(x, 0.0), limit)
        if not xs or x > xs[-1]:
            xs.append(x)
    return xs, clipped


@dataclass
class FitResult:
    x_opt: float
    db_opt: float
    coeffs: Optional[tuple]      # (a, b, c) of the dB parabola, None on fallback
    fit_x: List[float]
    note: str = ''


@dataclass
class FocusOutcome:
    move: bool                   # True: go to x_opt
    text: str
    fit: Optional[FitResult] = None
    notices: List[str] = field(default_factory=list)


def fit_parabola_db(xs, amps, i_max, n_points=FIT_POINTS):
    """Parabola on 20·log10(amp) over up to n_points centred on i_max (at least 3)."""
    half = n_points // 2
    lo, hi = max(0, i_max - half), min(len(xs), i_max + half + 1)
    x = np.asarray(xs[lo:hi], dtype=float)
    y = np.array([to_db(a) for a in amps[lo:hi]])
    if len(x) < 3:
        return FitResult(xs[i_max], to_db(amps[i_max]), None, list(x),
                         'fewer than 3 points: optimum = measured maximum')
    a, b, c = np.polyfit(x, y, 2)
    if a >= 0:
        return FitResult(xs[i_max], to_db(amps[i_max]), None, list(x),
                         'fit is not concave: optimum = measured maximum')
    xv = -b / (2.0 * a)
    if not (x[0] <= xv <= x[-1]):
        return FitResult(xs[i_max], to_db(amps[i_max]), None, list(x),
                         'fit vertex outside the fitted points: optimum = measured maximum')
    return FitResult(float(xv), float(a * xv * xv + b * xv + c), (a, b, c), list(x))


class FocusPlan:
    """
    Decisions of the focus search, without Qt or hardware:
        plan = FocusPlan(center, half_range, coarse, fine, limit, window, ...)
        plan.coarse_positions                        -> measure them
        plan.after_coarse(xs, measures)              -> (fine_positions, None) or (None, FocusOutcome)
        plan.after_fine(xs, measures)                -> FocusOutcome
    measures are PeakMeasure objects (window_peak).
    """

    def __init__(self, center, half_range, coarse_step, fine_step, limit,
                 window, edge_margin=DEFAULT_EDGE_MARGIN, samples_per_mm=None):
        if not (fine_step > 0 and coarse_step > 0 and half_range > 0):
            raise ValueError('range and steps must be positive')
        if fine_step >= coarse_step:
            raise ValueError('the fine step must be smaller than the coarse step')
        if coarse_step > half_range:
            raise ValueError('the coarse step must not exceed the range')
        if limit is None or limit <= 0:
            raise ValueError('beam-axis limit unknown')
        self.center = float(center)
        self.half_range = float(half_range)
        self.coarse_step = float(coarse_step)
        self.fine_step = float(fine_step)
        self.limit = float(limit)
        self.window = window
        self.edge_margin = edge_margin
        self.samples_per_mm = samples_per_mm
        self.coarse_positions, self.clipped = sweep_positions(
            self.center, self.half_range, self.coarse_step, self.limit)
        self.notices = []
        if self.clipped:
            self.notices.append(
                f'Range clipped to the session limits: '
                f'{self.coarse_positions[0]:g}–{self.coarse_positions[-1]:g} mm.')
        if len(self.coarse_positions) < 3:
            raise ValueError('fewer than 3 coarse points inside the session limits')

    def flags(self, xs, measures):
        return point_flags(xs, measures, self.window, self.edge_margin, self.samples_per_mm)

    def _flagged_outcome(self, xs, measures, fit=None):
        bad = [(x, f) for x, f in zip(xs, self.flags(xs, measures)) if f]
        if not bad:
            return None
        kinds = sorted({k for _, f in bad for k in f})
        what = describe_flags(kinds)
        fix = []
        if 'edge' in kinds or 'outside' in kinds:
            fix.append('widen Smin–Smax on the Acquisition tab')
        if 'saturated' in kinds:
            fix.append('lower the gain')
        pts = ', '.join(f'{x:g}' for x, _ in bad)
        return FocusOutcome(
            False, f'{what} at {len(bad)} point(s) ({pts} mm): the curve is incomplete. '
                   f'{_upper_first(" and ".join(fix))}, then run again. Not moved to the optimum.',
            fit, list(self.notices))

    def after_coarse(self, xs, measures):
        outcome = self._flagged_outcome(xs, measures)
        if outcome is not None:
            return None, outcome
        amps = [m.amp for m in measures]
        i = int(np.argmax(amps))
        if i == 0 or i == len(xs) - 1:
            side = 'lower' if i == 0 else 'upper'
            extra = (' The range is clipped by the session limits there: the focus may be '
                     'outside the working volume.' if self.clipped else '')
            return None, FocusOutcome(
                False, f'Maximum on the {side} edge of the range ({xs[i]:g} mm): '
                       f'widen the range. Not moved to the optimum.{extra}', notices=list(self.notices))
        fine, _ = sweep_positions(xs[i], self.coarse_step, self.fine_step, self.limit)
        return fine, None

    def after_fine(self, xs, measures):
        amps = [m.amp for m in measures]
        fit = fit_parabola_db(xs, amps, int(np.argmax(amps)))
        outcome = self._flagged_outcome(xs, measures, fit)
        if outcome is not None:
            return outcome
        i = int(np.argmax(amps))
        if i == 0 or i == len(xs) - 1:
            return FocusOutcome(
                False, f'Fine-sweep maximum on its edge ({xs[i]:g} mm): the coarse curve '
                       'was misleading (noise?). Increase the averages. Not moved to the optimum.',
                notices=list(self.notices))
        x_opt = round(min(max(fit.x_opt, 0.0), self.limit), POSITION_DECIMALS)
        fit.x_opt = x_opt
        text = f'Focus at {x_opt:.2f} mm ({fit.db_opt:.2f} dB).'
        if fit.note:
            text += f' ({fit.note})'
        return FocusOutcome(True, text, fit, list(self.notices))


# ===========================================================================
#  Qt part: controller on top of the ScanSequencer, plot and widget
# ===========================================================================
import pyqtgraph as pg  # noqa: E402
from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QDoubleSpinBox, QFormLayout, QGroupBox, QLabel, QPushButton, QSpinBox,
)

_COL_COARSE = (150, 150, 150)
_COL_FINE = (80, 160, 255)
_COL_FLAG = (235, 60, 60)
_COL_FIT = (255, 200, 0)
_COL_OPT = (0, 220, 120)


class FocusPlot:
    """Amplitude (dB) vs beam position on the big 'Scanner' plot."""

    def __init__(self, plot_widget):
        self._pw = plot_widget

    def reset(self, axis):
        pw = self._pw
        pw.clear()
        pw.setTitle('Focus: envelope peak in Smin–Smax (PE)')
        pw.setLabel('bottom', f'Beam axis {axis}', units='mm')
        pw.setLabel('left', 'Envelope peak', units='dB')
        pw.getAxis('bottom').enableAutoSIPrefix(False)
        pw.getAxis('left').enableAutoSIPrefix(False)
        pw.enableAutoRange()
        self._data = {'coarse': ([], []), 'fine': ([], [])}
        self._curves = {
            'coarse': pw.plot(pen=pg.mkPen(_COL_COARSE, width=1), symbol='o', symbolSize=6,
                              symbolBrush=_COL_COARSE, symbolPen=None),
            'fine': pw.plot(pen=None, symbol='o', symbolSize=7,
                            symbolBrush=_COL_FINE, symbolPen=None),
            'flag': pw.plot(pen=None, symbol='x', symbolSize=12,
                            symbolBrush=_COL_FLAG, symbolPen=pg.mkPen(_COL_FLAG, width=2)),
        }

    def add_point(self, phase, x, db):
        xs, ys = self._data[phase]
        xs.append(x)
        ys.append(db)
        self._curves[phase].setData(xs, ys)

    def set_flagged(self, points):
        """points: [(x, dB)] of the measures that cannot be trusted (red crosses)."""
        self._curves['flag'].setData([p[0] for p in points], [p[1] for p in points])

    def show_fit(self, fit):
        if fit.coeffs is not None:
            a, b, c = fit.coeffs
            span = fit.fit_x[-1] - fit.fit_x[0]
            xx = np.linspace(fit.fit_x[0] - 0.25 * span, fit.fit_x[-1] + 0.25 * span, 100)
            self._pw.plot(xx, a * xx * xx + b * xx + c, pen=pg.mkPen(_COL_FIT, width=2))
        self._pw.plot([fit.x_opt], [fit.db_opt], pen=None, symbol='star', symbolSize=16,
                      symbolBrush=_COL_OPT, symbolPen=None)
        self._pw.addItem(pg.InfiniteLine(pos=fit.x_opt, angle=90,
                                         pen=pg.mkPen(_COL_OPT, width=1, style=Qt.DashLine)))


class FocusTool(QObject):
    """
    Runs a FocusPlan through the shared ScanSequencer: coarse, fine and the
    final move are three consecutive sequences. When the result does not allow
    moving to the optimum, a one-point 'return' sequence takes the beam axis
    back to where it was before the sweep. STOP (scanner panel) ends the
    current sequence and nothing else runs: no move to the optimum, no return;
    the current position is reported.

    Signals: status(str) progress/result text, warning(str) window-edge or
    saturation notices (emitted as soon as a point shows it), done(bool moved).
    """
    status = pyqtSignal(str)
    warning = pyqtSignal(str)
    done = pyqtSignal(bool)

    def __init__(self, sequencer, panel, window_fn, plot_widget, show_plot_fn=None,
                 cw_fn=None, parent=None):
        """
        sequencer     ScanSequencer (phase 2), used as is
        panel         ScannerPanel (role_axis, pe_side, current_coords, axis_limit,
                      sequence_blocker, validate_position)
        window_fn     () -> (smin, smax): the Acquisition tab window, read only
        cw_fn         () -> water speed of sound [m/s] or None (C_W_NOMINAL); only
                      used to predict where the echo moves
        """
        super().__init__(parent)
        self._seq = sequencer
        self._panel = panel
        self._window_fn = window_fn
        self._plot = FocusPlot(plot_widget)
        self._show_plot = show_plot_fn
        self._cw_fn = cw_fn
        self._phase = None
        self.last_outcome = None
        sequencer.point_done.connect(self._on_point)
        sequencer.finished.connect(self._on_finished)

    @property
    def running(self):
        return self._phase is not None

    def run(self, half_range, coarse, fine, avg_n=DEFAULT_AVG_N,
            settle_ms=DEFAULT_SETTLE_MS, edge_margin=DEFAULT_EDGE_MARGIN):
        """Start the search. Returns None if started, else the reason it could not."""
        if self._phase is not None or self._seq.active:
            return 'A sequence is already running.'
        reason = self._panel.sequence_blocker()
        if reason:
            return reason
        axis = self._panel.role_axis('beam')
        smin, smax = self._window_fn()
        if smax - smin < MIN_WINDOW_SAMPLES:
            return f'Acquisition window Smin–Smax too short ({smin}–{smax}).'
        c_w = (self._cw_fn() if self._cw_fn else None) or C_W_NOMINAL
        try:
            plan = FocusPlan(self._panel.current_coords()[axis], half_range, coarse, fine,
                             self._panel.axis_limit(axis), (smin, smax), edge_margin,
                             echo_samples_per_mm(self._panel.pe_side(), c_w))
        except ValueError as e:
            return str(e)
        self._axis, self._plan = axis, plan
        self._start_x = round(float(self._panel.current_coords()[axis]), POSITION_DECIMALS)
        self._window = (smin, smax)
        self._avg_n, self._settle_ms, self._margin = avg_n, settle_ms, edge_margin
        self.last_outcome = None
        self._plot.reset(axis)
        for text in plan.notices:
            self.warning.emit(text)
        reason = self._start_phase('coarse', plan.coarse_positions)
        if reason is None and self._show_plot is not None:
            self._show_plot()
        return reason

    # -- phases ----------------------------------------------------------------
    def _measure(self, ch1, ch2):
        sig = ch2 if PE_CHANNEL == 2 else ch1
        return window_peak(sig, self._window[0], self._window[1], self._margin)

    def _start_phase(self, phase, xs):
        self._phase = phase
        self._xs, self._measures = [], []
        self._warned = set()
        n = len(xs)
        if phase == 'move':
            self.status.emit(f'Focus: moving to {xs[0]:.2f} mm…')
        elif phase == 'return':
            self.status.emit(f'{self._return_text} Returning to {xs[0]:.2f} mm…')
        else:
            self.status.emit(f'Focus: {phase} sweep, {n} point{"s" if n != 1 else ""}…')
        reason = self._seq.start(
            [{self._axis: x} for x in xs], self._settle_ms, self._avg_n, self._measure,
            validate_fn=self._panel.validate_position, record_temperature=False)
        if reason is not None:
            self._phase = None
        return reason

    def _on_point(self, i, coords, value):
        if self._phase is None:
            return
        x = float(coords.get(self._axis, float('nan')))
        self._xs.append(x)
        self._measures.append(value)
        if self._phase in ('move', 'return'):
            return
        self._plot.add_point(self._phase, x, to_db(value.amp))
        # Checked on every point, not only at the end: a new reference can also
        # flag earlier points, so the whole phase is re-evaluated.
        flags = self._plan.flags(self._xs, self._measures)
        self._plot.set_flagged([(self._xs[k], to_db(self._measures[k].amp))
                                for k, f in enumerate(flags) if f])
        new = [k for k, f in enumerate(flags) if f and k not in self._warned]
        if new:
            self._warned.update(new)
            kinds = sorted({kind for k in new for kind in flags[k]})
            fix = []
            if 'edge' in kinds or 'outside' in kinds:
                fix.append('widen Smin–Smax')
            if 'saturated' in kinds:
                fix.append('lower the gain')
            pts = ', '.join(f'{self._xs[k]:g}' for k in new)
            self.warning.emit(f'{describe_flags(kinds)} at {pts} mm '
                              f'({len(self._warned)} marked point(s) in the {self._phase} sweep): '
                              f'{" and ".join(fix)}.')

    def _on_finished(self, status, text):
        if self._phase is None:
            return
        if status != 'done':
            # STOP (or a fault): nothing else moves, only report where the scanner is.
            phase = self._phase
            where = self._panel.current_coords().get(self._axis)
            pos = f' Scanner at {self._axis} = {where:.2f} mm.' if where is not None else ''
            self._end(False, f'Focus {status} during the {phase} phase: {text} '
                             f'Not moved.{pos}')
            return
        # Next phase outside the finished() emission (the sequencer is idle by now).
        QTimer.singleShot(0, self._next_phase)

    def _next_phase(self):
        if self._phase is None:
            return
        phase, xs, measures = self._phase, self._xs, self._measures
        if phase == 'coarse':
            fine, outcome = self._plan.after_coarse(xs, measures)
            if outcome is not None:
                self._return_to_start(outcome.text, outcome)
                return
            reason = self._start_phase('fine', fine)
            if reason:
                self._end(False, f'Focus: fine sweep could not start: {reason}')
        elif phase == 'fine':
            outcome = self._plan.after_fine(xs, measures)
            self.last_outcome = outcome
            if outcome.fit is not None:
                self._plot.show_fit(outcome.fit)
            if not outcome.move:
                self._return_to_start(outcome.text, outcome)
                return
            reason = self._start_phase('move', [outcome.fit.x_opt])
            if reason:
                self._end(False, f'{outcome.text} Could not move there: {reason}', outcome)
        elif phase == 'move':
            outcome = self.last_outcome
            self._end(True, f'{outcome.text} Moved there.', outcome)
        else:   # 'return'
            self._end(False, f'{self._return_text} Back at the start position '
                             f'({self._axis} = {self._start_x:.2f} mm).', self.last_outcome)

    def _return_to_start(self, text, outcome):
        """No move to the optimum: back to the beam position held before the sweep."""
        self.last_outcome = outcome
        self._return_text = text
        reason = self._start_phase('return', [self._start_x])
        if reason:
            self._end(False, f'{text} Could not return to {self._start_x:.2f} mm: {reason}',
                      outcome)

    def _end(self, moved, text, outcome=None):
        self._phase = None
        if outcome is not None:
            self.last_outcome = outcome
        self.status.emit(text)
        self.done.emit(moved)


class FocusGroup(QGroupBox):
    """Focus controls for the Scanner tab (spec 5.4). The window is Smin–Smax
    of the Acquisition tab; there is deliberately no window parameter here."""

    def __init__(self, tool, sequencer, window_fn, parent=None):
        super().__init__('Focus', parent)
        self._tool = tool
        self._window_fn = window_fn
        form = QFormLayout(self)

        def dspin(lo, hi, val, dec, step, suffix):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setSingleStep(step)
            s.setValue(val)
            s.setSuffix(suffix)
            return s

        self._spin_range = dspin(0.1, 100.0, DEFAULT_HALF_RANGE_MM, 2, 0.5, ' mm')
        self._spin_coarse = dspin(0.02, 20.0, DEFAULT_COARSE_MM, 2, 0.1, ' mm')
        self._spin_fine = dspin(0.01, 10.0, DEFAULT_FINE_MM, 2, 0.05, ' mm')
        self._spin_avg = QSpinBox()
        self._spin_avg.setRange(1, 1000)
        self._spin_avg.setValue(DEFAULT_AVG_N)
        self._spin_avg.setToolTip('Default pending measurement on the real equipment.')
        self._spin_settle = QSpinBox()
        self._spin_settle.setRange(0, 10000)
        self._spin_settle.setValue(DEFAULT_SETTLE_MS)
        self._spin_settle.setSuffix(' ms')
        self._spin_settle.setToolTip('Default pending measurement on the real equipment.')
        self._spin_margin = dspin(0.0, 25.0, DEFAULT_EDGE_MARGIN * 100, 1, 1.0, ' %')
        self._spin_margin.setToolTip('An envelope peak this close to Smin or Smax '
                                     '(fraction of the window width) is flagged.')
        form.addRow('Range (beam, ±):', self._spin_range)
        form.addRow('Coarse step:', self._spin_coarse)
        form.addRow('Fine step:', self._spin_fine)
        form.addRow('Averages:', self._spin_avg)
        form.addRow('Settle:', self._spin_settle)
        form.addRow('Window edge margin:', self._spin_margin)

        self._lbl_window = QLabel()
        self._lbl_window.setWordWrap(True)
        self._lbl_window.setStyleSheet('color: gray;')
        form.addRow(self._lbl_window)

        self._btn_run = QPushButton('Run focus')
        self._btn_run.clicked.connect(self._on_run)
        form.addRow(self._btn_run)

        self._lbl_warn = QLabel()
        self._lbl_warn.setWordWrap(True)
        self._lbl_warn.setStyleSheet('color: rgb(230, 120, 0);')
        form.addRow(self._lbl_warn)
        self._lbl_status = QLabel('Idle.')
        self._lbl_status.setWordWrap(True)
        form.addRow(self._lbl_status)

        tool.status.connect(self._lbl_status.setText)
        tool.warning.connect(self._on_warning)
        sequencer.state_changed.connect(lambda st: self._btn_run.setEnabled(st == 'idle'))
        self._refresh_window_label()

    def _refresh_window_label(self):
        try:
            smin, smax = self._window_fn()
            self._lbl_window.setText(f'Search window: Smin–Smax = {smin}–{smax} samples '
                                     '(Acquisition tab, read only).')
        except Exception:
            self._lbl_window.setText('Search window: Smin–Smax of the Acquisition tab.')

    def _on_warning(self, text):
        self._lbl_warn.setText(text)

    def _on_run(self):
        self._refresh_window_label()
        self._lbl_warn.setText('')
        reason = self._tool.run(
            self._spin_range.value(), self._spin_coarse.value(), self._spin_fine.value(),
            self._spin_avg.value(), self._spin_settle.value(),
            self._spin_margin.value() / 100.0)
        if reason:
            self._lbl_status.setText(reason)
