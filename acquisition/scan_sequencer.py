# -*- coding: utf-8 -*-
"""
scan_sequencer.py — generic event-driven sequencer for the scanner tools.
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See scanner_tab_spec.md section 3 and task_scanner_phase2.md section 4.

One sequencer serves focus, flatness and scans (phases 3-6). It lives in the
GUI thread and is driven by events, not by a loop or a thread of its own:

    request move   -> ScannerWorker (its own thread) moves, then emits point_moved
    point_moved    -> QTimer.singleShot(settle)
    settle expired -> acquire in the GUI thread, measure, emit point_done,
                      read temperature if asked, request the next point

The slow part (the move) happens in the worker, so the window never freezes;
the SeDaq is only ever touched from the GUI thread, exactly as before, so it
needs no lock. Pause and stop are honoured between points.

While a sequence runs the live-refresh timer must be off: the host passes
enter_exclusive / leave_exclusive (stop / start of that timer). The leave hook
runs on every way out (done, stop, error, pause) from a finally.
"""
import time
from contextlib import ExitStack, contextmanager

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

SEQUENCE_AXES = ('X', 'Y', 'Z')   # R needs its own stepwise handling: not sequenced here
NAN = float('nan')


@contextmanager
def preserved_reclen(sedaq, new_reclen=None):
    """
    SeDaq's RecLen is global state: SetRecLen fixes the record length for every
    later acquisition, live refresh included (tools/SeDaq.py). Optionally set
    `new_reclen` for the duration of the block and always put the previous
    value back afterwards, also when the block raises.
    """
    saved = sedaq.RecLen
    try:
        if new_reclen is not None and int(new_reclen) != saved:
            sedaq.SetRecLen(int(new_reclen))
        yield
    finally:
        if sedaq.RecLen != saved:
            sedaq.SetRecLen(saved)


class ScanSequencer(QObject):
    """
    Signals
    -------
    started(n)                     sequence accepted, n points
    progress(done, n, remaining_s) after every point; remaining_s is NaN until known
    point_done(i, coords, value)   coords: {axis: mm}, value: whatever measure_fn returned
    state_changed(state)           'running' | 'paused' | 'idle'
    message(text)                  non-fatal notices (e.g. temperature unavailable)
    finished(status, text)         status: 'done' | 'stopped' | 'error'
    """
    started = pyqtSignal(int)
    progress = pyqtSignal(int, int, float)
    point_done = pyqtSignal(int, object, object)
    state_changed = pyqtSignal(str)
    message = pyqtSignal(str)
    finished = pyqtSignal(str, str)

    def __init__(self, worker, sedaq, acquire_fn, *, coords_fn=None,
                 blocker_fn=None, temp_factory=None,
                 enter_exclusive=None, leave_exclusive=None, parent=None):
        """
        worker          ScannerWorker (only its enqueue() and signals are used)
        sedaq           SeDaq object, used to guard RecLen
        acquire_fn      acquire_fn(avg_n) -> (ch1, ch2), averaged full records
        coords_fn       () -> {axis: mm}, real coordinates after a move (default: targets)
        blocker_fn      () -> None or a reason string; the single place that decides
                        whether a sequence may start (connection, free-movement...)
        temp_factory    () -> object with getTemperatures() -> (T1, T2) and close(),
                        opened once per sequence. None: temperature stored as NaN.
        """
        super().__init__(parent)
        self._worker = worker
        self._sedaq = sedaq
        self._acquire = acquire_fn
        self._coords_fn = coords_fn
        self._blocker_fn = blocker_fn
        self._temp_factory = temp_factory
        self._enter_hook = enter_exclusive
        self._leave_hook = leave_exclusive

        self._active = False
        self._state = 'idle'
        self._exclusive_on = False
        self._token = 0
        self._stack = None
        self._arduino = None
        self._stop_requested = False
        self._stop_text = 'Stopped.'
        self.results = []          # (i, coords, value) of the last sequence
        self.temperatures = []     # dicts: point, time, T1, T2 (point: -1 start, i after point i, n end)

        worker.point_moved.connect(self._on_point_moved)
        worker.error.connect(self._on_worker_fault)
        worker.disconnected.connect(lambda: self._on_worker_fault('Scanner disconnected.'))

    # -- read-only view --------------------------------------------------------
    @property
    def active(self):
        return self._active

    @property
    def state(self):
        return self._state

    # -- control ---------------------------------------------------------------
    def start(self, positions, settle_ms, avg_n, measure_fn, *,
              temp_after=(), reclen=None, validate_fn=None):
        """
        positions   list of {axis: target_mm}, axes among X/Y/Z
        settle_ms   wait after each move before acquiring
        avg_n       captures averaged per point
        measure_fn  measure_fn(ch1, ch2) -> scalar or tuple
        temp_after  point indices after which the temperature is read (besides
                    the start and the end, which are always read)
        reclen      optional RecLen for the duration of the sequence
        validate_fn validate_fn(position) -> None or an error string, per position

        Returns None when the sequence started, otherwise the reason it could
        not (nothing has been touched in that case).
        """
        if self._active:
            return 'A sequence is already running.'
        if self._blocker_fn is not None:
            reason = self._blocker_fn()
            if reason:
                return reason
        positions = [dict(p) for p in positions]
        if not positions:
            raise ValueError('positions is empty')
        for pos in positions:
            for axis in pos:
                if axis not in SEQUENCE_AXES:
                    raise ValueError(f'axis {axis!r} cannot be sequenced (only {SEQUENCE_AXES})')
            if validate_fn is not None:
                err = validate_fn(pos)
                if err:
                    return err

        self._positions = positions
        self._settle_ms = max(0, int(settle_ms))
        self._avg_n = max(1, int(avg_n))
        self._measure = measure_fn
        self._temp_after = set(temp_after)
        self._index = 0
        self.results = []
        self.temperatures = []
        self._stop_requested = False
        self._stop_text = 'Stopped.'
        self._pause_requested = False
        self._t0 = time.monotonic()
        self._paused_total = 0.0
        self._pause_started = None
        self._active = True
        self._state = 'running'
        self._stack = ExitStack()
        self.started.emit(len(positions))
        self.state_changed.emit('running')
        try:
            self._enter_exclusive()
            self._stack.enter_context(preserved_reclen(self._sedaq, reclen))
            self._open_temperature()
            self._read_temperature(-1)
            self.progress.emit(0, len(positions), NAN)
            self._request_move()
        except Exception as e:
            self._finish('error', f'{type(e).__name__}: {e}', final_temperature=False)
        return None

    def pause(self):
        """Pause after the point in flight (checked between points)."""
        if self._active and self._state != 'paused':
            self._pause_requested = True

    def resume(self):
        if not self._active:
            return
        if self._state != 'paused':
            self._pause_requested = False      # pause not yet in effect: cancel it
            return
        self._guard(self._do_resume)

    def stop(self):
        """Stop after the point in flight (checked between points)."""
        self._request_stop('Stopped.')

    def abort(self):
        """The scanner STOP button was pressed: end the sequence."""
        self._request_stop('Aborted by scanner STOP.')

    def shutdown(self):
        """Host window closing: end now, no final temperature read."""
        if self._active:
            self._stop_requested = True
            self._finish('stopped', 'Window closed.', final_temperature=False)

    # -- events ----------------------------------------------------------------
    def _request_stop(self, text):
        if not self._active:
            return
        self._stop_text = text
        self._stop_requested = True
        if self._state == 'paused':
            self._guard(self._finish, 'stopped', text)

    def _on_worker_fault(self, text):
        if not self._active:
            return
        if self._stop_requested:    # a STOP interrupting a move also surfaces as a fault
            self._finish('stopped', self._stop_text, final_temperature=False)
        else:
            self._finish('error', text, final_temperature=False)

    def _on_point_moved(self, token, ok):
        if not self._active or token != self._token:
            return
        self._guard(self._handle_moved, token, ok)

    def _handle_moved(self, token, ok):
        if self._stop_requested:
            self._finish('stopped', self._stop_text)
        elif not ok:
            self._finish('error', 'The scanner did not reach the requested position.')
        else:
            QTimer.singleShot(self._settle_ms, lambda: self._on_settled(token))

    def _on_settled(self, token):
        if not self._active or token != self._token:
            return
        self._guard(self._handle_settled)

    def _handle_settled(self):
        if self._stop_requested:
            self._finish('stopped', self._stop_text)
            return
        i = self._index
        ch1, ch2 = self._acquire(self._avg_n)
        value = self._measure(ch1, ch2)
        coords = self._coords_fn() if self._coords_fn else dict(self._positions[i])
        self.results.append((i, coords, value))
        self._index = i + 1
        self.point_done.emit(i, coords, value)
        if i in self._temp_after:
            self._read_temperature(i)
        n = len(self._positions)
        done = self._index
        elapsed = time.monotonic() - self._t0 - self._paused_total
        self.progress.emit(done, n, elapsed / done * (n - done))
        self._advance()

    def _advance(self):
        if self._stop_requested:
            self._finish('stopped', self._stop_text)
        elif self._index >= len(self._positions):
            self._finish('done', f'Done: {len(self._positions)} points.')
        elif self._pause_requested:
            self._state = 'paused'
            self._pause_started = time.monotonic()
            self._leave_exclusive()      # live refresh runs while paused
            self.state_changed.emit('paused')
        else:
            self._request_move()

    def _do_resume(self):
        self._pause_requested = False
        self._paused_total += time.monotonic() - self._pause_started
        self._state = 'running'
        self._enter_exclusive()
        self.state_changed.emit('running')
        self._request_move()

    def _request_move(self):
        self._token += 1
        self._worker.enqueue(('move_point', self._token,
                              list(self._positions[self._index].items())))

    def _guard(self, fn, *args):
        """Every event handler runs through here: a failure ends the sequence
        (releasing the live refresh) instead of escaping into Qt."""
        try:
            fn(*args)
        except Exception as e:
            self._finish('error', f'{type(e).__name__}: {e}', final_temperature=False)

    # -- exclusive access to the SeDaq (live-refresh timer) --------------------
    def _enter_exclusive(self):
        if not self._exclusive_on:
            self._exclusive_on = True
            if self._enter_hook:
                self._enter_hook()

    def _leave_exclusive(self):
        if self._exclusive_on:
            self._exclusive_on = False
            if self._leave_hook:
                self._leave_hook()

    # -- temperature: one Arduino instance for the whole sequence --------------
    def _open_temperature(self):
        self._arduino = None
        err = 'no temperature source'
        if self._temp_factory is not None:
            try:
                self._arduino = self._temp_factory()
            except Exception as e:
                err = str(e)
        if self._arduino is None:
            # Never a modal dialog here: it would block the sequence.
            self.message.emit(f'Temperature unavailable ({err}); stored as NaN.')

    def _read_temperature(self, point):
        t1 = t2 = NAN
        if self._arduino is not None:
            try:
                r1, r2 = self._arduino.getTemperatures()
                t1 = NAN if r1 is None else float(r1)
                t2 = NAN if r2 is None else float(r2)
            except Exception as e:
                self.message.emit(f'Temperature read failed ({e}); stored as NaN.')
        self.temperatures.append({'point': point, 'time': time.time(), 'T1': t1, 'T2': t2})

    # -- end -------------------------------------------------------------------
    def _finish(self, status, text, final_temperature=True):
        if not self._active:
            return
        self._active = False
        self._token += 1            # any event still in flight is now stale
        try:
            self._cleanup(final_temperature and status != 'error')
        finally:
            self._leave_exclusive()
            self._state = 'idle'
            self.state_changed.emit('idle')
            self.finished.emit(status, text)

    def _cleanup(self, final_temperature):
        try:
            if final_temperature:      # NaN record when there is no Arduino
                self._read_temperature(len(self._positions))
        finally:
            try:
                if self._arduino is not None:
                    self._arduino.close()
            except Exception:
                pass
            self._arduino = None
            self._stack.close()     # restores RecLen
