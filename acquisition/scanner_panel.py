# -*- coding: utf-8 -*-
"""
scanner_panel.py — Standalone panel for the XYZR scanner (SE SC-03-00), phase 1.
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

Phase 1 scope only (see task_scanner_phase1.md, scanner_tab_spec.md sections
1-3, 5.1-5.3, 6, later fixes in task_scanner_phase1_fixes.md and
task_scanner_jog.md, and task_scanner_freemode.md for the free-movement mode
and the port-list wording): worker thread + command queue, status, session
(beam axis, PE side, limits, speed), manual movement (per-axis jog + Go/Go to
origin), free-movement mode (unlimited signed jog, no GUI/firmware limit
protection) and STOP. Phase 2 (task_scanner_phase2.md): the panel is also
embedded as a tab of ecos_gui.py (shutdown() is then called by the host window).
No focus/flatness/scan tools yet (task_scanner_freemode.md point 4: those must
gate on ScannerPanel.is_free_movement_active() once they exist).

Run standalone:
    python acquisition/scanner_panel.py          (real hardware)
    python acquisition/scanner_panel.py --sim     (simulator, no hardware needed)

Requires: numpy, pyserial, PyQt5 (no scipy, no pyqtgraph: works in the 32-bit .venv).
"""
import argparse
import json
import os
import queue
import re
import sys
import threading
import time

os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, '..'))
_HW_SCANNER_DIR = os.path.join(_REPO_ROOT, 'hardware', 'scanner')
# The driver is imported by package path (hardware.scanner.Scanner), never as a
# bare `Scanner`: tools/Scanner.py is an unrelated old driver, and with both
# directories on sys.path the order would silently decide which one loads.
# Appended (not inserted) so it cannot shadow anything else.
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)

import serial
import serial.tools.list_ports

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QComboBox, QPushButton, QMessageBox,
    QScrollArea, QFrame, QCheckBox,
)

from hardware.scanner.Scanner import Scanner
from hardware.scanner.sim_scanner import FakeSerial

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BAUDRATE = 19200
PORT_TIMEOUT = 0.1  # s, matches Scanner's own default

# Verified format (scanner_tab_spec.md section 5.1): 'OK' + axis + 6 digits + CR.
IDENTITY_CMD = b'SCX\r'
IDENTITY_REPLY_RE = re.compile(rb'^OKX\d{6}\r$')
IDENTITY_READ_TIMEOUT = 1.0  # s, generous upper bound while polling for the reply

SIM_PORT_LABEL = 'Simulator'

SESSION_FILE = os.path.join(_HW_SCANNER_DIR, 'scanner_session.json')
# Read-only lookup. This is another app's last-used port for its own (Arduino
# PT100) device, kept only as a hint that a serial device other than the
# scanner may be present there — COM numbers can be reassigned by Windows, so
# this is never treated as proof of what is actually on that port today (task
# task_scanner_freemode.md point 3). Never used to preselect a port.
_ECOS_GUI_SESSION_FILE = os.path.join(_THIS_DIR, 'ecos_gui_session.json')

AXES = ('X', 'Y', 'Z', 'R')
ROLE_ORDER = ('beam', 'lateral', 'Z', 'R')
ROLE_LABELS = {'beam': 'Beam', 'lateral': 'Lateral', 'Z': 'Z', 'R': 'R'}
GO_TO_ORIGIN_AXIS_ORDER = ('R', 'Z', 'X', 'Y')  # fixed physical order, see fixes task point 5

# Hardware fact (verified): after a controller power cut every axis limit
# resets to 10000 steps in firmware, i.e. 100/100/50 mm and 18000 deg
# (Scanner's uStepX/Y/Z/R). Used only to DETECT that a reset happened, by
# comparing it against what Scanner reports right after connecting.
HARDWARE_RESET_LIMITS_MM = {'X': 100.0, 'Y': 100.0, 'Z': 50.0, 'R': 18000.0}
HARDWARE_RESET_LIMITS_TOL = {'X': 0.05, 'Y': 0.05, 'Z': 0.05, 'R': 5.0}

# GUI default limits: used for a brand-new session (no scanner_session.json
# yet) and, per task_scanner_phase1_fixes.md point 3, as what is offered
# after a detected reset when there is no saved session to resend. R
# defaults to 360 deg (one full turn), not the firmware's post-reset
# 18000 deg.
SESSION_DEFAULT_LIMITS_MM = {'X': 100.0, 'Y': 100.0, 'Z': 50.0, 'R': 360.0}


# R's mechanical resolution (1.8 deg/step). Read from Scanner's own class
# attribute (see Scanner.py's ADD 2026-09) instead of hand-writing the
# number here, so it can't silently drift from Scanner.py — and without
# instantiating a Scanner (which opens a port) just to read one attribute.
R_STEP_UNIT = Scanner.uStepR

# Steps in one full revolution (360 deg / uStepR = 200). Verified on hardware
# (23-24/09/2026): R's physical counter wraps to 0 past this point going up,
# but a relative step that would cross 0 going down is rejected instead
# (task_scanner_r_zerocross.md).
R_STEPS_PER_REV = round(360.0 / R_STEP_UNIT)

# Default per-axis jog amount (task_scanner_jog.md point 2): X/Y 1.0 mm,
# Z 0.5 mm, R one resolution unit (1.8 deg).
JOG_DEFAULTS_MM = {'X': 1.0, 'Y': 1.0, 'Z': 0.5, 'R': R_STEP_UNIT}

# Verified on hardware (23/09/2026): SPR (speed) has no effect on the R axis
# at all. Speed is therefore only tracked/shown/applied for X/Y/Z — R has no
# Speed field and 'Apply speeds' never sends SPR (task_scanner_r_axis.md
# point 3).
SPEED_AXES = ('X', 'Y', 'Z')

# Verified on hardware (23/09/2026): a single large continuous R move loses
# steps once the sample holder is mounted, but loose 1.8 deg (R_STEP_UNIT)
# orders do not. So every R move (jog, 'Move to', 'Go to origin') is sent as
# a sequence of independent single-step commands by default
# (task_scanner_r_axis.md point 1).
R_STEP_PAUSE_MS_DEFAULT = 100
R_STEP_PAUSE_MS_RANGE = (0, 2000)

# A sequenced move counts as reached when the axis reads back within this of
# its target (X/Y resolve 0.01 mm, Z 0.005 mm).
POINT_TOLERANCE_MM = 0.05


# ===========================================================================
#  Helpers: beam/lateral <-> X/Y translation (spec 2: "la traduccion a X/Y
#  ocurre en una sola funcion")
# ===========================================================================
def lateral_axis_of(beam_axis):
    return 'Y' if beam_axis == 'X' else 'X'


def role_axis_map(beam_axis):
    """Role ('beam'/'lateral'/'Z'/'R') -> real axis letter, for a given beam axis."""
    return {'beam': beam_axis, 'lateral': lateral_axis_of(beam_axis), 'Z': 'Z', 'R': 'R'}


def fmt_pos(axis, value):
    """Position display, rounded to roughly the axis' mechanical resolution."""
    if axis == 'R':
        return f'{value:.1f}°'
    if axis == 'Z':
        return f'{value:.3f} mm'
    return f'{value:.2f} mm'


def round_r_jog(value):
    """R jog field: nearest multiple of R_STEP_UNIT, at least one unit (1.8 deg)."""
    n = max(1, round(value / R_STEP_UNIT))
    return round(n * R_STEP_UNIT, 6)


def round_r_target_circular(value):
    """
    R 'Move to' target: normalized to [0, 360) and rounded to the nearest
    multiple of R_STEP_UNIT. R's position counter is circular (verified on
    hardware, 23/09/2026), so a target is always a point on the circle, not
    an absolute step count (task_scanner_r_axis.md point 2).
    """
    n = round((value % 360.0) / R_STEP_UNIT)
    return round(n * R_STEP_UNIT, 6) % 360.0


def r_shortest_path(current_deg, target_deg):
    """
    Shortest signed path from current_deg to target_deg (both expected in
    [0, 360)), quantized to R_STEP_UNIT.

    Returns (signed_degrees, n_steps): n_steps is the non-negative number of
    R_STEP_UNIT commands to send, and signed_degrees = n_steps * R_STEP_UNIT
    with the sign giving the direction (>0 = '+', <0 = '-'). Used to move R
    with diffMoveR/unlimitedDiffMoveR instead of an absolute SM target, which
    would not respect the circular counter (task_scanner_r_axis.md point 2).
    """
    diff = (target_deg - current_deg + 180.0) % 360.0 - 180.0
    n_steps = int(round(abs(diff) / R_STEP_UNIT))
    sign = 1.0 if diff >= 0 else -1.0
    return sign * n_steps * R_STEP_UNIT, n_steps


# ===========================================================================
#  _LockingSerialProxy
# ===========================================================================
class _LockingSerialProxy:
    """
    Thin proxy in front of a serial-like object (serial.Serial or FakeSerial)
    that serializes .write() calls with a lock. Everything else (read,
    isOpen, open, close, flush*, power_cycle in --sim, ...) passes through
    unchanged.

    This is the "lock propio del panel" from task_scanner_phase1.md's STOP
    section: the panel creates the lock and passes it in here; the worker
    thread's normal commands go through Scanner -> this proxy's write(), and
    the STOP button (GUI thread) writes 'SSF\\r' directly to the very same
    proxy instance, bypassing the worker's queue but never the lock. That
    keeps a STOP write from interleaving, at the byte level, with whatever
    the worker is writing at that moment.
    """

    def __init__(self, ser, lock):
        self._ser = ser
        self._lock = lock

    def write(self, data):
        with self._lock:
            return self._ser.write(data)

    def __getattr__(self, name):
        return getattr(self._ser, name)


# ===========================================================================
#  ScannerWorker — the only object that calls Scanner methods
# ===========================================================================
class ScannerWorker(QThread):
    """
    Owns the serial port (through Scanner) and processes a FIFO command
    queue. All slow/blocking calls into Scanner happen here, never on the
    GUI thread — the one documented exception is the STOP button, which
    writes directly to the shared `ser` proxy (see ScannerPanel._on_stop_clicked
    and _LockingSerialProxy above).
    """
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    moved = pyqtSignal(tuple)     # (X, Y, Z, R) in mm/mm/mm/deg
    # task_scanner_r_axis.md point 5: single-axis move result (axis, value),
    # cheaper than `moved` when only one axis actually moved — avoids
    # rereading the other three via getCoords().
    moved_axis = pyqtSignal(str, float)
    limits = pyqtSignal(tuple)    # (Xlim, Ylim, Zlim, Rlim)
    busy = pyqtSignal(bool)
    error = pyqtSignal(str)
    message = pyqtSignal(str)
    # Phase 2: result of a 'move_point' command, (token, reached). The token is
    # the caller's own, so a sequencer can ignore answers to stale requests.
    point_moved = pyqtSignal(int, bool)

    def __init__(self, port_lock, parent=None):
        super().__init__(parent)
        self._port_lock = port_lock
        self._queue = queue.Queue()
        self._running = True
        self.scanner = None  # Scanner instance once connected, else None
        self.ser = None      # shared _LockingSerialProxy, also used by STOP
        # Fix 5 (go-to-origin): set by the GUI thread's STOP handler so a
        # multi-axis sequence stops after the axis being interrupted instead
        # of moving on to the next one.
        self._abort_sequence = threading.Event()

    def enqueue(self, cmd):
        self._queue.put(cmd)

    def request_sequence_abort(self):
        self._abort_sequence.set()

    def stop_thread(self):
        self._running = False
        self._queue.put(('_quit',))

    def run(self):
        while self._running:
            cmd = self._queue.get()
            try:
                self._dispatch(cmd)
            except Exception as e:
                self.error.emit(f'Scanner worker error: {e}')
                self.busy.emit(False)

    def _dispatch(self, cmd):
        op = cmd[0]
        if op == '_quit':
            return
        elif op == 'connect':
            self._do_connect(*cmd[1:])
        elif op == 'disconnect':
            self._do_disconnect()
        elif op == 'read_status':
            self._emit_status()
        elif op == 'read_limits':
            self._emit_limits()
        elif op == 'move_axis':
            self._do_move_axis(*cmd[1:])
        elif op == 'jog_unlimited':
            self._do_jog_unlimited(*cmd[1:])
        elif op == 'move_sequence':
            self._do_move_sequence(cmd[1])
        elif op == 'move_point':
            self._do_move_point(*cmd[1:])
        elif op == 'set_limits':
            self._do_set_limits(cmd[1])
        elif op == 'set_zero':
            self._do_set_zero(cmd[1])
        elif op == 'set_speeds':
            self._do_set_speeds(cmd[1])
        elif op == 'power_cycle_sim':
            self._do_power_cycle_sim()

    # -- connection ---------------------------------------------------------
    def _do_connect(self, port_name, is_sim):
        self.busy.emit(True)
        try:
            if is_sim:
                raw = FakeSerial(port=SIM_PORT_LABEL, timeout=PORT_TIMEOUT)
            else:
                try:
                    raw = serial.Serial(port_name, BAUDRATE, timeout=PORT_TIMEOUT)
                except Exception as e:
                    self.error.emit(f'Could not open {port_name}: {e}')
                    return

            try:
                raw.reset_input_buffer()
                raw.reset_output_buffer()
            except Exception:
                pass

            # Identity check *before* handing the port to Scanner (spec 5.1):
            # only a real scanner should reply 'OKX' + 6 digits + CR to 'SCX'.
            raw.write(IDENTITY_CMD)
            reply = self._read_identity_reply(raw)
            if not IDENTITY_REPLY_RE.match(reply):
                label = SIM_PORT_LABEL if is_sim else port_name
                self.error.emit(f'The device on {label} is not the scanner.')
                try:
                    raw.close()
                except Exception:
                    pass
                return

            # Verification passed: reuse this same connection (wrapped so the
            # panel's STOP button can share it) instead of opening the port
            # twice.
            self.ser = _LockingSerialProxy(raw, self._port_lock)
            self.scanner = Scanner(port=port_name, ser=self.ser)

            label = SIM_PORT_LABEL if is_sim else port_name
            self.connected.emit(f'Connected: scanner on {label}')
            self.limits.emit(self.scanner.getLimits())
            self.moved.emit(self.scanner.getCoords())
        finally:
            self.busy.emit(False)

    @staticmethod
    def _read_identity_reply(raw, timeout=IDENTITY_READ_TIMEOUT):
        t0 = time.time()
        data = b''
        while len(data) < 10 and time.time() - t0 < timeout:
            chunk = raw.read(10 - len(data))
            if chunk:
                data += chunk
            else:
                time.sleep(0.05)
        return data

    def _do_disconnect(self):
        if self.scanner is not None:
            try:
                self.scanner.close()
            except Exception:
                pass
        self.scanner = None
        self.ser = None
        self.disconnected.emit()

    # -- status / limits ------------------------------------------------
    def _emit_status(self):
        if self.scanner is None:
            return
        self.busy.emit(True)
        try:
            self.moved.emit(self.scanner.getCoords())
        finally:
            self.busy.emit(False)

    def _emit_limits(self):
        if self.scanner is None:
            return
        self.limits.emit(self.scanner.getLimits())

    # -- movement ---------------------------------------------------------
    #
    # task_scanner_r_axis.md point 5 (jog latency): a jog is a single-axis
    # move, so re-reading all four coordinates via getCoords() after one
    # (3 extra blocking SC reads, each with Scanner.write's own >=0.1 s
    # settle) is wasted time; _do_move_axis/_do_jog_unlimited below only
    # re-read the axis that actually moved. Busy is also released as soon as
    # the move's own OK arrives, before that single readback, so the
    # buttons accept the next click sooner. What is left (Scanner.write's
    # 0.1 s sleep-then-poll around the move command itself, and one more
    # such round trip for the readback) is inherent to the serial protocol
    # and is not forced further, since Scanner.py is out of scope here.
    def _do_move_axis(self, axis, value):
        if self.scanner is None:
            return
        self.busy.emit(True)
        try:
            self.scanner.moveAxis(axis, value)
        finally:
            self.busy.emit(False)
        if self.scanner is not None:
            self.moved_axis.emit(axis, self.scanner.getAxis(axis))

    def _do_jog_unlimited(self, axis, value):
        """
        Free-movement mode (task_scanner_freemode.md point 4): unlimited
        signed relative move (SN / unlimitedDiffMoveAxis). The sign of
        `value` sets the direction (verified on hardware 23/09/2026); the
        firmware's own limit protection is bypassed, so this can take the
        axis negative. The panel only sends this while free-movement mode is
        active (see ScannerPanel._make_jog_handler).
        """
        if self.scanner is None:
            return
        self.busy.emit(True)
        try:
            self.scanner.unlimitedDiffMoveAxis(axis, value)
        finally:
            self.busy.emit(False)
        if self.scanner is not None:
            self.moved_axis.emit(axis, self.scanner.getAxis(axis))

    def _do_move_sequence(self, steps):
        """
        Fix 5 (go-to-origin) + task_scanner_r_axis.md point 1: runs a list of
        move steps in order, one at a time. Each step is either:
          ('axis', axis, target)  -- a single absolute SM move (X/Y/Z), or
          ('r', total_degrees, stepwise, pause_ms, unlimited)  -- R's own
              relative, circular-aware sequence (see _run_r_step_sequence);
              R is never moved with an absolute SM target.
        STOP (see ScannerPanel._on_stop_clicked) sets _abort_sequence, which
        is checked both between steps here and between R's own sub-steps
        inside _run_r_step_sequence, so a single STOP press aborts the whole
        sequence, not just whichever step (or R sub-step) is running.
        """
        if self.scanner is None:
            return
        self._abort_sequence.clear()
        self.busy.emit(True)
        try:
            for step in steps:
                if self._abort_sequence.is_set():
                    break
                if step[0] == 'axis':
                    _, axis, target = step
                    self.scanner.moveAxis(axis, target)
                    self.moved_axis.emit(axis, self.scanner.getAxis(axis))
                else:  # 'r'
                    _, total_degrees, stepwise, pause_ms, unlimited = step
                    self._run_r_step_sequence(total_degrees, stepwise, pause_ms, unlimited)
                if self._abort_sequence.is_set():
                    break
        finally:
            self.busy.emit(False)

    def _do_move_point(self, token, targets):
        """
        Phase 2 (sequencer): move X/Y/Z axes to absolute targets, in order,
        [(axis, mm), ...], then answer with point_moved(token, reached).
        `reached` is True only if every axis read back within
        POINT_TOLERANCE_MM of its target: Scanner.moveAxis only prints a
        warning when the firmware rejects a move (ER), it does not raise, so
        the readback is what tells a rejected or interrupted move apart. A
        STOP (request_sequence_abort) ends it quietly with reached=False.
        """
        reached = False
        try:
            if self.scanner is None:
                raise RuntimeError('scanner not connected')
            self._abort_sequence.clear()
            self.busy.emit(True)
            try:
                for axis, target in targets:
                    if self._abort_sequence.is_set():
                        break
                    self.scanner.moveAxis(axis, target)
                    pos = self.scanner.getAxis(axis)
                    self.moved_axis.emit(axis, pos)
                    if self._abort_sequence.is_set():
                        break
                    if abs(pos - target) > POINT_TOLERANCE_MM:
                        raise RuntimeError(
                            f'{axis} is at {pos:g}, target {target:g} '
                            '(move rejected or interrupted)')
                else:
                    reached = True
            finally:
                self.busy.emit(False)
        except Exception as e:
            self.error.emit(f'Move failed: {e}')
        finally:
            self.point_moved.emit(token, reached)

    def _run_r_step_sequence(self, total_degrees, stepwise, pause_ms, unlimited):
        """
        task_scanner_r_axis.md point 1: moves R by `total_degrees` (signed,
        relative) using diffMoveR, or unlimitedDiffMoveR in free-movement
        mode. When `stepwise` is True (the default, from the 'Mover R paso a
        paso' checkbox), it is split into independent R_STEP_UNIT (1.8 deg)
        commands with `pause_ms` between them -- verified on hardware
        23/09/2026: one large continuous move loses steps once the sample
        holder is mounted, but loose 1.8 deg orders do not (task_scanner_r_
        axis.md); 24/09/2026 confirmed this also holds WITH the holder
        mounted. When False, it is sent as a single command (only safe
        without the holder mounted; the zero-crossing handling below does
        not apply to it, see task_scanner_r_zerocross.md).

        task_scanner_r_zerocross.md point 1: R's counter is circular only
        going up (it wraps to 0 on its own past R_STEPS_PER_REV); a
        DOWNWARD relative step that would cross 0 is rejected by the
        firmware instead. So, for a downward limited move (not
        unlimitedDiffMoveR, which is verified to allow negative positions
        outright), this tracks the running position and, exactly when it
        reaches step 0, sends setAxis('R', 360) first -- a raw SAR that only
        redefines the counter to one full turn, verified not to move
        anything -- before the next (now valid) negative step. Progress
        numbering is not reset at the crossing. Point 2 (upward crossing at
        the limit) was checked in the simulator and does not need the
        symmetric fix: with R's default limit at exactly one revolution,
        the boundary step (199 -> 200) is not rejected (the check is a
        strict '>'), so it wraps via the ordinary circular behaviour (see
        test_sim_scanner.TestRZeroCrossing).

        Reads R's real position back exactly once, at the end (or as soon
        as _abort_sequence is set), never after every sub-step.
        """
        move_one = self.scanner.unlimitedDiffMoveR if unlimited else self.scanner.diffMoveR
        try:
            if not stepwise:
                if abs(total_degrees) > 1e-9:
                    move_one(total_degrees)
                return
            sign = 1.0 if total_degrees >= 0 else -1.0
            n_steps = int(round(abs(total_degrees) / R_STEP_UNIT))
            if n_steps == 0:
                return

            # Only a limited downward move can hit the "crossing 0" rejection.
            track_crossing = sign < 0 and not unlimited
            if track_crossing:
                pos_steps = int(round(self.scanner.getAxis('R') / R_STEP_UNIT)) % R_STEPS_PER_REV

            for i in range(1, n_steps + 1):
                if self._abort_sequence.is_set():
                    break
                if track_crossing and pos_steps == 0:
                    # About to cross 0 going down: redefine the counter to
                    # one full turn first (point 1). Point 3 (Reserva): call
                    # Scanner.write directly, not setAxis, so an unexpected
                    # ER can be detected and the sequence aborted instead of
                    # silently continuing with a stale/wrong counter.
                    reply = self.scanner.write(f'SAR{R_STEPS_PER_REV}')
                    if reply[:2] != b'OK':
                        self.message.emit(
                            f'R: SAR de cruce de cero rechazado ({reply!r}); secuencia abortada.'
                        )
                        break
                    pos_steps = R_STEPS_PER_REV
                    if self._abort_sequence.is_set():
                        break
                move_one(sign * R_STEP_UNIT)
                if track_crossing:
                    pos_steps -= 1
                self.message.emit(f'R: paso {i}/{n_steps}')
                if i < n_steps and pause_ms > 0 and not self._abort_sequence.is_set():
                    time.sleep(pause_ms / 1000.0)
        finally:
            if self.scanner is not None:
                self.moved_axis.emit('R', self.scanner.getAxis('R'))

    # -- session: limits / zero / set-value / speeds -----------------------
    def _do_set_limits(self, limits_dict):
        if self.scanner is None:
            return
        self.busy.emit(True)
        try:
            for axis, value in limits_dict.items():
                self.scanner.setAxisLimit(axis, value)
            self.limits.emit(self.scanner.getLimits())
        finally:
            self.busy.emit(False)

    def _do_set_zero(self, axes_list):
        if self.scanner is None:
            return
        self.busy.emit(True)
        try:
            for axis in axes_list:
                self.scanner.setAxis(axis, 0)
            self.moved.emit(self.scanner.getCoords())
        finally:
            self.busy.emit(False)

    def _do_set_speeds(self, speeds_dict):
        if self.scanner is None:
            return
        self.busy.emit(True)
        try:
            for axis, value in speeds_dict.items():
                self.scanner.setAxisSpeed(axis, value)
            self.message.emit('Speeds applied.')
        finally:
            self.busy.emit(False)

    # -- debug (only reachable from the GUI in --sim mode) ------------------
    def _do_power_cycle_sim(self):
        if self.ser is not None and hasattr(self.ser, 'power_cycle'):
            self.ser.power_cycle()
            self.message.emit('Simulated power cycle done. Reconnect to see the reset warning.')


# ===========================================================================
#  ScannerPanel — QWidget, runnable standalone or embeddable as a tab (phase 2)
# ===========================================================================
class ScannerPanel(QWidget):
    # Emitted first thing when the panel's STOP is pressed, so a sequencer can
    # end its sequence (the worker only aborts its own multi-step moves).
    stop_pressed = pyqtSignal()

    def __init__(self, use_sim=False, parent=None):
        super().__init__(parent)
        self._use_sim = use_sim
        self.setWindowTitle('ECOS Scanner Panel' + (' (simulator)' if use_sim else ''))
        self.resize(460, 900)

        self._connected = False
        self._busy = False
        self._shut_down = False
        # Phase 2: a sequence (see scan_sequencer.py) is running. Locks the
        # manual movement, the session controls and disconnecting; STOP stays.
        self._seq_active = False
        self._seq_text = ''
        # Phase 1 gate (task_scanner_phase1.md section "Conexion"): until both
        # post-connect warnings are acknowledged, only manual movement + STOP
        # are enabled.
        self._awaiting_ack = False
        self._pending_post_connect_check = False

        self._coords = {ax: 0.0 for ax in AXES}

        self._session = self._load_session_from_disk()
        beam = self._session.get('beam_axis', 'Y')
        self._role_axis = role_axis_map(beam)
        self._pe_side = self._session.get('pe_side', 'origin')
        self._limits = {ax: float(self._session.get('limits', {}).get(ax, SESSION_DEFAULT_LIMITS_MM[ax]))
                         for ax in AXES}
        # task_scanner_jog.md: 'jog' replaces the old 'step' session key. An
        # old JSON with 'step' still loads (used as the initial jog); the
        # next save writes only 'jog'.
        jog_source = self._session.get('jog', self._session.get('steps', {}))
        self._jogs = {ax: float(jog_source.get(ax, JOG_DEFAULTS_MM[ax])) for ax in AXES}
        # SPR has no effect on R (verified 23/09/2026): only X/Y/Z carry a
        # speed. An old session JSON with a speeds.R value is simply never
        # read here, so it is ignored without error (task_scanner_r_axis.md
        # point 3).
        self._speeds = {ax: int(self._session.get('speeds', {}).get(ax, 100))
                         for ax in SPEED_AXES}

        # task_scanner_r_axis.md point 1: R-stepwise mode (default on) and
        # the pause between its 1.8 deg sub-steps, both persisted to the
        # session.
        self._r_stepwise = bool(self._session.get('r_stepwise', True))
        self._r_step_pause_ms = self._clamp_r_pause(
            self._session.get('r_step_pause_ms', R_STEP_PAUSE_MS_DEFAULT))

        self._movement_widgets = []
        # Subset of movement controls that only make sense as absolute
        # targets (Move to / Go to origin): disabled in free-movement mode
        # on top of the normal connected/busy gating (see _update_enabled_state).
        self._goto_widgets = []
        self._session_widgets = []

        # Free-movement mode (task_scanner_freemode.md point 4): off by
        # default, never persisted to the session file, forced off on
        # disconnect (see _on_disconnected). is_free_movement_active() is the
        # single point later phases (focus, flatness, scans) must check
        # before starting.
        self._free_movement = False

        # Port list: which port (if any) has actually had its scanner
        # identity verified this run (see _on_connected), and which port a
        # connect attempt is currently in flight for (see _on_connect_clicked).
        self._verified_scanner_port = None
        self._pending_connect_port = None

        self._port_lock = threading.Lock()
        self._worker = ScannerWorker(self._port_lock)
        self._worker.connected.connect(self._on_connected)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.moved.connect(self._on_moved)
        self._worker.moved_axis.connect(self._on_moved_axis)
        self._worker.limits.connect(self._on_limits)
        self._worker.busy.connect(self._on_busy)
        self._worker.error.connect(self._on_message)
        self._worker.message.connect(self._on_message)
        self._worker.start()

        self._build_ui()
        self._populate_ports()
        self._refresh_role_label_texts()
        self._refresh_position_labels()
        self._refresh_all_role_limit_fields()
        self._refresh_role_speed_fields()
        self._refresh_role_jog_fields()
        self._update_enabled_state()

    # =======================================================================
    #  UI construction
    # =======================================================================
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        # Free-movement banner: kept outside the scroll area, so it stays
        # visible ("bien visible en el panel") no matter where the user has
        # scrolled to (task_scanner_freemode.md point 4).
        self._lbl_free_banner = QLabel('MOVIMIENTO LIBRE — sin protección de límites')
        self._lbl_free_banner.setAlignment(Qt.AlignCenter)
        self._lbl_free_banner.setStyleSheet(
            'background-color: #b00020; color: white; font-weight: bold; '
            'font-size: 13px; padding: 6px;'
        )
        self._lbl_free_banner.setVisible(False)
        outer.addWidget(self._lbl_free_banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setSpacing(6)
        self._content_layout = layout

        layout.addWidget(self._build_status_group())
        layout.addWidget(self._build_session_group())
        layout.addWidget(self._build_movement_group())
        layout.addStretch()

    # -- Status (spec 5.1) ---------------------------------------------------
    def _build_status_group(self):
        group = QGroupBox('Status')
        layout = QVBoxLayout(group)

        # Port selection
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel('Port:'))
        self._cmb_port = QComboBox()
        port_row.addWidget(self._cmb_port, 1)
        self._btn_refresh = QPushButton('↺')
        self._btn_refresh.setFixedWidth(28)
        self._btn_refresh.setToolTip('Refresh port list')
        self._btn_refresh.clicked.connect(self._populate_ports)
        port_row.addWidget(self._btn_refresh)
        layout.addLayout(port_row)

        # Connect / Disconnect
        conn_row = QHBoxLayout()
        self._btn_connect = QPushButton('Connect')
        self._btn_connect.clicked.connect(self._on_connect_clicked)
        conn_row.addWidget(self._btn_connect)
        self._btn_disconnect = QPushButton('Disconnect')
        self._btn_disconnect.clicked.connect(self._on_disconnect_clicked)
        conn_row.addWidget(self._btn_disconnect)
        layout.addLayout(conn_row)

        # Result message, always visible
        self._lbl_result = QLabel('Not connected.')
        self._lbl_result.setWordWrap(True)
        layout.addWidget(self._lbl_result)

        # Position display, one row per role
        pos_grid = QGridLayout()
        self._lbl_role_name = {}
        self._lbl_pos = {}
        for i, role in enumerate(ROLE_ORDER):
            lbl_name = QLabel()
            lbl_name.setStyleSheet('font-weight: bold;')
            lbl_pos = QLabel('—')
            self._lbl_role_name[role] = lbl_name
            self._lbl_pos[role] = lbl_pos
            pos_grid.addWidget(lbl_name, i, 0)
            pos_grid.addWidget(lbl_pos, i, 1)
        layout.addLayout(pos_grid)

        # STOP: always enabled, never disabled by busy/ack state
        self._btn_stop = QPushButton('STOP')
        self._btn_stop.setStyleSheet(
            'background-color: #b00020; color: white; font-weight: bold; font-size: 16px; padding: 8px;'
        )
        self._btn_stop.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self._btn_stop)

        self._lbl_state = QLabel('Disconnected')
        layout.addWidget(self._lbl_state)

        if self._use_sim:
            btn_power_cycle = QPushButton('Simulate power cycle (debug)')
            btn_power_cycle.clicked.connect(
                lambda: self._worker.enqueue(('power_cycle_sim',))
            )
            layout.addWidget(btn_power_cycle)

        return group

    # -- Session (spec 5.2) --------------------------------------------------
    def _build_session_group(self):
        group = QGroupBox('Session')
        layout = QVBoxLayout(group)

        cfg_row = QHBoxLayout()
        cfg_row.addWidget(QLabel('Beam axis:'))
        self._cmb_beam_axis = QComboBox()
        self._cmb_beam_axis.addItems(['X', 'Y'])
        self._cmb_beam_axis.setCurrentText(self._role_axis['beam'])
        self._cmb_beam_axis.currentTextChanged.connect(self._on_beam_axis_changed)
        cfg_row.addWidget(self._cmb_beam_axis)
        cfg_row.addWidget(QLabel('PE side:'))
        self._cmb_pe_side = QComboBox()
        self._cmb_pe_side.addItems(['Origin', 'Max'])
        self._cmb_pe_side.setCurrentIndex(0 if self._pe_side == 'origin' else 1)
        self._cmb_pe_side.currentIndexChanged.connect(self._on_pe_side_changed)
        cfg_row.addWidget(self._cmb_pe_side)
        layout.addLayout(cfg_row)
        self._session_widgets += [self._cmb_beam_axis, self._cmb_pe_side]

        grid = QGridLayout()
        # Column layout (see the per-role loop below): 0 axis name, 1 limit
        # edit, 2 apply-limit button, 3 speed edit, 4 zero button. Placed
        # explicitly, column by column, rather than via a flat list that is
        # easy to get out of sync with the widgets below (that was the
        # phase-1 header-alignment bug). task_scanner_jog.md removed the old
        # Step and Set-value columns (Step moved to Manual movement as Jog;
        # Set-value dropped).
        grid.addWidget(QLabel('<b>Axis</b>'), 0, 0)
        grid.addWidget(QLabel('<b>Limit (mm / °)</b>'), 0, 1)
        grid.addWidget(QLabel('<b>Speed</b>'), 0, 3)
        grid.addWidget(QLabel('<b>Zero</b>'), 0, 4)

        self._edit_limit = {}
        self._edit_speed = {}

        for r, role in enumerate(ROLE_ORDER, start=1):
            grid.addWidget(self._lbl_role_name_for_session(role), r, 0)

            edit_limit = QLineEdit()
            edit_limit.setFixedWidth(70)
            self._edit_limit[role] = edit_limit
            grid.addWidget(edit_limit, r, 1)

            btn_apply_limit = QPushButton('Apply')
            btn_apply_limit.clicked.connect(self._make_apply_limit_handler(role))
            grid.addWidget(btn_apply_limit, r, 2)

            if role == 'R':
                # SPR has no effect on R (verified 23/09/2026): no speed
                # field for it, just a placeholder cell (task_scanner_r_axis.md
                # point 3).
                grid.addWidget(QLabel('—'), r, 3)
            else:
                edit_speed = QLineEdit()
                edit_speed.setFixedWidth(60)
                self._edit_speed[role] = edit_speed
                grid.addWidget(edit_speed, r, 3)
                self._session_widgets.append(edit_speed)

            btn_zero = QPushButton('Zero')
            btn_zero.clicked.connect(self._make_zero_handler(role))
            grid.addWidget(btn_zero, r, 4)

            self._session_widgets += [edit_limit, btn_apply_limit, btn_zero]
        layout.addLayout(grid)

        btn_row = QHBoxLayout()
        btn_zero_all = QPushButton('Zero all')
        btn_zero_all.clicked.connect(self._on_zero_all_clicked)
        btn_row.addWidget(btn_zero_all)
        btn_apply_speeds = QPushButton('Apply speeds')
        btn_apply_speeds.clicked.connect(self._on_apply_speeds_clicked)
        btn_row.addWidget(btn_apply_speeds)
        layout.addLayout(btn_row)
        self._session_widgets += [btn_zero_all, btn_apply_speeds]

        btn_row2 = QHBoxLayout()
        btn_save = QPushButton('Save session')
        btn_save.clicked.connect(self._on_save_session_clicked)
        btn_row2.addWidget(btn_save)
        btn_load = QPushButton('Load session')
        btn_load.clicked.connect(self._on_load_session_clicked)
        btn_row2.addWidget(btn_load)
        btn_refresh_limits = QPushButton('Reread limits')
        btn_refresh_limits.clicked.connect(lambda: self._worker.enqueue(('read_limits',)))
        btn_row2.addWidget(btn_refresh_limits)
        layout.addLayout(btn_row2)
        self._session_widgets += [btn_save, btn_load, btn_refresh_limits]

        return group

    def _lbl_role_name_for_session(self, role):
        # Separate QLabel instance from the Status group's, but kept in sync
        # by _refresh_role_label_texts.
        lbl = QLabel()
        if not hasattr(self, '_lbl_role_name_session'):
            self._lbl_role_name_session = {}
        self._lbl_role_name_session[role] = lbl
        return lbl

    # -- Movement (spec 5.3 + task_scanner_jog.md) ---------------------------
    def _build_movement_group(self):
        group = QGroupBox('Manual movement')
        layout = QVBoxLayout(group)

        # Free-movement mode toggle (task_scanner_freemode.md point 4):
        # replaces the removed "=N" maneuver for setting zero/limits. See
        # _on_free_movement_toggled for the confirm/deactivate dialogs.
        self._btn_free_movement = QPushButton('Movimiento libre (sin límites)')
        self._btn_free_movement.setCheckable(True)
        self._btn_free_movement.toggled.connect(self._on_free_movement_toggled)
        layout.addWidget(self._btn_free_movement)
        self._movement_widgets.append(self._btn_free_movement)

        # R stepwise mode (task_scanner_r_axis.md point 1): on by default.
        # Every R move (jog, 'Move to', 'Go to origin') is chopped into
        # independent R_STEP_UNIT (1.8 deg) commands with a pause in
        # between, because a single large continuous move loses steps once
        # the sample holder is mounted (verified on hardware 23/09/2026).
        r_step_row = QHBoxLayout()
        self._chk_r_stepwise = QCheckBox('Mover R paso a paso')
        self._chk_r_stepwise.setChecked(self._r_stepwise)
        self._chk_r_stepwise.toggled.connect(self._on_r_stepwise_toggled)
        r_step_row.addWidget(self._chk_r_stepwise)
        r_step_row.addWidget(QLabel('Pausa entre pasos de R (ms):'))
        self._edit_r_pause_ms = QLineEdit(str(self._r_step_pause_ms))
        self._edit_r_pause_ms.setFixedWidth(50)
        self._edit_r_pause_ms.editingFinished.connect(self._on_r_pause_edited)
        r_step_row.addWidget(self._edit_r_pause_ms)
        layout.addLayout(r_step_row)
        self._movement_widgets += [self._chk_r_stepwise, self._edit_r_pause_ms]

        r_step_note = QLabel(
            'Sin trocear y con el soporte de muestras puesto, el eje R pierde pasos.'
        )
        r_step_note.setWordWrap(True)
        r_step_note.setStyleSheet('color: gray; font-size: 10px;')
        layout.addWidget(r_step_note)

        grid = QGridLayout()
        # Column layout: 0 axis name, 1 jog edit, 2 minus, 3 plus, 4 move-to
        # edit, 5 go button. Every widget gets a fixed width (including Go,
        # which used to stretch to fill the row) so the row reads as evenly
        # proportioned columns instead of Go eating the leftover space.
        grid.addWidget(QLabel('<b>Jog (mm / °)</b>'), 0, 1)
        grid.addWidget(QLabel('<b>Move to (mm / °)</b>'), 0, 4)

        self._edit_jog = {}
        self._edit_goto = {}
        for r, role in enumerate(ROLE_ORDER, start=1):
            lbl = QLabel()
            if not hasattr(self, '_lbl_role_name_move'):
                self._lbl_role_name_move = {}
            self._lbl_role_name_move[role] = lbl
            grid.addWidget(lbl, r, 0)

            edit_jog = QLineEdit()
            edit_jog.setFixedWidth(55)
            self._edit_jog[role] = edit_jog
            if role == 'R':  # role 'R' always maps to axis 'R', fix 1
                edit_jog.editingFinished.connect(self._on_r_jog_edited)
            grid.addWidget(edit_jog, r, 1)

            btn_minus = QPushButton('-')
            btn_minus.setFixedWidth(30)
            btn_minus.clicked.connect(self._make_jog_handler(role, -1))
            grid.addWidget(btn_minus, r, 2)

            btn_plus = QPushButton('+')
            btn_plus.setFixedWidth(30)
            btn_plus.clicked.connect(self._make_jog_handler(role, +1))
            grid.addWidget(btn_plus, r, 3)

            edit_goto = QLineEdit()
            edit_goto.setFixedWidth(65)
            self._edit_goto[role] = edit_goto
            grid.addWidget(edit_goto, r, 4)

            btn_goto = QPushButton('Go')
            btn_goto.setFixedWidth(40)
            btn_goto.clicked.connect(self._make_goto_handler(role))
            grid.addWidget(btn_goto, r, 5)

            self._movement_widgets += [edit_jog, btn_minus, btn_plus]
            # 'Move to' is an absolute target: disabled in free-movement mode
            # (the firmware does not accept negative absolute destinations).
            self._goto_widgets += [edit_goto, btn_goto]
        layout.addLayout(grid)

        # Fix 5: fixed physical-axis order (R, Z, X, Y), regardless of which
        # axis is currently mapped to "beam".
        btn_goto_origin = QPushButton('Go to origin (R, Z, X, Y)')
        btn_goto_origin.clicked.connect(self._on_goto_origin_clicked)
        layout.addWidget(btn_goto_origin)
        # Also absolute: same restriction as 'Move to' in free-movement mode.
        self._goto_widgets.append(btn_goto_origin)

        note = QLabel(
            "SN (unlimitedDiffMoveAxis) is only used by the jog -/+ buttons "
            "while free-movement mode is active; every other move is "
            "checked against the limits before it is sent."
        )
        note.setWordWrap(True)
        note.setStyleSheet('color: gray; font-size: 10px;')
        layout.addWidget(note)

        return group

    # =======================================================================
    #  Ports
    # =======================================================================
    def _populate_ports(self):
        self._cmb_port.blockSignals(True)
        self._cmb_port.clear()
        if self._use_sim:
            self._cmb_port.addItem(SIM_PORT_LABEL, SIM_PORT_LABEL)
        else:
            other_device_hint_port = self._read_arduino_port()
            ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)
            for p in ports:
                # Only the system description identifies the port; we do not
                # claim to know which physical device is on it. The hint
                # below is a generic "heads up", never an identity claim, and
                # it does not appear for a port already verified to be the
                # scanner (task_scanner_freemode.md point 3).
                label = f'{p.device} — {p.description}'
                if (other_device_hint_port and p.device == other_device_hint_port
                        and p.device != self._verified_scanner_port):
                    label += '  [other serial devices may be present]'
                self._cmb_port.addItem(label, p.device)
            last_port = self._session.get('last_port', '')
            if last_port and last_port != other_device_hint_port:
                idx = self._cmb_port.findData(last_port)
                if idx >= 0:
                    self._cmb_port.setCurrentIndex(idx)
        self._cmb_port.blockSignals(False)

    @staticmethod
    def _read_arduino_port():
        try:
            with open(_ECOS_GUI_SESSION_FILE) as f:
                port = json.load(f).get('arduino_port', '')
                return port.strip() or None
        except Exception:
            return None

    # =======================================================================
    #  Connect / disconnect / STOP
    # =======================================================================
    def _on_connect_clicked(self):
        if self._use_sim:
            port_name, is_sim = SIM_PORT_LABEL, True
        else:
            port_name = self._cmb_port.currentData()
            is_sim = False
            if not port_name:
                QMessageBox.warning(self, 'Scanner', 'Select a serial port first.')
                return
        self._pending_connect_port = port_name
        self._lbl_result.setText(f'Connecting to {port_name}...')
        self._worker.enqueue(('connect', port_name, is_sim))

    def _on_disconnect_clicked(self):
        self._worker.enqueue(('disconnect',))

    def _on_stop_clicked(self):
        self.stop_pressed.emit()
        # FIX/ADD (2026-09): does NOT go through the worker's queue, and does
        # NOT call any Scanner method — it writes 'SSF\r' straight to the
        # shared _LockingSerialProxy from the GUI thread, exactly so it can
        # interrupt a move while the worker is blocked inside Scanner.write's
        # own polling loop (see _LockingSerialProxy docstring for the lock).
        # NOT verified on real hardware: what the controller replies to a
        # move interrupted like this (scanner_tab_spec.md section 8).
        ser = self._worker.ser
        if ser is None:
            self._lbl_result.setText('STOP: not connected.')
            return
        try:
            ser.write(b'SSF\r')
        except Exception as e:
            self._lbl_result.setText(f'STOP: error writing to the port: {e}')
            return
        # Fix 5: also aborts a "Go to origin" sequence, if one is running,
        # instead of letting it continue with the next axis.
        self._worker.request_sequence_abort()
        self._lbl_result.setText('STOP sent.')
        self._worker.enqueue(('read_status',))

    # -- worker signal handlers -----------------------------------------------
    def _on_connected(self, msg):
        self._connected = True
        self._awaiting_ack = True
        self._pending_post_connect_check = True
        if not self._use_sim and self._pending_connect_port:
            # ScannerWorker._do_connect only got here after the SCX identity
            # check passed, so this port is now confirmed to be the scanner:
            # drop any "other serial devices" hint it may have had.
            self._verified_scanner_port = self._pending_connect_port
            self._populate_ports()
        self._lbl_result.setText(msg)
        self._update_enabled_state()

    def _on_disconnected(self):
        self._connected = False
        self._awaiting_ack = False
        self._pending_post_connect_check = False
        self._coords = {ax: 0.0 for ax in AXES}
        self._refresh_position_labels()
        self._lbl_result.setText('Disconnected.')
        if self._free_movement:
            # task_scanner_freemode.md point 4: never persists across a
            # disconnect; reconnecting always starts with it off.
            self._deactivate_free_movement()
        self._update_enabled_state()

    def _on_moved(self, coords_tuple):
        self._coords = dict(zip(AXES, coords_tuple))
        self._refresh_position_labels()

    def _on_moved_axis(self, axis, value):
        """task_scanner_r_axis.md point 5: single-axis counterpart of
        _on_moved, for moves that only ever touch one axis (jog, 'Move to',
        R's stepwise sequence) — updates just that axis instead of
        overwriting all four from a full getCoords()."""
        self._coords[axis] = value
        for role in ROLE_ORDER:
            if self._role_axis[role] == axis:
                self._lbl_pos[role].setText(fmt_pos(axis, value))

    def _on_limits(self, limits_tuple):
        self._limits = dict(zip(AXES, limits_tuple))
        self._refresh_all_role_limit_fields()
        if self._pending_post_connect_check:
            self._pending_post_connect_check = False
            self._run_post_connect_checks()

    def _on_busy(self, is_busy):
        self._busy = is_busy
        self._update_enabled_state()

    def _on_message(self, msg):
        self._lbl_result.setText(msg)

    def _run_post_connect_checks(self):
        is_default = all(
            abs(self._limits[ax] - HARDWARE_RESET_LIMITS_MM[ax]) <= HARDWARE_RESET_LIMITS_TOL[ax]
            for ax in AXES
        )
        if is_default:
            # Falls back to SESSION_DEFAULT_LIMITS_MM (R = 360 deg, not the
            # firmware's 18000) axis by axis, so this still makes sense even
            # when there is no saved session at all (fixes task point 3).
            session_limits = self._session.get('limits', {})
            to_send = {ax: float(session_limits.get(ax, SESSION_DEFAULT_LIMITS_MM[ax])) for ax in AXES}
            proposal = (f'{to_send["X"]:g}/{to_send["Y"]:g}/{to_send["Z"]:g} mm, '
                        f'{to_send["R"]:g}°')
            resend = QMessageBox.question(
                self, 'Scanner',
                'All four limits are at the factory default (10000 steps). '
                'The controller may have been reset by a power cut.\n\n'
                f'Apply these limits now (X/Y/Z, R): {proposal}?',
                QMessageBox.Yes | QMessageBox.No,
            )
            if resend == QMessageBox.Yes:
                self._worker.enqueue(('set_limits', to_send))
        QMessageBox.information(
            self, 'Scanner',
            'Has any axis been moved by hand since the last session?\n'
            'If so, zero it again before relying on saved positions.',
        )
        self._awaiting_ack = False
        self._update_enabled_state()

    # =======================================================================
    #  Role <-> axis mapping (spec 2: single translation function)
    # =======================================================================
    def _on_beam_axis_changed(self, text):
        new_beam = 'X' if text.strip().upper() == 'X' else 'Y'
        if new_beam == self._role_axis['beam']:
            return
        self._capture_role_edits_into_state()
        self._role_axis = role_axis_map(new_beam)
        self._refresh_role_label_texts()
        self._refresh_position_labels()
        self._refresh_all_role_limit_fields()
        self._refresh_role_speed_fields()
        self._refresh_role_jog_fields()

    def _on_pe_side_changed(self, index):
        self._pe_side = 'origin' if index == 0 else 'max'

    def _capture_role_edits_into_state(self):
        """Reads whatever is currently typed in the jog/speed fields into the
        per-real-axis session state, before swapping which axis a role points
        to (or before saving), so in-progress edits are not silently lost."""
        for role in ROLE_ORDER:
            axis = self._role_axis[role]
            jog = self._read_float(self._edit_jog[role], None)
            if jog is not None:
                self._jogs[axis] = jog
            if role in self._edit_speed:  # R has no speed field, see SPEED_AXES
                speed = self._read_float(self._edit_speed[role], None)
                if speed is not None:
                    self._speeds[axis] = int(speed)

    def _refresh_role_label_texts(self):
        for role in ROLE_ORDER:
            axis = self._role_axis[role]
            text = f'{ROLE_LABELS[role]} ({axis})' if role in ('beam', 'lateral') else ROLE_LABELS[role]
            self._lbl_role_name[role].setText(text)
            if hasattr(self, '_lbl_role_name_session'):
                self._lbl_role_name_session[role].setText(text)
            if hasattr(self, '_lbl_role_name_move'):
                self._lbl_role_name_move[role].setText(text)

    def _refresh_position_labels(self):
        for role in ROLE_ORDER:
            axis = self._role_axis[role]
            self._lbl_pos[role].setText(fmt_pos(axis, self._coords.get(axis, 0.0)))

    def _refresh_all_role_limit_fields(self):
        for role in ROLE_ORDER:
            axis = self._role_axis[role]
            self._edit_limit[role].setText(f'{self._limits.get(axis, 0.0):g}')

    def _refresh_role_speed_fields(self):
        for role in ROLE_ORDER:
            if role not in self._edit_speed:  # R: no speed field (point 3)
                continue
            axis = self._role_axis[role]
            self._edit_speed[role].setText(str(self._speeds.get(axis, 100)))

    def _refresh_role_jog_fields(self):
        for role in ROLE_ORDER:
            axis = self._role_axis[role]
            self._edit_jog[role].setText(f'{self._jogs.get(axis, JOG_DEFAULTS_MM[axis]):g}')

    # =======================================================================
    #  Movement handlers (spec 5.3 + section 6, "seguridad")
    # =======================================================================
    def _validate_target(self, axis, target):
        limit = self._limits.get(axis)
        if limit is None:
            QMessageBox.warning(self, 'Scanner', 'Limits are unknown; read them first.')
            return False
        if not (0 <= target <= limit):
            QMessageBox.warning(
                self, 'Scanner',
                f'{axis} target ({target:g}) is out of range [0, {limit:g}].',
            )
            return False
        return True

    def _on_r_jog_edited(self):
        """Fix 1 (still applies to the jog field after task_scanner_jog.md):
        R only accepts multiples of R_STEP_UNIT (min. one unit); round it as
        soon as the user leaves the field."""
        edit = self._edit_jog['R']
        value = self._read_float(edit, None)
        if value is None:
            return
        rounded = round_r_jog(value)
        edit.setText(f'{rounded:g}')
        if abs(rounded - value) > 1e-6:
            self._lbl_result.setText(
                f'R jog rounded to {rounded:g}° (multiple of {R_STEP_UNIT:g}°).'
            )

    def _on_r_stepwise_toggled(self, checked):
        self._r_stepwise = checked

    def _on_r_pause_edited(self):
        edit = self._edit_r_pause_ms
        value = self._read_float(edit, None)
        self._r_step_pause_ms = self._clamp_r_pause(
            value if value is not None else self._r_step_pause_ms
        )
        edit.setText(str(self._r_step_pause_ms))

    def _make_jog_handler(self, role, sign):
        """+/- buttons: move by the jog amount typed in that row's field,
        read at click time (no Enter needed)."""
        def handler():
            axis = self._role_axis[role]
            jog = self._read_float(self._edit_jog[role], None)
            if jog is None:
                QMessageBox.warning(self, 'Scanner', 'Invalid jog value.')
                return
            if axis == 'R':
                # task_scanner_r_axis.md point 1: R never moves with a
                # single absolute SM; always diffMoveR/unlimitedDiffMoveR,
                # chopped into 1-step commands unless 'Mover R paso a paso'
                # is off (see ScannerWorker._run_r_step_sequence).
                rounded_jog = round_r_jog(jog)
                if abs(rounded_jog - jog) > 1e-6:
                    self._edit_jog[role].setText(f'{rounded_jog:g}')
                    self._lbl_result.setText(
                        f'R jog rounded to {rounded_jog:g}° (multiple of {R_STEP_UNIT:g}°).'
                    )
                jog = rounded_jog
                total_degrees = sign * jog
                if not self._free_movement:
                    target = round(self._coords.get('R', 0.0) + total_degrees, 4)
                    if not self._validate_target('R', target):
                        return
                self._worker.enqueue(('move_sequence', [
                    ('r', total_degrees, self._r_stepwise, self._r_step_pause_ms, self._free_movement)
                ]))
                return
            if self._free_movement:
                # task_scanner_freemode.md point 4: signed unlimited relative
                # move (SN), GUI limit check skipped — the firmware's own
                # protection is bypassed too.
                self._worker.enqueue(('jog_unlimited', axis, sign * jog))
                return
            current = self._coords.get(axis, 0.0)
            target = round(current + sign * jog, 4)
            if not self._validate_target(axis, target):
                return
            self._worker.enqueue(('move_axis', axis, target))
        return handler

    def _make_goto_handler(self, role):
        def handler():
            axis = self._role_axis[role]
            raw_target = self._read_float(self._edit_goto[role], None)
            if raw_target is None:
                QMessageBox.warning(self, 'Scanner', 'Invalid target value.')
                return
            if axis == 'R':
                # task_scanner_r_axis.md point 2: R is circular, so the
                # target is normalized to [0, 360) and reached via the
                # shortest signed path, sent as relative step(s) — never as
                # an absolute SM (which would ignore the wraparound).
                target_deg = round_r_target_circular(raw_target)
                self._edit_goto[role].setText(f'{target_deg:g}')
                current_deg = self._coords.get('R', 0.0) % 360.0
                signed_degrees, n_steps = r_shortest_path(current_deg, target_deg)
                if n_steps == 0:
                    self._lbl_result.setText(f'R ya está en {current_deg:.1f}°.')
                    return
                # Status-bar notice, not a blocking dialog (point 2): shows
                # direction, degrees and step count before sending anything.
                self._lbl_result.setText(
                    f'R: {current_deg:.1f}° → {target_deg:.1f}°, girando '
                    f'{signed_degrees:+.1f}° ({n_steps} pasos)'
                )
                self._worker.enqueue(('move_sequence', [
                    ('r', signed_degrees, self._r_stepwise, self._r_step_pause_ms, False)
                ]))
                return
            target = raw_target
            if not self._validate_target(axis, target):
                return
            self._worker.enqueue(('move_axis', axis, target))
        return handler

    def _on_goto_origin_clicked(self):
        """
        Fix 5: moves every axis that is not already at 0 to 0, one axis at a
        time, in the fixed physical order R, Z, X, Y (never reordered by
        which axis is currently "beam"). Confirms first, showing that order
        and each axis' current -> final position/path. Goes through the
        worker's move_sequence command, exactly like any other move, so STOP
        (which also calls ScannerWorker.request_sequence_abort) stops the
        sequence after whichever step is interrupted instead of moving on.

        task_scanner_r_axis.md point 1/2: R's step is built as a 'r'
        shortest-path entry (see _make_goto_handler), not an ('axis', 'R', 0)
        absolute SM target — R is circular and does not accept negative
        absolute destinations either.
        """
        steps = []
        lines = []
        axes_included = []
        for ax in GO_TO_ORIGIN_AXIS_ORDER:
            cur = self._coords.get(ax, 0.0)
            if ax == 'R':
                cur_deg = cur % 360.0
                signed_degrees, n_steps = r_shortest_path(cur_deg, 0.0)
                if n_steps == 0:
                    continue
                steps.append(('r', signed_degrees, self._r_stepwise, self._r_step_pause_ms, False))
                lines.append(
                    f'  R: {cur_deg:.1f}° -> 0.0°, girando {signed_degrees:+.1f}° ({n_steps} pasos)'
                )
                axes_included.append('R')
            else:
                if abs(cur) <= 1e-9:
                    continue
                if not self._validate_target(ax, 0.0):
                    return
                steps.append(('axis', ax, 0.0))
                lines.append(f'  {ax}: {fmt_pos(ax, cur)} -> {fmt_pos(ax, 0.0)}')
                axes_included.append(ax)

        if not steps:
            self._lbl_result.setText('All axes are already at 0.')
            return

        order_text = ' -> '.join(axes_included)
        resp = QMessageBox.question(
            self, 'Scanner',
            f'Move to origin in this order: {order_text}\n\n' + '\n'.join(lines) + '\n\nProceed?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        self._worker.enqueue(('move_sequence', steps))

    # =======================================================================
    #  Free-movement mode (task_scanner_freemode.md point 4)
    # =======================================================================
    def is_free_movement_active(self):
        """
        Single point to check whether free-movement mode is active. Later
        phases (focus, flatness, scans) must gate on this before starting,
        per task_scanner_freemode.md point 4 ("Deja el punto único donde
        comprobarlo").
        """
        return self._free_movement

    # =======================================================================
    #  API for the host window / sequencer (phase 2)
    # =======================================================================
    @property
    def worker(self):
        return self._worker

    @property
    def uses_simulator(self):
        return self._use_sim

    def sequence_blocker(self):
        """
        The one place that says whether a sequence may start: None if it can,
        otherwise the reason. Covers the connection and post-connect warnings
        of phase 1 and free-movement mode (task_scanner_freemode.md point 4).
        """
        if not self._connected:
            return 'Scanner not connected.'
        if self._awaiting_ack:
            return 'Acknowledge the post-connect warnings first.'
        if self.is_free_movement_active():
            return 'Free-movement mode is active: turn it off first.'
        if self._seq_active:
            return 'A sequence is already running.'
        if self._busy:
            return 'The scanner is moving.'
        return None

    def role_axis(self, role):
        """Physical axis ('X'/'Y'/'Z'/'R') currently playing role beam/lateral/Z/R."""
        return self._role_axis[role]

    def current_coords(self):
        return dict(self._coords)

    def axis_limit(self, axis):
        return self._limits.get(axis)

    def validate_position(self, position):
        """None if every {axis: mm} target is inside [0, limit], else an error string."""
        for axis, value in position.items():
            limit = self._limits.get(axis)
            if limit is None:
                return 'Limits are unknown; read them first.'
            if not (0 <= value <= limit):
                return f'{axis} target ({value:g}) is out of range [0, {limit:g}].'
        return None

    def set_sequence_active(self, active):
        self._seq_active = bool(active)
        if not active:
            self._seq_text = ''
        self._update_enabled_state()

    def set_sequence_progress(self, done, total):
        self._seq_text = f'Sequence {done}/{total}'
        self._update_enabled_state()

    def add_tool_widget(self, widget):
        """Add a widget (a tool's own controls) at the bottom of the scrollable panel."""
        self._content_layout.insertWidget(self._content_layout.count() - 1, widget)

    def _axes_out_of_range(self):
        """Axes whose current GUI position falls outside [0, limit]."""
        return [
            ax for ax in AXES
            if self._coords.get(ax, 0.0) < -1e-9
            or self._coords.get(ax, 0.0) > self._limits.get(ax, 0.0) + 1e-9
        ]

    def _on_free_movement_toggled(self, checked):
        if checked:
            box = QMessageBox(self)
            box.setWindowTitle('Movimiento libre')
            box.setIcon(QMessageBox.Warning)
            box.setText(
                'El firmware deja de proteger el recorrido: los botones -/+ '
                'moverán el eje aunque se salga de [0, límite] o pase a ser '
                'negativo.\n\n'
                'La responsabilidad de evitar colisiones (con los '
                'transductores u otros elementos) pasa a ser del usuario.\n\n'
                '¿Activar el movimiento libre?'
            )
            btn_activate = box.addButton('Activar', QMessageBox.AcceptRole)
            box.addButton('Cancelar', QMessageBox.RejectRole)
            box.setDefaultButton(btn_activate)
            box.exec_()
            if box.clickedButton() is btn_activate:
                self._free_movement = True
                self._lbl_free_banner.setVisible(True)
                self._lbl_result.setText('Movimiento libre activado: sin protección de límites.')
                self._update_enabled_state()
            else:
                self._btn_free_movement.blockSignals(True)
                self._btn_free_movement.setChecked(False)
                self._btn_free_movement.blockSignals(False)
            return

        # Turning it off.
        out_of_range = self._axes_out_of_range()
        if not out_of_range:
            self._deactivate_free_movement()
            return

        lines = '\n'.join(
            f'  {ax}: {fmt_pos(ax, self._coords.get(ax, 0.0))} '
            f'(límite {fmt_pos(ax, self._limits.get(ax, 0.0))})'
            for ax in out_of_range
        )
        box = QMessageBox(self)
        box.setWindowTitle('Movimiento libre — ejes fuera de rango')
        box.setIcon(QMessageBox.Warning)
        box.setText(
            f'Estos ejes están fuera de su rango [0, límite]:\n\n{lines}\n\n'
            '· Fijar cero aquí: pone a cero SOLO estos ejes fuera de rango '
            '(los demás no se tocan).\n'
            '· Mantener posición: desactiva el modo libre sin mover nada; '
            'los destinos absolutos (Move to / Go to origin) fallarán en '
            'estos ejes hasta que se corrija.\n'
            '· Seguir en modo libre: cancela la desactivación.'
        )
        btn_zero = box.addButton('Fijar cero aquí', QMessageBox.AcceptRole)
        btn_keep = box.addButton('Mantener posición', QMessageBox.DestructiveRole)
        btn_stay = box.addButton('Seguir en modo libre', QMessageBox.RejectRole)
        box.setDefaultButton(btn_stay)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is btn_zero:
            self._worker.enqueue(('set_zero', out_of_range))
            self._deactivate_free_movement()
        elif clicked is btn_keep:
            self._deactivate_free_movement()
            self._lbl_result.setText(
                'Movimiento libre desactivado con posiciones fuera de rango: '
                'los destinos absolutos fallarán hasta corregirlo.'
            )
        else:  # Seguir en modo libre: cancel, keep it on.
            self._btn_free_movement.blockSignals(True)
            self._btn_free_movement.setChecked(True)
            self._btn_free_movement.blockSignals(False)

    def _deactivate_free_movement(self):
        self._free_movement = False
        self._lbl_free_banner.setVisible(False)
        self._btn_free_movement.blockSignals(True)
        self._btn_free_movement.setChecked(False)
        self._btn_free_movement.blockSignals(False)
        self._update_enabled_state()

    # =======================================================================
    #  Session handlers (spec 5.2)
    # =======================================================================
    def _make_apply_limit_handler(self, role):
        def handler():
            axis = self._role_axis[role]
            value = self._read_float(self._edit_limit[role], None)
            if value is None or value < 0:
                QMessageBox.warning(self, 'Scanner', 'Invalid limit value.')
                return
            self._worker.enqueue(('set_limits', {axis: value}))
        return handler

    def _make_zero_handler(self, role):
        def handler():
            axis = self._role_axis[role]
            self._worker.enqueue(('set_zero', [axis]))
        return handler

    def _on_zero_all_clicked(self):
        self._worker.enqueue(('set_zero', list(AXES)))

    def _on_apply_speeds_clicked(self):
        # SPR has no effect on R (verified 23/09/2026): SPEED_AXES excludes
        # it, so 'Apply speeds' can never send SPR (task_scanner_r_axis.md
        # point 3).
        self._capture_role_edits_into_state()
        speeds = {ax: int(self._speeds.get(ax, 100)) for ax in SPEED_AXES}
        for ax, v in speeds.items():
            if not (1 <= v <= 65536):
                QMessageBox.warning(self, 'Scanner', f'Speed for {ax} must be between 1 and 65536.')
                return
        self._worker.enqueue(('set_speeds', speeds))

    def _on_save_session_clicked(self):
        self._capture_role_edits_into_state()
        self._write_session_file()
        self._lbl_result.setText('Session saved.')

    def _on_load_session_clicked(self):
        self._session = self._load_session_from_disk()
        self._apply_session_dict(self._session)
        self._lbl_result.setText('Session loaded.')

    def _apply_session_dict(self, d):
        beam = d.get('beam_axis', 'Y')
        self._role_axis = role_axis_map(beam)
        self._cmb_beam_axis.blockSignals(True)
        self._cmb_beam_axis.setCurrentText(beam)
        self._cmb_beam_axis.blockSignals(False)

        self._pe_side = d.get('pe_side', 'origin')
        self._cmb_pe_side.blockSignals(True)
        self._cmb_pe_side.setCurrentIndex(0 if self._pe_side == 'origin' else 1)
        self._cmb_pe_side.blockSignals(False)

        self._limits = {ax: float(d.get('limits', {}).get(ax, SESSION_DEFAULT_LIMITS_MM[ax])) for ax in AXES}
        # 'jog' replaces the old 'step' key; an old JSON with 'step' still loads.
        jog_source = d.get('jog', d.get('steps', {}))
        self._jogs = {ax: float(jog_source.get(ax, JOG_DEFAULTS_MM[ax])) for ax in AXES}
        # SPEED_AXES excludes R: a speeds.R value in an old JSON is simply
        # never read, so it loads without error (task_scanner_r_axis.md point 3).
        self._speeds = {ax: int(d.get('speeds', {}).get(ax, 100)) for ax in SPEED_AXES}

        self._r_stepwise = bool(d.get('r_stepwise', True))
        self._chk_r_stepwise.blockSignals(True)
        self._chk_r_stepwise.setChecked(self._r_stepwise)
        self._chk_r_stepwise.blockSignals(False)
        self._r_step_pause_ms = self._clamp_r_pause(d.get('r_step_pause_ms', R_STEP_PAUSE_MS_DEFAULT))
        self._edit_r_pause_ms.setText(str(self._r_step_pause_ms))

        self._refresh_role_label_texts()
        self._refresh_all_role_limit_fields()
        self._refresh_role_speed_fields()
        self._refresh_role_jog_fields()

    @staticmethod
    def _load_session_from_disk():
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE) as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _write_session_file(self):
        data = {
            'beam_axis': self._role_axis['beam'],
            'pe_side': self._pe_side,
            'last_port': ('' if self._use_sim else (self._cmb_port.currentData() or '')),
            'limits': dict(self._limits),
            'jog': dict(self._jogs),
            'speeds': dict(self._speeds),
            'r_stepwise': self._r_stepwise,
            'r_step_pause_ms': self._r_step_pause_ms,
        }
        try:
            with open(SESSION_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self._lbl_result.setText(f'Could not save session: {e}')

    # =======================================================================
    #  Enabled/disabled state (spec: controls disabled while moving except
    #  STOP; only manual movement allowed until the post-connect acks)
    # =======================================================================
    def _update_enabled_state(self):
        connected = self._connected
        unlocked = connected and not self._awaiting_ack
        can_move = connected and not self._busy and not self._seq_active
        can_use_session = unlocked and not self._busy and not self._seq_active

        self._btn_connect.setEnabled(not connected and not self._busy)
        self._btn_disconnect.setEnabled(connected and not self._seq_active)
        self._cmb_port.setEnabled(not connected and not self._use_sim)
        self._btn_refresh.setEnabled(not connected and not self._use_sim)

        for w in self._movement_widgets:
            w.setEnabled(can_move)
        # Absolute-target controls: also disabled in free-movement mode,
        # since the firmware rejects negative absolute destinations
        # (task_scanner_freemode.md point 4).
        for w in self._goto_widgets:
            w.setEnabled(can_move and not self._free_movement)
        for w in self._session_widgets:
            w.setEnabled(can_use_session)

        self._btn_stop.setEnabled(True)  # always active, per spec

        if not connected:
            self._lbl_state.setText('Disconnected')
        elif self._seq_active:
            self._lbl_state.setText(self._seq_text or 'Sequence')
        elif self._busy:
            self._lbl_state.setText('Moving')
        else:
            self._lbl_state.setText('Free')

    # =======================================================================
    #  Misc helpers
    # =======================================================================
    @staticmethod
    def _read_float(edit, default=0.0):
        try:
            return float(edit.text().strip())
        except (ValueError, AttributeError):
            return default

    @staticmethod
    def _clamp_r_pause(value):
        lo, hi = R_STEP_PAUSE_MS_RANGE
        try:
            return max(lo, min(hi, int(round(float(value)))))
        except (ValueError, TypeError):
            return R_STEP_PAUSE_MS_DEFAULT

    # =======================================================================
    #  Shutdown
    # =======================================================================
    def closeEvent(self, event):
        self.shutdown()
        event.accept()

    def shutdown(self):
        """
        Save the session, stop any move in flight, close the port and stop the
        worker thread. Called from closeEvent when run standalone and by the
        host window when the panel is embedded as a tab (a child widget gets no
        closeEvent of its own). Safe to call more than once.
        """
        if self._shut_down:
            return
        self._shut_down = True
        self._capture_role_edits_into_state()
        self._write_session_file()
        if self._worker is not None:
            if self._busy:
                self._on_stop_clicked()
            self._worker.enqueue(('disconnect',))
            self._worker.stop_thread()
            self._worker.wait(2000)


# ===========================================================================
#  Entry point
# ===========================================================================
def _parse_args():
    parser = argparse.ArgumentParser(description='ECOS Scanner Panel (phase 1)')
    parser.add_argument('--sim', action='store_true',
                         help='Use the serial simulator (sim_scanner.FakeSerial) instead of hardware.')
    return parser.parse_args()


def main():
    args = _parse_args()
    app = QApplication(sys.argv)
    panel = ScannerPanel(use_sim=args.sim)
    panel.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
