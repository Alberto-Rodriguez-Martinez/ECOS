# -*- coding: utf-8 -*-
"""
stability_tool.py — Stability test: what drifts when nothing moves (Calibration tab).
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See scanner_tab_spec.md (Calibration sub-tab, stability test). A permanent
diagnostic tool, not a phase.

Why: on 2026-10-05 six consecutive scans of the same line in three minutes
showed a linear drift of −2.46 µm/min (residual 0.78 µm), the face coming
closer to the pulse-echo transducer. Over a 16-minute surface scan that is
~39 µm, comparable to the real structure of the face, and it would look like a
tilt along the slow axis. This test tells whether it saturates and why.

What it does: stays at the current position WITHOUT MOVING ANY AXIS (the
sequencer's no_move option: not even a null move, no motor is energized
between measures) and takes N measures, the interval being the settle time.
Per point:
    - front-face echo of Ch2 (pulse-echo), found with FrontEchoTracker as in
      focus / flatness; its ToF change against the first point by
      cross-correlation (the ECOS estimator) of a gate of ±band around the
      tracked echo (the back echo of a thin sample stays out) → face
      displacement c_w·Δt/2 (negative: the face comes closer to the PE
      transducer), and its amplitude. The envelope-peak interpolation of the
      tracker jitters ±0.3 samples (±2 µm) at this SNR: fine for a focus, not
      for µm drifts; it is kept in the dump (tof_ch2_samples) for reference;
    - Ch1 (transmission through the sample): ToF change against the first
      record by cross-correlation over the whole record
      (ECOS_US_ToolBox.CalcToFAscanCosine_XCRFFT) and the envelope maximum;
    - the water temperature, on EVERY point (the series matters as much as the
      ToF: the test exists to see whether temperature explains the drift),
      with one Arduino instance for the whole test. If one reading takes more
      than TEMP_BUDGET_S it reads every few points instead, and says so in the
      metadata (temp_every, temp_read_s);
    - both full records, Ch1 and Ch2.
Two channels tell the causes apart: if the sample swells, the face comes
closer AND the thickness grows, and Ch1 sees it; if the holder moves, the face
comes closer and the thickness does not change (Ch1 flat).

Output: the debug dump (data/stability_debug, always written, also after a
STOP: what was measured is kept), plus live plots vs time and the live drift
rates (µm/min, ns/min, °C/min) with their RMS residuals.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass

import numpy as np

from ECOS_US_ToolBox import CalcToFAscanCosine_XCRFFT, Envelope
from echo_tracking import (
    ACQ_FS, DEFAULT_BAND_US, DEFAULT_EDGE_MARGIN, DEFAULT_THRESHOLD, MIN_WINDOW_SAMPLES,
    FrontEchoTracker, band_samples,
)
from focus_tool import (
    DEFAULT_EMISSION_SAMPLE, FocusDebugDump, acq_time, format_duration, host_value,
    measurement_meta, resolve_cw, to_db,
)

PE_CHANNEL = 2
DEFAULT_N = 240                 # 240 measures every 5 s: twenty minutes
DEFAULT_INTERVAL_S = 5.0
DEFAULT_AVG_N = 20
TEMP_BUDGET_S = 0.5             # longer temperature readings → read every few points
DEFAULT_DUMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'data', 'stability_debug')


# ===========================================================================
#  Pure part
# ===========================================================================
@dataclass
class StabilityParams:
    n: int = DEFAULT_N
    interval_s: float = DEFAULT_INTERVAL_S      # = the sequencer settle time
    avg_n: int = DEFAULT_AVG_N
    band_us: float = DEFAULT_BAND_US
    threshold: float = DEFAULT_THRESHOLD
    edge_margin: float = DEFAULT_EDGE_MARGIN
    emission_sample: int = DEFAULT_EMISSION_SAMPLE


def estimate_stability_s(params, acq_s, temp_s=0.0):
    """Total duration: per measure the interval, the averages and a temperature read."""
    return params.n * (params.interval_s + params.avg_n * acq_s + temp_s)


def temp_every(read_s, budget=TEMP_BUDGET_S):
    """Read the temperature on every point, or every k points when a reading is slow."""
    if not (read_s > budget):
        return 1
    return int(math.ceil(read_s / budget))


def drift_fit(t_min, y):
    """(slope per minute, RMS residual) of a straight line, or (nan, nan) with < 3 points."""
    t = np.asarray(t_min, dtype=float)
    v = np.asarray(y, dtype=float)
    ok = np.isfinite(t) & np.isfinite(v)
    if ok.sum() < 3 or np.ptp(t[ok]) <= 0:
        return float('nan'), float('nan')
    slope, icept = np.polyfit(t[ok], v[ok], 1)
    r = v[ok] - (icept + slope * t[ok])
    return float(slope), float(np.sqrt(np.mean(r * r)))


# ===========================================================================
#  Qt part
# ===========================================================================
import pyqtgraph as pg  # noqa: E402
from PyQt5.QtCore import QObject, pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QWidget,
)

_COL_CH2 = (255, 220, 0)
_COL_CH1 = (255, 80, 80)
_COL_T1 = (80, 160, 255)
_COL_T2 = (0, 220, 120)


class StabilityPlot:
    """Four panels vs time [min], linked in x: face displacement (Ch2), Ch1 ΔToF,
    amplitudes, temperatures."""

    def __init__(self, layout_widget):
        self._w = layout_widget
        self._curves = None

    def reset(self):
        w = self._w
        w.clear()
        rows = [('Face (Ch2 front echo)', 'µm'), ('Ch1 transmission ΔToF', 'ns'),
                ('Amplitude (vs first)', 'dB'), ('Water temperature', '°C')]
        self._plots = []
        for k, (title, unit) in enumerate(rows):
            p = w.addPlot(row=k, col=0, title=title)
            p.showGrid(x=True, y=True)
            p.setLabel('left', unit)
            p.getAxis('left').enableAutoSIPrefix(False)
            if self._plots:
                p.setXLink(self._plots[0])
            self._plots.append(p)
        self._plots[-1].setLabel('bottom', 'Time', units='min')
        self._plots[-1].getAxis('bottom').enableAutoSIPrefix(False)

        def curve(p, col):
            return p.plot(pen=pg.mkPen(col, width=1), symbol='o', symbolSize=4,
                          symbolBrush=col, symbolPen=None, connect='finite')
        self._curves = {
            'face': curve(self._plots[0], _COL_CH2), 'ch1_dtof': curve(self._plots[1], _COL_CH1),
            'amp2': curve(self._plots[2], _COL_CH2), 'amp1': curve(self._plots[2], _COL_CH1),
            'T1': curve(self._plots[3], _COL_T1), 'T2': curve(self._plots[3], _COL_T2),
        }

    def update(self, t_min, series):
        if self._curves is None:
            return
        for key, curve in self._curves.items():
            y = np.asarray(series[key], dtype=float)
            ok = np.isfinite(y)
            curve.setData(np.asarray(t_min)[ok], y[ok])


class StabilityTool(QObject):
    """
    Signals: status(str), warning(str), echo_used(PeakMeasure) (A-scan mark),
    done(str 'done' | 'stopped' | 'error').
    """
    status = pyqtSignal(str)
    warning = pyqtSignal(str)
    echo_used = pyqtSignal(object)
    done = pyqtSignal(str)

    def __init__(self, sequencer, panel, window_fn, layout_widget, show_plot_fn=None,
                 temp_factory=None, sos_fn=None, cw_fn=None, gains_fn=None,
                 acq_time_fn=None, dump_dir=None, parent=None):
        """
        temp_factory() -> Arduino-like (getTemperatures, close) or None: opened ONCE
        sos_fn(T) -> c_w (ECOS: water_temp2sos); cw_fn() -> (c_w, source) without
        opening the Arduino, when there is no PT100; gains_fn() -> (g1, g2) [dB].
        """
        super().__init__(parent)
        self._seq = sequencer
        self._panel = panel
        self._window_fn = window_fn
        self._plot = StabilityPlot(layout_widget)
        self._show_plot = show_plot_fn
        self._temp_factory = temp_factory
        self._sos_fn = sos_fn
        self._cw_fn = cw_fn
        self._gains_fn = gains_fn
        self._acq_time_fn = acq_time_fn
        self._dump_dir = dump_dir or DEFAULT_DUMP_DIR
        self.running = False
        self.last_dump_path = None
        self.last_temp_read_s = None
        sequencer.point_done.connect(self._on_point)
        sequencer.finished.connect(self._on_finished)

    # -- estimate --------------------------------------------------------------
    def estimate(self, params):
        acq_s, timed = acq_time(self._acq_time_fn)
        temp_s = self.last_temp_read_s or 0.0
        total = estimate_stability_s(params, acq_s, min(temp_s, TEMP_BUDGET_S))
        temp = (f' + temperature reads (~{temp_s:.2f} s, last measured)' if temp_s else
                ' + temperature reads (not timed yet)')
        return total, (f'Total ≈ {format_duration(total)}: {params.n} measures every '
                       f'{params.interval_s:g} s + {params.avg_n} × {acq_s * 1e3:.0f} ms '
                       f'({"timed" if timed else "assumed"}){temp}. No axis moves.')

    # -- run -------------------------------------------------------------------
    def run(self, params):
        """Start. None if started, else the reason it could not."""
        if self.running or self._seq.active:
            return 'A sequence is already running.'
        reason = self._seq.reserved_reason(self) or self._panel.sequence_blocker()
        if reason:
            return reason
        if params.n < 2 or params.interval_s < 0 or params.avg_n < 1:
            return 'At least 2 measures, a non-negative interval and 1 average.'
        smin, smax = self._window_fn()
        if smax - smin < MIN_WINDOW_SAMPLES:
            return f'Acquisition window Smin–Smax too short ({smin}–{smax}).'
        self.params = params
        self.window = (int(smin), int(smax))
        self.position = self._panel.current_coords()
        self._beam_x = float(self.position.get(self._panel.role_axis('beam'), 0.0))
        self._tracker = FrontEchoTracker(self.window, 0.0, band_samples(params.band_us),
                                         params.threshold, params.edge_margin)
        self._tracker.new_sweep()
        self._t0 = None
        self._ref = None
        self.t_s, self.epoch, self.T1, self.T2 = [], [], [], []
        self.face_um, self.ch1_dtof_ns, self.amp2_db, self.amp1_db = [], [], [], []
        self.temp_reads = []
        self._every = 1
        self._open_temperature()
        start = self._read_temperature()
        self._start_temp = start
        self._resolve_cw(start)
        g = host_value(self._gains_fn)
        self._dump = FocusDebugDump(dict(
            tool='stability', started=time.strftime('%Y-%m-%dT%H:%M:%S'),
            position=self.position, interval_s=params.interval_s, n_requested=params.n,
            smin=smin, smax=smax, c_w=self.c_w, cw_source=self.cw_source,
            band_us=params.band_us, threshold=params.threshold,
            emission_sample=params.emission_sample, fs=ACQ_FS, pe_channel=PE_CHANNEL,
            **measurement_meta(params.interval_s * 1000.0, params.avg_n, g,
                               start if start is not None and start['ok'] else None),
        ), prefix='stability_debug')
        self._plot.reset()
        reason = self._seq.start([{}] * params.n, int(round(params.interval_s * 1000.0)),
                                 params.avg_n, self._measure, record_temperature=False,
                                 owner=self, no_move=True)
        if reason:
            self._close_temperature()
            return reason
        self.running = True
        if self._show_plot is not None:
            self._show_plot()
        self.status.emit(f'Stability test: {params.n} measures every {params.interval_s:g} s at '
                         f'{self._fmt_pos()}, nothing moves. ' + self.estimate(params)[1])
        return None

    def stop(self):
        """Same as the panel STOP: what was measured is kept and saved."""
        self._seq.abort()

    def _fmt_pos(self):
        return ', '.join(f'{a} = {self.position[a]:.2f}' for a in ('X', 'Y', 'Z', 'R')
                         if a in self.position)

    # -- temperature -----------------------------------------------------------
    def _open_temperature(self):
        self._arduino = None
        if self._temp_factory is not None:
            try:
                self._arduino = self._temp_factory()
            except Exception as e:
                self.warning.emit(f'PT100 could not be opened ({e}).')
        if self._arduino is None:
            self.warning.emit('PT100 not available: the temperature series is NaN, the test '
                              'cannot tell whether temperature explains the drift.')

    def _close_temperature(self):
        try:
            if self._arduino is not None:
                self._arduino.close()
        except Exception:
            pass
        self._arduino = None

    def _read_temperature(self):
        """One timed reading: {'T1', 'T2', 'time', 'read_s', 'ok', 'source'} or None."""
        if self._arduino is None:
            return None
        t0 = time.perf_counter()
        t1 = t2 = float('nan')
        try:
            r1, r2 = self._arduino.getTemperatures()
            t1 = float('nan') if r1 is None else float(r1)
            t2 = float('nan') if r2 is None else float(r2)
        except Exception as e:
            self.warning.emit(f'Temperature read failed ({e}): NaN.')
        read_s = time.perf_counter() - t0
        self.temp_reads.append(read_s)
        self.last_temp_read_s = read_s
        every = temp_every(read_s)
        if every > self._every:
            self._every = every
            self.warning.emit(f'A temperature reading took {read_s:.2f} s (> {TEMP_BUDGET_S:g} s): '
                              f'reading every {every} points (in the metadata).')
        return {'T1': t1, 'T2': t2, 'time': time.time(), 'read_s': read_s,
                'ok': t1 == t1 or t2 == t2, 'source': 'PT100'}

    def _resolve_cw(self, t):
        temps = [] if t is None else [v for v in (t['T1'], t['T2']) if v == v]
        if temps and self._sos_fn is not None:
            self.c_w = float(np.mean([self._sos_fn(v) for v in temps]))
            self.cw_source = 'PT100 at the start'
        else:
            self.c_w, self.cw_source = resolve_cw(self._cw_fn)

    # -- per point -------------------------------------------------------------
    def _measure(self, ch1, ch2):
        sig = ch2 if PE_CHANNEL == 2 else ch1
        m = self._tracker.measure(sig, self._beam_x,             # saturation: raw, Smin–Smax
                                  self._seq.top_count(PE_CHANNEL, self._tracker.window))
        self._last = (np.array(ch1, dtype=float), np.array(sig, dtype=float))
        return m

    def _on_point(self, i, coords, value):
        if not self.running:
            return
        now = time.time()
        if self._t0 is None:
            self._t0 = now
        ch1, ch2 = self._last
        measures = list(self._tracker.measures)
        h = self._tracker.band
        if self._ref is None:
            c = int(value.index)
            self._ref = {'ch1': ch1, 'amp1': float(np.max(Envelope(ch1))),
                         'amp2': value.amp, 'c2': c, 'gate2': ch2[max(c - h, 0):c + h]}
            self.face_xcorr_um = []
        if value.confident:
            c = int(value.index)
            gate = ch2[max(c - h, 0):c + h]
            ref = self._ref['gate2']
            if len(gate) == len(ref):
                shift, _, _ = CalcToFAscanCosine_XCRFFT(gate, ref)
                dt = float(shift) + (c - self._ref['c2'])          # samples, vs the first
                self.face_xcorr_um.append(self.c_w * dt / ACQ_FS / 2.0 * 1e6)
            else:
                self.face_xcorr_um.append(float('nan'))      # gate cut by the record edge
        else:
            self.face_xcorr_um.append(float('nan'))          # no clear front echo
        temp = self._read_temperature() if i % self._every == 0 else None
        self.t_s.append(now - self._t0)
        self.epoch.append(now)
        self.T1.append(temp['T1'] if temp else float('nan'))
        self.T2.append(temp['T2'] if temp else float('nan'))
        dtof, _, _ = CalcToFAscanCosine_XCRFFT(ch1, self._ref['ch1'])
        self.ch1_dtof_ns.append(float(dtof) / ACQ_FS * 1e9)
        self.amp1_db.append(to_db(np.max(Envelope(ch1))) - to_db(self._ref['amp1']))
        # Ch2 face position from the (possibly re-lock revised) tracker measures
        tof = np.array([m.index_frac for m in measures])
        self.face_um = list(self.face_xcorr_um)
        self.amp2_db = [to_db(m.amp) - to_db(measures[0].amp) for m in measures]
        self._dump.add('stability', self._beam_x, value, *self._tracker.point_signals(-1),
                       ch2, self.window, extra={}, records={'record_ch1': ch1})
        self._dump.revise(0, measures)
        for k in range(len(measures)):
            self._dump.set_extra(
                k, t_s=self.t_s[k], epoch=self.epoch[k], T1=self.T1[k], T2=self.T2[k],
                temp_read=bool(self.T1[k] == self.T1[k] or self.T2[k] == self.T2[k]),
                tof_ch2_samples=float(tof[k] - self.params.emission_sample),
                face_um=float(self.face_um[k]), ch1_dtof_ns=self.ch1_dtof_ns[k],
                amp_ch2_db=float(self.amp2_db[k]), amp_ch1_db=self.amp1_db[k])
        self.echo_used.emit(value)
        t_min = np.array(self.t_s) / 60.0
        self._plot.update(t_min, {'face': self.face_um, 'ch1_dtof': self.ch1_dtof_ns,
                                  'amp2': self.amp2_db, 'amp1': self.amp1_db,
                                  'T1': self.T1, 'T2': self.T2})
        self.status.emit(f'Stability {i + 1}/{self.params.n}: ' + self.rates_text())

    def rates(self):
        t_min = np.array(self.t_s) / 60.0
        return {'face_um_per_min': drift_fit(t_min, self.face_um),
                'ch1_ns_per_min': drift_fit(t_min, self.ch1_dtof_ns),
                'T1_C_per_min': drift_fit(t_min, self.T1),
                'T2_C_per_min': drift_fit(t_min, self.T2)}

    def rates_text(self):
        r = self.rates()

        def f(key, unit, dec):
            s, res = r[key]
            return 'n/a' if s != s else f'{s:+.{dec}f} {unit}/min (residual {res:.{dec}f})'
        return (f'face {f("face_um_per_min", "µm", 2)}; Ch1 ΔToF {f("ch1_ns_per_min", "ns", 2)}; '
                f'T1 {f("T1_C_per_min", "°C", 3)}')

    # -- end -------------------------------------------------------------------
    def _on_finished(self, status, text):
        if not self.running:
            return
        self.running = False
        self._close_temperature()
        n = len(self.t_s)
        rates = self.rates()
        self._dump.meta.update(
            result=f'{status}: {text}', n_measured=n, temp_every=self._every,
            temp_budget_s=TEMP_BUDGET_S, temp_read_s=self.temp_reads,
            temp_note=('temperature read on every point' if self._every == 1 else
                       f'temperature read every {self._every} points: a reading took more than '
                       f'{TEMP_BUDGET_S:g} s'),
            rates={k: {'slope_per_min': v[0], 'rms_residual': v[1]} for k, v in rates.items()})
        tail = ''
        if n:
            try:
                self.last_dump_path = self._dump.save(self._dump_dir)
                tail = f'\nSaved: {self.last_dump_path}'
            except Exception as e:
                self.warning.emit(f'Stability dump not saved: {e}')
        how = status if status in ('done', 'stopped') else 'error'
        self.status.emit(f'Stability test {status}: {n} of {self.params.n} measures. '
                         f'{self.rates_text()}{tail}')
        self.done.emit(how)


class StabilityGroup(QGroupBox):
    """Stability test controls, «Calibration» sub-tab."""

    def __init__(self, tool, sequencer, parent=None):
        super().__init__('Stability test (nothing moves)', parent)
        self._tool = tool
        form = QFormLayout(self)
        self._spin_n = QSpinBox()
        self._spin_n.setRange(2, 100000)
        self._spin_n.setValue(DEFAULT_N)
        self._spin_interval = QDoubleSpinBox()
        self._spin_interval.setRange(0.0, 3600.0)
        self._spin_interval.setDecimals(1)
        self._spin_interval.setValue(DEFAULT_INTERVAL_S)
        self._spin_interval.setSuffix(' s')
        self._spin_avg = QSpinBox()
        self._spin_avg.setRange(1, 10000)
        self._spin_avg.setValue(DEFAULT_AVG_N)
        form.addRow('Measures:', self._spin_n)
        form.addRow('Interval:', self._spin_interval)
        form.addRow('Averages:', self._spin_avg)
        self._lbl_estimate = QLabel()
        self._lbl_estimate.setWordWrap(True)
        self._lbl_estimate.setStyleSheet('font-weight: bold;')
        form.addRow(self._lbl_estimate)
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        self._btn_run = QPushButton('Run stability test')
        self._btn_stop = QPushButton('Stop')
        lay.addWidget(self._btn_run)
        lay.addWidget(self._btn_stop)
        form.addRow(row)
        self._lbl_warn = QLabel()
        self._lbl_warn.setWordWrap(True)
        self._lbl_warn.setStyleSheet('color: rgb(230, 120, 0);')
        form.addRow(self._lbl_warn)
        self._lbl_status = QLabel('Idle.')
        self._lbl_status.setWordWrap(True)
        form.addRow(self._lbl_status)

        self._btn_run.clicked.connect(self._on_run)
        self._btn_stop.clicked.connect(tool.stop)
        tool.status.connect(self._lbl_status.setText)
        tool.warning.connect(self._lbl_warn.setText)
        sequencer.state_changed.connect(self._on_seq_state)
        for w in (self._spin_n, self._spin_interval, self._spin_avg):
            w.valueChanged.connect(self._refresh_estimate)
        self._on_seq_state('idle')
        self._refresh_estimate()

    def params(self):
        return StabilityParams(n=self._spin_n.value(), interval_s=self._spin_interval.value(),
                               avg_n=self._spin_avg.value())

    def _refresh_estimate(self, *_):
        self._lbl_estimate.setText(self._tool.estimate(self.params())[1])

    def showEvent(self, event):
        self._refresh_estimate()
        super().showEvent(event)

    def _on_seq_state(self, state):
        self._btn_run.setEnabled(state == 'idle')
        self._btn_stop.setEnabled(self._tool.running)

    def _on_run(self):
        self._refresh_estimate()
        self._lbl_warn.setText('')
        reason = self._tool.run(self.params())
        if reason:
            self._lbl_status.setText(reason)
        self._btn_stop.setEnabled(self._tool.running)
