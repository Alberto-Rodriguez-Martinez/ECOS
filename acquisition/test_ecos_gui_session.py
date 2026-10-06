# -*- coding: utf-8 -*-
"""
test_ecos_gui_session.py — the GUI in simulator mode: default Smin–Smax holding the
front echo, and a temporary session file (the hardware session is never touched).

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

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

HW_SESSION = os.path.join(_HERE, 'ecos_gui_session.json')
SIM_SESSION = os.path.join(_HERE, 'ecos_gui_session_sim.json')


def _digest(path):
    if not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


class TestGuiSimulatorSession(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = tempfile.mkdtemp(prefix='ecos_gui_session_test_')
        cls.session = os.path.join(cls.tmp, 'session.json')
        cls.before = {p: _digest(p) for p in (HW_SESSION, SIM_SESSION)}
        # ecos_gui parses sys.argv and changes the working directory at import
        cls._argv, cls._cwd = sys.argv, os.getcwd()
        cls._boxes = {n: getattr(QMessageBox, n) for n in ('question', 'information', 'warning')}
        for n in cls._boxes:
            setattr(QMessageBox, n, staticmethod(lambda *a, **k: QMessageBox.Yes))
        sys.argv = [os.path.join(_HERE, 'ecos_gui.py'), '--demo', '--session', cls.session]
        try:
            cls.gui = importlib.import_module('ecos_gui')
        finally:
            sys.argv = cls._argv
            os.chdir(cls._cwd)

    @classmethod
    def tearDownClass(cls):
        for n, f in cls._boxes.items():
            setattr(QMessageBox, n, f)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_session_file_is_the_temporary_one(self):
        self.assertEqual(self.gui.SESSION_FILE, self.session)

    def test_default_window_holds_the_front_echo_and_hardware_session_untouched(self):
        self.assertFalse(os.path.exists(self.session))            # nothing restored
        win = self.gui.EcosGUI()
        try:
            smin, smax = win._get_smin_smax()
            sim = win._sedaq
            p = sim.params
            front = sim.front_tof(p.x_focus, p.lat0, p.z0) * p.fs
            back = sim.back_tof(p.x_focus, p.lat0, p.z0) * p.fs
            self.assertLess(smin, front - 100)
            self.assertGreater(smax, front + 100)
            self.assertGreater(smax, back)                         # the back wall too
            self.assertGreater(smin, 50)                           # not the main bang
            self.assertLess(smax, 2 * front)                       # nor the reverberation
        finally:
            win.close()
        self.assertTrue(os.path.exists(self.session))             # saved where asked
        with open(self.session) as f:
            region = json.load(f)['region']
        self.assertAlmostEqual(region[0], smin, delta=1)
        for path, digest in self.before.items():                  # never the real ones
            self.assertEqual(_digest(path), digest, path)


if __name__ == '__main__':
    unittest.main()
