# -*- coding: utf-8 -*-
"""
test_ecos_gui_session.py — the GUI in simulator mode: default Smin–Smax holding the
front echo, a temporary session file (the hardware session is never touched), and the
cross-hair cursor of the live A-scan.

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


_ENV = {}


def setUpModule():
    """ecos_gui in demo mode with a temporary session file, imported once for every test
    here (it parses sys.argv and changes the working directory at import)."""
    _ENV['app'] = QApplication.instance() or QApplication([])
    _ENV['tmp'] = tempfile.mkdtemp(prefix='ecos_gui_session_test_')
    _ENV['session'] = os.path.join(_ENV['tmp'], 'session.json')
    _ENV['before'] = {p: _digest(p) for p in (HW_SESSION, SIM_SESSION)}
    argv, cwd = sys.argv, os.getcwd()
    _ENV['boxes'] = {n: getattr(QMessageBox, n) for n in ('question', 'information', 'warning')}
    for n in _ENV['boxes']:
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: QMessageBox.Yes))
    sys.argv = [os.path.join(_HERE, 'ecos_gui.py'), '--demo', '--session', _ENV['session']]
    try:
        _ENV['gui'] = importlib.import_module('ecos_gui')
    finally:
        sys.argv = argv
        os.chdir(cwd)


def tearDownModule():
    for n, f in _ENV['boxes'].items():
        setattr(QMessageBox, n, f)
    shutil.rmtree(_ENV['tmp'], ignore_errors=True)
    for path, digest in _ENV['before'].items():          # whatever ran here, never the real ones
        assert _digest(path) == digest, f'{path} was modified by the GUI tests'


class TestGuiSimulatorSession(unittest.TestCase):

    def setUp(self):
        self.gui, self.session, self.before = _ENV['gui'], _ENV['session'], _ENV['before']
        if os.path.exists(self.session):                  # start without a saved session
            os.remove(self.session)

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


class _LiveWindow(unittest.TestCase):
    """A fresh GUI window, shown, without a saved session (each window saves its own on
    close, which the next one would restore: check boxes switched off by a test)."""

    def setUp(self):
        if os.path.exists(_ENV['session']):
            os.remove(_ENV['session'])
        self.win = _ENV['gui'].EcosGUI()
        self.win.resize(1400, 900)
        self.win.show()
        QApplication.processEvents()
        self.addCleanup(self.win.close)
        self.plot = self.win._plot_zoom
        self.vb = self.plot.getViewBox()

    def move_to(self, x, y):
        from PyQt5.QtCore import QPointF
        self.win._on_mouse_moved(self.vb.mapViewToScene(QPointF(x, y)))



class TestLiveCursor(_LiveWindow):
    """The live A-scan cursor is a full cross: both lines, one control, values with units."""

    def lines(self):
        return self.win._vline_cursor, self.win._hline_cursor

    def test_cross_follows_the_mouse_and_hides_together(self):
        v, h = self.lines()
        self.assertEqual((v.angle, h.angle), (90, 0))
        self.assertEqual(v.pen.color().getRgb(), h.pen.color().getRgb())      # same style
        self.assertEqual((v.pen.width(), v.pen.style()), (h.pen.width(), h.pen.style()))
        (x0, x1), (y0, y1) = self.vb.viewRange()
        x, y = x0 + 0.4 * (x1 - x0), y0 + 0.7 * (y1 - y0)
        self.move_to(x, y)
        self.assertTrue(v.isVisible() and h.isVisible())
        self.assertAlmostEqual(v.value(), x, delta=1e-6 * abs(x) + 1e-9)
        self.assertAlmostEqual(h.value(), y, delta=1e-6)
        from PyQt5.QtCore import QPointF
        self.win._on_mouse_moved(QPointF(-5000.0, -5000.0))                # off the plot
        self.assertFalse(v.isVisible() or h.isVisible())
        self.assertEqual(self.win._lbl_cursor.text(), '')

    def test_one_control_for_both_lines(self):
        v, h = self.lines()
        (x0, x1), (y0, y1) = self.vb.viewRange()
        self.move_to(0.5 * (x0 + x1), 0.5 * (y0 + y1))
        self.win._chk_cursor.setChecked(False)
        self.assertFalse(v.isVisible() or h.isVisible())
        self.move_to(0.5 * (x0 + x1), 0.5 * (y0 + y1))
        self.assertFalse(v.isVisible() or h.isVisible())                   # stays off
        self.win._chk_cursor.setChecked(True)
        self.move_to(0.5 * (x0 + x1), 0.5 * (y0 + y1))
        self.assertTrue(v.isVisible() and h.isVisible())

    def test_values_with_units_in_every_x_unit(self):
        win = self.win
        for unit, radio in (('samples', win._radio_samples), ('mus', win._radio_mus),
                            ('mm', win._radio_mm)):
            with self.subTest(unit=unit):
                radio.setChecked(True)
                QApplication.processEvents()
                (x0, x1), (y0, y1) = self.vb.viewRange()
                x, y = 0.5 * (x0 + x1), y0 + 0.25 * (y1 - y0)
                self.move_to(x, y)
                text = win._lbl_cursor.text()
                t_us = win._unit_to_us(x)
                self.assertIn(f't = {t_us:.3f} µs', text)
                self.assertIn(f'A = {y:.4f} a.u.', text)
                if unit == 'samples':
                    self.assertAlmostEqual(t_us, x / 100.0, places=6)      # 100 MHz
                    self.assertIn('sample', text)
                if unit == 'mm':
                    self.assertIn('mm', text)


class TestFullScaleLines(_LiveWindow):
    """Faint lines at the quantizer full scale, ±, and the amplitude in % of it."""

    def test_lines_at_full_scale_inside_the_view_behind_the_traces(self):
        gui = _ENV['gui']
        lines = self.win._fullscale_lines
        self.assertEqual(sorted(line.value() for line in lines),
                         [-gui.QUANT_FULL_SCALE, gui.QUANT_FULL_SCALE])
        self.assertEqual(gui.QUANT_FULL_SCALE, 0.5)                 # ±midpoint/full scale
        _, (y0, y1) = self.vb.viewRange()
        for line in lines:
            self.assertEqual(line.angle, 0)
            self.assertTrue(line.isVisible())
            self.assertTrue(y0 < line.value() < y1)                  # not on the border
            self.assertLess(line.zValue(), self.win._curve_zoom_ch2.zValue())
            self.assertLess(line.pen.color().alpha(), 255)          # faint
            self.assertNotEqual(line.pen.color().getRgb(),
                                self.win._vline_cursor.pen.color().getRgb())

    def test_own_check_box_independent_of_the_cursor(self):
        lines = self.win._fullscale_lines
        self.win._chk_fullscale.setChecked(False)
        self.assertFalse(any(line.isVisible() for line in lines))
        self.win._chk_cursor.setChecked(True)                       # the cursor does not bring them
        self.assertFalse(any(line.isVisible() for line in lines))
        self.win._chk_fullscale.setChecked(True)
        self.win._chk_cursor.setChecked(False)
        self.assertTrue(all(line.isVisible() for line in lines))

    def test_amplitude_in_percent_of_full_scale(self):
        (x0, x1), _ = self.vb.viewRange()
        for y, pct in ((0.25, '+50.0 % FS'), (-0.4, '-80.0 % FS'), (0.5, '+100.0 % FS')):
            with self.subTest(y=y):
                self.move_to(0.5 * (x0 + x1), y)
                self.assertIn(f'A = {y:.4f} a.u. ({pct})', self.win._lbl_cursor.text())


class TestSaturationIndicator(_LiveWindow):
    """Red indicator per channel, from the raw counts of the last acquisition."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, os.path.join(_HERE, '..', 'database'))
        from scan_counts import count_at_top, top_mask
        self.count_at_top, self.top_mask = count_at_top, top_mask
        self.lbl = self.win._lbl_sat
        self.sim = self.win._sedaq

    def test_only_when_it_happens_with_the_count(self):
        import numpy as np
        n = self.win._reclen
        clean = np.zeros(n, dtype=bool)
        self.win._show_saturation((clean, clean))
        self.assertFalse(self.lbl[1].isVisible() or self.lbl[2].isVisible())
        ch2 = clean.copy()
        ch2[[10, 500, 501]] = True
        self.win._show_saturation((clean, ch2))
        self.assertFalse(self.lbl[1].isVisible())
        self.assertTrue(self.lbl[2].isVisible())
        self.assertIn('3 samples', self.lbl[2].text())
        self.assertIn('230, 30, 30', self.lbl[2].styleSheet())            # red
        one = clean.copy()
        one[7] = True
        self.win._show_saturation((one, clean))
        self.assertEqual(self.lbl[1].text(), 'SATURATED: 1 sample at full scale')
        self.assertFalse(self.lbl[2].isVisible())

    @staticmethod
    def layout_of(layout, widget):
        """The (nested) layout that holds widget directly."""
        if layout.indexOf(widget) >= 0:
            return layout
        for i in range(layout.count()):
            child = layout.itemAt(i).layout()
            found = child is not None and TestSaturationIndicator.layout_of(child, widget)
            if found:
                return found
        return None

    def test_next_to_the_channel_name(self):
        row = self.layout_of(self.win._chk_ch1.parentWidget().layout(), self.win._chk_ch1)
        for ch, chk in ((1, self.win._chk_ch1), (2, self.win._chk_ch2)):
            items = [row.itemAt(i).widget() for i in range(row.count())]
            self.assertEqual(items.index(self.lbl[ch]), items.index(chk) + 1)

    def raw_count(self, buf):
        return self.count_at_top(self.top_mask(buf[:self.win._reclen]))

    def test_live_refresh_whole_record(self):
        self.sim.SetGain1(self.sim.params.gain_ref_ch1 + 30.0)     # Ch1 clips (0.43 → 1.4)
        self.win._running, self.win._inspection_mode = True, False
        self.win._update_plots()
        n1 = self.raw_count(self.sim.DataADC1)
        self.assertGreater(n1, 0)
        self.assertTrue(self.lbl[1].isVisible())
        self.assertIn(f'{n1} samples', self.lbl[1].text())
        # Ch2: the simulator's main bang clips on purpose; the whole record is checked
        self.assertEqual(self.lbl[2].isVisible(), self.raw_count(self.sim.DataADC2) > 0)

    def test_sequence_acquisition_any_capture(self):
        import numpy as np
        self.sim.SetGain1(self.sim.params.gain_ref_ch1 + 30.0)
        self.win._seq_acquire(4)
        top1 = self.win._last_top[0]
        self.assertTrue(self.lbl[1].isVisible())
        self.assertIn(f'{self.count_at_top(top1)} samples', self.lbl[1].text())
        self.assertIs(self.win._last_counts['top'], self.win._last_top)
        self.sim.SetGain1(self.sim.params.gain_ref_ch1)             # back to normal
        self.win._seq_acquire(4)
        self.assertFalse(self.lbl[1].isVisible())
        self.assertEqual(int(np.count_nonzero(self.win._last_top[0])), 0)


if __name__ == '__main__':
    unittest.main()
