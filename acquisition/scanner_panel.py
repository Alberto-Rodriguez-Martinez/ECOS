# -*- coding: utf-8 -*-
"""
scanner_panel.py — Standalone panel for the XYZR scanner (SE SC-03-00), phase 1.
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

Phase 1 scope only (see task_scanner_phase1.md and scanner_tab_spec.md sections
1-3, 5.1-5.3, 6): worker thread + command queue, status, session (beam axis,
PE side, limits, manual step, speed), manual movement and STOP. NOT wired
into ecos_gui.py (that is phase 2) and no focus/flatness/scan tools yet.

Run standalone:
    python acquisition/scanner_panel.py          (real hardware)
    python acquisition/scanner_panel.py --sim     (simulator, no hardware needed)

Requires (Python 32-bit): numpy, pyserial, PyQt5, pyqtgraph 0.11. No scipy.
"""
import argparse
import ast
import inspect
import json
import os
import queue
import re
import sys
import textwrap
import threading
import time

os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_HW_SCANNER_DIR = os.path.join(_THIS_DIR, '..', 'hardware', 'scanner')
sys.path.insert(0, _HW_SCANNER_DIR)

import serial
import serial.tools.list_ports

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QComboBox, QPushButton, QMessageBox,
    QScrollArea, QFrame,
)

from Scanner import Scanner
from sim_scanner import FakeSerial

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
# Read-only lookup, so the Arduino PT100's port can be marked (never preselected)
# in the port list without hard-coding a COM number anywhere (spec 5.1).
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


def _derive_r_step_unit():
    """
    R_STEP_UNIT (R's mechanical resolution, 1.8 deg/step) read straight out
    of Scanner.__init__'s source instead of hand-writing the number here (so
    it can't silently drift from Scanner.py) — without paying the ~2 s /
    20-command cost of actually instantiating a Scanner (even over the
    simulator) just to read one attribute.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(Scanner.__init__)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Attribute) and target.attr == 'uStepR'
                        and isinstance(target.value, ast.Name) and target.value.id == 'self'):
                    return float(ast.literal_eval(node.value))
    raise RuntimeError('Could not derive R_STEP_UNIT from Scanner.uStepR.')


R_STEP_UNIT = _derive_r_step_unit()


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


def round_r_step(value):
    """R step field: nearest multiple of R_STEP_UNIT, at least one unit (1.8 deg)."""
    n = max(1, round(value / R_STEP_UNIT))
    return round(n * R_STEP_UNIT, 6)


def round_r_target(value):
    """R Go / '=N' target: nearest multiple of R_STEP_UNIT (0 is allowed)."""
    n = round(value / R_STEP_UNIT)
    return round(n * R_STEP_UNIT, 6)


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
    limits = pyqtSignal(tuple)    # (Xlim, Ylim, Zlim, Rlim)
    busy = pyqtSignal(bool)
    error = pyqtSignal(str)
    message = pyqtSignal(str)

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
        elif op == 'move_sequence':
            self._do_move_sequence(cmd[1])
        elif op == 'set_limits':
            self._do_set_limits(cmd[1])
        elif op == 'set_zero':
            self._do_set_zero(cmd[1])
        elif op == 'set_value':
            self._do_set_value(*cmd[1:])
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
    def _do_move_axis(self, axis, value):
        if self.scanner is None:
            return
        self.busy.emit(True)
        try:
            self.scanner.moveAxis(axis, value)
            self.moved.emit(self.scanner.getCoords())
        finally:
            self.busy.emit(False)

    def _do_move_sequence(self, axis_targets):
        """
        Fix 5 (go-to-origin): moves one axis at a time, in the given order,
        going through Scanner.moveAxis exactly like a single manual move.
        STOP (see ScannerPanel._on_stop_clicked) both interrupts whichever
        axis is currently moving (via the shared serial proxy, same as any
        other move) and sets _abort_sequence, so the sequence stops there
        instead of continuing to the next axis.
        """
        if self.scanner is None:
            return
        self._abort_sequence.clear()
        self.busy.emit(True)
        try:
            for axis, target in axis_targets:
                if self._abort_sequence.is_set():
                    break
                self.scanner.moveAxis(axis, target)
                self.moved.emit(self.scanner.getCoords())
                if self._abort_sequence.is_set():
                    break
        finally:
            self.busy.emit(False)

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

    def _do_set_value(self, axis, value):
        if self.scanner is None:
            return
        self.busy.emit(True)
        try:
            self.scanner.setAxis(axis, value)
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

    def __init__(self, use_sim=False, parent=None):
        super().__init__(parent)
        self._use_sim = use_sim
        self.setWindowTitle('ECOS Scanner Panel' + (' (simulator)' if use_sim else ''))
        self.resize(460, 900)

        self._connected = False
        self._busy = False
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
        self._steps = {ax: float(self._session.get('steps', {}).get(ax, R_STEP_UNIT if ax == 'R' else 1.0))
                        for ax in AXES}
        self._speeds = {ax: int(self._session.get('speeds', {}).get(ax, 100))
                         for ax in AXES}

        self._movement_widgets = []
        self._session_widgets = []

        self._port_lock = threading.Lock()
        self._worker = ScannerWorker(self._port_lock)
        self._worker.connected.connect(self._on_connected)
        self._worker.disconnected.connect(self._on_disconnected)
        self._worker.moved.connect(self._on_moved)
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
        self._refresh_role_step_speed_fields()
        self._update_enabled_state()

    # =======================================================================
    #  UI construction
    # =======================================================================
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setSpacing(6)

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
        # edit, 2 apply-limit button, 3 step edit, 4 speed edit, 5 zero
        # button, 6-7 set-value edit + '=N' button (merged header, spanning
        # both, since they act together). Placed explicitly, column by
        # column, rather than via a flat list that is easy to get out of
        # sync with the widgets below (that was the phase-1 bug: 'Zero' and
        # '=N' ended up shifted one column to the right).
        grid.addWidget(QLabel('<b>Axis</b>'), 0, 0)
        grid.addWidget(QLabel('<b>Limit</b>'), 0, 1)
        grid.addWidget(QLabel('<b>Step (mm / °)</b>'), 0, 3)
        grid.addWidget(QLabel('<b>Speed</b>'), 0, 4)
        grid.addWidget(QLabel('<b>Zero</b>'), 0, 5)
        lbl_setvalue_header = QLabel('<b>Set value</b>')
        lbl_setvalue_header.setAlignment(Qt.AlignCenter)
        grid.addWidget(lbl_setvalue_header, 0, 6, 1, 2)

        self._edit_limit = {}
        self._edit_step = {}
        self._edit_speed = {}
        self._edit_setvalue = {}

        for r, role in enumerate(ROLE_ORDER, start=1):
            grid.addWidget(self._lbl_role_name_for_session(role), r, 0)

            edit_limit = QLineEdit()
            edit_limit.setFixedWidth(70)
            self._edit_limit[role] = edit_limit
            grid.addWidget(edit_limit, r, 1)

            btn_apply_limit = QPushButton('Apply')
            btn_apply_limit.clicked.connect(self._make_apply_limit_handler(role))
            grid.addWidget(btn_apply_limit, r, 2)

            edit_step = QLineEdit()
            edit_step.setFixedWidth(60)
            self._edit_step[role] = edit_step
            if role == 'R':  # role 'R' always maps to axis 'R', fix 1
                edit_step.editingFinished.connect(self._on_r_step_edited)
            grid.addWidget(edit_step, r, 3)

            edit_speed = QLineEdit()
            edit_speed.setFixedWidth(60)
            self._edit_speed[role] = edit_speed
            grid.addWidget(edit_speed, r, 4)

            btn_zero = QPushButton('Zero')
            btn_zero.clicked.connect(self._make_zero_handler(role))
            grid.addWidget(btn_zero, r, 5)

            edit_setvalue = QLineEdit()
            edit_setvalue.setFixedWidth(60)
            self._edit_setvalue[role] = edit_setvalue
            grid.addWidget(edit_setvalue, r, 6)

            btn_setvalue = QPushButton('=N')
            btn_setvalue.clicked.connect(self._make_setvalue_handler(role))
            grid.addWidget(btn_setvalue, r, 7)

            self._session_widgets += [edit_limit, btn_apply_limit, edit_step, edit_speed,
                                       btn_zero, edit_setvalue, btn_setvalue]
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

    # -- Movement (spec 5.3) --------------------------------------------------
    def _build_movement_group(self):
        group = QGroupBox('Manual movement')
        layout = QVBoxLayout(group)

        grid = QGridLayout()
        self._edit_goto = {}
        for r, role in enumerate(ROLE_ORDER):
            lbl = QLabel()
            if not hasattr(self, '_lbl_role_name_move'):
                self._lbl_role_name_move = {}
            self._lbl_role_name_move[role] = lbl
            grid.addWidget(lbl, r, 0)

            btn_minus = QPushButton('-')
            btn_minus.setFixedWidth(30)
            btn_minus.clicked.connect(self._make_step_handler(role, -1))
            grid.addWidget(btn_minus, r, 1)

            btn_plus = QPushButton('+')
            btn_plus.setFixedWidth(30)
            btn_plus.clicked.connect(self._make_step_handler(role, +1))
            grid.addWidget(btn_plus, r, 2)

            edit_goto = QLineEdit()
            edit_goto.setFixedWidth(70)
            self._edit_goto[role] = edit_goto
            grid.addWidget(edit_goto, r, 3)

            btn_goto = QPushButton('Go')
            btn_goto.clicked.connect(self._make_goto_handler(role))
            grid.addWidget(btn_goto, r, 4)

            self._movement_widgets += [btn_minus, btn_plus, edit_goto, btn_goto]
        layout.addLayout(grid)

        # Fix 5: fixed physical-axis order (R, Z, X, Y), regardless of which
        # axis is currently mapped to "beam".
        btn_goto_origin = QPushButton('Go to origin (R, Z, X, Y)')
        btn_goto_origin.clicked.connect(self._on_goto_origin_clicked)
        layout.addWidget(btn_goto_origin)
        self._movement_widgets.append(btn_goto_origin)

        note = QLabel('SN (unlimitedDiffMove) is never used. Every target is checked '
                       'against the limits before it is sent.')
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
            arduino_port = self._read_arduino_port()
            ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)
            for p in ports:
                label = f'{p.device} — {p.description}'
                if arduino_port and p.device == arduino_port:
                    label += '  [Arduino PT100 — not the scanner]'
                self._cmb_port.addItem(label, p.device)
            last_port = self._session.get('last_port', '')
            if last_port and last_port != arduino_port:
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
        self._lbl_result.setText(f'Connecting to {port_name}...')
        self._worker.enqueue(('connect', port_name, is_sim))

    def _on_disconnect_clicked(self):
        self._worker.enqueue(('disconnect',))

    def _on_stop_clicked(self):
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
        self._lbl_result.setText(msg)
        self._update_enabled_state()

    def _on_disconnected(self):
        self._connected = False
        self._awaiting_ack = False
        self._pending_post_connect_check = False
        self._coords = {ax: 0.0 for ax in AXES}
        self._refresh_position_labels()
        self._lbl_result.setText('Disconnected.')
        self._update_enabled_state()

    def _on_moved(self, coords_tuple):
        self._coords = dict(zip(AXES, coords_tuple))
        self._refresh_position_labels()

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
        self._refresh_role_step_speed_fields()

    def _on_pe_side_changed(self, index):
        self._pe_side = 'origin' if index == 0 else 'max'

    def _capture_role_edits_into_state(self):
        """Reads whatever is currently typed in the step/speed fields into the
        per-real-axis session state, before swapping which axis a role points
        to (or before saving), so in-progress edits are not silently lost."""
        for role in ROLE_ORDER:
            axis = self._role_axis[role]
            step = self._read_float(self._edit_step[role], None)
            if step is not None:
                self._steps[axis] = step
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

    def _refresh_role_step_speed_fields(self):
        for role in ROLE_ORDER:
            axis = self._role_axis[role]
            self._edit_step[role].setText(f'{self._steps.get(axis, 1.0):g}')
            self._edit_speed[role].setText(str(self._speeds.get(axis, 100)))

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

    def _on_r_step_edited(self):
        """Fix 1: the R step field only accepts multiples of R_STEP_UNIT
        (min. one unit); round it as soon as the user leaves the field."""
        edit = self._edit_step['R']
        value = self._read_float(edit, None)
        if value is None:
            return
        rounded = round_r_step(value)
        edit.setText(f'{rounded:g}')
        if abs(rounded - value) > 1e-6:
            self._lbl_result.setText(
                f'R step rounded to {rounded:g}° (multiple of {R_STEP_UNIT:g}°).'
            )

    def _make_step_handler(self, role, sign):
        def handler():
            axis = self._role_axis[role]
            step = self._read_float(self._edit_step[role], None)
            if step is None:
                QMessageBox.warning(self, 'Scanner', 'Invalid step value.')
                return
            if axis == 'R':
                rounded_step = round_r_step(step)
                if abs(rounded_step - step) > 1e-6:
                    self._edit_step[role].setText(f'{rounded_step:g}')
                    self._lbl_result.setText(
                        f'R step rounded to {rounded_step:g}° (multiple of {R_STEP_UNIT:g}°).'
                    )
                step = rounded_step
            current = self._coords.get(axis, 0.0)
            target = round(current + sign * step, 4)
            if not self._validate_target(axis, target):
                return
            self._worker.enqueue(('move_axis', axis, target))
        return handler

    def _make_goto_handler(self, role):
        def handler():
            axis = self._role_axis[role]
            target = self._read_float(self._edit_goto[role], None)
            if target is None:
                QMessageBox.warning(self, 'Scanner', 'Invalid target value.')
                return
            if axis == 'R':
                rounded_target = round_r_target(target)
                if abs(rounded_target - target) > 1e-6:
                    self._edit_goto[role].setText(f'{rounded_target:g}')
                    self._lbl_result.setText(
                        f'R target rounded to {rounded_target:g}° (multiple of {R_STEP_UNIT:g}°).'
                    )
                target = rounded_target
            if not self._validate_target(axis, target):
                return
            self._worker.enqueue(('move_axis', axis, target))
        return handler

    def _on_goto_origin_clicked(self):
        """
        Fix 5: moves every axis that is not already at 0 to 0, one axis at a
        time, in the fixed physical order R, Z, X, Y (never reordered by
        which axis is currently "beam"). Confirms first, showing that order
        and each axis' current -> final position. Goes through the worker's
        move_sequence command, exactly like any other move, so STOP (which
        also calls ScannerWorker.request_sequence_abort) stops the sequence
        after whichever axis is interrupted instead of moving on.
        """
        pending = [(ax, self._coords.get(ax, 0.0)) for ax in GO_TO_ORIGIN_AXIS_ORDER
                   if abs(self._coords.get(ax, 0.0)) > 1e-9]
        if not pending:
            self._lbl_result.setText('All axes are already at 0.')
            return

        axis_targets = []
        for ax, _cur in pending:
            if not self._validate_target(ax, 0.0):
                return
            axis_targets.append((ax, 0.0))

        order_text = ' -> '.join(ax for ax, _ in pending)
        lines = '\n'.join(
            f'  {ax}: {fmt_pos(ax, cur)} -> {fmt_pos(ax, 0.0)}' for ax, cur in pending
        )
        resp = QMessageBox.question(
            self, 'Scanner',
            f'Move to origin in this order: {order_text}\n\n{lines}\n\nProceed?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        self._worker.enqueue(('move_sequence', axis_targets))

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

    def _make_setvalue_handler(self, role):
        def handler():
            axis = self._role_axis[role]
            value = self._read_float(self._edit_setvalue[role], None)
            if value is None:
                QMessageBox.warning(self, 'Scanner', 'Invalid value.')
                return
            if axis == 'R':
                rounded_value = round_r_target(value)
                if abs(rounded_value - value) > 1e-6:
                    self._edit_setvalue[role].setText(f'{rounded_value:g}')
                    self._lbl_result.setText(
                        f'R value rounded to {rounded_value:g}° (multiple of {R_STEP_UNIT:g}°).'
                    )
                value = rounded_value
            if not self._validate_target(axis, value):
                return
            self._worker.enqueue(('set_value', axis, value))
        return handler

    def _on_apply_speeds_clicked(self):
        self._capture_role_edits_into_state()
        speeds = {ax: int(self._speeds.get(ax, 100)) for ax in AXES}
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
        self._steps = {ax: float(d.get('steps', {}).get(ax, R_STEP_UNIT if ax == 'R' else 1.0)) for ax in AXES}
        self._speeds = {ax: int(d.get('speeds', {}).get(ax, 100)) for ax in AXES}

        self._refresh_role_label_texts()
        self._refresh_all_role_limit_fields()
        self._refresh_role_step_speed_fields()

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
            'steps': dict(self._steps),
            'speeds': dict(self._speeds),
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
        can_move = connected and not self._busy
        can_use_session = unlocked and not self._busy

        self._btn_connect.setEnabled(not connected and not self._busy)
        self._btn_disconnect.setEnabled(connected)
        self._cmb_port.setEnabled(not connected and not self._use_sim)
        self._btn_refresh.setEnabled(not connected and not self._use_sim)

        for w in self._movement_widgets:
            w.setEnabled(can_move)
        for w in self._session_widgets:
            w.setEnabled(can_use_session)

        self._btn_stop.setEnabled(True)  # always active, per spec

        if not connected:
            self._lbl_state.setText('Disconnected')
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

    # =======================================================================
    #  Shutdown
    # =======================================================================
    def closeEvent(self, event):
        self._capture_role_edits_into_state()
        self._write_session_file()
        if self._worker is not None:
            self._worker.enqueue(('disconnect',))
            self._worker.stop_thread()
            self._worker.wait(2000)
        event.accept()


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
