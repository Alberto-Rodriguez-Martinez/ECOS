# -*- coding: utf-8 -*-
"""
scan_tool.py — Line and surface scans with live maps, water references, thickness,
witness point and saving (scanner phases 5 and 6).
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See task_scanner_phase5.md, task_scanner_phase6.md and scanner_tab_spec.md 5.6.

Phase 6 (surface). A line is the case of a single line. The whole scan is one
sequence (scan_schedule): every point of every line in the order of the path
(zigzag by default, or always the same direction) and the witness visits, with
a fixed axis order and its own settle per entry (a longer, not characterized
one after every long move: line change, witness visit). Per point, besides the
phase-5 values:
    - thickness: echo 1 → echo 2 by cross-correlation (echo_pair_delay) and the
      correlation coefficient as its quality. Checked at Start: if echo 2 does
      not fit in Smin–Smax it is disabled and not offered. Immune to the drift
      of the sample, so it is the default magnitude of the map;
    - witness point: a fixed point measured again every N lines. Saved raw; the
      lines where it jumps off the trend are marked as doubtful. The drift is
      corrected only in the analysis (and, if asked, on the live ToF map), and
      never on the thickness.
The temperature is also read at the end of every line. The live map of a
surface is 2-D (SurfaceMap), drawn as the lines come in. Saved in spatial order
(N_line × N_point), a stopped line padded and marked as partial.

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
measured with 1 mm steps). DEFAULT_SCAN_SETTLE_MS = 100 ms, measured on the
real equipment (see the constant); DEFAULT_SCAN_AVG_N still pending.
"""
from __future__ import annotations

import math
import os
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional

import numpy as np

from echo_tracking import (
    ACQ_FS, DEFAULT_BAND_SAMPLES, DEFAULT_BAND_US, DEFAULT_EDGE_MARGIN, DEFAULT_THRESHOLD,
    MIN_WINDOW_SAMPLES, EchoDelay, FrontEchoTracker, band_samples, echo_pair_delay,
)
from flatness_tool import line_flags
from ECOS_US_ToolBox import CalcToFAscanCosine_XCRFFT, Envelope
from echo_tracking import CONFIDENT_CONTRAST
from focus_tool import (
    DEFAULT_EMISSION_SAMPLE, MOVE_MM_S, POSITION_DECIMALS, FocusDebugDump, acq_time,
    format_duration, measurement_meta, resolve_cw,
)

_DB_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                        'database'))
if _DB_DIR not in sys.path:
    sys.path.insert(0, _DB_DIR)
from scan_counts import ADC_BITS_DEFAULT, counts_to_float  # noqa: E402

PE_CHANNEL = 2
# Settle between neighbouring points of a line. MEASURED on the real equipment
# on 2026-10-05: two identical scans of 21 points with 0.5 mm steps and 20
# averages, one at 500 ms and one at 100 ms, agree point by point within
# 0.22 samples RMS (2.2 ns, 1.5 µm) and their fit residuals correlate at 0.988:
# nothing is gained at 500 ms. VALIDATED FOR STEPS OF 0.5 mm OR LESS only; not
# checked for large moves (e.g. the line change of a one-direction surface scan,
# see scanner_tab_spec.md 5.6, phase 6).
DEFAULT_SCAN_SETTLE_MS = 100
# PENDIENTE DE CARACTERIZAR: the averages of a scan (20 was used in the settle
# measurement above, not characterized itself).
DEFAULT_SCAN_AVG_N = 20
DEFAULT_SCAN_STEP_MM = 0.5
DEFAULT_REF_AVG_N = 100
# Thickness (echo 1 → echo 2), phase 6. The delay is what is measured; the thickness
# in mm uses a NOMINAL sound speed of the sample, for the live map only (the
# definitive thickness is computed in the analysis from the saved signals).
DEFAULT_C_SAMPLE = 1540.0      # m/s, PVA, nominal
DEFAULT_MIN_CORR = 0.9         # echo 1 / echo 2 correlation below this: point marked less reliable
# Settle after a LONG move: the first point of every line (line change, and the
# travel from the start point to the first point) and every witness visit.
# NOT CHARACTERIZED: the 100 ms above were validated for steps <= 0.5 mm only; a
# line change of a one-direction scan is a jump of tens of mm and excites the
# mechanics much more. 1000 ms is a guess to be measured (phase 6, 05/10).
DEFAULT_LINE_SETTLE_MS = 1000
# Witness point (phase 6): a fixed point measured again every N lines, so the
# analysis can remove the drift of the sample from the position of the face
# (PVA, 05/10: −4.34 µm/min in jerks, 97.5 µm in 21 min; steel: +0.32 µm/min).
DEFAULT_WITNESS_EVERY = 1
# A jump: the witness off the trend, between two visits, by more than a threshold
# taken from the scatter of the witness series itself (witness_threshold): the
# jitter depends on the echo amplitude and varies with the sample (05/10: 0.41 µm on
# steel, 1.0-1.4 µm on PVA). This is its FLOOR: ~3σ of the difference of two visits
# with ≈1 µm per point, below the jumps seen on PVA (5–7 µm).
DEFAULT_WITNESS_JUMP_FLOOR_UM = 4.0
WITNESS_JUMP_SIGMAS = 3.0
WITNESS_MODES = ('first', 'start', 'custom')
LONG_SCAN_S = 30 * 60          # warn above half an hour
# Per-move overhead besides the travel at MOVE_MM_S: command, read-back of the axes
# and processing. MEASURED on 05/10 (line of 21 points, 0.5 mm steps, no water
# references): 0.43 s per point with 5 averages and 0.57 s with 20, of which about
# 0.28 s is movement and processing (0.075 s of it the travel), 9.5 ms each A-scan
# and the rest the settle.
MOVE_OVERHEAD_S = 0.2
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
    pair: Optional[EchoDelay] = None     # echo 1 → echo 2 (None: thickness off)
    c_sample: float = DEFAULT_C_SAMPLE


@dataclass
class Magnitude:
    label: str
    unit: str
    fn: Callable[[PointContext], float]
    uses_echo: bool = False      # depends on the tracked front echo (lost echo → NaN)
    tip: str = ''                # tooltip of the map selector


MAGNITUDES = OrderedDict()


def register_magnitude(name, label, unit, fn, uses_echo=False, tip=''):
    """Add a map magnitude: fn(PointContext) -> float. The scan computes all of them."""
    MAGNITUDES[name] = Magnitude(label, unit, fn, uses_echo, tip)


def pair_thickness_mm(pair, c_sample, fs=ACQ_FS):
    """Thickness [mm] from an EchoDelay at the sound speed c_sample; NaN if not found."""
    if pair is None or not pair.found:
        return float('nan')
    return c_sample * pair.delay_samples / fs / 2.0 * 1e3


# The thickness first: it is the default of the map. Measured between echoes 1
# and 2, it is immune to the drift of the sample (05/10: 0.20 µm residual vs 2.4 µm
# for the position of the face), the most reliable quantity of the system.
register_magnitude('thickness', 'Thickness (echo 1 → echo 2)', 'mm',
                   lambda c: pair_thickness_mm(c.pair, c.c_sample, c.fs), uses_echo=True)
register_magnitude('tof', 'Front-echo time of flight', 'µs',
                   lambda c: (c.measure.index_frac - c.emission_sample) / c.fs * 1e6,
                   uses_echo=True)
register_magnitude('amplitude', 'Max. envelope in the window (PE)', '',
                   lambda c: float(np.max(c.env)))
register_magnitude('energy', 'Energy in the window (PE)', 'a.u.·µs',
                   lambda c: float(np.sum(c.seg * c.seg)) / c.fs * 1e6)
register_magnitude('thickness_corr', 'Thickness quality (r)', '',
                   lambda c: c.pair.corr if c.pair is not None and c.pair.found
                   else float('nan'), uses_echo=True,
                   tip='Correlation coefficient between echoes 1 and 2 at each point: no '
                       'units, from 0 to 1. Not another way of measuring the thickness: it '
                       'tells in which zones of the thickness map to trust it (low where the '
                       'echo is deformed, e.g. an inclined face).')
THICKNESS_MAGNITUDES = ('thickness', 'thickness_corr')


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
    # Thickness per point (phase 6): echo 1 → echo 2 by cross-correlation.
    thickness: bool = True
    c_sample: float = DEFAULT_C_SAMPLE
    min_corr: float = DEFAULT_MIN_CORR
    # Settle after a long move (line change, witness visit): see DEFAULT_LINE_SETTLE_MS.
    line_settle_ms: int = DEFAULT_LINE_SETTLE_MS
    # Witness point (phase 6): 'first' scan point, position at 'start', or 'custom'
    # (absolute lateral / Z). Visited before the first line, after every N lines and
    # after the last one.
    witness: bool = True
    witness_mode: str = 'first'
    witness_lat: float = 0.0
    witness_z: float = 0.0
    witness_every: int = DEFAULT_WITNESS_EVERY
    witness_jump_floor_um: float = DEFAULT_WITNESS_JUMP_FLOOR_UM
    # Surface (phase 6): a line is the case of a single line, as in the data format.
    # The second axis is the other of lateral / Z; same range mode as the first.
    surface: bool = False
    start2: float = -5.0
    end2: float = 5.0
    step2: float = DEFAULT_SCAN_STEP_MM
    path: str = 'zigzag'                 # 'zigzag' or 'same' (always the same direction)


SCAN_ARRAYS_DOC = {
    'point_valid': 'bool (N_line, N_point): the point was acquired (False on the rest of a '
                   'partial line; its signals are 0, offsets, coords and times NaN)',
    'acq_index': 'int64 (N_line, N_point): acquisition order of each point, -1 if not acquired',
    'positions_requested': 'float64 (N_line, N_point): planned position on the line axis',
    'line_position_requested': 'float64 (N_line,): planned position on the other axis',
    'line_partial': 'bool (N_line,): line stopped before its end',
    'line_doubtful': 'bool (N_line,): the witness jumped (or was lost) while it was measured',
    'live_<magnitude>': 'float64 (N_line, N_point): live-map values (thickness [mm] at the '
                        'nominal c_sample, thickness_corr, tof [µs], amplitude, energy); metadata '
                        'only, the results are computed in the analysis',
    'echo_delay_us': 'float64 (N_line, N_point): echo 1 → echo 2 by cross-correlation (NaN '
                     'where there is no echo 2)',
    'echo_polarity': 'int8 (N_line, N_point): +1 / -1 polarity of echo 2 relative to echo 1, '
                     '0 not measured',
}
PT100_NOTE = ('The PT100 probes are at the bottom of the tank, NOT in the beam path. Measured '
              'on 05/10: 0.07 K in the boundary layer around a freshly immersed piece is worth '
              '5 µm of time of flight. These temperatures follow the trend of the water; they '
              'are not the temperature of the water the beam crosses. A limitation of the '
              'set-up, not of the program.')


class ScanPlan:
    """
    Positions of a scan from the start coordinates (no Qt, no hardware). A line
    is the case of a single line (lines = [(None, xs)]). With params.surface the
    second axis (the other of lateral / Z) gives the lines: zigzag alternates the
    direction of the first axis, 'same' always scans it in the same direction
    (avoids the backlash between alternate lines). Acquiring a surface is phase 6.
    """

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
        self.axis2, self.ys = None, [None]
        if params.surface:
            if params.path not in ('zigzag', 'same'):
                raise ValueError("path must be 'zigzag' or 'same'")
            self.axis2 = 'Z' if self.axis != 'Z' else lat_axis
            limit2 = limits.get(self.axis2)
            if limit2 is None or limit2 <= 0:
                raise ValueError(f'{self.axis2} limit unknown')
            origin2 = self.start_coords[self.axis2] if params.mode == 'relative' else 0.0
            self.ys, clipped2 = line_positions(origin2 + params.start2, origin2 + params.end2,
                                               params.step2, limit2)
            if clipped2:
                self.notices.append(f'Second-axis range clipped to the session limits of '
                                    f'{self.axis2} [0, {limit2:g}] mm: {len(self.ys)} lines left.')
            if not self.ys:
                raise ValueError('no line inside the session limits of the second axis')
        self.lat_axis = lat_axis
        # The axis across the lines (Z or lateral), also for a line scan, where it
        # stays at its start coordinate (a witness point may still move it).
        self.other = self.axis2 or ('Z' if self.axis != 'Z' else lat_axis)
        self.limits = dict(limits)
        self.lines = []
        for k, y in enumerate(self.ys):
            xs = list(self.xs)
            if params.surface and params.path == 'zigzag' and k % 2:
                xs.reverse()
            self.lines.append((y, xs))

    def line_y(self, k):
        """Coordinate of line k on self.other (the start coordinate for a line scan)."""
        y = self.lines[k][0]
        return self.start_coords[self.other] if y is None else y

    @property
    def n_points(self):
        return sum(len(xs) for _, xs in self.lines)

    def positions(self):
        """Line scan positions (one line)."""
        return [{self.axis: x} for x in self.xs]

    def all_positions(self):
        """Every point of every line, as sequencer positions (second axis first on each)."""
        out = []
        for y, xs in self.lines:
            for x in xs:
                out.append({self.axis: x} if y is None else {self.axis2: y, self.axis: x})
        return out

    @property
    def home(self):
        """The scanned axis back at the start point."""
        return {self.axis: self.start_coords[self.axis]}


@dataclass
class Entry:
    """One step of the scan sequence: a scan point or a witness visit."""
    kind: str            # 'point' or 'witness'
    line: int            # point: its line; witness: the number of lines completed before it
    j: int               # point: index in plan.xs (spatial order); witness: visit number
    pos: dict            # sequencer position (axes moved in this order)
    settle_ms: int


def witness_position(plan):
    """{axis, other} of the witness point (see ScanParams.witness_mode)."""
    p = plan.params
    if p.witness_mode == 'first':
        x, y = plan.lines[0][1][0], plan.line_y(0)
    elif p.witness_mode == 'start':
        x, y = plan.start_coords[plan.axis], plan.start_coords[plan.other]
    elif p.witness_mode == 'custom':
        lat, z = float(p.witness_lat), float(p.witness_z)
        x, y = (lat, z) if plan.axis != 'Z' else (z, lat)
    else:
        raise ValueError(f'witness mode must be one of {WITNESS_MODES}')
    for a, v in ((plan.axis, x), (plan.other, y)):
        limit = plan.limits.get(a)
        if limit is not None and not 0.0 <= v <= limit:
            raise ValueError(f'witness point outside the session limits of {a} [0, {limit:g}] mm')
    return {plan.axis: round(x, POSITION_DECIMALS), plan.other: round(y, POSITION_DECIMALS)}


def scan_schedule(plan):
    """
    The whole scan as one sequence: every point of every line, in the order of the
    path, and the witness visits (before the first line, after every N lines and
    after the last one). Fixed and reproducible axis order:
      - along a line only the line axis moves;
      - when the other axis has to change (line change, witness visit and the
        return from it) it moves FIRST, then the line axis.
    Settle: params.line_settle_ms after every long move (first point of each line,
    witness visits), params.settle_ms between neighbouring points of a line.
    """
    p = plan.params
    wit = witness_position(plan) if p.witness else None
    every = max(1, int(p.witness_every))
    entries, cur_y = [], plan.start_coords[plan.other]
    n_lines = len(plan.lines)

    def visit(after):
        nonlocal cur_y
        y = wit[plan.other]
        pos = ({plan.other: y} if abs(y - cur_y) > 1e-9 else {})
        pos[plan.axis] = wit[plan.axis]
        cur_y = y
        entries.append(Entry('witness', after, sum(e.kind == 'witness' for e in entries), pos,
                             p.line_settle_ms))

    if wit:
        visit(0)
    last = len(plan.xs) - 1
    for k, (_, xs) in enumerate(plan.lines):
        y = plan.line_y(k)
        reverse = xs[0] != plan.xs[0]
        for i, x in enumerate(xs):
            pos = {}
            if i == 0 and abs(y - cur_y) > 1e-9:
                pos[plan.other] = y
            pos[plan.axis] = x
            cur_y = y
            entries.append(Entry('point', k, last - i if reverse else i, pos,
                                 p.line_settle_ms if i == 0 else p.settle_ms))
        if wit and ((k + 1) % every == 0 or k == n_lines - 1):
            visit(k + 1)
    return entries


def witness_jumps(times, face_um):
    """
    Jumps of the witness between consecutive visits. The drift of PVA comes in
    jerks, so a jump between two visits cannot be reconstructed: the lines
    measured in between are in doubt. Trend = median rate of every interval
    (robust to the jump itself); the deviation of interval k (visit k → k+1) is
    its displacement minus trend × its duration. With fewer than three intervals
    the trend is not robust and a jump cannot be told from the drift.
    Returns (deviation_um per interval, NaN where a visit had no echo; rate µm/s).
    """
    t = np.asarray(times, dtype=float)
    w = np.asarray(face_um, dtype=float)
    if t.size < 2:
        return np.zeros(0), float('nan')
    dt, dw = np.diff(t), np.diff(w)
    ok = np.isfinite(dw) & (dt > 0)
    rate = float(np.median(dw[ok] / dt[ok])) if ok.any() else float('nan')
    dev = np.where(ok, dw - (rate if np.isfinite(rate) else 0.0) * dt, np.nan)
    return dev, rate


def witness_threshold(dev, floor_um=DEFAULT_WITNESS_JUMP_FLOOR_UM, k=WITNESS_JUMP_SIGMAS):
    """
    Jump threshold from the witness series itself: k × the scatter of the
    deviations between consecutive visits (witness_jumps: the differences with the
    trend removed), never below floor_um. The scatter is 1.4826 × MAD, the standard
    deviation for Gaussian noise but not inflated by the jump it has to find (a
    plain standard deviation of five intervals with one 40 µm jump is ~16 µm, and
    3σ would hide that jump). Fewer than three valid intervals: the floor.
    Returns (threshold_um, sigma_um or NaN).
    """
    d = np.asarray(dev, dtype=float)
    d = d[np.isfinite(d)]
    if d.size < 3:
        return float(floor_um), float('nan')
    sigma = 1.4826 * float(np.median(np.abs(d - np.median(d))))
    return max(float(floor_um), k * sigma), sigma


def witness_doubt(visits, dev, threshold_um):
    """
    {line: reason} of the lines in doubt: the lines measured between two visits
    where the witness jumped off the trend by more than threshold_um, or where a
    visit had no echo (drift unknown there). visits: dicts with 'after_line'.
    """
    out = {}
    after = [v['after_line'] for v in visits]
    for k, dv in enumerate(dev):
        if not np.isfinite(dv):
            reason = 'witness echo lost'
        elif abs(dv) > threshold_um:
            reason = f'witness jump {dv:+.1f} µm'
        else:
            continue
        for line in range(after[k], after[k + 1]):
            out.setdefault(line, reason)
    return out


def witness_correction(t, times, values):
    """Witness value interpolated at time(s) t, relative to the first valid visit: the
    drift of the face. Held flat before the first and after the last visit. NaN
    visits are skipped; no valid visit gives zeros."""
    ts, vs = np.asarray(times, dtype=float), np.asarray(values, dtype=float)
    ok = np.isfinite(vs)
    if not ok.any():
        return np.zeros_like(np.asarray(t, dtype=float))
    return np.interp(t, ts[ok], vs[ok] - vs[ok][0])


def estimate_scan_s(plan, acq_s, move_mm_s=MOVE_MM_S, overhead_s=0.0, temp_s=0.0):
    """Seconds, over the whole schedule (scan_schedule): travel of every move (lines,
    line changes, witness visits) and back to the start, the settle of each entry
    (long-move settle included), the averages of every point and witness visit, a
    per-move overhead (command, read-back, processing: MOVE_OVERHEAD_S on the real
    equipment), one temperature reading per line (temp_s each) and the two
    reference acquisitions (the manual steps are not included)."""
    p = plan.params
    total, cur = 0.0, dict(plan.start_coords)
    for e in scan_schedule(plan):
        travel = sum(abs(v - cur.get(a, v)) for a, v in e.pos.items())
        cur.update(e.pos)
        total += travel / move_mm_s + e.settle_ms / 1000.0 + p.avg_n * acq_s + overhead_s
    total += sum(abs(cur[a] - plan.start_coords[a]) for a in (plan.axis, plan.other)) \
        / move_mm_s + overhead_s
    total += len(plan.lines) * temp_s
    if p.references:
        total += 2 * p.ref_avg_n * acq_s
    return total


@dataclass
class ScanData:
    """
    Everything acquired in one scan session. Scan points in acquisition order
    (flat lists), each with its line and its index j in plan.xs (spatial order:
    a zigzag line runs j backwards). The witness visits go apart, in `witness`.
    """
    line: List[int] = field(default_factory=list)
    j: List[int] = field(default_factory=list)
    witness: List[dict] = field(default_factory=list)
    witness_dev: Optional[np.ndarray] = None    # deviation per interval between visits, µm
    witness_rate: float = float('nan')          # median drift rate, µm/s
    sum1: List[np.ndarray] = field(default_factory=list)    # Σ(raw − midpoint), window, Ch1
    sum2: List[np.ndarray] = field(default_factory=list)    # same, Ch2
    off1: List[float] = field(default_factory=list)         # whole-record offset, Ch1
    off2: List[float] = field(default_factory=list)
    coords: List[List[float]] = field(default_factory=list)      # real X, Y, Z, R
    times: List[float] = field(default_factory=list)
    requested: List[float] = field(default_factory=list)
    measures: list = field(default_factory=list)
    pairs: List[Optional[EchoDelay]] = field(default_factory=list)   # echo 1 → echo 2
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
    no_back = [x for x, f in zip(xs, flags) if 'no_back' in f]
    low = [x for x, f in zip(xs, flags) if 'low_corr' in f]
    if no_back:
        msgs.append(f'No second echo (back face) inside Smin–Smax at {_pts(no_back)} mm: '
                    'no thickness there (NaN).')
    if low:
        msgs.append(f'Echo 1 / echo 2 correlation below the limit at {_pts(low)} mm: the echo '
                    'is deformed (inclined face?), thickness less reliable there.')
    return msgs


def thickness_flags(pair, min_corr):
    """'no_back' (echo 2 not found / not inside the window) or 'low_corr'; [] when off."""
    if pair is None:
        return []
    if not pair.found:
        return ['no_back']
    return ['low_corr'] if pair.corr < min_corr else []


THICKNESS_FLAGS = ('no_back', 'low_corr')


def point_marked(magnitude, flags):
    """Is a point marked on the map of `magnitude`? The thickness flags only mark the
    thickness maps; saturation and a pinned echo mark every map."""
    if magnitude in THICKNESS_MAGNITUDES:
        return bool(flags)
    if MAGNITUDES[magnitude].uses_echo:
        return any(f not in THICKNESS_FLAGS for f in flags)
    return 'saturated' in flags or 'edge' in flags


THICKNESS_REASONS = {
    'front_gate': 'the gate around the front echo does not fit in Smin–Smax',
    'no_back': 'there is no clear second echo (back face) after the front echo inside '
               'Smin–Smax: it is beyond Smax, or too weak',
    'back_at_edge': 'the second echo (back face) is at the edge of Smin–Smax',
}


def _pts(xs):
    if len(xs) > 8:
        return ', '.join(f'{x:g}' for x in xs[:4]) + f' … {xs[-1]:g} ({len(xs)} points)'
    return ', '.join(f'{x:g}' for x in xs)


# ===========================================================================
#  Qt part
# ===========================================================================
import pyqtgraph as pg  # noqa: E402
from PyQt5.QtCore import QObject, QRectF, Qt, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtGui import QImage  # noqa: E402
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
        self.shown_reference = (ch1, ch2)          # exactly what is up for approval
        pw = self._pw
        pw.clear()
        self._curve = None
        pw.setTitle(f'Water reference ({which}), averaged as saved: Ch1 (transmission) red, '
                    'Ch2 (PE) yellow — OK, Repeat or Cancel')
        pw.setLabel('bottom', 'Time', units='µs')
        pw.setLabel('left', 'Amplitude', units=None)
        pw.getAxis('bottom').enableAutoSIPrefix(False)
        t = (smin + np.arange(len(ch1))) / fs * 1e6
        pw.plot(t, ch1, pen=pg.mkPen(_COL_CH1, width=1))
        pw.plot(t, ch2, pen=pg.mkPen(_COL_CH2, width=1))
        pw.enableAutoRange()


# Colour map of the surface maps (viridis anchors), as RGB tuples; NaN and the
# points not measured yet get their own colours.
_CMAP_ANCHORS = ((68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37))
_COL_NAN = (120, 120, 120, 255)          # measured, no value (echo lost, no echo 2)
_COL_EMPTY = (0, 0, 0, 0)                # not measured yet


def colour_lut(n=256):
    """(n, 3) uint8 lookup table interpolated through _CMAP_ANCHORS."""
    anchors = np.array(_CMAP_ANCHORS, dtype=float)
    x = np.linspace(0.0, 1.0, len(anchors))
    t = np.linspace(0.0, 1.0, n)
    return np.stack([np.interp(t, x, anchors[:, c]) for c in range(3)], axis=1).astype(np.uint8)


_LUT = colour_lut()


def map_levels(values, scale=None):
    """(lo, hi) of a map: the fixed scale, or the finite range of the values."""
    if scale is not None:
        lo, hi = float(scale[0]), float(scale[1])
    else:
        v = np.asarray(values, dtype=float)
        v = v[np.isfinite(v)]
        lo, hi = (float(v.min()), float(v.max())) if v.size else (0.0, 1.0)
    if not hi > lo:
        pad = max(abs(lo) * 1e-3, 1e-12)
        lo, hi = lo - pad, hi + pad
    return lo, hi


def map_rgba(grid, measured, lo, hi):
    """RGBA uint8 image of a 2-D grid: LUT colour, _COL_NAN where measured but NaN,
    transparent where not measured yet."""
    g = np.asarray(grid, dtype=float)
    out = np.zeros(g.shape + (4,), dtype=np.uint8)
    ok = np.isfinite(g) & measured
    idx = np.clip(((g[ok] - lo) / (hi - lo) * (len(_LUT) - 1)).round(), 0, len(_LUT) - 1)
    out[ok, :3] = _LUT[idx.astype(int)]
    out[ok, 3] = 255
    out[measured & ~np.isfinite(g)] = _COL_NAN
    out[~measured] = _COL_EMPTY
    return out


class RGBAImageItem(pg.ImageItem):
    """
    ImageItem for an RGBA uint8 image already coloured by the caller (map_rgba). Its
    render() builds the QImage directly. pyqtgraph 0.11 renders every ImageItem
    through functions.makeARGB, which calls np.float, removed in numpy 1.24 (the
    .venv32 of the laptop): the AttributeError is raised inside paint(), Qt swallows
    it and the item stays blank, with its axes, rect and colour bar ranges all
    correct. Building the QImage here does not depend on the numpy version.
    """

    def render(self):
        image = self.image
        if image is None:
            self.qimage = None
            return
        # col-major (pyqtgraph 0.11 default): image[x, y] → QImage rows are y
        rows = np.ascontiguousarray(np.asarray(image, dtype=np.uint8).transpose(1, 0, 2))
        h, w = rows.shape[:2]
        self.qimage = QImage(rows.tobytes(), w, h, 4 * w, QImage.Format_RGBA8888).copy()


class SurfaceMap:
    """
    Live 2-D maps of a surface scan in a GraphicsLayoutWidget (pyqtgraph 0.11:
    ImageItem fed with an RGBA array coloured here, colours as RGB tuples, and a
    colour bar built from an ImageItem, since ColorBarItem is later than 0.11).
    Lateral horizontal, Z vertical and growing downwards, as the PE transducer
    sees the face. The main map (chosen magnitude) and optionally the amplitude
    beside it: the amplitude says where to trust the other one.
    """

    def __init__(self, layout_widget):
        self.widget = layout_widget
        self.panels = {}                # name -> (plot, image, bar plot, bar image, marks)
        self.last = {}                  # name -> (grid lat × z, levels): for inspection

    def reset(self, names, titles, units, lat_vals, z_vals):
        """names: magnitudes shown (main first); lat_vals / z_vals: ascending grid centres."""
        w = self.widget
        w.clear()
        self.panels, self.last, self.notes = {}, {}, {}
        self._lat = np.asarray(lat_vals, dtype=float)
        self._z = np.asarray(z_vals, dtype=float)
        dl = float(np.median(np.diff(self._lat))) if self._lat.size > 1 else 1.0
        dz = float(np.median(np.diff(self._z))) if self._z.size > 1 else 1.0
        # pixels centred on the measured points: half a step beyond the first and last
        self.rect = rect = QRectF(self._lat[0] - dl / 2, self._z[0] - dz / 2,
                                  dl * self._lat.size, dz * self._z.size)
        for col, name in enumerate(names):
            plot = w.addPlot(row=0, col=2 * col, title=titles[name])
            plot.setLabel('bottom', 'Lateral', units='mm')
            plot.setLabel('left', 'Z (down)', units='mm')
            for ax in ('bottom', 'left'):
                plot.getAxis(ax).enableAutoSIPrefix(False)
            plot.getViewBox().invertY(True)
            plot.getViewBox().setAspectLocked(True)
            img = RGBAImageItem()
            # 0.11: setRect scales by the image size, so the (empty) image goes first
            img.setImage(np.zeros((self._lat.size, self._z.size, 4), dtype=np.uint8),
                         autoLevels=False)
            img.setRect(rect)
            plot.addItem(img)
            plot.setXRange(rect.left(), rect.right(), padding=0.02)
            plot.setYRange(rect.top(), rect.bottom(), padding=0.02)
            marks = pg.ScatterPlotItem(symbol='x', size=9, pen=pg.mkPen(_COL_FLAG, width=2),
                                       brush=pg.mkBrush(_COL_FLAG))
            plot.addItem(marks)
            note = pg.TextItem('', color=(230, 120, 0), anchor=(0.5, 0.5))
            note.setPos(rect.center())
            plot.addItem(note)
            bar = w.addPlot(row=0, col=2 * col + 1)
            bar.setMaximumWidth(80)
            bar.hideAxis('bottom')
            bar.setLabel('left', '', units=units[name] or None)
            bar.getAxis('left').enableAutoSIPrefix(False)
            bar.setMouseEnabled(x=False, y=False)
            bar_img = RGBAImageItem()
            bar_img.setImage(map_rgba(np.linspace(0.0, 1.0, 256)[None, :],
                                      np.ones((1, 256), bool), 0.0, 1.0), autoLevels=False)
            bar.addItem(bar_img)
            self.panels[name] = (plot, img, bar, bar_img, marks)
            self.notes[name] = note

    def set_title(self, name, title):
        if name in self.panels:
            self.panels[name][0].setTitle(title)

    def set_data(self, name, grid, measured, marks_xy=(), scale=None, empty_reason=''):
        """grid, measured: (n_lat, n_z); marks_xy: [(lat, z)] of marked points. With no
        finite value to draw, the map says so (empty_reason: why) instead of staying
        blank."""
        if name not in self.panels:
            return
        plot, img, bar, bar_img, marks = self.panels[name]
        grid = np.asarray(grid, dtype=float)
        lo, hi = map_levels(grid[measured], scale)
        img.setImage(map_rgba(grid, measured, lo, hi), autoLevels=False)
        img.setRect(self.rect)                       # always the scan, half a step each side
        if np.isfinite(grid[measured]).any():
            self.notes[name].setText('')
        elif not measured.any():
            self.notes[name].setText('No point measured yet')
        else:
            self.notes[name].setText('No valid value to draw'
                                     + (f':\n{empty_reason}' if empty_reason else ''))
        bar_img.setRect(QRectF(0.0, lo, 1.0, hi - lo))
        bar.setYRange(lo, hi, padding=0)
        bar.setXRange(0.0, 1.0, padding=0)
        xy = list(marks_xy)
        marks.setData([p[0] for p in xy], [p[1] for p in xy])
        self.last[name] = (np.array(grid, dtype=float), (lo, hi))


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
    thickness_available = pyqtSignal(bool, str)      # (on, reason when off), at every Start

    def __init__(self, sequencer, panel, window_fn, plot_widget, acquire_fn, gains_fn,
                 set_gains_fn, counts_fn=None, temp_factory=None, sos_fn=None, cw_fn=None,
                 info_fn=None, base_dir=None, show_plot_fn=None, acq_time_fn=None, lock_fn=None,
                 dump_dir=None, adc_bits=ADC_BITS_DEFAULT, hold_live_fn=None, map_widget=None,
                 show_map_fn=None, move_overhead_s=MOVE_OVERHEAD_S, parent=None):
        """
        acquire_fn(avg_n) -> (ch1, ch2) full averaged records (references)
        counts_fn() -> {'sum': (s1, s2), 'offset': (o1, o2), 'n': avg_n} of the LAST
                     acquisition (the sequencer's or acquire_fn's): integer sums of
                     (raw − midpoint) over the whole record, as scan_counts defines
        adc_bits: ADC resolution assumed for the conversion (written in every file)
        hold_live_fn(bool): host stops / restarts the live A-scan refresh. While a
                     water reference is up for approval the live view is held, so
                     what is shown (and approved) is the averaged reference that
                     is saved, not single live captures
        gains_fn() -> (gain1, gain2) of the Acquisition tab (the scan gains)
        set_gains_fn(g1, g2): Gain1 then Gain2, always both (pulser fault)
        temp_factory() -> Arduino-like (getTemperatures, close) or None: opened ONCE
        sos_fn(T) -> c_w from the water temperature (ECOS: water_temp2sos)
        cw_fn() -> (c_w, source) WITHOUT opening the Arduino, when there is no PT100
        info_fn() -> {specimen, protocol, equipment1, equipment2, name_parts}
        base_dir: automatic save folder (default ../database)
        lock_fn(bool): host locks/unlocks the Acquisition tab for the whole session
        map_widget: pg.GraphicsLayoutWidget for the 2-D maps of a surface scan (one is
                     created, not shown, when None); show_map_fn() brings it to front
        move_overhead_s: per-move overhead for the estimate (MOVE_OVERHEAD_S, measured)
        """
        super().__init__(parent)
        self._seq = sequencer
        self._panel = panel
        self._window_fn = window_fn
        self._plot = ScanPlot(plot_widget)
        self.map_widget = map_widget if map_widget is not None else pg.GraphicsLayoutWidget()
        self._map = SurfaceMap(self.map_widget)
        self._show_map = show_map_fn
        self._move_overhead_s = float(move_overhead_s)
        self.map_scale = None            # None: automatic; (lo, hi): fixed (main map)
        self.drift_corrected = False     # face ToF map corrected with the witness (live only)
        self.companion = True            # amplitude map beside the main one
        self._map_names = []
        self.last_temp_read_s = None
        self._acquire = acquire_fn
        self._counts_fn = counts_fn
        self.adc_bits = int(adc_bits)
        self._hold_live_fn = hold_live_fn
        self._holding = False
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
        self.magnitude = 'thickness'
        self.thickness_on = False
        self.thickness_reason = ''
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

    def scan_gains(self):
        """(gain1, gain2) of the Acquisition tab (to prefill the reference gains)."""
        return tuple(float(g) for g in self._gains_fn())

    def _hold_live(self, hold):
        if hold != self._holding and self._hold_live_fn is not None:
            self._hold_live_fn(hold)
        self._holding = hold

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
            n_wit = sum(e.kind == 'witness' for e in scan_schedule(plan))
        except Exception as e:
            return None, f'Estimate not available ({e}).', False
        acq_s, timed = acq_time(self._acq_time_fn)
        temp_s = (self.last_temp_read_s or 0.0) if params.surface else 0.0
        total = estimate_scan_s(plan, acq_s, overhead_s=self._move_overhead_s, temp_s=temp_s)
        long_ = total > LONG_SCAN_S
        refs = ' + two water references (manual steps not included)' if params.references else ''
        wit = f' + witness point × {n_wit}' if n_wit else ''
        where = (f'{len(plan.xs)} points along {plan.axis} ({plan.xs[0]:g} → {plan.xs[-1]:g} mm)'
                 if not params.surface else
                 f'{plan.n_points} points: {len(plan.lines)} lines along {plan.axis} × '
                 f'{len(plan.xs)} points, {plan.axis2} {plan.ys[0]:g} → {plan.ys[-1]:g} mm, '
                 f'{"zigzag" if params.path == "zigzag" else "same direction"}')
        text = (f'Estimated time ≈ {format_duration(total)}: {where}{wit}{refs}; per point '
                f'{params.settle_ms / 1000.0:g} s settle ({params.line_settle_ms / 1000.0:g} s '
                f'after a line change or a witness visit) + {params.avg_n} × {acq_s * 1e3:.0f} ms '
                f'({"timed" if timed else "assumed"}) + {self._move_overhead_s:g} s per move.')
        if params.surface and self.last_temp_read_s is None:
            text += ' Temperature reading per line not timed yet (not included).'
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
            schedule = scan_schedule(plan)
            witness_pos = witness_position(plan) if params.witness else None
        except ValueError as e:
            return str(e)
        self.plan, self.params = plan, params
        self._schedule, self._witness_pos = schedule, witness_pos
        self._doubt_lines = {}
        self._witness_ref = None
        self._witness_thr, self._witness_sigma = params.witness_jump_floor_um, float('nan')
        self._line_start = self._dump_line_start = 0
        self.window = (int(smin), int(smax))
        self._check_thickness(params)
        self.data = ScanData()
        self.last_saved_path = None
        self.last_dump_path = None
        self._t_start = time.time()
        self._ts = time.strftime('%Y%m%d_%H%M%S')
        self._warned_kinds = set()
        self._scan_gains = tuple(float(g) for g in self._gains_fn())
        self._tracker = FrontEchoTracker(self.window, 0.0, band_samples(params.band_us),
                                         params.threshold, params.edge_margin)
        self._witness_tracker = FrontEchoTracker(self.window, 0.0, band_samples(params.band_us),
                                                 params.threshold, params.edge_margin)
        self._dump = FocusDebugDump(dict(tool='scan', started=time.strftime('%Y-%m-%dT%H:%M:%S'),
                                         axis=plan.axis, xs=plan.xs, smin=smin, smax=smax),
                                    prefix='scan_debug') if params.debug_dump else None
        self._seq.reserve(self, 'A scan session is in progress (scanner tab).')
        if self._lock_fn:
            self._lock_fn(True)
        self._open_temperature()
        start_t = self._read_temperature('start', -1)
        if self._dump is not None:
            has_t = start_t['T1'] == start_t['T1'] or start_t['T2'] == start_t['T2']
            self._dump.meta.update(measurement_meta(
                params.settle_ms, params.avg_n, self._scan_gains,
                dict(start_t, source='PT100, scan start') if has_t else None))
        self._resolve_cw()
        for text in plan.notices:
            self.warning.emit(text)
        self._reset_view()
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

    def _read_temperature(self, label, point, line=None):
        """One reading, with its time, the index of the last acquired point and the
        line (the last line with acquired points when not given; −1 before any)."""
        t1 = t2 = float('nan')
        if self._arduino is not None:
            t0 = time.monotonic()
            try:
                r1, r2 = self._arduino.getTemperatures()
                t1 = float('nan') if r1 is None else float(r1)
                t2 = float('nan') if r2 is None else float(r2)
            except Exception as e:
                self.warning.emit(f'Temperature read failed ({e}): stored as NaN.')
            self.last_temp_read_s = time.monotonic() - t0
        if line is None:
            line = self.data.line[-1] if self.data.line else -1
        entry = {'label': label, 'point': int(point), 'line': int(line), 'time': time.time(),
                 'T1': t1, 'T2': t2}
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

    # -- thickness (echo 1 → echo 2) -------------------------------------------
    def _check_thickness(self, params):
        """
        Before anything moves: one acquisition where the scan starts, the front
        echo by the first-peak rule and then echo 2. If echo 2 does not fit in
        Smin–Smax the thickness is disabled for the whole scan and the magnitude
        is not offered: better no thickness than one measured against whatever
        lies at the edge of the window.
        """
        on, reason = False, 'disabled (Thickness unchecked)'
        if params.thickness:
            _, sig = self._acquire(params.avg_n)
            tr = FrontEchoTracker(self.window, 0.0, band_samples(params.band_us),
                                  params.threshold, params.edge_margin)
            m = tr.measure(sig, 0.0)
            if not m.confident:
                reason = ('no clear front echo where the scan starts, so the second echo cannot '
                          'be checked')
            else:
                seg, env = tr.point_signals()
                pair = echo_pair_delay(seg, env, m.index - self.window[0], tr.band,
                                       params.threshold, params.edge_margin, self.window[0])
                on = pair.found
                reason = '' if on else (THICKNESS_REASONS[pair.reason] + ' where the scan '
                                        'starts: widen Smax (Acquisition tab) to include it')
        self.thickness_on, self.thickness_reason = on, reason
        self.thickness_available.emit(on, reason)
        if not on:
            if params.thickness:
                self.warning.emit(f'Thickness NOT available for this scan: {reason}.')
            if self.magnitude in THICKNESS_MAGNITUDES:
                self.magnitude = 'amplitude'

    def _pair(self, seg, env, m):
        """Echo 1 → echo 2 on one point's window (None when the thickness is off)."""
        if not self.thickness_on:
            return None
        p, smin = self.params, self.window[0]
        return echo_pair_delay(seg, env, m.index - smin, self._tracker.band, p.threshold,
                               p.edge_margin, smin)

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
        # Approve what is saved: the averaged reference, held on screen (the live
        # refresh would replace it by single captures) and shown on the big plot.
        self._hold_live(True)
        self._plot.show_reference(which, self._pending_ref['ch1'], self._pending_ref['ch2'],
                                  smin, ACQ_FS)
        if self._show_plot is not None:
            self._show_plot()
        self._set_state('ref_review')
        self.reference_ready.emit(which)
        self.status.emit(f'Water reference ({which}): {n} averages at gains '
                         f'{p.ref_gain1:g}/{p.ref_gain2:g} dB (the averaged signal shown is the '
                         'one saved). OK, or change the reference gains and Repeat, or Cancel.')

    def repeat_reference(self, gain1=None, gain2=None):
        """Measure the reference again, optionally with new reference gains."""
        if self.state != 'ref_review':
            return 'No reference to repeat.'
        changes = {}
        if gain1 is not None:
            changes['ref_gain1'] = float(gain1)
        if gain2 is not None:
            changes['ref_gain2'] = float(gain2)
        if changes:
            self.params = replace(self.params, **changes)
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
        self._hold_live(False)
        self._pending_ref = None
        if which == 'final' and 'initial' in self.data.references:
            self._compare_references()
        self._reset_view()
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
        self._hold_live(False)
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

    def _home_path(self):
        """Back to the start point after the scan: the line axis first, then the other
        axis if the scan moved it (surface, or a witness point off the line)."""
        s, plan = self.plan.start_coords, self.plan
        pos = {plan.axis: s[plan.axis]}
        if any(plan.other in e.pos for e in self._schedule):
            pos[plan.other] = s[plan.other]
        return [pos]

    def _to_reference_path(self):
        """Scanned axes home first (the path just scanned), then the recorded order."""
        ref = self.data.reference_position or {}
        path = self._home_path()
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
        self._cursor = 0
        self._cur_line = None
        plan, sched = self.plan, self._schedule
        nw = sum(e.kind == 'witness' for e in sched)
        lines = (f'{len(plan.lines)} lines along {plan.axis}' if plan.params.surface else
                 f'along {plan.axis}')
        self.status.emit(f'Scanning {plan.n_points} points, {lines}'
                         + (f', witness point visited {nw} times' if nw else '')
                         + f' (c_w = {self.c_w:.1f} m/s, {self.cw_source})…')
        reason = self._seq.start([e.pos for e in sched], [e.settle_ms for e in sched],
                                 self.params.avg_n, self._measure,
                                 validate_fn=self._panel.validate_position,
                                 record_temperature=False, owner=self)
        if reason:
            self._stopped(f'The scan could not start: {reason}')

    def _measure(self, ch1, ch2):
        if self._phase != 'scan':
            return None
        smin, smax = self.window
        e = self._schedule[self._cursor]
        if e.kind == 'witness':
            tracker = self._witness_tracker
        else:
            tracker = self._tracker
            if e.line != self._cur_line:            # a new line: a new sweep, same anchor
                tracker.new_sweep()
                self._cur_line = e.line
                self._line_start = self.data.n
                self._dump_line_start = len(self._dump) if self._dump is not None else 0
        sig = ch2 if PE_CHANNEL == 2 else ch1
        m = tracker.measure(sig, self.plan.beam_x)
        seg, env = tracker.point_signals(-1)
        self._last = (seg, env, np.array(ch1[smin:smax], dtype=float),
                      np.array(sig, dtype=float) if self._dump is not None else None,
                      self._pair(seg, env, m), self._last_counts(smin, smax))
        return m

    def _on_point(self, i, coords, value):
        if self._phase != 'scan':
            return
        e = self._schedule[i]
        self._cursor = i + 1
        if e.kind == 'witness':
            self._on_witness(e, coords, value)
        else:
            self._on_scan_point(e, coords, value)

    def _on_scan_point(self, e, coords, value):
        d, p = self.data, self.params
        seg, env, seg1, record, pair, ((s1, s2), (o1, o2)) = self._last
        d.sum1.append(s1)
        d.sum2.append(s2)
        d.off1.append(o1)
        d.off2.append(o2)
        d.line.append(e.line)
        d.j.append(e.j)
        d.coords.append([float(coords.get(a, float('nan'))) for a in AXES4])
        d.times.append(time.time())
        d.requested.append(e.pos[self.plan.axis])
        ls = self._line_start                            # this line: d[ls:]
        d.measures[ls:] = list(self._tracker.measures)   # a re-lock revises earlier points
        xs = self.positions_read()[ls:]
        d.pairs.append(pair)
        flags = line_flags(xs, d.measures[ls:], self.window, p.edge_margin)
        lost = 'weak' in flags[-1] or 'outside' in flags[-1]
        ctx = PointContext(value, seg, env, seg1, ACQ_FS, p.emission_sample, pair, p.c_sample)
        d.magnitudes.append(compute_magnitudes(ctx, lost))
        # ToF and thickness depend on the (possibly revised) measures: refresh them
        for k, (m, f) in enumerate(zip(d.measures[ls:], flags)):
            self._refresh_echo_values(ls + k, k, m, f)
        d.flags[ls:] = flags
        if self._dump is not None:
            self._dump.add('scan', self.plan.beam_x, value, seg, env, record, self.window,
                           extra=dict(line_position=xs[-1], line=e.line, **d.magnitudes[-1]))
            self._dump.revise(self._dump_line_start, d.measures[ls:], d.flags[ls:])
        self.echo_used.emit(value)
        self._redraw()
        f = d.flags[-1]
        if f and not self._warned_kinds >= set(f):
            self._warned_kinds |= set(f)
            self.warning.emit(' '.join(scan_messages([xs[-1]], [f], [d.measures[-1]])))
        nxt = self._schedule[self._cursor] if self._cursor < len(self._schedule) else None
        if nxt is None or nxt.kind != 'point' or nxt.line != e.line:
            self._line_done(e.line)

    def _line_done(self, k):
        """Line k complete: in a surface scan, the temperature with its line index (one
        Arduino for the whole session; NaN without PT100, never a dialog)."""
        if self.params.surface:
            self._read_temperature('line_end', self.data.n - 1, k)

    # -- witness point ---------------------------------------------------------
    def _on_witness(self, e, coords, value):
        """
        One visit: measured as a scan point (own tracker, so the lines keep their
        anchor), stored raw with its time and the number of lines done. The face
        displacement since the first visit is measured as the stability test does,
        by cross-correlation of a ±band gate around the tracked echo: the envelope
        peak of a scan point jitters ±0.3 samples (±2 µm) in the simulator, fine
        for a map but not for jumps of a few µm. The jumps off the trend mark the
        lines measured in between as doubtful. Nothing is corrected.
        """
        d, p = self.data, self.params
        seg, env, seg1, record, pair, ((s1, s2), (o1, o2)) = self._last
        wt = self._witness_tracker
        flags = line_flags([0.0] * len(wt.measures), wt.measures, self.window, p.edge_margin)
        lost = 'weak' in flags[-1] or 'outside' in flags[-1]
        ctx = PointContext(value, seg, env, seg1, ACQ_FS, p.emission_sample, pair, p.c_sample)
        mags = compute_magnitudes(ctx, lost)
        d.witness.append(dict(
            visit=e.j, after_line=e.line, time=time.time(), measure=value, pair=pair,
            coords=[float(coords.get(a, float('nan'))) for a in AXES4],
            requested=[float(self._witness_pos.get(a, float('nan'))) for a in AXES4],
            amplitude=mags['amplitude'], thickness_mm=mags['thickness'],
            thickness_corr=mags['thickness_corr'], flags=flags[-1],
            sum1=s1, sum2=s2, offset1=o1, offset2=o2))
        for v, m, f in zip(d.witness, wt.measures, flags):       # a re-lock revises them
            v['measure'], v['flags'] = m, f
            v['lost'] = 'weak' in f or 'outside' in f
            v['tof_us'] = (float('nan') if v['lost'] else
                           (m.index_frac - p.emission_sample) / ACQ_FS * 1e6)
        d.witness[-1]['face_um'] = self._witness_face_um(seg, value, lost)
        if self._dump is not None:
            self._dump.add('witness', self.plan.beam_x, value, seg, env, record, self.window,
                           extra=dict(line_position=e.pos[self.plan.axis], line=e.line, **mags))
        self._update_witness()
        if lost:
            self.warning.emit(f'Witness point: no clear front echo at visit {e.j}: the drift is '
                              'not known around it (the lines next to it are marked).')

    def _witness_face_um(self, seg, m, lost):
        """Face displacement [µm, + away from the PE transducer] since the first visit
        with an echo: cross-correlation of a ±band gate around the tracked echo
        against that visit's gate, plus the shift of the gate itself."""
        if lost:
            return float('nan')
        h = self._witness_tracker.band
        c = int(m.index) - self.window[0]
        gate = np.array(seg[max(c - h, 0):c + h], dtype=float)
        if self._witness_ref is None:
            self._witness_ref = (c, gate)
        c0, ref = self._witness_ref
        if len(gate) != len(ref):
            return float('nan')                          # gate cut by the window edge
        shift, _, _ = CalcToFAscanCosine_XCRFFT(gate, ref)
        return self.c_w * (float(shift) + c - c0) / ACQ_FS / 2.0 * 1e6

    def _update_witness(self):
        """The trend of the witness and the lines in doubt."""
        d, p = self.data, self.params
        dev, rate = witness_jumps([v['time'] for v in d.witness],
                                  [v['face_um'] for v in d.witness])
        d.witness_dev, d.witness_rate = dev, rate
        self._witness_thr, self._witness_sigma = witness_threshold(dev, p.witness_jump_floor_um)
        doubt = witness_doubt(d.witness, dev, self._witness_thr)
        new = sorted(set(doubt) - set(self._doubt_lines))
        self._doubt_lines = doubt
        if new and any('jump' in doubt[k] for k in new):
            self.warning.emit(
                f'Witness point jumped by more than {self._witness_thr:.1f} µm off the trend '
                f'during line(s) {", ".join(str(k) for k in new)}: the drift there cannot be '
                'reconstructed, those lines are marked as doubtful.')

    def _refresh_echo_values(self, k, ks, m, f):
        """
        Point k (flat index; ks in the current sweep) after its front-echo measure m
        (revised by a re-lock or not) and its echo flags f: ToF, echo 1 → echo 2
        again if echo 1 moved, the thickness magnitudes and the thickness flags
        (appended to f).
        """
        d, p = self.data, self.params
        gone = 'weak' in f or 'outside' in f
        pair = d.pairs[k]
        if pair is not None and pair.front != m.index:
            pair = d.pairs[k] = self._pair(*self._tracker.point_signals(ks), m)
        if gone and pair is not None and pair.found:      # no echo 1 there: no pair either
            pair = d.pairs[k] = EchoDelay(False, 'front_lost', front=m.index)
        mags = d.magnitudes[k]
        mags['tof'] = (float('nan') if gone else
                       (m.index_frac - p.emission_sample) / ACQ_FS * 1e6)
        mags['thickness'] = float('nan') if gone else pair_thickness_mm(pair, p.c_sample)
        mags['thickness_corr'] = (pair.corr if not gone and pair is not None and pair.found
                                  else float('nan'))
        if not gone:
            f.extend(thickness_flags(pair, p.min_corr))

    def positions_read(self):
        """Real positions along the scanned axis of the points acquired so far."""
        k = AXES4.index(self.plan.axis)
        return [c[k] for c in self.data.coords]

    def set_magnitude(self, name):
        if name in THICKNESS_MAGNITUDES and self.state != 'idle' and not self.thickness_on:
            name = 'amplitude'                 # not offered in this scan (see _check_thickness)
        self.magnitude = name
        self._refresh_view()

    def set_map_scale(self, auto, lo=None, hi=None):
        """Main map scale: automatic, or fixed to [lo, hi]."""
        self.map_scale = None if auto or lo is None or hi is None else (float(lo), float(hi))
        self._refresh_view()

    def set_drift_corrected(self, on):
        """Show the face ToF corrected with the witness (live map only, never saved)."""
        self.drift_corrected = bool(on)
        self._refresh_view()

    def set_companion(self, on):
        """Amplitude map beside the main one (surface)."""
        self.companion = bool(on)
        self._refresh_view()

    def _refresh_view(self):
        if self.plan is not None and self.state != 'ref_review':
            self._reset_view(bring_to_front=False)

    def _reset_view(self, bring_to_front=True):
        """The 1-D plot for a line, the 2-D maps for a surface; then redraw."""
        if self.plan.params.surface:
            self._setup_map()
            if bring_to_front and self._show_map is not None:
                self._show_map()
        else:
            self._plot.reset(self.plan.axis, self.magnitude)
            if bring_to_front and self._show_plot is not None:
                self._show_plot()
        self._redraw()

    def _redraw(self):
        d = self.data
        if d is None or not d.coords:
            return
        if self.plan.params.surface:
            self._redraw_map()
            return
        flagged = [point_marked(self.magnitude, f) for f in d.flags]
        self._plot.set_data(self.positions_read(), self._map_values(self.magnitude), flagged)

    def _map_values(self, name):
        """Per acquired point; the face ToF minus the witness drift when asked (live)."""
        d = self.data
        vals = np.array([m.get(name, float('nan')) for m in d.magnitudes], dtype=float)
        if name == 'tof' and self.drift_corrected and d.witness:
            # the witness displacement back to time of flight: Δt [µs] = 2·face [µm] / c_w
            vals = vals - witness_correction(d.times, [v['time'] for v in d.witness],
                                             [2.0 * v['face_um'] / self.c_w for v in d.witness])
        return vals

    def _map_title(self, name):
        mag = MAGNITUDES[name]
        title = mag.label + (f' [{mag.unit}]' if mag.unit else '')
        if name == 'tof' and self.drift_corrected:
            title += ' — drift-corrected with the witness (live only, not saved)'
        if name == self._map_names[0] and self._doubt_lines:
            title += ' — doubtful lines: ' + ', '.join(str(k) for k in sorted(self._doubt_lines))
        return title

    def _setup_map(self):
        plan = self.plan
        xs = np.asarray(plan.xs, dtype=float)
        ys = np.asarray([plan.line_y(k) for k in range(len(plan.lines))], dtype=float)
        rank_x = np.argsort(np.argsort(xs))
        rank_y = np.argsort(np.argsort(ys))
        lat_is_x = plan.axis != 'Z'
        self._map_index = (rank_x, rank_y, lat_is_x)
        xs_s, ys_s = np.sort(xs), np.sort(ys)
        lat, z = (xs_s, ys_s) if lat_is_x else (ys_s, xs_s)
        names = [self.magnitude]
        if self.companion and self.magnitude != 'amplitude':
            names.append('amplitude')
        self._map_names = names
        self._map.reset(names, {n: self._map_title(n) for n in names},
                        {n: MAGNITUDES[n].unit for n in names}, lat, z)
        self._map_cells = (lat, z)

    def _cell(self, k, j):
        rank_x, rank_y, lat_is_x = self._map_index
        return (rank_x[j], rank_y[k]) if lat_is_x else (rank_y[k], rank_x[j])

    def _redraw_map(self):
        d = self.data
        lat, z = self._map_cells
        for name in self._map_names:
            grid = np.full((lat.size, z.size), np.nan)
            measured = np.zeros(grid.shape, dtype=bool)
            marks = []
            for v, k, j, f in zip(self._map_values(name), d.line, d.j, d.flags):
                cell = self._cell(k, j)
                grid[cell], measured[cell] = v, True
                if point_marked(name, f):
                    marks.append((lat[cell[0]], z[cell[1]]))
            if name in THICKNESS_MAGNITUDES and not self.thickness_on:
                why = f'thickness not available in this scan ({self.thickness_reason})'
            elif MAGNITUDES[name].uses_echo:
                why = 'no clear echo at any measured point'
            else:
                why = 'NaN at every measured point'
            self._map.set_title(name, self._map_title(name))
            self._map.set_data(name, grid, measured, marks,
                               self.map_scale if name == self._map_names[0] else None,
                               empty_reason=why)

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
                self._move('back', self._home_path(), 'Scan done. Back to the start point…')
        elif phase == 'to_ref':
            self._ref_which = 'final'
            self._take_reference('final')
        elif phase == 'back':
            self._finish_and_save('completed' if self.data.n == self.plan.n_points else 'stopped')

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
        self.status.emit(f'{text} Not moved. {self.data.n} of {self.plan.n_points} points '
                         'acquired: save them' + (', take the final reference first' if can_ref else '')
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
        msgs += self._witness_summary()
        if self.data.drift is not None:
            msgs = drift_lines(self.data.drift) + msgs
        self._end(how, '\n'.join([text] + msgs))

    def _witness_summary(self):
        d = self.data
        if not d.witness:
            return []
        face = [v['face_um'] for v in d.witness if v['face_um'] == v['face_um']]
        span = (max(face) - min(face)) if face else float('nan')
        rate = d.witness_rate * 60.0 if np.isfinite(d.witness_rate) else float('nan')
        out = [f'Witness point: {len(d.witness)} visits, face moved over {span:.1f} µm, median '
               f'drift {rate:+.2f} µm/min (saved raw; corrected only in the analysis, never '
               'the thickness).']
        if self._doubt_lines:
            out.append('Doubtful lines (witness): ' + ', '.join(
                f'{k} ({r})' for k, r in sorted(self._doubt_lines.items())) + '.')
        return out

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
        n_line, n_point = (max(d.line) + 1 if n else 0), len(plan.xs)
        cube = self._cube
        valid = cube([True] * n, False, bool)
        line_status = ['complete' if valid[k].all() else 'partial' for k in range(n_line)]
        equipment1 = dict(info.get('equipment1', {'nombre': 'SEDAQ'}))
        params = dict(equipment1.get('params', {}))
        params.update(Gain_Ch1=self._scan_gains[0], Gain_Ch2=self._scan_gains[1],
                      F_muestreo=ACQ_FS, Smin=smin, Smax=smax, Slen=n_samp,
                      AvgSamplesNum=p.avg_n)
        equipment1['params'] = params
        scan = {
            'type': 'surface' if p.surface else 'line',
            'timestamp_start': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(self._t_start)),
            'axis_role': p.axis_role, 'axis': plan.axis, 'beam_axis': plan.beam_axis,
            'range_mode': p.mode, 'start_mm': p.start, 'end_mm': p.end, 'step_mm': p.step,
            'first_mm': plan.first, 'last_mm': plan.last, 'positions_requested': plan.xs,
            'axis2': plan.other, 'path': p.path if p.surface else None,
            'start2_mm': p.start2 if p.surface else None,
            'end2_mm': p.end2 if p.surface else None,
            'step2_mm': p.step2 if p.surface else None,
            'lines_requested': [plan.line_y(k) for k in range(len(plan.lines))],
            'n_lines': len(plan.lines), 'n_lines_acquired': n_line,
            'line_status': line_status,
            'partial_line': line_status.index('partial') if 'partial' in line_status else None,
            'n_points': plan.n_points, 'n_points_per_line': n_point, 'n_acquired': n,
            'status': getattr(self, '_completion', 'completed'),
            'completed': n == plan.n_points,
            'array_order': 'spatial: [k, j] is line k at the j-th position of '
                           'positions_requested, whatever the path (a zigzag line is acquired '
                           'with j decreasing); point_valid marks what was acquired, acq_index '
                           'and point_time give the acquisition order',
            'axis_order': f'fixed: along a line only {plan.axis} moves; at a line change or a '
                          f'witness visit {plan.other} moves first, then {plan.axis}; back to '
                          f'the start {plan.axis} first, then {plan.other}',
            'temperature_note': PT100_NOTE,
            'start_point': plan.start_coords,
            'settle_ms': p.settle_ms, 'avg_n': p.avg_n,
            'settle_avg_note': 'default settle 100 ms measured 2026-10-05, valid for steps '
                               '<= 0.5 mm; default averages (20) pending characterization',
            'c_w': self.c_w, 'c_w_source': self.cw_source,
            'references': p.references, 'ref_gains': [p.ref_gain1, p.ref_gain2],
            'ref_avg_n': p.ref_avg_n, 'reference_position': d.reference_position,
            'manual_axis_order': d.axis_order,
            'manual_moves': [{'axis': a, 'value': v, 'time': t} for a, v, t in d.manual_log],
            'tracking': {'band_us': p.band_us, 'threshold': p.threshold,
                         'edge_margin': p.edge_margin, 'emission_sample': p.emission_sample},
            'flags': {f'{k},{j}': f for k, j, f in zip(d.line, d.j, d.flags) if f},
            'flags_key': 'line,j',
            'reference_drift': d.drift,
            'thickness': {
                'enabled': self.thickness_on, 'reason_off': self.thickness_reason or None,
                'method': 'echo 1 (tracked front echo) to echo 2 (first clear echo after it), '
                          'cross-correlation of ±gate_samples gates around their envelope '
                          'peaks (ECOS_US_ToolBox.CalcToFAscanCosine_XCRFFT)',
                'gate_samples': self._tracker.band, 'c_sample': p.c_sample,
                'c_sample_note': 'nominal, for the live map (live_thickness) only: the '
                                 'measured quantity is echo_delay_us',
                'min_corr': p.min_corr,
                'drift_note': 'immune to the movement of the sample (both echoes move '
                              'together); never drift-corrected',
            },
            'live_values_note': 'live_* arrays: the values of the live map, for the '
                                'metadata only; the results are computed in the analysis',
            'line_settle_ms': p.line_settle_ms,
            'line_settle_note': 'settle after a long move (first point of every line, witness '
                                'visits): NOT characterized',
            'witness': self._witness_meta(),
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
            scan=scan,
            signals_ch1=cube(d.sum1, 0, np.int64, (n_samp,)),
            signals_ch2=cube(d.sum2, 0, np.int64, (n_samp,)),
            offsets_ch1=cube(d.off1), offsets_ch2=cube(d.off2),
            n_avg=p.avg_n, gains=self._scan_gains, adc_bits=self.adc_bits,
            coords=cube(d.coords, tail=(4,)), point_time=cube(d.times),
            temperatures=d.temperatures, references=refs, witness=self._witness_arrays(),
            operator=p.operator, comment=p.comment, base_dir=base_dir, exp_name=name,
            extra_arrays=dict(
                self._point_cubes(),
                point_valid=valid, acq_index=cube(range(n), -1, np.int64),
                positions_requested=np.tile(np.asarray(plan.xs, dtype=float), (n_line, 1)),
                line_position_requested=np.array(
                    [plan.line_y(k) for k in range(n_line)], dtype=float),
                line_partial=np.array([s == 'partial' for s in line_status], dtype=bool),
                line_doubtful=np.array([k in self._doubt_lines for k in range(n_line)],
                                       dtype=bool)),
            files_extra=SCAN_ARRAYS_DOC)
        if os.path.abspath(base_dir) == os.path.abspath(self.base_dir) or self.last_saved_path is None:
            self.last_saved_path = path
        self.saved.emit(path)
        return path

    def _witness_arrays(self):
        """The witness series, raw (None without a witness or before its first visit)."""
        w = self.data.witness
        if not w:
            return None

        def col(key, dtype=float):
            return np.array([v[key] for v in w], dtype=dtype)
        return {'sum1': np.array([v['sum1'] for v in w], dtype=np.int64),
                'sum2': np.array([v['sum2'] for v in w], dtype=np.int64),
                'offset1': col('offset1'), 'offset2': col('offset2'),
                'coords': col('coords'), 'requested': col('requested'), 'time': col('time'),
                'line': col('after_line', np.int64), 'visit': col('visit', np.int64),
                'tof_us': col('tof_us'), 'amplitude': col('amplitude'),
                'face_um': col('face_um'), 'thickness_mm': col('thickness_mm'),
                'thickness_corr': col('thickness_corr'), 'lost': col('lost', bool)}

    def _witness_meta(self):
        p, d = self.params, self.data
        if not p.witness:
            return {'enabled': False}
        dev = d.witness_dev if d.witness_dev is not None else np.zeros(0)
        last_after = d.witness[-1]['after_line'] if d.witness else 0
        n_lines = (max(d.line) + 1) if d.line else 0
        return {
            'enabled': True, 'mode': p.witness_mode, 'position': self._witness_pos,
            'every_lines': p.witness_every,
            'jump_threshold_um': self._witness_thr, 'jump_floor_um': p.witness_jump_floor_um,
            'jitter_sigma_um': (self._witness_sigma if np.isfinite(self._witness_sigma)
                                else None),
            'threshold_rule': f'max(floor, {WITNESS_JUMP_SIGMAS:g} × 1.4826·MAD of the '
                              'deviations between consecutive visits); the floor alone with '
                              'fewer than three intervals',
            'n_visits': len(d.witness),
            'median_rate_um_per_min': (d.witness_rate * 60.0 if np.isfinite(d.witness_rate)
                                       else None),
            'interval_deviation_um': [float(x) if np.isfinite(x) else None for x in dev],
            'doubtful_lines': {str(k): r for k, r in sorted(self._doubt_lines.items())},
            'lines_after_last_visit': list(range(last_after, n_lines)),
            'face_um_note': 'face displacement since the first visit, + away from the PE '
                            'transducer: cross-correlation of a ±gate_samples gate around the '
                            'tracked front echo against the first visit (as the stability '
                            'test), c_w of this scan. tof_us is the envelope peak, as for '
                            'every scan point',
            'gate_samples': self._witness_tracker.band,
            'note': 'raw data: no drift correction is applied in this file. The analysis '
                    'corrects the position of the face (ToF) with the witness series, '
                    'never the thickness, which is immune to the drift.',
            'trend_note': 'jump = displacement between two visits minus median rate × '
                          'duration; with fewer than three intervals the trend is not robust',
        }

    def _cube(self, flat, fill=float('nan'), dtype=float, tail=()):
        """Per-point values (acquisition order) into the (N_line, N_point, *tail) array
        of the file, in spatial order; `fill` where nothing was acquired."""
        d = self.data
        n_line = max(d.line) + 1 if d.line else 0
        out = np.full((n_line, len(self.plan.xs)) + tuple(tail), fill, dtype=dtype)
        for v, k, j in zip(flat, d.line, d.j):
            out[k, j] = v
        return out

    def _point_cubes(self):
        """Per-point live values (live_<magnitude>) and the echo 1 → echo 2 measure."""
        d = self.data
        out = {f'live_{name}': self._cube([m.get(name, float('nan')) for m in d.magnitudes])
               for name in MAGNITUDES}
        out['echo_delay_us'] = self._cube(
            [q.delay_samples / ACQ_FS * 1e6 if q is not None and q.found else float('nan')
             for q in d.pairs])
        out['echo_polarity'] = self._cube([q.polarity if q is not None else 0 for q in d.pairs],
                                          0, np.int8)
        return out

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
        self._hold_live(False)
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
    """
    Scan controls, for the «Scans» sub-tab (spec 4 and 5.6). A line is the case
    of a single line: «Surface» enables the second-axis fields and the path.
    """

    def __init__(self, tool, sequencer, parent=None):
        super().__init__('Scan', parent)
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
        self._spin_settle.setToolTip('Scan default, NOT the focus one. 100 ms measured on '
                                     '05/10: same result as 500 ms (0.22 samples RMS) with '
                                     '0.5 mm steps. Valid for steps of 0.5 mm or less; not '
                                     'checked for large moves.')
        self._spin_avg = QSpinBox()
        self._spin_avg.setRange(1, 10000)
        self._spin_avg.setValue(DEFAULT_SCAN_AVG_N)
        self._spin_avg.setToolTip('Scan default, NOT the focus one: pending characterization.')
        self._cmb_mag = QComboBox()
        for name, mag in MAGNITUDES.items():
            self._cmb_mag.addItem(mag.label, name)
            if mag.tip:
                self._cmb_mag.setItemData(self._cmb_mag.count() - 1, mag.tip, Qt.ToolTipRole)
        form.addRow('Line axis:', self._cmb_axis)
        form.addRow('Range:', self._cmb_mode)
        form.addRow('Start:', self._spin_start)
        form.addRow('End:', self._spin_end)
        form.addRow('Step:', self._spin_step)

        self._chk_surface = QCheckBox('Surface')
        self._chk_surface.setToolTip('Several lines along the second axis, drawn line by line '
                                     'as a 2-D map. A line scan is a surface of one line, as in '
                                     'the data format.')
        self._lbl_axis2 = QLabel()
        self._spin_start2 = dspin(-500.0, 500.0, -5.0, 2, 0.5, ' mm')
        self._spin_end2 = dspin(-500.0, 500.0, 5.0, 2, 0.5, ' mm')
        self._spin_step2 = dspin(0.01, 50.0, DEFAULT_SCAN_STEP_MM, 2, 0.05, ' mm')
        self._cmb_path = QComboBox()
        self._cmb_path.addItem('Zigzag', 'zigzag')
        self._cmb_path.addItem('Same direction', 'same')
        self._cmb_path.setToolTip('Same direction: every line is scanned the same way, so the '
                                  'mechanical backlash does not shift alternate lines (zigzag '
                                  'is faster).')
        form.addRow(self._chk_surface)
        form.addRow('Second axis:', self._lbl_axis2)
        form.addRow('Start (2nd):', self._spin_start2)
        form.addRow('End (2nd):', self._spin_end2)
        form.addRow('Step (2nd):', self._spin_step2)
        form.addRow('Path:', self._cmb_path)
        self._surface_widgets = (self._spin_start2, self._spin_end2, self._spin_step2,
                                 self._cmb_path, self._lbl_axis2)
        self._spin_line_settle = QSpinBox()
        self._spin_line_settle.setRange(0, 60000)
        self._spin_line_settle.setValue(DEFAULT_LINE_SETTLE_MS)
        self._spin_line_settle.setSuffix(' ms')
        self._spin_line_settle.setToolTip('Settle after a long move: first point of every line '
                                          'and every witness visit. NOT characterized (the 100 ms '
                                          'between points hold for steps ≤ 0.5 mm only).')
        form.addRow('Settle (scan):', self._spin_settle)
        form.addRow('Settle, line change:', self._spin_line_settle)
        form.addRow('Averages (scan):', self._spin_avg)
        form.addRow('Map:', self._cmb_mag)
        self._chk_auto = QCheckBox('Automatic colour scale')
        self._chk_auto.setChecked(True)
        self._spin_lo = dspin(-1e6, 1e6, 0.0, 4, 0.01, '')
        self._spin_hi = dspin(-1e6, 1e6, 1.0, 4, 0.01, '')
        self._spin_lo.setToolTip('Fixed scale of the main map, in its units.')
        self._spin_hi.setToolTip('Fixed scale of the main map, in its units.')
        self._chk_corr = QCheckBox('Face ToF drift-corrected with the witness (live only)')
        self._chk_corr.setToolTip('Only the live map: the file is saved raw. Never applied to '
                                  'the thickness.')
        self._chk_companion = QCheckBox('Amplitude map beside it (surface)')
        self._chk_companion.setChecked(True)
        self._chk_companion.setToolTip('The amplitude says where the other map can be trusted.')
        form.addRow(self._chk_auto)
        form.addRow('Scale min:', self._spin_lo)
        form.addRow('Scale max:', self._spin_hi)
        form.addRow(self._chk_corr)
        form.addRow(self._chk_companion)

        self._chk_witness = QCheckBox('Witness point (drift of the sample)')
        self._chk_witness.setChecked(True)
        self._chk_witness.setToolTip('A fixed point measured again every N lines. Without it the '
                                     'topography of the face of a soft sample is not valid: PVA '
                                     'drifted −4.34 µm/min in jerks on 05/10. Saved raw; the '
                                     'correction is done in the analysis.')
        self._cmb_witness = QComboBox()
        self._cmb_witness.addItem('First point of the scan', 'first')
        self._cmb_witness.addItem('Position at Start', 'start')
        self._cmb_witness.addItem('Custom (absolute)', 'custom')
        self._spin_wlat = dspin(0.0, 1000.0, 0.0, 2, 0.5, ' mm')
        self._spin_wz = dspin(0.0, 1000.0, 0.0, 2, 0.5, ' mm')
        self._spin_wevery = QSpinBox()
        self._spin_wevery.setRange(1, 1000)
        self._spin_wevery.setValue(DEFAULT_WITNESS_EVERY)
        self._spin_wevery.setSuffix(' line(s)')
        self._spin_wjump = dspin(0.1, 1000.0, DEFAULT_WITNESS_JUMP_FLOOR_UM, 1, 0.5, ' µm')
        self._spin_wjump.setToolTip('Minimum jump threshold. The threshold is 3 × the scatter of '
                                    'the witness series itself (its jitter depends on the echo: '
                                    '0.41 µm on steel, 1.0–1.4 µm on PVA), never below this. '
                                    'A jump off the trend marks the lines in between as '
                                    'doubtful.')
        form.addRow(self._chk_witness)
        form.addRow('Witness position:', self._cmb_witness)
        form.addRow('Witness lateral:', self._spin_wlat)
        form.addRow('Witness Z:', self._spin_wz)
        form.addRow('Witness every:', self._spin_wevery)
        form.addRow('Witness jump floor:', self._spin_wjump)

        self._chk_thick = QCheckBox('Thickness per point (echo 1 → echo 2)')
        self._chk_thick.setChecked(True)
        self._chk_thick.setToolTip('Cross-correlation of the front and back echoes, both inside '
                                   'Smin–Smax. Immune to the drift of the sample. Checked at '
                                   'Start: if the second echo is not inside the window it is '
                                   'disabled for the scan.')
        self._spin_csample = dspin(500.0, 5000.0, DEFAULT_C_SAMPLE, 0, 10.0, ' m/s')
        self._spin_csample.setToolTip('NOMINAL sound speed of the sample, for the thickness in mm '
                                      'of the live map only. The delay is what is saved and '
                                      'analysed.')
        self._spin_mincorr = dspin(0.0, 1.0, DEFAULT_MIN_CORR, 2, 0.05, '')
        self._spin_mincorr.setToolTip('Echo 1 / echo 2 correlation below this marks the point as '
                                      'less reliable (deformed echo: inclined face).')
        self._lbl_thick = QLabel('')
        self._lbl_thick.setWordWrap(True)
        form.addRow(self._chk_thick)
        form.addRow('Sample sound speed:', self._spin_csample)
        form.addRow('Min. correlation:', self._spin_mincorr)
        form.addRow(self._lbl_thick)

        self._chk_refs = QCheckBox('Take water references at the start and at the end')
        self._spin_rg1 = dspin(0.0, 100.0, 0.0, 1, 1.0, ' dB')
        self._spin_rg2 = dspin(0.0, 100.0, 0.0, 1, 1.0, ' dB')
        self._rg2_touched = False
        self._prefilling = False
        self._spin_rg2.valueChanged.connect(self._on_rg2_edited)
        self._lbl_rg2_note = QLabel('Prefilled with the Acquisition gain of Ch2. With the sample '
                                    'out, Ch2 receives the echo of the opposite transducer and '
                                    'can saturate too: check it in the reference shown.')
        self._lbl_rg2_note.setWordWrap(True)
        self._lbl_rg2_note.setStyleSheet('color: gray;')
        self._spin_ravg = QSpinBox()
        self._spin_ravg.setRange(1, 10000)
        self._spin_ravg.setValue(DEFAULT_REF_AVG_N)
        self._lbl_ref_hint = QLabel('The reference gains can be changed before Repeat.')
        self._lbl_ref_hint.setWordWrap(True)
        self._lbl_ref_hint.setStyleSheet('color: gray;')
        form.addRow(self._chk_refs)
        form.addRow('Reference gain Ch1:', self._spin_rg1)
        form.addRow('Reference gain Ch2:', self._spin_rg2)
        form.addRow(self._lbl_rg2_note)
        form.addRow('Reference averages:', self._spin_ravg)
        form.addRow(self._lbl_ref_hint)
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
        self._btn_repeat.clicked.connect(lambda: self._report(tool.repeat_reference(
            self._spin_rg1.value(), self._spin_rg2.value())))
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
        tool.thickness_available.connect(self._on_thickness_available)
        self._chk_thick.toggled.connect(lambda on: self._on_thickness_available(on, '', False))
        sequencer.state_changed.connect(lambda st: self._on_state(tool.state, st))
        for w in (self._spin_start, self._spin_end, self._spin_step, self._spin_settle,
                  self._spin_avg, self._spin_ravg):
            w.valueChanged.connect(self._refresh_estimate)
        for c in (self._cmb_axis, self._cmb_mode):
            c.currentIndexChanged.connect(self._refresh_estimate)
        self._chk_refs.toggled.connect(self._refresh_estimate)
        self._chk_refs.toggled.connect(lambda on: on and self._prefill_ref_gain2())
        self._chk_surface.toggled.connect(self._on_surface_toggled)
        self._cmb_axis.currentIndexChanged.connect(self._update_axis2_label)
        for w in (self._spin_start2, self._spin_end2, self._spin_step2):
            w.valueChanged.connect(self._refresh_estimate)
        self._cmb_path.currentIndexChanged.connect(self._refresh_estimate)
        for w in (self._spin_line_settle, self._spin_wlat, self._spin_wz, self._spin_wevery):
            w.valueChanged.connect(self._refresh_estimate)
        self._chk_auto.toggled.connect(self._on_scale)
        self._spin_lo.valueChanged.connect(self._on_scale)
        self._spin_hi.valueChanged.connect(self._on_scale)
        self._chk_corr.toggled.connect(tool.set_drift_corrected)
        self._chk_companion.toggled.connect(tool.set_companion)
        self._on_scale()
        self._chk_witness.toggled.connect(self._on_witness_widgets)
        self._cmb_witness.currentIndexChanged.connect(self._on_witness_widgets)
        self._on_witness_widgets()
        self._on_surface_toggled(False)
        self._prefill_ref_gain2()
        self._on_state('idle')
        self._refresh_estimate()

    def _on_surface_toggled(self, on):
        for w in self._surface_widgets:
            w.setEnabled(on)
        self._update_axis2_label()
        self._btn_start.setText('Start surface scan' if on else 'Start scan')
        self._refresh_estimate()

    def _on_scale(self, *_):
        auto = self._chk_auto.isChecked()
        self._spin_lo.setEnabled(not auto)
        self._spin_hi.setEnabled(not auto)
        self._tool.set_map_scale(auto, self._spin_lo.value(), self._spin_hi.value())

    def _on_witness_widgets(self, *_):
        on = self._chk_witness.isChecked()
        custom = self._cmb_witness.currentData() == 'custom'
        for w in (self._cmb_witness, self._spin_wevery, self._spin_wjump):
            w.setEnabled(on)
        for w in (self._spin_wlat, self._spin_wz):
            w.setEnabled(on and custom)
        self._refresh_estimate()

    def _update_axis2_label(self, *_):
        self._lbl_axis2.setText('Z' if self._cmb_axis.currentData() == 'lateral' else 'Lateral')

    def _on_rg2_edited(self, _v):
        if not self._prefilling:
            self._rg2_touched = True

    def _prefill_ref_gain2(self):
        """Ch2 reference gain = the Acquisition one, unless the user already set it."""
        if self._rg2_touched or self._tool.state != 'idle':
            return
        try:
            g2 = self._tool.scan_gains()[1]
        except Exception:
            return
        self._prefilling = True
        self._spin_rg2.setValue(g2)
        self._prefilling = False

    def params(self):
        return ScanParams(
            axis_role=self._cmb_axis.currentData(), mode=self._cmb_mode.currentData(),
            start=self._spin_start.value(), end=self._spin_end.value(),
            step=self._spin_step.value(), settle_ms=self._spin_settle.value(),
            avg_n=self._spin_avg.value(), references=self._chk_refs.isChecked(),
            ref_gain1=self._spin_rg1.value(), ref_gain2=self._spin_rg2.value(),
            ref_avg_n=self._spin_ravg.value(), operator=self._txt_operator.text().strip(),
            comment=self._txt_comment.text(), debug_dump=self._chk_dump.isChecked(),
            drift_tol_db=self._spin_drift_db.value(), drift_tol_ns=self._spin_drift_ns.value(),
            surface=self._chk_surface.isChecked(), start2=self._spin_start2.value(),
            end2=self._spin_end2.value(), step2=self._spin_step2.value(),
            path=self._cmb_path.currentData(), thickness=self._chk_thick.isChecked(),
            c_sample=self._spin_csample.value(), min_corr=self._spin_mincorr.value(),
            line_settle_ms=self._spin_line_settle.value(), witness=self._chk_witness.isChecked(),
            witness_mode=self._cmb_witness.currentData(), witness_lat=self._spin_wlat.value(),
            witness_z=self._spin_wz.value(), witness_every=self._spin_wevery.value(),
            witness_jump_floor_um=self._spin_wjump.value())

    def _refresh_estimate(self, *_):
        _, text, long_ = self._tool.estimate(self.params())
        self._lbl_estimate.setText(text)
        self._lbl_estimate.setStyleSheet('color: rgb(200, 40, 40); font-weight: bold;' if long_
                                         else 'font-weight: bold;')

    def showEvent(self, event):
        self._prefill_ref_gain2()
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

    def _on_thickness_available(self, on, reason, at_start=True):
        """Offer the thickness magnitudes only when they can be measured."""
        model = self._cmb_mag.model()
        for i in range(self._cmb_mag.count()):
            if self._cmb_mag.itemData(i) in THICKNESS_MAGNITUDES:
                model.item(i).setEnabled(bool(on))
        if not on and self._cmb_mag.currentData() in THICKNESS_MAGNITUDES:
            self._cmb_mag.setCurrentIndex(self._cmb_mag.findData('amplitude'))
        if at_start:
            self._lbl_thick.setText('' if on else f'Thickness not available: {reason}.')
            self._lbl_thick.setStyleSheet('' if on else 'color: rgb(200, 40, 40);')
        else:
            self._lbl_thick.setText('')

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
