# -*- coding: utf-8 -*-
"""
echo_tracking.py — Front-face echo of the pulse-echo channel along a scanner sweep.
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

Shared by the focus tool (phase 3) and the flatness tool (phase 4). No Qt.

Why: with a thin sample both the front-face and the back-face echoes fall
inside Smin–Smax, and the back one can be the larger. Taking the global
maximum of the window then jumps from one echo to the other along the sweep.

FrontEchoTracker, one measure per point, always inside Smin–Smax:
    - first point (no anchor yet): the FIRST envelope peak above the threshold
      inside the window, not the largest. The threshold is the larger of
      CONFIDENT_CONTRAST × median of the envelope (noise floor) and
      `threshold` × maximum of the envelope;
    - next points: the echo is predicted at t_prev + 2·Δx/c_w (samples_per_mm
      carries the sign of the PE side, spec section 2) and the maximum is taken
      only in a narrow band ±band around that prediction. t_prev is the last
      point where the tracked echo stood clearly above the noise; while the
      echo is too weak the anchor is kept, so noise never drags it away;
    - re-lock: if a clear, separate echo shows up BEFORE the band, the tracker
      was on a later echo (on the first point the front face was too far out
      of focus to pass the threshold and the back face did). It re-locks on
      that earlier echo and re-measures the previous points of the sweep from
      their stored envelopes, predicting backwards. A peak pinned on the left
      edge of the window (e.g. the tail of the main bang) never triggers it.

echo_pair_delay (scan, phase 6): time from the front echo to the next one (the
back face) by cross-correlation of a gate around each, the thickness of the
sample. Echo 2 is the first clear lobe after echo 1 (echo_lobes, the same rule
as the first-peak rule), never searched outside Smin–Smax.

The positions passed to measure() are beam-axis positions. For moves along
lateral or Z (flatness), pass the unchanged beam-axis coordinate: the
prediction is then t_prev and the band has to absorb the shift due to the
tilt, 2·step·tan(θ)/c_w per point (≈ 7 samples per mm at 3°).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

_TOOLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools')
if _TOOLS_DIR not in sys.path:
    sys.path.append(_TOOLS_DIR)
from ECOS_US_ToolBox import CalcToFAscanCosine_XCRFFT, Envelope  # noqa: E402

DEFAULT_EDGE_MARGIN = 0.05     # fraction of the window width
CONFIDENT_CONTRAST = 8.0       # envelope peak / median envelope: a clear echo
EDGE_MIN_CONTRAST = 6.0        # below this the peak is noise and where it falls means nothing
C_W_NOMINAL = 1480.0           # m/s, when no temperature has been read
ACQ_FS = 100e6                 # Hz
MIN_WINDOW_SAMPLES = 16
DEFAULT_BAND_US = 0.5          # tracking band ±, µs: below the front/back separation of a thin sample
DEFAULT_THRESHOLD = 0.10       # first-echo threshold, fraction of the window envelope maximum


@dataclass
class PeakMeasure:
    amp: float            # envelope peak of the echo used
    index: int            # absolute sample index of that peak
    at_edge: bool         # a clear peak within the edge margin of Smin or Smax
    saturated: bool       # n_top > 0: raw samples at the quantizer top in Smin–Smax
    contrast: float = float('inf')   # peak / median of the envelope in the window
    # Which echo was used:
    #   'max'      window maximum (window_peak, no tracking)
    #   'none'     tracker without anchor and no clear echo: window maximum
    #   'first'    first peak above the threshold (first point of a track)
    #   'tracked'  maximum in the band around the prediction
    #   'relock'   an earlier echo appeared: the track restarts on it
    mode: str = 'max'
    band: Optional[Tuple[int, int]] = None    # absolute samples searched / around the echo
    predicted: Optional[float] = None         # absolute sample predicted (tracked)
    outside: bool = False                     # the predicted band is out of Smin–Smax
    index_frac: float = float('nan')          # sub-sample envelope peak (parabolic), absolute
    echo_elsewhere: bool = False              # tracked: a clear echo in the window, off the band
    # Raw samples at the top of the quantizer in Smin–Smax, any capture of the
    # acquisition (scan_counts.top_mask / count_at_top); None: not checked (no raw counts).
    n_top: Optional[int] = None

    @property
    def flagged(self):
        return self.at_edge or self.saturated or self.outside

    @property
    def confident(self):
        return self.contrast >= CONFIDENT_CONTRAST and not self.outside


def band_samples(band_us, fs=ACQ_FS):
    return max(1, int(round(band_us * 1e-6 * fs)))


DEFAULT_BAND_SAMPLES = band_samples(DEFAULT_BAND_US)


def echo_samples_per_mm(pe_side, c_w=C_W_NOMINAL, fs=ACQ_FS):
    """Signed shift of the front echo, in samples, per +1 mm on the beam axis."""
    sign = 1.0 if pe_side == 'origin' else -1.0
    return sign * 2e-3 / c_w * fs


def _window_env(sig, smin, smax):
    seg = np.asarray(sig[smin:smax], dtype=float)
    if len(seg) < MIN_WINDOW_SAMPLES:
        raise ValueError(f'window Smin–Smax too short ({len(seg)} samples)')
    return seg, Envelope(seg)


def _peak_measure(seg, env, smin, k, edge_margin, **extra):
    """PeakMeasure for relative index k (saturation: set_saturation, from raw counts)."""
    med = float(np.median(env))
    contrast = float(env[k]) / med if med > 0 else float('inf')
    margin = max(1, int(round(edge_margin * len(seg))))
    at_edge = (k < margin or k >= len(seg) - margin) and contrast >= EDGE_MIN_CONTRAST
    extra.setdefault('index_frac', smin + subsample_peak(env, k))
    return PeakMeasure(float(env[k]), smin + int(k), at_edge, False, contrast, **extra)


def set_saturation(m, n_top):
    """
    Saturation of a measure from the RAW counts of its acquisition: n_top samples
    at the top of the quantizer in Smin–Smax, in any capture (scan_counts.top_mask
    and count_at_top, the one detection of ECOS). The float the echo is measured on
    has been averaged and has its mean removed, so it cannot tell for certain.
    None: no raw counts available, not checked (saturated stays False).
    """
    m.n_top = None if n_top is None else int(n_top)
    m.saturated = bool(n_top)
    return m


def subsample_peak(env, k):
    """Envelope peak position refined by a parabola through env[k-1], env[k], env[k+1]."""
    k = int(k)
    if k <= 0 or k >= len(env) - 1:
        return float(k)
    y0, y1, y2 = float(env[k - 1]), float(env[k]), float(env[k + 1])
    den = y0 - 2.0 * y1 + y2
    if den >= 0:
        return float(k)
    return k + 0.5 * (y0 - y2) / den


def window_peak(sig, smin, smax, edge_margin=DEFAULT_EDGE_MARGIN, n_top=None):
    """Envelope maximum of sig[smin:smax] (never the whole record). No tracking.
    n_top: raw samples at the quantizer top in Smin–Smax (set_saturation)."""
    seg, env = _window_env(sig, smin, smax)
    return set_saturation(_peak_measure(seg, env, smin, int(np.argmax(env)), edge_margin),
                          n_top)


def echo_threshold(env, fraction=DEFAULT_THRESHOLD):
    """Level a clear echo must reach: above the noise floor and `fraction` of the maximum."""
    return max(CONFIDENT_CONTRAST * float(np.median(env)), fraction * float(np.max(env)))


def echo_lobes(env, threshold):
    """[(start, end, peak)] of every run of env >= threshold, in time order (end exclusive)."""
    above = np.asarray(env) >= threshold
    if not above.any():
        return []
    d = np.diff(above.astype(np.int8))
    starts = list(np.flatnonzero(d == 1) + 1)
    ends = list(np.flatnonzero(d == -1) + 1)
    if above[0]:
        starts.insert(0, 0)
    if above[-1]:
        ends.append(len(above))
    return [(int(s), int(e), int(s + np.argmax(env[s:e]))) for s, e in zip(starts, ends)]


@dataclass
class EchoDelay:
    """Echo 1 (front face) → echo 2 (back face) of one pulse-echo record."""
    found: bool
    reason: str = ''              # when not found: 'front_gate', 'no_back' or 'back_at_edge'
    front: int = -1               # absolute sample of echo 1 (the tracked envelope peak)
    back: int = -1                # absolute sample of echo 2 (envelope peak)
    delay_samples: float = float('nan')   # echo 2 − echo 1, cross-correlation, sub-sample
    corr: float = float('nan')    # |normalized correlation| of the aligned gates (1 = same shape)
    polarity: int = 0             # +1 same sign as echo 1, −1 inverted (PVA back face in water)


def echo_pair_delay(seg, env, front_k, half, threshold=DEFAULT_THRESHOLD,
                    edge_margin=DEFAULT_EDGE_MARGIN, smin=0):
    """
    Delay from echo 1 (relative index front_k of seg, the tracked front echo) to
    echo 2, the first clear lobe of the envelope after echo 1 whose gate does not
    overlap echo 1's (peak more than 2·half samples later). Both gates are
    ±half samples around the envelope peaks; the delay is (k2 − k1) plus the
    cross-correlation shift of gate 2 against gate 1 (CalcToFAscanCosine_XCRFFT,
    the ECOS estimator: it takes the largest |xcorr|, so an inverted echo 2 is
    measured as well and reported by `polarity`). corr is the normalized
    correlation of the aligned gates: it drops where the echo deforms (an
    inclined face), a quality indicator of the point.
    Not found when gate 1 does not fit in the window ('front_gate'), there is no
    clear echo after echo 1 ('no_back': echo 2 beyond Smax, or no back face), or
    gate 2 reaches the edge margin of the window ('back_at_edge'): no number is
    given rather than one measured against the edge.
    """
    n = len(seg)
    k1, half = int(front_k), max(1, int(half))
    if k1 - half < 0 or k1 + half >= n:
        return EchoDelay(False, 'front_gate', front=smin + k1)
    margin = max(1, int(round(edge_margin * n)))
    lobes = echo_lobes(env, echo_threshold(env, threshold))
    front_end = next((e for s, e, _ in lobes if s <= k1 < e), k1)
    later = [pk for s, e, pk in lobes if s >= front_end and pk > k1 + 2 * half]
    if not later:
        return EchoDelay(False, 'no_back', front=smin + k1)
    k2 = later[0]
    if k2 + half >= n - margin or k2 - half < 0:
        return EchoDelay(False, 'back_at_edge', front=smin + k1, back=smin + k2)
    g1 = np.asarray(seg[k1 - half:k1 + half + 1], dtype=float)
    g2 = np.asarray(seg[k2 - half:k2 + half + 1], dtype=float)
    shift, _, aligned = CalcToFAscanCosine_XCRFFT(g2, g1)
    norm = float(np.linalg.norm(g1) * np.linalg.norm(g2))
    rho = float(np.dot(np.real(aligned[:len(g1)]), g1)) / norm if norm > 0 else 0.0
    return EchoDelay(True, '', smin + k1, smin + k2, float(k2 - k1 + shift),
                     min(abs(rho), 1.0), 1 if rho >= 0 else -1)


class FrontEchoTracker:
    """
    Follows the front-face echo along a sweep (see the module docstring):
        tr = FrontEchoTracker((smin, smax), echo_samples_per_mm(pe_side, c_w))
        tr.new_sweep()              # at the start of every sweep (keeps the anchor)
        m = tr.measure(sig, x)      # per point; x = beam-axis position
        tr.measures                 # this sweep, possibly revised by a re-lock
    reset() also forgets the anchor (next point uses the first-peak rule).
    """

    def __init__(self, window, samples_per_mm=None, band=DEFAULT_BAND_SAMPLES,
                 threshold=DEFAULT_THRESHOLD, edge_margin=DEFAULT_EDGE_MARGIN):
        self.window = (int(window[0]), int(window[1]))
        self.samples_per_mm = float(samples_per_mm or 0.0)
        self.band = max(1, int(band))
        self.threshold = float(threshold)
        self.edge_margin = edge_margin
        self.reset()

    def reset(self):
        self.anchor = None          # (x, absolute index) of the last clear front echo
        self.new_sweep()

    def new_sweep(self):
        self.measures: List[PeakMeasure] = []
        self.relocks: List[int] = []        # indices in this sweep where it re-locked
        self._points = []                   # (x, seg, env, n_top) kept for a re-lock

    def predict(self, x, anchor=None):
        anchor = anchor if anchor is not None else self.anchor
        if anchor is None:
            return None
        return anchor[1] + self.samples_per_mm * (float(x) - anchor[0])

    def measure(self, sig, x, n_top=None):
        """n_top: raw samples at the quantizer top in Smin–Smax for this acquisition
        (set_saturation); None when the caller has no raw counts."""
        smin, smax = self.window
        seg, env = _window_env(sig, smin, smax)
        x = float(x)
        m = set_saturation(self._locate(seg, env, x, self.anchor, allow_relock=True), n_top)
        if m.mode in ('first', 'relock') or (m.mode == 'tracked' and m.confident):
            self.anchor = (x, m.index)
        if m.mode == 'relock':
            self.relocks.append(len(self.measures))
            self._retrack_backwards()
        self._points.append((x, seg, env, n_top))
        self.measures.append(m)
        return m

    def point_signals(self, j=-1):
        """(seg, env) of point j of this sweep: the exact window array the measure
        was computed on (float copy of sig[smin:smax]) and its Hilbert envelope."""
        _, seg, env, _ = self._points[j]
        return seg, env

    # -- internals ---------------------------------------------------------------
    def _locate(self, seg, env, x, anchor, allow_relock):
        smin = self.window[0]
        n = len(env)
        margin = max(1, int(round(self.edge_margin * n)))
        if anchor is None:
            lobes = echo_lobes(env, echo_threshold(env, self.threshold))
            if not lobes:
                return _peak_measure(seg, env, smin, int(np.argmax(env)), self.edge_margin,
                                     mode='none')
            return self._at_peak(seg, env, lobes[0][2], 'first')

        p = self.predict(x, anchor) - smin
        lo, hi = int(round(p - self.band)), int(round(p + self.band)) + 1
        lobes = echo_lobes(env, echo_threshold(env, self.threshold))
        if allow_relock:
            # Only the earliest lobe matters: a separate one ending before the band,
            # not pinned on the left edge of the window.
            if lobes and lobes[0][1] <= lo and lobes[0][2] >= margin:
                return self._at_peak(seg, env, lobes[0][2], 'relock')
        # A clear echo in the window that the band does not reach (with the wrong
        # PE side the prediction runs the opposite way to the echo).
        elsewhere = any(e <= lo or s >= hi for s, e, _ in lobes)
        lo_c, hi_c = max(lo, 0), min(hi, n)
        if hi_c - lo_c < 3:
            # The predicted echo is out of Smin–Smax: nothing to measure there.
            k = min(max(int(round(p)), 0), n - 1)
            m = _peak_measure(seg, env, smin, k, self.edge_margin,
                              mode='tracked', band=(smin + lo, smin + hi),
                              predicted=smin + p, outside=True, index_frac=float(smin + k),
                              echo_elsewhere=bool(lobes))
            m.amp = float(np.median(env))
            m.contrast = 1.0
            m.at_edge = False
            return m
        k = lo_c + int(np.argmax(env[lo_c:hi_c]))
        return _peak_measure(seg, env, smin, k, self.edge_margin,
                             mode='tracked', band=(smin + lo_c, smin + hi_c),
                             predicted=smin + p, echo_elsewhere=elsewhere)

    def _at_peak(self, seg, env, k, mode):
        """Measure on the echo at relative index k; band = ±band around it."""
        smin = self.window[0]
        lo, hi = max(k - self.band, 0), min(k + self.band + 1, len(env))
        return _peak_measure(seg, env, smin, k, self.edge_margin,
                             mode=mode, band=(smin + lo, smin + hi))

    def _retrack_backwards(self):
        """After a re-lock: the earlier points of this sweep, predicted from the new anchor."""
        anchor = self.anchor
        for j in range(len(self._points) - 1, -1, -1):
            x, seg, env, n_top = self._points[j]
            m = set_saturation(self._locate(seg, env, x, anchor, allow_relock=False), n_top)
            self.measures[j] = m
            if m.confident:
                anchor = (x, m.index)
