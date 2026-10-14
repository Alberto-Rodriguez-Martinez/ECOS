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


if __name__ == '__main__':
    unittest.main()
