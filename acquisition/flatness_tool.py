# -*- coding: utf-8 -*-
"""
flatness_tool.py — Flatness (tilt) of the sample face (scanner phase 4).
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See task_scanner_phase4.md and scanner_tab_spec.md section 5.5.

What it measures: two lines of time of flight (ToF) of the FRONT-FACE echo
around the current position, the beam axis never moving:
    - lateral line, ±N mm along the lateral axis: a tilt of the face about the
      vertical axis makes the ToF change with the lateral position;
    - Z line, ±M mm along Z: a tilt about the lateral axis makes it change with Z.
The front echo is found with echo_tracking.FrontEchoTracker (one tracker per
line, first-peak rule on its first point). The beam axis does not move, so the
tracker gets the same beam position on every point: the prediction is t_prev
and the band absorbs the shift due to the tilt (2·step·tanθ/c_w per point,
~7 samples per mm at 3°). ToF = sub-sample envelope peak − emission sample.

Per line: weighted straight line ToF(x) (weights ∝ contrast², since the timing
jitter of a peak scales as 1/SNR; the absolute scale comes from the residuals,
n − 2 degrees of freedom), and
    θ = atan(c_w · Δt / (2 · Δx))
with its 1σ from the slope's, the RMS residual (as face displacement, µm) and
a tolerance indicator:
    'ok'            |θ| ≤ tolerance
    'out'           |θ| > tolerance
    'undetermined'  σθ > UNDETERMINED_FRACTION · tolerance: the measure cannot
                    tell whether it is within tolerance (more averages / range)
    'no_result'     fewer than MIN_FIT_POINTS usable points
When |θ| < SIGNIFICANCE·σθ the angle is reported as not distinguishable from 0
instead of a number with false precision, and no correction is proposed.

Sign convention (the synthetic SeDaq uses the same, sim_sedaq.py): θ > 0 means
the face gets FARTHER from the PE transducer as the lateral (resp. Z) counter
grows. Z grows downwards (spec section 1).

Corrections are MANUAL; the tool measures and reports, it never moves an axis
to correct:
    - lateral tilt → manual rotation stage about the vertical axis;
    - Z tilt       → manual tilt.
Each comes with the direction to turn: which end of the face must come closer
to the PE transducer, and by how much. The R axis is never used here (1.8° per
step is far too coarse; R is for rough orientation only) and the sequencer
cannot move it anyway (SEQUENCE_AXES).

Unreliable points (point flags of the focus tool plus 'weak': no clear echo in
the tracking band) are marked and left out of the fit. When the echo fades at
the ends of a line (the beam leaves the face), the fit is restricted to the
span with a clear echo and the tool says so, suggesting a range.

At the end the scanner goes back to the centre. A STOP ends the sequence and
nothing else moves; the tool only reports. Nothing is saved except the
optional debug dump (data/flatness_debug, one .npz per run).

The pure part (FlatnessPlan, analyse_line, Correction) has no Qt dependency and
is what test_flatness_tool.py exercises against sim_sedaq.SimSeDaq.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from echo_tracking import (
    ACQ_FS, DEFAULT_BAND_SAMPLES, DEFAULT_BAND_US, DEFAULT_EDGE_MARGIN, DEFAULT_THRESHOLD,
    MIN_WINDOW_SAMPLES, FrontEchoTracker, band_samples,
)
from focus_tool import (
    DEFAULT_EMISSION_SAMPLE, MOVE_MM_S, POSITION_DECIMALS, FocusDebugDump, acq_time,
    format_duration, host_value, measurement_meta, point_flags, resolve_cw, sweep_positions,
)
from scan_sequencer import DEFAULT_AVG_N, DEFAULT_SETTLE_MS

PE_CHANNEL = 2                 # ecos_gui.py: s_PE is Ch2
DEFAULT_LAT_HALF_MM = 10.0
DEFAULT_LAT_STEP_MM = 1.0
DEFAULT_Z_HALF_MM = 5.0
DEFAULT_Z_STEP_MM = 0.5
DEFAULT_TOLERANCE_DEG = 0.1
MIN_FIT_POINTS = 3
SIGNIFICANCE = 2.0             # |θ| below this × σθ: not distinguishable from 0
UNDETERMINED_FRACTION = 0.5    # σθ above this × tolerance: cannot judge the tolerance
DEFAULT_DUMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'data', 'flatness_debug')   # data/ is local only

LINES = ('lateral', 'z')
CONTROLS = {'lateral': 'rotation stage (manual, about the vertical axis)',
            'z': 'tilt (manual)'}


# ===========================================================================
#  Pure part
# ===========================================================================
@dataclass
class Correction:
    """
    Manual correction of one line's tilt. plus_end_toward_pe: the end of the
    face at the + side of the line's axis must come CLOSER to the PE
    transducer (False: it must move away). amount_deg: how much to turn.
    """
    line: str
    control: str
    plus_end_toward_pe: bool
    amount_deg: float
    text: str

    @property
    def delta_deg(self):
        """Signed change of θ that the correction applies (θ → θ + delta)."""
        return -self.amount_deg if self.plus_end_toward_pe else self.amount_deg


@dataclass
class LineResult:
    line: str                    # 'lateral' or 'z'
    axis: str                    # scanner axis of the line ('X', 'Y' or 'Z')
    center: float                # line centre [mm]
    xs: List[float]              # positions measured [mm]
    tof_samples: List[float]     # front-echo ToF from the emission sample, per point
    flags: List[List[str]]       # per point: 'edge', 'outside', 'saturated', 'weak'
    used: List[bool]             # per point: in the fit
    status: str = 'no_result'    # 'ok', 'out', 'undetermined', 'no_result'
    angle_deg: float = float('nan')
    sigma_deg: float = float('nan')
    slope: float = float('nan')          # samples/mm
    intercept: float = float('nan')      # samples at x = 0
    rms_um: float = float('nan')         # RMS residual as face displacement
    span: Optional[tuple] = None         # (lo, hi) positions used [mm]
    ends_lost: List[float] = field(default_factory=list)   # positions lost at the ends
    suggested_half: Optional[float] = None                  # ± range with a clear echo
    correction: Optional[Correction] = None
    messages: List[str] = field(default_factory=list)
    c_w: float = 1480.0
    fs: float = ACQ_FS

    @property
    def significant(self):
        return (self.status != 'no_result'
                and abs(self.angle_deg) >= SIGNIFICANCE * self.sigma_deg)

    def displacement_um(self, samples):
        """ToF samples → face displacement (one way) in µm."""
        return np.asarray(samples, dtype=float) / self.fs * self.c_w / 2.0 * 1e6

    def angle_text(self):
        """The angle with a precision that its 1σ supports, or 'not distinguishable from 0'."""
        if self.status == 'no_result':
            return 'no result'
        dec = decimals_for(self.sigma_deg)
        if not self.significant:
            return (f'not distinguishable from 0 (θ = {self.angle_deg:+.{dec}f}° ± '
                    f'{self.sigma_deg:.{dec}f}°, |θ| < {SIGNIFICANCE:g}σ)')
        return f'θ = {self.angle_deg:+.{dec}f}° ± {self.sigma_deg:.{dec}f}° (1σ)'


def decimals_for(sigma):
    """Decimals so that the 1σ shows two significant digits (2 to 4)."""
    if not (sigma > 0) or not math.isfinite(sigma):
        return 2
    return int(min(4, max(2, 1 - math.floor(math.log10(sigma)))))


def line_flags(xs, measures, window, edge_margin=DEFAULT_EDGE_MARGIN):
    """Point flags of the focus tool (no prediction: the beam does not move) plus
    'weak': no clear front echo in the tracking band."""
    flags = point_flags(xs, measures, window, edge_margin, None)
    for f, m in zip(flags, measures):
        if not m.confident and 'outside' not in f:
            f.append('weak')
    return flags


def correction_for(line, axis, angle_deg, dec=2):
    """Manual correction bringing θ to 0, with the direction spelled out."""
    toward = angle_deg > 0          # the + end is too far from the PE transducer
    amount = abs(angle_deg)
    how = 'comes closer to' if toward else 'moves away from'
    if line == 'lateral':
        text = (f'Turn the rotation stage (about the vertical axis) by {amount:.{dec}f}° so that '
                f'the {axis}+ end of the face {how} the PE transducer (Δθ = {-angle_deg:+.{dec}f}°).')
    else:
        text = (f'Tilt by {amount:.{dec}f}° so that the lower edge of the face (Z+, Z grows '
                f'downwards) {how} the PE transducer (Δθ = {-angle_deg:+.{dec}f}°).')
    return Correction(line, CONTROLS[line], toward, amount, text)


def analyse_line(line, axis, center, xs, measures, window, c_w, tolerance_deg,
                 edge_margin=DEFAULT_EDGE_MARGIN, emission_sample=DEFAULT_EMISSION_SAMPLE,
                 fs=ACQ_FS):
    """
    One line: flags, span with a clear echo, weighted ToF(x) line, θ ± σθ,
    RMS residual, tolerance status and the manual correction. See the module
    docstring.
    """
    flags = line_flags(xs, measures, window, edge_margin)
    tof = [(m.index_frac if m.index_frac == m.index_frac else float(m.index)) - emission_sample
           for m in measures]
    res = LineResult(line, axis, float(center), list(xs), tof, flags, [False] * len(xs),
                     c_w=float(c_w), fs=fs)
    good = [k for k, f in enumerate(flags) if not f]
    lost = [k for k, f in enumerate(flags) if ('weak' in f or 'outside' in f)]
    if good:
        k0, k1 = good[0], good[-1]
        res.ends_lost = [xs[k] for k in lost if k < k0 or k > k1]
        if res.ends_lost:
            res.suggested_half = round(min(center - xs[k0], xs[k1] - center), POSITION_DECIMALS)
    res.used = [not f for f in flags]
    res.messages = _line_messages(res, measures)
    if len(good) < MIN_FIT_POINTS:
        res.messages.append(f'Fewer than {MIN_FIT_POINTS} points with a clear front echo: '
                            'no result for this line.')
        return res
    x = np.array([xs[k] for k in good])
    t = np.array([tof[k] for k in good])
    w = np.array([measures[k].contrast if math.isfinite(measures[k].contrast) else 1e3
                  for k in good]) ** 2
    X = np.column_stack([np.ones_like(x), x - center])
    cov = np.linalg.inv(X.T @ (X * w[:, None]))
    b0, b1 = cov @ (X.T @ (w * t))
    r = t - X @ np.array([b0, b1])
    dof = len(x) - 2
    s2 = float(np.sum(w * r * r)) / dof if dof > 0 else float('nan')
    sigma_b1 = math.sqrt(max(s2 * cov[1, 1], 0.0))
    k = c_w / (2.0 * fs) * 1e3            # samples/mm → tan θ
    theta = math.atan(k * b1)
    res.slope, res.intercept = float(b1), float(b0 - b1 * center)
    res.angle_deg = math.degrees(theta)
    res.sigma_deg = math.degrees(k * sigma_b1 / (1.0 + (k * b1) ** 2))
    res.rms_um = float(np.sqrt(np.mean(res.displacement_um(r) ** 2)))
    res.span = (float(x.min()), float(x.max()))
    if res.sigma_deg > UNDETERMINED_FRACTION * tolerance_deg:
        res.status = 'undetermined'
        res.messages.append(f'1σ = {res.sigma_deg:.3f}° is too large to judge a tolerance of '
                            f'{tolerance_deg:g}°: increase the averages or the range.')
    else:
        res.status = 'ok' if abs(res.angle_deg) <= tolerance_deg else 'out'
    if res.significant:
        res.correction = correction_for(line, axis, res.angle_deg, decimals_for(res.sigma_deg))
    return res


def _line_messages(res, measures):
    """Why points were left out: narrow window, face ends, tracking lost, saturation."""
    msgs = []
    edge = [x for x, f in zip(res.xs, res.flags) if 'edge' in f]
    if edge:
        msgs.append(f'Echo pinned at an edge of Smin–Smax at {_pts(edge)} mm: the window is too '
                    'narrow for the tilt, widen Smin–Smax on the Acquisition tab.')
    if res.ends_lost:
        rng = (f' Reduce the {res.line} range to ±{res.suggested_half:g} mm.'
               if res.suggested_half is not None else '')
        msgs.append(f'No clear front echo at the ends of the line ({_pts(res.ends_lost)} mm): '
                    f'the beam probably leaves the face there; those points are left out.{rng}')
    inner = [k for k, f in enumerate(res.flags)
             if ('weak' in f or 'outside' in f) and res.xs[k] not in res.ends_lost]
    if inner:
        elsewhere = any(measures[k].echo_elsewhere for k in inner)
        why = ('a clear echo lies outside the tracking band: the tilt shift per step exceeds the '
               'band, reduce the step or widen the band' if elsewhere else
               'no clear echo in the tracking band (defect of the face, or beam off the face)')
        msgs.append(f'Front-echo tracking lost at {_pts([res.xs[k] for k in inner])} mm: '
                    f'{why}. Left out of the fit.')
    sat = [x for x, f in zip(res.xs, res.flags) if 'saturated' in f]
    if sat:
        msgs.append(f'Signal saturated at {_pts(sat)} mm: lower the gain. Left out of the fit.')
    return msgs


def _pts(xs):
    return ', '.join(f'{x:g}' for x in xs)


@dataclass
class FlatnessOutcome:
    lines: Dict[str, LineResult]
    text: str
    notices: List[str] = field(default_factory=list)

    def report(self):
        out = []
        for name in LINES:
            r = self.lines.get(name)
            if r is None:
                continue
            head = 'Lateral' if name == 'lateral' else 'Z'
            line = f'{head} ({r.axis}): {r.angle_text()}'
            if r.status != 'no_result':
                line += f', RMS residual {r.rms_um:.1f} µm, {STATUS_TEXT[r.status]}'
            out.append(line + '.')
            if r.correction is not None and r.status in ('out', 'undetermined'):
                out.append(f'  → {r.correction.text}')
            elif r.status == 'ok':
                out.append('  → Within tolerance: no correction needed.')
            out.extend('  ' + m for m in r.messages)
        return out


STATUS_TEXT = {'ok': 'within tolerance', 'out': 'OUT of tolerance',
               'undetermined': 'undetermined against the tolerance', 'no_result': 'no result'}


class FlatnessPlan:
    """
    Positions and analysis of a flatness run, without Qt or hardware:
        plan = FlatnessPlan(coords, beam_axis, lat_axis, ...)
        plan.positions('lateral'), plan.positions('z')   -> sequencer positions
        plan.return_position                            -> back to the centre
        plan.new_tracker()                              -> one per line
        plan.analyse(line, xs, measures)                -> LineResult
    coords: current {axis: mm} (the centre). limits: {axis: limit}.
    """

    def __init__(self, coords, beam_axis, lat_axis, limits, lat_half, lat_step, z_half, z_step,
                 window, tolerance_deg=DEFAULT_TOLERANCE_DEG, edge_margin=DEFAULT_EDGE_MARGIN,
                 band=DEFAULT_BAND_SAMPLES, threshold=DEFAULT_THRESHOLD, c_w=1480.0,
                 cw_source='nominal', emission_sample=DEFAULT_EMISSION_SAMPLE, fs=ACQ_FS):
        for name, half, step in (('lateral', lat_half, lat_step), ('Z', z_half, z_step)):
            if not (half > 0 and step > 0):
                raise ValueError(f'{name} range and step must be positive')
            if step > half:
                raise ValueError(f'the {name} step must not exceed the {name} range')
        if not (tolerance_deg > 0):
            raise ValueError('the tolerance must be positive')
        self.beam_axis, self.lat_axis = beam_axis, lat_axis
        self.axes = {'lateral': lat_axis, 'z': 'Z'}
        self.centers = {'lateral': round(float(coords[lat_axis]), POSITION_DECIMALS),
                        'z': round(float(coords['Z']), POSITION_DECIMALS)}
        self.beam_x = float(coords[beam_axis])
        self.window = window
        self.tolerance_deg = float(tolerance_deg)
        self.edge_margin = edge_margin
        self.band, self.threshold = band, threshold
        self.c_w, self.cw_source = float(c_w), cw_source
        self.emission_sample, self.fs = emission_sample, fs
        self.notices = []
        self.line_xs = {}
        for line, half, step in (('lateral', lat_half, lat_step), ('z', z_half, z_step)):
            axis = self.axes[line]
            limit = limits.get(axis)
            if limit is None or limit <= 0:
                raise ValueError(f'{axis} limit unknown')
            xs, clipped = sweep_positions(self.centers[line], half, step, limit)
            if clipped:
                self.notices.append(f'{line.capitalize()} range clipped to the session limits: '
                                    f'{xs[0]:g}–{xs[-1]:g} mm.')
            if len(xs) < MIN_FIT_POINTS:
                raise ValueError(f'fewer than {MIN_FIT_POINTS} {line} points inside the limits')
            self.line_xs[line] = xs

    def positions(self, line):
        """Sequencer positions of a line. The Z line holds lateral at the centre."""
        if line == 'lateral':
            return [{self.lat_axis: x} for x in self.line_xs['lateral']]
        return [{self.lat_axis: self.centers['lateral'], 'Z': z} for z in self.line_xs['z']]

    @property
    def return_position(self):
        return {self.lat_axis: self.centers['lateral'], 'Z': self.centers['z']}

    def all_positions(self):
        return self.positions('lateral') + self.positions('z') + [self.return_position]

    def new_tracker(self):
        """Fresh tracker for a line: first-peak rule on its first point; the beam
        position never changes, so the prediction is t_prev."""
        return FrontEchoTracker(self.window, 0.0, self.band, self.threshold, self.edge_margin)

    def analyse(self, line, xs, measures):
        return analyse_line(line, self.axes[line], self.centers[line], xs, measures, self.window,
                            self.c_w, self.tolerance_deg, self.edge_margin,
                            self.emission_sample, self.fs)

    def outcome(self, results):
        text = 'Flatness: ' + '; '.join(
            f'{"lateral" if n == "lateral" else "Z"} {STATUS_TEXT[results[n].status]}'
            for n in LINES if n in results) + '.'
        return FlatnessOutcome(dict(results), text, list(self.notices))


def estimate_path_s(positions, start, settle_ms, avg_n, acq_s, move_mm_s=MOVE_MM_S):
    """Multi-axis positions: moves axis by axis at move_mm_s + settle + acquisitions."""
    total, cur = 0.0, dict(start)
    for pos in positions:
        travel = sum(abs(v - cur.get(a, v)) for a, v in pos.items())
        cur.update(pos)
        total += travel / move_mm_s + settle_ms / 1000.0 + avg_n * acq_s
    return total


# ===========================================================================
#  Qt part: controller on top of the ScanSequencer, plot and widget
# ===========================================================================
import pyqtgraph as pg  # noqa: E402
from PyQt5.QtCore import QObject, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QWidget,
)

_COL = {'lateral': (80, 160, 255), 'z': (255, 150, 40)}
_COL_FLAG = (235, 60, 60)
_STATUS_STYLE = {
    'ok': 'background: rgb(40, 160, 70); color: white;',
    'out': 'background: rgb(200, 40, 40); color: white;',
    'undetermined': 'background: rgb(230, 150, 0); color: black;',
    'no_result': 'background: gray; color: white;',
}


class FlatnessPlot:
    """Face displacement (µm, from the ToF) vs position relative to the centre, both lines."""

    def __init__(self, plot_widget):
        self._pw = plot_widget

    def reset(self, lat_axis):
        pw = self._pw
        pw.clear()
        pw.setTitle('Flatness: <span style="color:#50a0ff">lateral (%s)</span> and '
                    '<span style="color:#ff9628">Z</span> — front-face displacement' % lat_axis)
        pw.setLabel('bottom', 'Position relative to the centre', units='mm')
        pw.setLabel('left', 'Face displacement (from ToF)', units='µm')
        pw.getAxis('bottom').enableAutoSIPrefix(False)
        pw.getAxis('left').enableAutoSIPrefix(False)
        pw.enableAutoRange()
        self._curves = {}
        for line in LINES:
            col = _COL[line]
            self._curves[line] = pw.plot(pen=None, symbol='o', symbolSize=7,
                                         symbolBrush=col, symbolPen=None)
        self._flag = pw.plot(pen=None, symbol='x', symbolSize=12,
                             symbolBrush=_COL_FLAG, symbolPen=pg.mkPen(_COL_FLAG, width=2))
        self._flagged = {line: ([], []) for line in LINES}
        self._ref = {}

    def set_points(self, line, rel_xs, disp_um, flagged):
        """flagged: per point bool (red cross)."""
        self._curves[line].setData(list(rel_xs), list(disp_um))
        self._flagged[line] = ([x for x, f in zip(rel_xs, flagged) if f],
                               [y for y, f in zip(disp_um, flagged) if f])
        fx = self._flagged['lateral'][0] + self._flagged['z'][0]
        fy = self._flagged['lateral'][1] + self._flagged['z'][1]
        self._flag.setData(fx, fy)

    def show_fit(self, res, ref_samples):
        if res.status == 'no_result':
            return
        lo, hi = res.span
        xx = np.array([lo, hi])
        yy = res.displacement_um(res.intercept + res.slope * xx - ref_samples)
        self._pw.plot(xx - res.center, yy, pen=pg.mkPen(_COL[res.line], width=2))


class FlatnessTool(QObject):
    """
    Runs a FlatnessPlan through the shared ScanSequencer: the lateral line, the
    Z line and the return to the centre are three consecutive sequences. STOP
    (scanner panel) ends the current sequence and nothing else moves. After a
    fault nothing moves either.

    Signals: status(str), warning(str), echo_used(PeakMeasure) (A-scan mark),
    result(FlatnessOutcome), done(bool completed).
    """
    status = pyqtSignal(str)
    warning = pyqtSignal(str)
    echo_used = pyqtSignal(object)
    result = pyqtSignal(object)
    done = pyqtSignal(bool)

    def __init__(self, sequencer, panel, window_fn, plot_widget, show_plot_fn=None,
                 cw_fn=None, dump_dir=None, acq_time_fn=None, gains_fn=None, temp_fn=None,
                 parent=None):
        """Same collaborators as focus_tool.FocusTool (c_w from the PT100s, GetAScan timing)."""
        super().__init__(parent)
        self._seq = sequencer
        self._panel = panel
        self._window_fn = window_fn
        self._plot = FlatnessPlot(plot_widget)
        self._show_plot = show_plot_fn
        self._cw_fn = cw_fn
        self._acq_time_fn = acq_time_fn
        self._gains_fn = gains_fn        # () -> (g1, g2) [dB], debug-dump metadata only
        self._temp_fn = temp_fn          # () -> latest PT100 reading dict or None, idem
        self._dump_dir = dump_dir or DEFAULT_DUMP_DIR
        self._phase = None
        self._dump = None
        self.last_outcome = None
        self.last_dump_path = None
        self.last_params = None
        sequencer.point_done.connect(self._on_point)
        sequencer.finished.connect(self._on_finished)

    @property
    def running(self):
        return self._phase is not None

    def _coords_and_limits(self):
        beam = self._panel.role_axis('beam')
        lat = self._panel.role_axis('lateral')
        coords = self._panel.current_coords()
        limits = {a: self._panel.axis_limit(a) for a in (lat, 'Z')}
        return beam, lat, coords, limits

    def estimate(self, lat_half, lat_step, z_half, z_step, avg_n=DEFAULT_AVG_N,
                 settle_ms=DEFAULT_SETTLE_MS):
        """(seconds, text) before starting, or (None, reason)."""
        try:
            beam, lat, coords, limits = self._coords_and_limits()
            plan = FlatnessPlan(coords, beam, lat, limits, lat_half, lat_step, z_half, z_step,
                                (0, MIN_WINDOW_SAMPLES))
        except Exception as e:
            return None, f'Estimate not available ({e}).'
        acq_s, timed = acq_time(self._acq_time_fn)
        total = estimate_path_s(plan.all_positions(), coords, settle_ms, avg_n, acq_s)
        n_lat, n_z = len(plan.line_xs['lateral']), len(plan.line_xs['z'])
        acq = f'{acq_s * 1e3:.0f} ms/A-scan {"timed" if timed else "assumed"}'
        return total, (f'Estimated time ≈ {format_duration(total)} (lateral {n_lat} pts + Z '
                       f'{n_z} pts + return; per point {settle_ms / 1000.0:g} s settle + '
                       f'{avg_n} × {acq}, moves at {MOVE_MM_S:g} mm/s).')

    def run(self, lat_half=DEFAULT_LAT_HALF_MM, lat_step=DEFAULT_LAT_STEP_MM,
            z_half=DEFAULT_Z_HALF_MM, z_step=DEFAULT_Z_STEP_MM, avg_n=DEFAULT_AVG_N,
            settle_ms=DEFAULT_SETTLE_MS, tolerance_deg=DEFAULT_TOLERANCE_DEG,
            edge_margin=DEFAULT_EDGE_MARGIN, band_us=DEFAULT_BAND_US,
            threshold=DEFAULT_THRESHOLD, debug_dump=True,
            emission_sample=DEFAULT_EMISSION_SAMPLE):
        """Start both lines. Returns None if started, else the reason it could not."""
        params = dict(lat_half=lat_half, lat_step=lat_step, z_half=z_half, z_step=z_step,
                      avg_n=avg_n, settle_ms=settle_ms, tolerance_deg=tolerance_deg,
                      edge_margin=edge_margin, band_us=band_us, threshold=threshold,
                      debug_dump=debug_dump, emission_sample=emission_sample)
        if self._phase is not None or self._seq.active:
            return 'A sequence is already running.'
        reason = self._seq.reserved_reason(self)
        if reason:
            return reason
        reason = self._panel.sequence_blocker()
        if reason:
            return reason
        smin, smax = self._window_fn()
        if smax - smin < MIN_WINDOW_SAMPLES:
            return f'Acquisition window Smin–Smax too short ({smin}–{smax}).'
        estimate = self.estimate(lat_half, lat_step, z_half, z_step, avg_n, settle_ms)[1]
        c_w, cw_source = resolve_cw(self._cw_fn)
        beam, lat, coords, limits = self._coords_and_limits()
        try:
            plan = FlatnessPlan(coords, beam, lat, limits, lat_half, lat_step, z_half, z_step,
                                (smin, smax), tolerance_deg, edge_margin, band_samples(band_us),
                                threshold, c_w, cw_source, emission_sample)
        except ValueError as e:
            return str(e)
        self._plan = plan
        self.last_params = params
        self.last_outcome = None
        self.last_dump_path = None
        self._results = {}
        self._avg_n, self._settle_ms = avg_n, settle_ms
        self._dump = FocusDebugDump(dict(
            tool='flatness', started=time.strftime('%Y-%m-%dT%H:%M:%S'), beam_axis=beam,
            lateral_axis=lat, beam_x=plan.beam_x, centers=plan.centers, smin=smin, smax=smax,
            lat_half_mm=lat_half, lat_step_mm=lat_step, z_half_mm=z_half, z_step_mm=z_step,
            tolerance_deg=tolerance_deg,
            edge_margin=edge_margin, band_us=band_us, band_samples=plan.band,
            threshold=threshold, c_w=c_w, cw_source=cw_source, emission_sample=emission_sample,
            fs=ACQ_FS, pe_channel=PE_CHANNEL, notices=plan.notices,
            **measurement_meta(settle_ms, avg_n, host_value(self._gains_fn),
                               host_value(self._temp_fn)),
        ), prefix='flatness_debug') if debug_dump else None
        self._plot.reset(lat)
        for text in plan.notices:
            self.warning.emit(text)
        reason = self._start_phase('lateral')
        if reason is None:
            self.status.emit(f'Flatness: lateral line, {len(plan.line_xs["lateral"])} points '
                             f'(c_w = {c_w:.1f} m/s, {cw_source}). {estimate}')
            if self._show_plot is not None:
                self._show_plot()
        return reason

    def repeat(self):
        """Run again with the parameters of the last run (the usual loop: correct, re-measure)."""
        if self.last_params is None:
            return 'Nothing to repeat yet.'
        return self.run(**self.last_params)

    # -- phases ----------------------------------------------------------------
    def _measure(self, ch1, ch2):
        sig = ch2 if PE_CHANNEL == 2 else ch1
        if self._dump is not None:
            self._last_record = np.array(sig, dtype=float)
        return self._tracker.measure(sig, self._plan.beam_x,     # saturation: raw, Smin–Smax
                                     self._seq.top_count(PE_CHANNEL, self._tracker.window))

    def _start_phase(self, phase):
        self._phase = phase
        self._xs, self._measures = [], []
        self._warned = set()
        self._tracker = self._plan.new_tracker()
        self._tracker.new_sweep()
        self._dump_start = len(self._dump) if self._dump is not None else 0
        if phase == 'return':
            positions = [self._plan.return_position]
            self.status.emit('Flatness: back to the centre…')
        else:
            positions = self._plan.positions(phase)
            self.status.emit(f'Flatness: {"lateral" if phase == "lateral" else "Z"} line, '
                             f'{len(positions)} points…')
        reason = self._seq.start(
            positions, self._settle_ms, self._avg_n, self._measure,
            validate_fn=self._panel.validate_position, record_temperature=False)
        if reason is not None:
            self._phase = None
        return reason

    def _line_pos(self, coords):
        axis = self._plan.axes.get(self._phase, self._plan.lat_axis)
        return float(coords.get(axis, float('nan')))

    def _on_point(self, i, coords, value):
        if self._phase is None:
            return
        x = self._line_pos(coords)
        self._xs.append(x)
        self._measures = list(self._tracker.measures)     # a re-lock revises earlier points
        if self._dump is not None:
            seg, env = self._tracker.point_signals(-1)
            self._dump.add(self._phase, self._plan.beam_x, value, seg, env, self._last_record,
                           self._plan.window, extra={})
            self._dump.revise(self._dump_start, self._measures)
            for k, m in enumerate(self._measures):
                tof = m.index_frac - self._plan.emission_sample
                self._dump.set_extra(
                    self._dump_start + k, line=self._phase,
                    line_position=self._xs[k] if k < len(self._xs) else x,
                    line_offset=(self._xs[k] - self._plan.centers.get(self._phase, 0.0))
                    if self._phase in LINES else 0.0,
                    tof_samples=tof, tof_us=tof / self._plan.fs * 1e6)
        self.echo_used.emit(value)
        if self._phase not in LINES:
            return
        flags = line_flags(self._xs, self._measures, self._plan.window, self._plan.edge_margin)
        if self._dump is not None:
            self._dump.revise(self._dump_start, self._measures, flags)
        tofs = np.array([m.index_frac for m in self._measures])
        clear = [k for k, f in enumerate(flags) if not f]
        ref = float(np.median(tofs[clear])) if clear else float(tofs[0])
        self._ref = ref
        disp = self._plan.c_w * (tofs - ref) / self._plan.fs / 2.0 * 1e6
        center = self._plan.centers[self._phase]
        self._plot.set_points(self._phase, [xx - center for xx in self._xs], disp,
                              [bool(f) for f in flags])
        new = [k for k, f in enumerate(flags) if f and k not in self._warned
               and ('edge' in f or 'saturated' in f)]
        if new:
            self._warned.update(new)
            self.warning.emit(f'{"Lateral" if self._phase == "lateral" else "Z"} line: unreliable '
                              f'points at {_pts([self._xs[k] for k in new])} mm (window edge or '
                              'saturation), marked and left out of the fit.')

    def _on_finished(self, status, text):
        if self._phase is None:
            return
        if status != 'done':
            phase = self._phase
            where = self._panel.current_coords()
            pos = ', '.join(f'{a} = {where[a]:.2f} mm' for a in (self._plan.lat_axis, 'Z')
                            if a in where)
            self._end(False, f'Flatness {status} during the '
                             f'{"return" if phase == "return" else phase + " line"}: {text} '
                             f'Not moved. Scanner at {pos}.')
            return
        QTimer.singleShot(0, self._next_phase)

    def _next_phase(self):
        if self._phase is None:
            return
        phase = self._phase
        if phase in LINES:
            res = self._plan.analyse(phase, self._xs, self._measures)
            self._results[phase] = res
            self._plot.show_fit(res, getattr(self, '_ref', 0.0) - self._plan.emission_sample)
            nxt = 'z' if phase == 'lateral' else 'return'
            reason = self._start_phase(nxt)
            if reason:
                self._finish_result(f'Could not start the next step: {reason}', completed=False)
        else:
            self._finish_result('Back at the centre.', completed=True)

    def _finish_result(self, tail, completed):
        outcome = self._plan.outcome(self._results)
        self.last_outcome = outcome
        self.result.emit(outcome)
        self._end(completed, '\n'.join([f'{outcome.text} {tail}'] + outcome.report()))

    def _end(self, completed, text):
        self._phase = None
        text += self._save_dump(completed, text)
        self.status.emit(text)
        self.done.emit(completed)

    def _save_dump(self, completed, text):
        dump, self._dump = self._dump, None
        if dump is None or not len(dump):
            return ''
        dump.meta.update(result=text, completed=completed, lines={
            n: dict(angle_deg=r.angle_deg, sigma_deg=r.sigma_deg, rms_um=r.rms_um,
                    status=r.status, span=r.span, slope_samples_per_mm=r.slope)
            for n, r in self._results.items()})
        try:
            self.last_dump_path = dump.save(self._dump_dir)
        except Exception as e:
            self.warning.emit(f'Flatness debug dump not saved: {e}')
            return ''
        return f'\nDebug dump: {self.last_dump_path}'


class FlatnessGroup(QGroupBox):
    """Flatness controls for the Scanner tab (spec 5.5). Corrections are manual:
    the rotation stage for the lateral tilt, the tilt for Z. R is never used."""

    def __init__(self, tool, sequencer, parent=None):
        super().__init__('Flatness', parent)
        self._tool = tool
        form = QFormLayout(self)

        def dspin(lo, hi, val, dec, step, suffix):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setSingleStep(step)
            s.setValue(val)
            s.setSuffix(suffix)
            return s

        self._spin_lat = dspin(0.1, 100.0, DEFAULT_LAT_HALF_MM, 2, 0.5, ' mm')
        self._spin_lat_step = dspin(0.02, 20.0, DEFAULT_LAT_STEP_MM, 2, 0.1, ' mm')
        self._spin_z = dspin(0.1, 50.0, DEFAULT_Z_HALF_MM, 2, 0.5, ' mm')
        self._spin_z_step = dspin(0.02, 20.0, DEFAULT_Z_STEP_MM, 2, 0.1, ' mm')
        self._spin_avg = QSpinBox()
        self._spin_avg.setRange(1, 10000)
        self._spin_avg.setValue(DEFAULT_AVG_N)
        self._spin_settle = QSpinBox()
        self._spin_settle.setRange(0, 60000)
        self._spin_settle.setValue(DEFAULT_SETTLE_MS)
        self._spin_settle.setSuffix(' ms')
        self._spin_tol = dspin(0.001, 10.0, DEFAULT_TOLERANCE_DEG, 3, 0.01, ' °')
        self._spin_band = dspin(0.05, 10.0, DEFAULT_BAND_US, 2, 0.05, ' µs')
        self._spin_band.setToolTip('The echo is searched within ± this of its time on the '
                                   'previous point: it must absorb the tilt shift per step.')
        self._chk_dump = QCheckBox('Save debug dump (.npz, data/flatness_debug)')
        self._chk_dump.setChecked(True)
        form.addRow('Lateral range (±):', self._spin_lat)
        form.addRow('Lateral step:', self._spin_lat_step)
        form.addRow('Z range (±):', self._spin_z)
        form.addRow('Z step:', self._spin_z_step)
        form.addRow('Averages:', self._spin_avg)
        form.addRow('Settle:', self._spin_settle)
        form.addRow('Tolerance:', self._spin_tol)
        form.addRow('Tracking band (±):', self._spin_band)
        form.addRow(self._chk_dump)

        self._lbl_estimate = QLabel()
        self._lbl_estimate.setWordWrap(True)
        self._lbl_estimate.setStyleSheet('color: gray;')
        form.addRow(self._lbl_estimate)

        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        self._btn_run = QPushButton('Run flatness')
        self._btn_repeat = QPushButton('Repeat')
        self._btn_repeat.setToolTip('Same parameters again: correct by hand, then repeat.')
        self._btn_repeat.setEnabled(False)
        row.addWidget(self._btn_run)
        row.addWidget(self._btn_repeat)
        form.addRow(buttons)

        self._lbl_axis = {}
        for line, name in (('lateral', 'Lateral tilt → rotation stage'),
                           ('z', 'Z tilt → manual tilt')):
            lbl = QLabel('—')
            lbl.setWordWrap(True)
            lbl.setStyleSheet(_STATUS_STYLE['no_result'])
            self._lbl_axis[line] = lbl
            form.addRow(name + ':', lbl)

        self._lbl_warn = QLabel()
        self._lbl_warn.setWordWrap(True)
        self._lbl_warn.setStyleSheet('color: rgb(230, 120, 0);')
        form.addRow(self._lbl_warn)
        self._lbl_status = QLabel('Idle.')
        self._lbl_status.setWordWrap(True)
        form.addRow(self._lbl_status)

        self._btn_run.clicked.connect(self._on_run)
        self._btn_repeat.clicked.connect(self._on_repeat)
        tool.status.connect(self._lbl_status.setText)
        tool.warning.connect(self._lbl_warn.setText)
        tool.result.connect(self._on_result)
        sequencer.state_changed.connect(self._on_seq_state)
        for spin in (self._spin_lat, self._spin_lat_step, self._spin_z, self._spin_z_step,
                     self._spin_avg, self._spin_settle):
            spin.valueChanged.connect(self._refresh_estimate)
        self._refresh_estimate()

    def _on_seq_state(self, state):
        idle = state == 'idle'
        self._btn_run.setEnabled(idle)
        self._btn_repeat.setEnabled(idle and self._tool.last_params is not None)

    def _refresh_estimate(self, *_):
        _, text = self._tool.estimate(self._spin_lat.value(), self._spin_lat_step.value(),
                                      self._spin_z.value(), self._spin_z_step.value(),
                                      self._spin_avg.value(), self._spin_settle.value())
        self._lbl_estimate.setText(text)

    def showEvent(self, event):
        self._refresh_estimate()
        super().showEvent(event)

    def _params(self):
        return dict(lat_half=self._spin_lat.value(), lat_step=self._spin_lat_step.value(),
                    z_half=self._spin_z.value(), z_step=self._spin_z_step.value(),
                    avg_n=self._spin_avg.value(), settle_ms=self._spin_settle.value(),
                    tolerance_deg=self._spin_tol.value(), band_us=self._spin_band.value(),
                    debug_dump=self._chk_dump.isChecked())

    def _start(self, reason):
        if reason:
            self._lbl_status.setText(reason)
        else:
            for lbl in self._lbl_axis.values():
                lbl.setText('measuring…')
                lbl.setStyleSheet(_STATUS_STYLE['no_result'])

    def _on_run(self):
        self._refresh_estimate()
        self._lbl_warn.setText('')
        self._start(self._tool.run(**self._params()))

    def _on_repeat(self):
        self._lbl_warn.setText('')
        self._start(self._tool.repeat())

    def _on_result(self, outcome):
        for line, lbl in self._lbl_axis.items():
            r = outcome.lines.get(line)
            if r is None:
                lbl.setText('not measured')
                lbl.setStyleSheet(_STATUS_STYLE['no_result'])
                continue
            text = f'{r.angle_text()} — {STATUS_TEXT[r.status]}'
            if r.correction is not None and r.status != 'ok':
                text += f'\n{r.correction.text}'
            lbl.setText(text)
            lbl.setStyleSheet(_STATUS_STYLE[r.status])
