# -*- coding: utf-8 -*-
"""
sim_scanner.py — Serial-port simulator for the SE SC-03-00 scanner controller.

Location: hardware/scanner/sim_scanner.py

Implements FakeSerial, a stand-in for serial.Serial that speaks the same
protocol Scanner.py uses (see hardware/scanner/Scanner.py and
scanner_tab_spec.md section 1). It reproduces the *verified* hardware
behaviour only; anything not verified on hardware is marked ASSUMPTION below
and kept as an easily-changeable constant.

Intended use: `Scanner(ser=FakeSerial())` — see Scanner.__init__'s `ser`
parameter (# ADD 2026-09) — to exercise the real Scanner class and the GUI
without the physical controller connected.
"""
import threading
import time

AXES = ('X', 'Y', 'Z', 'R')

# Verified: after a power cut the controller keeps the position but resets
# every axis limit to 10000 steps (100/100/50 mm, 18000 deg).
DEFAULT_LIMIT_STEPS = 10000

# Verified on hardware (23/09/2026, check_negative.py): a rejected command
# (SD out of [0, limit]) replies with 'ER' + axis + 6 zero digits + CR, e.g.
# SDX-10 from position 0 -> b'ERX000000\r'. That is the same 10-byte reply
# shape as 'OK' ('OK'/'ER' + axis + 6 digits + '\r').
REJECT_PREFIX = 'ER'

# Verified on hardware (23-24/09/2026, task_scanner_r_axis.md /
# task_scanner_r_zerocross.md): R's physical counter is circular, but only
# going UP -- it wraps to 0 after a full revolution (200 steps = 360 deg,
# since Scanner.uStepR = 1.8 deg/step). Going down, the counter never jumps
# to 199; a relative move (SD) that would take it below 0 is rejected with
# ER instead (see _do_move_locked/_wrap_r below).
R_STEPS_PER_REV = 200

# ASSUMPTION (not verified on hardware): step speed is proportional to the
# firmware "speed" parameter and identical in steps/s on every axis; only the
# verified calibration point is X axis, speed=100 -> ~6.7 mm/s. Since
# Scanner.uStepX = 0.01 mm, that is ~670 steps/s. Z comes out at half the
# mm/s of X/Y because Scanner.uStepZ = 0.005 mm (half the step size), which
# matches what was observed. Kept as a constant so it can be recalibrated.
BASE_STEPS_PER_SEC_AT_SPEED_100 = 670.0


class _AxisState:
    """Internal per-axis state kept by FakeSerial."""
    __slots__ = ('pos', 'limit', 'direction', 'speedtype', 'speed', 'enabled')

    def __init__(self):
        self.pos = 0
        self.limit = DEFAULT_LIMIT_STEPS
        self.direction = '+'
        self.speedtype = 0
        self.speed = 100
        self.enabled = True


class FakeSerial:
    """
    Minimal double of serial.Serial that emulates the SE SC-03-00 scanner
    controller, implementing only the interface Scanner.py actually uses:
    write, read, isOpen, open, close, flushInput, flushOutput,
    reset_input_buffer, reset_output_buffer, and the `port`/`timeout`
    attributes.

    Positions/limits are kept in motor steps internally; Scanner.py converts
    to/from mm or degrees (uStepX/Y/Z/R), so this class never needs to know
    about those units.

    Thread safety: `write` and `read` are non-blocking (they never sleep) and
    protected by a single lock, so SSF ('write' from another thread) can
    interrupt a move while the calling thread is spin-free inside Scanner's
    own polling loop (Scanner.write sleeps between successive `read` calls).

    Parameters
    ----------
    port : str, optional
        Stored in `self.port`, mirrors serial.Serial. Default 'SIM'.
    timeout : float, optional
        Stored in `self.timeout`, mirrors serial.Serial. Not otherwise used,
        because `read` never blocks (see class docstring).
    time_scale : float, optional
        Divides every simulated move duration by this factor. Default 1.0
        (real duration). Use e.g. time_scale=50 to make tests fast without
        changing the underlying kinematics.
    extra_latency : dict, optional
        Maps a 2-letter command prefix (e.g. 'SM', 'SC') to an extra delay in
        seconds added on top of the computed response time. Default: empty,
        i.e. no extra latency, because Scanner.write already sleeps 0.1 s
        after every write before its first read.
    """

    def __init__(self, port='SIM', timeout=0.1, time_scale=1.0, extra_latency=None):
        self.port = port
        self.timeout = timeout
        self._time_scale = float(time_scale)
        self._extra_latency = dict(extra_latency) if extra_latency else {}

        self._is_open = True
        self._lock = threading.Lock()
        self._axes = {ax: _AxisState() for ax in AXES}

        # At most one command is "in flight" at a time (Scanner.write is a
        # synchronous request/response call), so a single pending buffer and
        # a single active move are enough.
        self._pending = None            # bytes waiting to be read, or None
        self._pending_ready_at = 0.0
        self._move = None               # dict describing the in-progress move, or None

    # ------------------------------------------------------------------
    # serial.Serial-compatible interface
    # ------------------------------------------------------------------
    def isOpen(self):
        return self._is_open

    def open(self):
        self._is_open = True

    def close(self):
        self._is_open = False

    def flushInput(self):
        pass

    def flushOutput(self):
        pass

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def write(self, data):
        """Accepts the same bytes Scanner.write sends: `(cmd + '\\r').encode('utf-8')`."""
        text = data.decode('utf-8').strip('\r')
        with self._lock:
            self._settle_move_locked()
            reply, ready_delay = self._handle_locked(text)
            if reply is not None:
                extra = self._extra_latency.get(text[:2], 0.0)
                self._pending = reply
                self._pending_ready_at = time.time() + ready_delay + extra
        return len(data)

    def read(self, size=1):
        """Non-blocking: returns b'' immediately if no reply is ready yet."""
        with self._lock:
            self._settle_move_locked()
            if self._pending is None or time.time() < self._pending_ready_at:
                return b''
            data = self._pending[:size]
            remainder = self._pending[size:]
            self._pending = remainder if remainder else None
            return data

    # ------------------------------------------------------------------
    # Debug / test helpers (not part of the serial.Serial interface)
    # ------------------------------------------------------------------
    def power_cycle(self):
        """
        Simulates cutting power to the controller: verified behaviour is that
        the position is kept and every axis limit resets to 10000 steps.
        """
        with self._lock:
            self._settle_move_locked()
            for axis in self._axes.values():
                axis.limit = DEFAULT_LIMIT_STEPS

    # ------------------------------------------------------------------
    # Internal protocol handling (all called with self._lock held)
    # ------------------------------------------------------------------
    def _settle_move_locked(self):
        mv = self._move
        if mv is not None and (time.time() - mv['start_time']) >= mv['duration']:
            pos = mv['target_pos']
            if mv['axis'] == 'R':
                pos = self._wrap_r(pos)
            self._axes[mv['axis']].pos = pos
            self._move = None

    def _handle_locked(self, text):
        if text.startswith('SSF'):
            return self._do_stop_locked()

        op, ax, rest = text[:2], text[2], text[3:]
        axis = self._axes[ax]

        if op == 'SC':                       # read coordinate
            return self._ok(ax, axis.pos), 0.0
        if op == 'SG':                       # read limit
            return self._ok(ax, axis.limit), 0.0
        if op == 'SL':                       # set limit
            axis.limit = int(rest)
            return self._ok(ax, axis.limit), 0.0
        if op == 'SA':                       # set current position (no motion)
            # Verified (24/09/2026): SA redefines the counter without moving
            # anything and without wrapping, even at a value equal to the
            # limit/one full revolution -- e.g. SAR200 (R_STEPS_PER_REV)
            # leaves R at 200 steps (360 deg), not 0. That is exactly what
            # the panel's zero-crossing handling relies on (see
            # scanner_panel.py's _run_r_step_sequence).
            axis.pos = int(rest)
            return self._ok(ax, axis.pos), 0.0
        if op == 'SW':                       # set direction
            # Verified (23/09/2026): SW only affects absolute moves (SM); it
            # has no effect on relative moves (SD/SN), whose direction is
            # given by the sign of the value. Relative moves below never
            # consult axis.direction, so its effect on SM does not need
            # simulating for the relative-move tests this module targets.
            axis.direction = rest
            return self._ok(ax, axis.pos), 0.0
        if op == 'ST':                       # set speed type
            axis.speedtype = int(rest)
            return self._ok(ax, axis.pos), 0.0
        if op == 'SP':                       # set speed
            axis.speed = int(rest)
            return self._ok(ax, axis.pos), 0.0
        if op == 'SO':                       # set ramping speed (gaussian/triangle)
            return self._ok(ax, axis.pos), 0.0
        if op == 'SR':                       # set random-speed parameter
            return self._ok(ax, axis.pos), 0.0
        if op == 'SE':                       # enable/disable axis
            axis.enabled = (rest == '+')
            return self._ok(ax, axis.pos), 0.0
        if op in ('SM', 'SD', 'SN'):         # absolute / relative / unlimited-relative move
            return self._do_move_locked(op, ax, int(rest))

        # Unknown command: real firmware behaviour is unverified; stay silent
        # rather than guess, matching the "response == b''" case Scanner.write
        # already tolerates for other commands.
        return None, 0.0

    def _do_move_locked(self, op, ax, param):
        axis = self._axes[ax]
        if op == 'SN':
            # Verified (23/09/2026): SN accepts a signed param (the sign sets
            # the direction) and ignores limits entirely, so target can go
            # negative.
            target = axis.pos + param
        elif op == 'SD':
            # Verified (23/09/2026): SD accepts a signed param (the sign sets
            # the direction) and rejects with ER if the destination falls
            # outside [0, limit]. For R specifically, a target < 0 is exactly
            # the "crossing 0 downward" rejection verified 24/09/2026 -- no
            # extra check needed here, target < 0 already covers it.
            target = axis.pos + param
            if target < 0 or target > axis.limit:
                return self._reject(ax), 0.0
        else:  # 'SM'
            target = param
            if target < 0 or target > axis.limit:
                return self._reject(ax), 0.0

        # `target` is kept raw/unwrapped here (used below for distance/
        # duration, and by _do_stop_locked for interpolation); the upward
        # wrap for R (_wrap_r) is only applied where a position actually
        # lands: below, in the immediate OK reply, and in
        # _settle_move_locked/_do_stop_locked.
        distance = abs(target - axis.pos)
        steps_per_sec = BASE_STEPS_PER_SEC_AT_SPEED_100 * (axis.speed / 100.0)
        duration = (distance / steps_per_sec) if steps_per_sec > 0 else 0.0
        duration /= self._time_scale

        self._move = {
            'axis': ax,
            'start_time': time.time(),
            'duration': duration,
            'start_pos': axis.pos,
            'target_pos': target,
        }
        reply_pos = self._wrap_r(target) if ax == 'R' else target
        # Verified: the OK reply (and the position update) is only available
        # once the move has finished, hence ready_delay = duration.
        return self._ok(ax, reply_pos), duration

    def _do_stop_locked(self):
        mv = self._move
        if mv is None:
            # Nothing is moving. Scanner.write does not check SSF's reply
            # ('SS' is not in the blocking-command list), so the exact
            # content here is never verified against hardware.
            return b'OK-000000\r', 0.0

        axis = self._axes[mv['axis']]
        elapsed = min(time.time() - mv['start_time'], mv['duration'])
        frac = (elapsed / mv['duration']) if mv['duration'] > 0 else 1.0
        delta = mv['target_pos'] - mv['start_pos']
        pos = mv['start_pos'] + int(round(delta * frac))
        if mv['axis'] == 'R':
            pos = self._wrap_r(pos)
        axis.pos = pos
        self._move = None
        # Releases the interrupted move's pending reply immediately, with the
        # real (partial) position, instead of the original target position.
        return self._ok(mv['axis'], axis.pos), 0.0

    @staticmethod
    def _wrap_r(pos):
        """
        R's physical counter is circular upward only (verified 23-24/09/2026):
        past R_STEPS_PER_REV (one full revolution) it wraps to 0. A negative
        value (only reachable via SN, which ignores limits) is never
        wrapped -- it stays negative, matching hardware ("al bajar de 0 no
        salta a 199").
        """
        if pos >= R_STEPS_PER_REV:
            return pos % R_STEPS_PER_REV
        return pos

    @staticmethod
    def _ok(ax, value):
        # Verified (23/09/2026): a negative position replies with the sign in
        # place of the first digit, still 6 characters total, e.g. -10 ->
        # '-00010' -> b'OKX-00010\r' (10 bytes). Python's ':06d' already
        # formats a negative int that way, so no special-casing is needed.
        return f'OK{ax}{int(value):06d}\r'.encode('utf-8')

    @staticmethod
    def _reject(ax):
        return f'{REJECT_PREFIX}{ax}000000\r'.encode('utf-8')
