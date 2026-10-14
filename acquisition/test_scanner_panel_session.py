# -*- coding: utf-8 -*-
"""
test_scanner_panel_session.py — the scanner panel's session file (scanner_panel.py):
a damaged one is kept as .bak, the defaults are used and it is said; a failed save
on closing is reported. Simulator only (use_sim=True): no port is opened, nothing
moves. A temporary session file: the real hardware/scanner/scanner_session.json is
never touched by these tests.

Run from the repo root with the 32-bit interpreter of the machine (CLAUDE.md):
    python -m unittest discover -s acquisition
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from PyQt5.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

import scanner_panel as sp  # noqa: E402


class _Panel(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='scanner_session_test_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, 'scanner_session.json')
        patcher = mock.patch.object(sp, 'SESSION_FILE', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open_with(self, content):
        if content is not None:
            with open(self.path, 'w') as f:
                f.write(content if isinstance(content, str) else json.dumps(content))
        out = io.StringIO()
        with redirect_stdout(out):
            panel = sp.ScannerPanel(use_sim=True)
        self.addCleanup(panel.shutdown)
        return panel, out.getvalue()


class TestScannerPanelSession(_Panel):

    def test_valid_session_read(self):
        panel, _ = self.open_with({'beam_axis': 'X', 'pe_side': 'max',
                                   'limits': {'X': 80.0}, 'speeds': {'X': 50}})
        self.assertIsNone(panel.session_notice)
        self.assertEqual((panel.role_axis('beam'), panel.pe_side()), ('X', 'max'))
        self.assertEqual(panel.axis_limit('X'), 80.0)
        self.assertFalse(os.path.exists(self.path + '.bak'))

    def test_no_file_defaults_silently(self):
        panel, printed = self.open_with(None)
        self.assertIsNone(panel.session_notice)
        self.assertEqual(panel.role_axis('beam'), 'Y')
        self.assertNotIn('could not be read', printed)

    def test_not_json(self):
        content = '{"beam_axis": "X", "limits": {'
        panel, printed = self.open_with(content)
        self.assertIn('could not be read', panel.session_notice)
        self.assertIn('could not be read', printed)                    # console
        self.assertIn('could not be read', panel._lbl_result.text())   # on screen
        self.assertEqual(panel.role_axis('beam'), 'Y')                 # defaults
        with open(self.path + '.bak') as f:
            self.assertEqual(f.read(), content)
        panel.shutdown()                                               # writes a valid one…
        with open(self.path) as f:
            json.load(f)
        with open(self.path + '.bak') as f:                            # …the backup stays
            self.assertEqual(f.read(), content)

    def test_wrong_types(self):
        panel, _ = self.open_with({'beam_axis': 'X', 'limits': {'X': 'abc'}})
        self.assertIn('ValueError', panel.session_notice)
        self.assertTrue(os.path.exists(self.path + '.bak'))
        self.assertEqual(panel.role_axis('beam'), 'Y')                 # all defaults
        self.assertEqual(panel.axis_limit('X'), sp.SESSION_DEFAULT_LIMITS_MM['X'])

    def test_load_button_with_a_damaged_file_keeps_the_values(self):
        panel, _ = self.open_with({'beam_axis': 'X', 'limits': {'X': 70.0}})
        with open(self.path, 'w') as f:
            json.dump({'beam_axis': 'Y', 'limits': {'X': 'abc'}}, f)
        with redirect_stdout(io.StringIO()):
            panel._on_load_session_clicked()
        self.assertIn('could not be read', panel._lbl_result.text())
        self.assertIn('current values are kept', panel._lbl_result.text())
        self.assertEqual((panel.role_axis('beam'), panel.axis_limit('X')), ('X', 70.0))
        self.assertTrue(os.path.exists(self.path + '.bak'))

    def test_failed_save_is_reported(self):
        panel, _ = self.open_with(None)
        os.makedirs(self.path)                          # a directory: open(..., 'w') fails
        out = io.StringIO()
        with redirect_stdout(out):
            panel.shutdown()
        self.assertIn('Could not save session', out.getvalue())


class TestPeSideDefault(_Panel):
    """PE side defaults to Max (the real set-up); a saved session overrides it."""

    def test_default_max(self):
        panel, _ = self.open_with(None)
        self.assertEqual(panel.pe_side(), 'max')
        self.assertEqual(panel._cmb_pe_side.currentText(), 'Max')
        self.assertIn('pulse-echo (PE) transducer', panel._cmb_pe_side.toolTip())
        self.assertIn('beam-axis travel', panel._cmb_pe_side.toolTip())

    def test_session_overrides(self):
        panel, _ = self.open_with({'pe_side': 'origin'})
        self.assertEqual(panel.pe_side(), 'origin')
        self.assertEqual(panel._cmb_pe_side.currentText(), 'Origin')


class TestEnglishLabels(_Panel):

    def test_free_movement_and_r_step_labels(self):
        from PyQt5.QtWidgets import QLabel
        panel, _ = self.open_with(None)
        self.assertEqual(panel._btn_free_movement.text(), 'Free movement (no limits)')
        self.assertEqual(panel._chk_r_stepwise.text(), 'Move R step by step')
        texts = [lbl.text() for lbl in panel.findChildren(QLabel)]
        self.assertIn('Pause between R steps (ms):', texts)
        self.assertIn('FREE MOVEMENT — no limit protection', texts)
        self.assertFalse([t for t in texts if 'Movimiento' in t or 'paso a paso' in t])


class TestApplyLimitGui(_Panel):
    """Apply: the GUI refuses a limit below the current position, without sending it."""

    def setUp(self):
        super().setUp()
        self.panel, _ = self.open_with(None)              # beam Y: lateral is X
        self.panel._coords['X'] = 50.0
        self.panel._limits['X'] = 100.0
        self.sent = []
        self.panel._worker.enqueue = self.sent.append

    def apply(self, role, value):
        self.panel._edit_limit[role].setText(str(value))
        with mock.patch.object(sp.QMessageBox, 'warning') as warn:
            self.panel._make_apply_limit_handler(role)()
        return warn

    def test_above_and_equal_are_sent_with_the_check(self):
        for value in (80.0, 50.0):
            with self.subTest(limit=value):
                self.sent.clear()
                warn = self.apply('lateral', value)
                self.assertFalse(warn.called)
                self.assertEqual(self.sent, [('set_limits', {'X': value}, ('X',))])

    def test_below_is_refused_and_the_old_limit_kept(self):
        warn = self.apply('lateral', 30.0)
        self.assertEqual(self.sent, [])                          # nothing sent
        self.assertIn('X is at 50.00 mm, above the new limit 30', warn.call_args[0][2])
        self.assertIn('Limit not changed', self.panel._lbl_result.text())
        self.assertEqual(self.panel._edit_limit['lateral'].text(), '100')   # field restored

    def test_r_is_not_checked(self):
        self.panel._coords['R'] = 270.0
        warn = self.apply('R', 180.0)
        self.assertFalse(warn.called)
        self.assertEqual(self.sent, [('set_limits', {'R': 180.0}, ())])


class TestApplyLimitWorker(unittest.TestCase):
    """The worker checks again with the position READ BACK from the controller, and
    reports a reply other than OK (simulated controller, no port)."""

    @classmethod
    def setUpClass(cls):
        import threading
        from hardware.scanner.Scanner import Scanner
        from hardware.scanner.sim_scanner import FakeSerial
        cls.raw = FakeSerial(port='SIM', timeout=0.1, time_scale=1000.0)
        cls.worker = sp.ScannerWorker(threading.Lock())
        cls.worker.ser = sp._LockingSerialProxy(cls.raw, threading.Lock())
        cls.worker.scanner = Scanner(port='SIM', ser=cls.worker.ser)

    def setUp(self):
        self.errors, self.limits = [], []
        self.worker.error.connect(self.errors.append)
        self.worker.limits.connect(self.limits.append)
        self.addCleanup(self.worker.error.disconnect)
        self.addCleanup(self.worker.limits.disconnect)
        self.worker.scanner.setAxisLimit('X', 100.0)
        self.worker.scanner.setAxis('X', 50.0)                    # SA: no motion

    def limit_x(self):
        return dict(zip(sp.AXES, self.limits[-1]))['X']

    def test_above_equal_below(self):
        for value, accepted in ((80.0, True), (50.0, True), (30.0, False)):
            with self.subTest(limit=value):
                self.worker.scanner.setAxisLimit('X', 100.0)
                self.errors.clear()
                self.worker._do_set_limits({'X': value}, ('X',))
                self.assertEqual(self.limit_x(), value if accepted else 100.0)
                self.assertEqual(bool(self.errors), not accepted)
                if not accepted:
                    self.assertIn('above the new limit', self.errors[-1])

    def test_stale_gui_position_does_not_matter(self):
        """The GUI may think the axis is low; the controller says 50 mm."""
        self.worker._do_set_limits({'X': 30.0}, ('X',))
        self.assertEqual(self.limit_x(), 100.0)

    def test_er_reply_is_reported(self):
        orig = self.raw._handle_locked

        def reject_sl(text):
            if text.startswith('SL'):
                return self.raw._reject(text[2]), 0.0
            return orig(text)
        with mock.patch.object(self.raw, '_handle_locked', reject_sl):
            self.worker._do_set_limits({'X': 80.0}, ('X',))
        self.assertTrue(self.errors)
        self.assertIn('did not accept the limit 80', self.errors[-1])
        self.assertIn('ERX', self.errors[-1])
        self.assertEqual(self.limit_x(), 100.0)                   # the one read back

    def test_r_without_check_is_sent(self):
        self.worker.scanner.setAxis('R', 270.0)
        self.worker._do_set_limits({'R': 180.0}, ())
        self.assertEqual(dict(zip(sp.AXES, self.limits[-1]))['R'], 180.0)
        self.worker.scanner.setAxisLimit('R', 360.0)


if __name__ == '__main__':
    unittest.main()
