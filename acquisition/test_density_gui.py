# -*- coding: utf-8 -*-
"""
test_density_gui.py — density GUI in demo mode: T and c_w from the restored field,
the Arduino opened and closed on every reading, an acquisition that cannot loop
forever and can be cancelled, and a damaged session kept aside. A temporary session
file: the real density_gui_session.json is never touched.

Run from the repo root with the 32-bit interpreter of the machine (CLAUDE.md):
    python -m unittest discover -s acquisition
"""
import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import numpy as np  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

REAL_SESSION = os.path.join(_HERE, 'density_gui_session.json')
_ENV = {}


def _digest(path):
    if not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def setUpModule():
    """density_gui in demo mode with a temporary session (it parses sys.argv and changes
    the working directory at import)."""
    _ENV['app'] = QApplication.instance() or QApplication([])
    _ENV['tmp'] = tempfile.mkdtemp(prefix='density_gui_test_')
    _ENV['session'] = os.path.join(_ENV['tmp'], 'session.json')
    _ENV['before'] = _digest(REAL_SESSION)
    _ENV['boxes'] = {n: getattr(QMessageBox, n) for n in ('question', 'information', 'warning',
                                                           'critical')}
    for n in _ENV['boxes']:
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: QMessageBox.Ok))
    argv, cwd = sys.argv, os.getcwd()
    sys.argv = [os.path.join(_HERE, 'density_gui.py'), '--demo', '--session', _ENV['session']]
    try:
        _ENV['gui'] = importlib.import_module('density_gui')
    finally:
        sys.argv = argv
        os.chdir(cwd)


def tearDownModule():
    for n, f in _ENV['boxes'].items():
        setattr(QMessageBox, n, f)
    shutil.rmtree(_ENV['tmp'], ignore_errors=True)
    assert _digest(REAL_SESSION) == _ENV['before'], 'density_gui_session.json was modified'


class _Window(unittest.TestCase):

    session = None          # dict written as the session before opening, None: no file

    def setUp(self):
        for p in os.listdir(_ENV['tmp']):
            os.remove(os.path.join(_ENV['tmp'], p))
        if self.session is not None:
            with open(_ENV['session'], 'w') as f:
                f.write(self.session if isinstance(self.session, str)
                        else json.dumps(self.session))
        self.dg = _ENV['gui']
        self.win = self.dg.DensityGUI()
        self.win._timer.stop()
        self.addCleanup(self.win.close)


class TestSessionFileIsTemporary(_Window):

    def test_demo_and_session(self):
        self.assertEqual(self.dg.SESSION_FILE, _ENV['session'])
        self.assertTrue(self.win._demo)


class TestTemperatureAtStart(_Window):
    """1: T and c_w from what the restored field shows."""

    session = {"temp_manual": "23.17"}

    def test_from_the_restored_field(self):
        self.assertEqual(self.win._txt_temp_manual.text(), "23.17")
        self.assertAlmostEqual(self.win._T, 23.17)
        self.assertAlmostEqual(self.win._cw, self.dg.cw_from_temperature(23.17))
        self.assertNotEqual(self.win._cw, self.dg.C_W_DEFAULT)
        label = self.win._lbl_cw.text()
        self.assertIn(f"cw = {self.win._cw:.1f} m/s", label)  # what the calculation uses
        self.assertIn("(manual)", label)


class TestTemperatureFieldNotANumber(_Window):

    session = {"temp_manual": "abc"}

    def test_default_kept_and_said(self):
        self.assertEqual((self.win._T, self.win._cw), (self.dg.T_DEFAULT, self.dg.C_W_DEFAULT))
        label = self.win._lbl_cw.text()
        self.assertIn("cw = 1480.0 m/s  (default)", label)
        self.assertIn("not a number", label)
        self.win._txt_temp_manual.setText("")                  # emptied later: same
        self.win._on_temp_manual_changed()
        self.assertIn("empty or not a number", self.win._lbl_cw.text())
        self.win._txt_temp_manual.setText("30")
        self.win._on_temp_manual_changed()
        self.assertAlmostEqual(self.win._cw, self.dg.cw_from_temperature(30.0))
        self.assertNotIn("not a number", self.win._lbl_cw.text())


class FakeArduinoPorts:
    """Arduino-like objects on simulated ports: a second open of a port that was not
    closed fails, as a busy COM port does on Windows."""

    def __init__(self, temps=(24.0, 24.2), fail_open=False):
        self.open, self.opens, self.temps, self.fail_open = set(), 0, temps, fail_open

    def __call__(self, port):
        if self.fail_open or port in self.open:
            raise OSError(f"could not open port '{port}': PermissionError(13, 'Access is denied.')")
        self.open.add(port)
        self.opens += 1
        ports = self

        class _Arduino:
            def getTemperatures(self):
                return ports.temps

            def close(self):
                ports.open.discard(port)
        return _Arduino()


class TestArduinoReading(_Window):
    """2: opened and closed on every press; a port that cannot be opened is said, with
    nothing changed."""

    def test_two_readings_in_a_row(self):
        ports = FakeArduinoPorts()
        self.win._arduino_factory = ports
        self.win._on_read_arduino()
        self.win._on_read_arduino()                             # would fail if left open
        self.assertEqual(ports.opens, 2)
        self.assertEqual(ports.open, set())
        self.assertAlmostEqual(self.win._T, 24.1)
        self.assertAlmostEqual(self.win._cw, (self.dg.cw_from_temperature(24.0)
                                              + self.dg.cw_from_temperature(24.2)) / 2.0)
        self.assertEqual(self.win._txt_temp_manual.text(), "24.10")
        self.assertIn("(Arduino)", self.win._lbl_cw.text())

    def test_port_cannot_be_opened(self):
        before = (self.win._T, self.win._cw, self.win._lbl_cw.text())
        self.win._arduino_factory = FakeArduinoPorts(fail_open=True)
        with mock.patch.object(self.dg.QMessageBox, 'warning') as warn:
            self.win._on_read_arduino()
        self.assertEqual(warn.call_count, 1)
        self.assertIn("Could not read the Arduino", warn.call_args[0][2])
        self.assertIn("unchanged", warn.call_args[0][2])
        self.assertEqual((self.win._T, self.win._cw, self.win._lbl_cw.text()), before)

    def test_no_data(self):
        before = (self.win._T, self.win._cw)
        self.win._arduino_factory = FakeArduinoPorts(temps=(None, None))
        with mock.patch.object(self.dg.QMessageBox, 'warning') as warn:
            self.win._on_read_arduino()
        self.assertIn("No temperature", warn.call_args[0][2])
        self.assertEqual((self.win._T, self.win._cw), before)


class _ZeroSeDaq:
    """A digitizer that only delivers constant (all-zero after the mean) captures."""

    def __init__(self, reclen):
        self.RecLen, self.calls = reclen, 0
        self.DataADC2 = [512] * reclen

    def GetAScan(self):
        self.calls += 1


class TestAcquisition(_Window):
    """3: a bounded number of attempts, a clear message, the GUI usable; Cancel."""

    def test_all_zero_captures_give_up(self):
        self.win._sedaq = _ZeroSeDaq(self.win._reclen)
        self.win._txt_n_avg.setText("5")
        with mock.patch.object(self.dg.QMessageBox, 'critical') as crit:
            self.win._on_acquire_sw1()
        self.assertEqual(self.win._sedaq.calls, self.dg.AVG_MAX_ATTEMPTS_FACTOR * 5)
        self.assertIn("only 0 of 5 valid captures", crit.call_args[0][2])
        self.assertIsNone(self.win._sW1)
        self.assertTrue(self.win._timer.isActive())             # live view back: usable

    def test_valid_capture_after_some_zeros(self):
        z = _ZeroSeDaq(self.win._reclen)
        good = list(np.random.default_rng(0).integers(400, 600, self.win._reclen))

        def get():
            z.calls += 1
            z.DataADC2 = good if z.calls % 3 == 0 else [512] * z.RecLen
        z.GetAScan = get
        self.win._sedaq = z
        self.win._txt_n_avg.setText("4")
        self.win._on_acquire_sw1()
        self.assertIsNotNone(self.win._sW1)
        self.assertEqual(z.calls, 12)                           # 4 valid among 12 (≤ 16)

    def test_cancel(self):
        self.win._sW1 = "previous"
        with mock.patch.object(self.dg.QProgressDialog, 'wasCanceled', return_value=True):
            self.win._on_acquire_sw1()
        self.assertEqual(self.win._sW1, "previous")             # nothing stored
        self.assertIn("cancelled", self.win._lbl_acq_status.text())
        self.assertTrue(self.win._timer.isActive())


class TestDamagedSession(_Window):
    """6: kept as .bak, defaults, said in the status bar; the next session written on
    close does not overwrite the backup."""

    session = '{"gain_ch2": "40", "voltage": '

    def test_kept_aside(self):
        self.assertIn("could not be read", self.win.statusBar().currentMessage())
        with open(_ENV['session'] + '.bak') as f:
            self.assertEqual(f.read(), self.session)
        self.assertEqual(self.win._txt_gain_ch2.text(), str(self.dg.DEFAULT_GAIN))
        self.win.close()
        with open(_ENV['session']) as f:
            json.load(f)
        with open(_ENV['session'] + '.bak') as f:
            self.assertEqual(f.read(), self.session)


class TestDamagedSessionTypes(_Window):

    session = {"gain_ch2": "40", "relay": True, "region": "not a region",
               "temp_manual": 23}                              # setText(int) raises

    def test_defaults_and_backup(self):
        self.assertIn("could not be read", self.win.statusBar().currentMessage())
        self.assertTrue(os.path.exists(_ENV['session'] + '.bak'))
        self.assertEqual(self.win._txt_gain_ch2.text(), str(self.dg.DEFAULT_GAIN))
        self.assertEqual(self.win._cw_source, "manual")         # the default field, 20 °C


if __name__ == '__main__':
    unittest.main()
