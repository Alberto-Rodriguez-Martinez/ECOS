# -*- coding: utf-8 -*-
"""
temperature_logger.py — Continuous PT100 log of a scan session. No Qt.
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

Why: the Arduino (MAX31865, two 4-wire PT100) sends one 'T1<tab>T2' line every
200 ms. Reading it on demand (Arduino.getTemperatures, 3 lines per call) once
in a while leaves the lines piling up in the serial buffer, so a later call
returns OLD lines: the temperature of minutes ago taken as the current one.

TemperatureLogger: one thread owns the port of an already opened Arduino-like
object (its `ser`, e.g. serial.Serial at 115200 with timeout 0.2 s) and reads
EVERY line, stamping each with time.time() and time.monotonic() of the PC when
the line is complete. Nothing else reads the port while it runs: the event
readings of the scan (start, references, line ends, end) ask latest() for the
newest sample and its age. A sample older than stale_after_s (several firmware
periods) is reported as stale instead of being passed off as current.

Robustness: malformed lines (empty, truncated, non-numeric, nan) are dropped
and counted, never raised; a port error ends the thread with the failure
recorded (the series is then incomplete) and the scan goes on. stop() always
returns: a stop event, a join with timeout, then the port is closed (which also
unblocks a stuck read). The thread is a daemon: it never keeps the application
alive.
"""
from __future__ import annotations

import math
import threading
import time

import numpy as np

LINE_PERIOD_S = 0.2              # firmware period (control_temepratura_1_ino.ino, LOOP_MS)
STALE_AFTER_S = 5 * LINE_PERIOD_S
FIRST_SAMPLE_TIMEOUT_S = 1.0     # wait for the first line after the port is opened
JOIN_TIMEOUT_S = 2.0
MAX_LINE_BYTES = 256             # a "line" longer than this without a newline is garbage
KEEP_DISCARDED = 5               # examples of dropped lines kept for the metadata

# The probes of the set-up: what is known of them for sure (the rest is filled in by
# the user, never guessed). See probe_fields().
PROBE_ELEMENT = 'PT100'
PROBE_WIRES = 4
PROBE_CONVERTER = 'MAX31865'
PROBE_USER_KEYS = ('id', 'position', 'class')


def parse_line(raw):
    """(T1, T2) [°C] of one complete line, or None if it is not two finite numbers."""
    try:
        parts = raw.decode('ascii', errors='replace').split()
        if len(parts) != 2:
            return None
        t1, t2 = float(parts[0]), float(parts[1])
    except (ValueError, AttributeError):
        return None
    if not (math.isfinite(t1) and math.isfinite(t2)):
        return None
    return t1, t2


def probe_fields(given=None):
    """
    {'T1': {...}, 'T2': {...}}: per probe the user fields (id, position in the tank,
    class), empty strings when not filled in (never a default value), plus what is
    known of the set-up: PT100, 4 wires, MAX31865.
    """
    given = given or {}
    out = {}
    for name in ('T1', 'T2'):
        g = given.get(name) or {}
        d = {k: str(g.get(k, '') or '').strip() for k in PROBE_USER_KEYS}
        d.update(element=PROBE_ELEMENT, wires=PROBE_WIRES, converter=PROBE_CONVERTER)
        out[name] = d
    return out


class TemperatureLogger:
    """
        log = TemperatureLogger(arduino)   # arduino.ser.readline(), arduino.close()
        log.start(); log.wait_first(1.0)
        log.latest()   -> {'T1', 'T2', 'wall', 'mono', 'age_s', 'stale'}
        log.stop()     # joins the thread and closes the port (arduino.close())
        log.series()   -> arrays wall, mono, T1, T2 and the number of dropped lines
    """

    def __init__(self, source, stale_after_s=STALE_AFTER_S, wall_fn=time.time,
                 mono_fn=time.monotonic):
        self._source = source
        self._port = source.ser            # AttributeError: not a serial Arduino
        self.stale_after_s = float(stale_after_s)
        self._wall_fn, self._mono_fn = wall_fn, mono_fn
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._first = threading.Event()
        self._wall, self._mono, self._t1, self._t2 = [], [], [], []
        self.discarded = 0
        self.discarded_examples = []
        self.failure = None                # {'time': epoch, 'error': text} when the port failed
        self.stopped_cleanly = None        # after stop(): the thread ended within the timeout
        self._thread = None

    @property
    def baudrate(self):
        return getattr(self._port, 'baudrate', None)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        self._thread = threading.Thread(target=self._run, name='ecos-pt100-log', daemon=True)
        self._thread.start()

    def wait_first(self, timeout=FIRST_SAMPLE_TIMEOUT_S):
        """True once a first valid line has arrived (waits up to timeout s)."""
        return self._first.wait(timeout)

    def _run(self):
        buf = b''
        while not self._stop.is_set():
            try:
                raw = self._port.readline()
            except Exception as e:
                if not self._stop.is_set():        # closing the port on stop() is not a failure
                    with self._lock:
                        self.failure = {'time': self._wall_fn(),
                                        'error': f'{type(e).__name__}: {e}'}
                return
            if not raw:
                continue                           # timeout, nothing received
            buf += raw
            if not buf.endswith(b'\n'):
                if len(buf) > MAX_LINE_BYTES:      # no newline coming: garbage
                    self._drop(buf)
                    buf = b''
                continue                           # the rest of the line comes next
            line, buf = buf, b''
            wall, mono = self._wall_fn(), self._mono_fn()
            values = parse_line(line)
            if values is None:
                self._drop(line)
                continue
            with self._lock:
                self._wall.append(wall)
                self._mono.append(mono)
                self._t1.append(values[0])
                self._t2.append(values[1])
            self._first.set()

    def _drop(self, line):
        with self._lock:
            self.discarded += 1
            if len(self.discarded_examples) < KEEP_DISCARDED:
                self.discarded_examples.append(repr(bytes(line[:80])))

    def latest(self):
        """The newest sample and its age; T1/T2 are still the values when stale (the
        caller decides what a stale sample is worth). No sample yet: NaN, stale."""
        now = self._mono_fn()
        with self._lock:
            if not self._mono:
                nan = float('nan')
                return {'T1': nan, 'T2': nan, 'wall': nan, 'mono': nan, 'age_s': nan,
                        'stale': True}
            t1, t2, wall, mono = self._t1[-1], self._t2[-1], self._wall[-1], self._mono[-1]
        age = max(0.0, now - mono)
        return {'T1': t1, 'T2': t2, 'wall': wall, 'mono': mono, 'age_s': age,
                'stale': age > self.stale_after_s}

    def stop(self, timeout=JOIN_TIMEOUT_S):
        """Stop the thread and close the port. Always returns (True: clean stop)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        try:
            self._source.close()               # also unblocks a read stuck in the driver
        except Exception:
            pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout)
        self.stopped_cleanly = not self.running
        return self.stopped_cleanly

    def series(self):
        """Copies of the series (float64, arrival order) and the dropped-line count."""
        with self._lock:
            return {'wall': np.array(self._wall, dtype=np.float64),
                    'mono': np.array(self._mono, dtype=np.float64),
                    'T1': np.array(self._t1, dtype=np.float64),
                    'T2': np.array(self._t2, dtype=np.float64),
                    'discarded': int(self.discarded)}

    def meta(self):
        """Summary for meta.json."""
        s = self.series()
        mono = s['mono']
        with self._lock:
            failure = dict(self.failure) if self.failure else None
            examples = list(self.discarded_examples)
        return {
            'n_lines': int(len(mono)), 'n_discarded': s['discarded'],
            'discarded_examples': examples,
            'complete': failure is None, 'failure': failure,
            'stopped_cleanly': self.stopped_cleanly,
            'median_period_s': float(np.median(np.diff(mono))) if len(mono) > 1 else None,
            'first_wall': float(s['wall'][0]) if len(mono) else None,
            'last_wall': float(s['wall'][-1]) if len(mono) else None,
            'stale_after_s': self.stale_after_s,
            'nominal_period_s': LINE_PERIOD_S,
        }
