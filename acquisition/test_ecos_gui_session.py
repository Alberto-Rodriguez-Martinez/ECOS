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

import numpy as np  # noqa: E402
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
    close, which the next one would restore: check boxes switched off by a test), and
    with its live timer stopped: the tests drive the refresh (_update_plots) themselves,
    so a timer tick can never land between two checks of one test."""

    def setUp(self):
        if os.path.exists(_ENV['session']):
            os.remove(_ENV['session'])
        self.win = _ENV['gui'].EcosGUI()
        self.win._timer.stop()
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
                t_us = x / 100.0                  # x is in samples in every unit (100 MHz)
                self.assertIn(f't = {t_us:.3f} µs', text)
                self.assertIn(f'A = {y:.4f} a.u.', text)
                if unit == 'samples':
                    self.assertIn(f'sample {x:.0f}', text)
                if unit == 'mm':
                    d = x / 1e8 * 1480.0 / 2.0 * 1e3          # no PT100: nominal c_w
                    self.assertIn(f'd = {d:.2f} mm', text)


class TestAxisUnits(_LiveWindow):
    """
    Regression (06/10): switching the x unit to µs or mm squashed the overview (its
    curves converted, its range, limits and Smin–Smax region still in samples) and
    froze the zoom (the mm inverse was off by 10^6: the region collapsed to
    [16384, 16384] through the zoom⇄region feedback, and the zoom stopped updating).
    No exception was raised: the state was wrong. Every item stays in samples; only
    the axis shows the unit (UnitAxisItem).
    """

    UNITS = ('samples', 'mus', 'mm')

    def radio(self, unit):
        return {'samples': self.win._radio_samples, 'mus': self.win._radio_mus,
                'mm': self.win._radio_mm}[unit]

    def refresh(self, n=3):
        self.win._running, self.win._inspection_mode = True, False
        for _ in range(n):
            self.win._update_plots()
        QApplication.processEvents()

    def finite_ranges(self):
        for plot in (self.win._plot_zoom, self.win._plot_ov):
            (x0, x1), (y0, y1) = plot.getViewBox().viewRange()
            self.assertTrue(np.all(np.isfinite([x0, x1, y0, y1])), plot)
            self.assertLess(x0, x1)
            axis = plot.getAxis('bottom')
            levels = axis.tickValues(x0, x1, 800)
            values = [v for _, vals in levels for v in vals]
            self.assertTrue(values and np.all(np.isfinite(values)))
            for _, vals in levels:
                strings = axis.tickStrings(vals, 1.0, levels[0][0])
                self.assertTrue(all(np.isfinite(float(t)) for t in strings), strings)

    def test_every_unit_keeps_the_physical_positions(self):
        from echo_tracking import PeakMeasure
        win = self.win
        self.refresh()
        region = tuple(win._region.getRegion())
        smin, smax = win._get_smin_smax()
        x_cursor = smin + 0.37 * (smax - smin)          # a sample in the window
        self.move_to(x_cursor, 0.1)
        win._mark_echo(PeakMeasure(0.1, smin + 300, False, False, 50.0, 'tracked',
                                   band=(smin + 250, smin + 350)))
        band, peak, _ = win._echo_mark
        for unit in self.UNITS + ('mus', 'samples', 'mm'):
            with self.subTest(unit=unit):
                self.radio(unit).setChecked(True)
                self.refresh()
                self.assertEqual(win._unit, unit)
                self.assertEqual(tuple(win._region.getRegion()), region)     # Smin–Smax
                self.assertEqual(win._get_smin_smax(), (smin, smax))
                self.assertAlmostEqual(win._vline_cursor.value(), x_cursor,  # the cursor
                                       delta=1e-6)
                self.assertEqual(peak.value(), smin + 300)                   # the echo mark
                self.assertEqual(tuple(band.getRegion()), (smin + 250, smin + 350))
                x_zoom, _ = win._curve_zoom_ch2.getData()
                self.assertEqual((x_zoom[0], x_zoom[-1] + 1), (smin, smax))  # the curve
                x_ov, _ = win._curve_ov_ch2.getData()
                self.assertEqual((x_ov[0], x_ov[-1] + 1), (0, win._reclen))
                (zx0, zx1), _ = self.vb.viewRange()
                self.assertAlmostEqual(zx0, smin, delta=1e-6)               # zoom = region
                self.assertAlmostEqual(zx1, smax, delta=1e-6)
                (ox0, ox1), _ = win._plot_ov.getViewBox().viewRange()
                self.assertTrue(ox0 <= region[0] and region[1] <= ox1 + 1)  # region visible
                self.finite_ranges()

    def test_live_refresh_still_running_after_the_change(self):
        win = self.win
        win._timer.start(_ENV['gui'].REALTIME_INTERVAL)      # the live timer, as at start
        for unit in ('mus', 'mm', 'samples'):
            with self.subTest(unit=unit):
                self.radio(unit).setChecked(True)
                self.refresh(1)
                _, y_before = win._curve_zoom_ch2.getData()
                y_before = np.array(y_before)
                self.refresh(1)
                _, y_after = win._curve_zoom_ch2.getData()
                self.assertTrue(win._timer.isActive())
                self.assertFalse(np.array_equal(y_before, y_after))         # new data drawn
                self.assertLess(*win._get_smin_smax())

    def test_distance_without_pt100(self):
        """c_w None or NaN (no PT100): the nominal c_w, said in the label, never a NaN range."""
        win = self.win
        for cw in (None, float('nan'), 0.0):
            with self.subTest(cw=cw):
                win._state.Cw_mean = cw
                self.radio('mm').setChecked(True)
                win._on_unit_changed('mm')
                self.refresh()
                self.assertIn('nominal', win._plot_zoom.getAxis('bottom').labelText)
                self.finite_ranges()
                self.move_to(sum(win._get_smin_smax()) / 2.0, 0.0)
                self.assertNotIn('nan', win._lbl_cursor.text().lower())
        win._state.Cw_mean = 1500.0          # a value that is not a PT100 reading (manual,
        win._on_unit_changed('mm')            # assumed): the axis still says nominal
        self.assertIn('1480.0 m/s, nominal', win._plot_zoom.getAxis('bottom').labelText)
        win._state.Cw_mean = None

    def test_one_conversion_and_its_inverse(self):
        gui = _ENV['gui']
        n = np.array([0.0, 1.0, 2672.0, 16383.0])
        for unit in self.UNITS:
            for cw in (None, float('nan'), 1480.0, 1497.3):
                with self.subTest(unit=unit, cw=cw):
                    x = gui.samples_to_axis(n, unit, cw)
                    self.assertTrue(np.all(np.isfinite(x)))
                    np.testing.assert_allclose(gui.axis_to_samples(x, unit, cw), n, atol=1e-9)
        self.assertAlmostEqual(float(gui.samples_to_axis(2672, 'mus', None)), 26.72)
        self.assertAlmostEqual(float(gui.samples_to_axis(2702.7027, 'mm', 1480.0)), 20.0,
                               places=4)


class TestAxisCwFrozen(_LiveWindow):
    """The c_w of the mm axis is taken once, when the unit goes to mm, and held."""

    def pt100(self, cw):
        """As a PT100 reading leaves the state (Acquisition tab or a scanner tool)."""
        self.win._state.T1 = self.win._state.T2 = 24.0       # a reading sets T and c_w
        self.win._state.Cw_mean = cw
        self.win._note_temperature('PT100 (test)')

    def label(self):
        return self.win._plot_zoom.getAxis('bottom').labelText

    def mm_of(self, sample):
        unit, cw = self.win._axis_unit()
        return float(_ENV['gui'].samples_to_axis(sample, unit, cw))

    def test_held_while_the_reading_changes(self):
        win = self.win
        self.pt100(1497.0)
        win._radio_mm.setChecked(True)
        self.assertIn('c_w 1497.0 m/s, PT100, read', self.label())
        d0 = self.mm_of(2700)
        self.pt100(1502.0)                               # the next reading, during the session
        win._running, win._inspection_mode = True, False
        for _ in range(3):
            win._update_plots()
        self.assertEqual(win._axis_unit()[1], 1497.0)    # the axis did not move
        self.assertEqual(self.mm_of(2700), d0)
        self.assertIn('1497.0 m/s', self.label())
        smin, smax = win._get_smin_smax()
        from PyQt5.QtCore import QPointF
        win._on_mouse_moved(win._plot_zoom.getViewBox().mapViewToScene(QPointF(2700, 0.0)))
        self.assertIn(f'd = {d0:.2f} mm', win._lbl_cursor.text())       # the cursor too

    def test_retake_without_changing_the_unit(self):
        win = self.win
        self.assertFalse(win._btn_retake_cw.isEnabled())                 # only in mm
        self.pt100(1497.0)
        win._radio_mm.setChecked(True)
        self.assertTrue(win._btn_retake_cw.isEnabled())
        self.pt100(1502.0)
        win._btn_retake_cw.click()
        self.assertEqual(win._unit, 'mm')
        self.assertEqual(win._axis_unit()[1], 1502.0)
        self.assertIn('1502.0 m/s, PT100', self.label())
        self.pt100(1499.0)
        win._radio_mus.setChecked(True)
        self.assertFalse(win._btn_retake_cw.isEnabled())
        win._radio_mm.setChecked(True)                   # back to mm: taken again
        self.assertEqual(win._axis_unit()[1], 1499.0)

    def enter_manual(self):
        """The real manual-entry path, its dialog accepted with the default 20.0 °C."""
        from unittest import mock
        gui = _ENV['gui']
        with mock.patch.object(gui.QDialog, 'exec_', lambda _self: gui.QDialog.Accepted):
            self.assertTrue(self.win._ask_manual_temperature())

    def test_manual_temperature_on_screen_not_in_the_files(self):
        win = self.win
        self.enter_manual()
        win._radio_mm.setChecked(True)
        self.assertIn(f'c_w {win._approx_cw(20.0):.1f} m/s, manual, T = 20.0 °C', self.label())
        self.assertEqual(win._axis_unit()[1], win._approx_cw(20.0))
        self.assertIsNone(win._latest_temperature())     # files: still not a reading
        self.pt100(1499.0)                               # a reading replaces it
        win._btn_retake_cw.click()
        self.assertIn('1499.0 m/s, PT100', self.label())

    def test_assumed_temperature_is_not_manual(self):
        win = self.win
        self.enter_manual()
        win._read_temperature()                          # no hardware: assumed 20 °C
        win._radio_mm.setChecked(True)
        self.assertIn('1480.0 m/s, nominal', self.label())

    def test_nominal_without_a_pt100_reading(self):
        win = self.win
        win._state.Cw_mean = None
        win._radio_mm.setChecked(True)
        self.assertIn('c_w 1480.0 m/s, nominal, no PT100 reading', self.label())
        self.assertEqual(win._axis_unit()[1], 1480.0)


class TestScanMetadataFields(_LiveWindow):
    """Probes and transducers typed in the Acquisition tab reach the scan metadata and the
    session file; the tab (and its own Arduino reads) is locked during a scan session."""

    def fill(self):
        win = self.win
        win._txt_transducer_pe.setText('V310 5 MHz')
        win._txt_transducer_tt.setText('V311 5 MHz')
        win._txt_probe[('T1', 'id')].setText('S-17')
        win._txt_probe[('T1', 'position')].setText('bottom, left')
        win._txt_probe[('T2', 'class')].setText('A')

    def test_scan_info_carries_them_empty_when_not_filled(self):
        info = self.win._scan_experiment_info()
        self.assertEqual((info['equipment1']['transductor_pe'],
                          info['equipment1']['transductor_tt']), ('', ''))
        self.assertEqual(info['equipment2']['probes']['T1'],
                         {'id': '', 'position': '', 'class': ''})
        self.fill()
        info = self.win._scan_experiment_info()
        self.assertEqual(info['equipment1']['transductor_pe'], 'V310 5 MHz')
        self.assertEqual(info['equipment2']['probes']['T1']['position'], 'bottom, left')
        self.assertEqual(info['equipment2']['probes']['T2']['class'], 'A')

    def test_kept_in_the_session(self):
        self.fill()
        saved = self.win._collect_session()
        for txt in [self.win._txt_transducer_pe] + list(self.win._txt_probe.values()):
            txt.setText('')
        self.win._restore_session(saved)
        self.assertEqual(self.win._txt_transducer_tt.text(), 'V311 5 MHz')
        self.assertEqual(self.win._txt_probe[('T1', 'id')].text(), 'S-17')
        self.win._restore_session({})                     # an old session: empty, no error
        self.assertEqual(self.win._txt_probe[('T1', 'id')].text(), '')

    def test_acquisition_tab_locked_during_a_scan_session(self):
        self.win._scan_lock(True)
        self.assertFalse(self.win._acq_scroll.isEnabled())   # "Read from Arduino" included
        self.win._scan_lock(False)
        self.assertTrue(self.win._acq_scroll.isEnabled())

    def test_point_measurement_still_works(self):
        win = self.win
        win._on_acquire_pett()
        win._on_acquire_wp()
        for s in (win._state.PE_Ascan, win._state.TT_Ascan, win._state.WP_Ascan):
            self.assertIsNotNone(s)
        win._on_apply_window()
        self.assertEqual(win._lbl_res_d.text(), f'{win._L * 1e3:.3f}')
        self.assertTrue(win._btn_save.isEnabled())


class TestCorruptSessionRegion(unittest.TestCase):
    """06/10: the unit bug saved an empty Smin–Smax ([16384, 16384]) in the session."""

    def window_with(self, session):
        with open(_ENV['session'], 'w') as f:
            json.dump(session, f)
        win = _ENV['gui'].EcosGUI()
        win.resize(1400, 900)
        win.show()
        QApplication.processEvents()
        self.addCleanup(win.close)
        return win

    def draws(self, win):
        win._running, win._inspection_mode = True, False
        win._update_plots()
        smin, smax = win._get_smin_smax()
        x, y = win._curve_zoom_ch2.getData()
        self.assertEqual(len(x), smax - smin)                         # the big plot draws
        self.assertGreater(len(x), 0)
        (z0, z1), _ = win._plot_zoom.getViewBox().viewRange()
        self.assertEqual((round(z0), round(z1)), (smin, smax))        # zoom = region
        self.assertTrue(np.all(np.isfinite([z0, z1])))

    def test_empty_region_discarded_at_start(self):
        win = self.window_with({'region': [16384, 16384], 'reclen': '16384'})
        smin, smax = win._get_smin_smax()
        self.assertGreaterEqual(smax - smin, 16)                      # not the empty region
        self.assertEqual((smin, smax), tuple(win._sedaq.default_window()))
        self.assertEqual((smin, smax), win._default_region(16384))
        self.assertTrue(any('[16384, 16384]' in n and 'not valid' in n
                            for n in win.session_notices))
        self.draws(win)

    def test_other_invalid_regions(self):
        for region in ([5000, 3000], [10000, 20000], [-50, 3000], [100, 105],
                       [float('nan'), 4000], ['a', 'b'], [3000]):
            with self.subTest(region=region):
                win = self.window_with({'region': region, 'reclen': '16384'})
                self.assertEqual(win._get_smin_smax(), win._default_region(16384))
                self.assertTrue(win.session_notices)
                self.draws(win)
                win.close()

    def test_valid_region_kept_silently(self):
        win = self.window_with({'region': [2500, 4000], 'reclen': '16384'})
        self.assertEqual(win._get_smin_smax(), (2500, 4000))
        self.assertEqual(win.session_notices, [])
        self.draws(win)

    def test_never_saves_an_empty_region(self):
        win = self.window_with({'region': [2500, 4000], 'reclen': '16384'})
        win._region.setRegion([5000, 5000])                          # however it got there
        win.close()
        with open(_ENV['session']) as f:
            saved = json.load(f)['region']
        self.assertEqual(saved, [2500, 4000])                        # the last valid one
        self.assertTrue(any('saves [2500, 4000]' in n for n in win.session_notices))

    def test_zoom_range_never_writes_an_empty_region(self):
        win = self.window_with({'region': [2500, 4000], 'reclen': '16384'})
        win._on_zoom_xrange_changed(None, (16384.0, 16384.0))       # the old feedback path
        self.assertEqual(win._get_smin_smax(), (2500, 4000))
        win._on_zoom_xrange_changed(None, (3000.0, 3500.0))          # a valid one goes through
        self.assertEqual(win._get_smin_smax(), (3000, 3500))


class TestExactCounts(_LiveWindow):
    """
    What a scan file holds is exactly the counts measured: the production
    acquisition (EcosGUI._seq_acquire → _acquire_counts) summed over the raw captures
    with no rounding and no offset subtracted, saved (save_scan_raw_32) and read back
    (load_scan_raw_32). Expected values computed independently, in Python integers,
    from every raw capture the digitizer delivered.
    """

    def test_read_back_equals_the_measured_counts(self):
        sys.path.insert(0, os.path.join(_HERE, '..', 'database'))
        from BD_Experimentos_PVA import load_scan_raw_32, save_scan_raw_32
        from scan_counts import counts_to_float
        win, sim = self.win, self.win._sedaq
        # the DC offsets of the real set-up, fractional: with them, a mean subtracted (and
        # rounded) per capture would differ from the midpoint and change the sums
        sim.params.dc_offset_lsb_ch1, sim.params.dc_offset_lsb_ch2 = 1.2, -7.4
        captures = []                                   # every raw capture, both channels
        get = sim.GetAScan

        def recording():
            get()
            captures.append(([int(v) for v in sim.DataADC1[:sim.RecLen]],
                             [int(v) for v in sim.DataADC2[:sim.RecLen]]))
        sim.GetAScan = recording
        n, (smin, smax) = 20, win._get_smin_smax()
        points = []
        for _ in range(3):                              # three points, as a scan line
            del captures[:]
            ch1, ch2 = win._seq_acquire(n)              # the production path
            lc = win._last_counts
            points.append((list(captures), lc, ch1, ch2))
        sim.GetAScan = get
        mid = 512                                       # 10 bits
        ch2_mean = np.mean([np.mean(cap[1]) for caps, _, _, _ in points for cap in caps])
        self.assertLess(ch2_mean - mid, -5)              # the offset is really there
        tmp = tempfile.mkdtemp(prefix='exact_counts_')
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        sums = [np.array([np.asarray(lc['sum'][c])[smin:smax] for _, lc, _, _ in points])
                [None] for c in (0, 1)]
        offs = [np.array([[lc['offset'][c] for _, lc, _, _ in points]]) for c in (0, 1)]
        path = save_scan_raw_32(
            specimen={}, protocol={}, equipment1={'params': {'Smin': smin, 'Smax': smax}},
            equipment2={}, scanner_session={}, scan={'type': 'line'},
            signals_ch1=sums[0], signals_ch2=sums[1], offsets_ch1=offs[0], offsets_ch2=offs[1],
            n_avg=n, gains=(65.0, 35.0), coords=np.zeros((1, 3, 4)),
            point_time=np.zeros((1, 3)), temperatures=[], base_dir=tmp, exp_name='exact')
        meta, d = load_scan_raw_32(path)
        for k, (caps, lc, ch1, ch2) in enumerate(points):
            self.assertEqual(len(caps), n)              # n captures, none discarded
            for c, name in ((0, 'ch1'), (1, 'ch2')):
                # Σ raw counts of the n captures, in Python integers (no numpy, no float)
                measured = [sum(cap[c][i] for cap in caps) for i in range(smin, smax)]
                stored = d[f'signals_{name}_sum'][0, k]
                self.assertTrue(np.issubdtype(stored.dtype, np.integer))
                # exact, not approximate: the stored sum is Σ(raw − midpoint), nothing else
                self.assertEqual([int(v) + mid * n for v in stored], measured)
                # the offset is stored apart, and the reader's float is the one measured
                self.assertEqual(float(d[f'offsets_{name}'][0, k]), lc['offset'][c])
                x = (ch1, ch2)[c][smin:smax]
                np.testing.assert_array_equal(d[f'signals_{name}'][0, k], x)
                np.testing.assert_array_equal(
                    x, counts_to_float(stored, n, 10, lc['offset'][c])[0])
        self.assertEqual(meta['conversion']['dtype'], 'int16')    # 20 × 512 fits int16


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
    """Red indicator per channel, from the raw counts of the last acquisition, within
    Smin–Smax: the samples that are measured and saved, as the marks of the tools."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, os.path.join(_HERE, '..', 'database'))
        from scan_counts import count_at_top, top_mask
        self.count_at_top, self.top_mask = count_at_top, top_mask
        self.lbl = self.win._lbl_sat
        self.sim = self.win._sedaq
        self.smin, self.smax = self.win._get_smin_smax()

    def mask(self, *samples):
        m = np.zeros(self.win._reclen, dtype=bool)
        m[list(samples)] = True
        return m

    def live(self):
        self.win._running, self.win._inspection_mode = True, False
        self.win._update_plots()

    def test_only_when_it_happens_with_the_count(self):
        clean = self.mask()
        self.win._show_saturation((clean, clean))
        self.assertFalse(self.lbl[1].isVisible() or self.lbl[2].isVisible())
        s = self.smin
        self.win._show_saturation((clean, self.mask(s + 10, s + 500, s + 501)))
        self.assertFalse(self.lbl[1].isVisible())
        self.assertTrue(self.lbl[2].isVisible())
        self.assertIn('3 samples', self.lbl[2].text())
        self.assertIn('230, 30, 30', self.lbl[2].styleSheet())            # red
        self.win._show_saturation((self.mask(s + 7), clean))
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

    def test_outside_smin_smax_off_inside_on(self):
        """Only the window counts: the edges included (Smin), excluded (Smax)."""
        clean, s0, s1 = self.mask(), self.smin, self.smax
        for outside in ((0, 30, s0 - 1), (s1, s1 + 1, 14000, self.win._reclen - 1)):
            with self.subTest(outside=outside):
                self.win._show_saturation((self.mask(*outside), self.mask(*outside)))
                self.assertFalse(self.lbl[1].isVisible() or self.lbl[2].isVisible())
        for inside in ((s0,), (s1 - 1,), ((s0 + s1) // 2,)):
            with self.subTest(inside=inside):
                self.win._show_saturation((self.mask(*inside), clean))
                self.assertTrue(self.lbl[1].isVisible())
                self.assertIn('1 sample', self.lbl[1].text())

    def test_live_outside_off_inside_on(self):
        """With the simulator: its main bang clips by design before Smin (off); the Ch1
        transmission pulse (~sample 3990) clipped at +30 dB, after Smax (off) and then
        inside the window (on)."""
        self.live()
        self.assertGreater(self.count_at_top(self.top_mask(self.sim.DataADC2[:self.win._reclen])),
                           0)                                    # the bang does clip …
        self.assertFalse(self.lbl[2].isVisible())                # … outside the window
        self.sim.params.snr_db = 60.0          # quiet: at +30 dB only the pulse clips, not noise
        self.sim.SetGain1(self.sim.params.gain_ref_ch1 + 30.0)   # Ch1 pulse clips
        tt = int(np.argmax(np.abs(self.sim.clean_signals()[0])))   # the Ch1 pulse
        self.assertTrue(self.smin + 400 < tt < self.smax)
        self.win._region.setRegion([self.smin, tt - 300])        # pulse after Smax
        self.live()
        top = self.top_mask(self.sim.DataADC1[:self.win._reclen])
        self.assertGreater(self.count_at_top(top), 0)
        self.assertEqual(self.count_at_top(top, self.win._get_smin_smax()), 0)
        self.assertFalse(self.lbl[1].isVisible())
        self.win._region.setRegion([self.smin, self.smax])      # pulse inside
        self.live()
        n1 = self.count_at_top(self.top_mask(self.sim.DataADC1[:self.win._reclen]),
                               self.win._get_smin_smax())
        self.assertGreater(n1, 0)
        self.assertTrue(self.lbl[1].isVisible())
        self.assertIn(f'{n1} samples', self.lbl[1].text())

    def test_sequence_acquisition_any_capture(self):
        self.sim.SetGain1(self.sim.params.gain_ref_ch1 + 30.0)
        self.win._seq_acquire(4)
        top1 = self.win._last_top[0]
        self.assertTrue(self.lbl[1].isVisible())
        self.assertIn(f'{self.count_at_top(top1, self.win._get_smin_smax())} samples',
                      self.lbl[1].text())
        self.assertIs(self.win._last_counts['top'], self.win._last_top)
        self.sim.SetGain1(self.sim.params.gain_ref_ch1)             # back to normal
        self.win._seq_acquire(4)
        self.assertFalse(self.lbl[1].isVisible())
        self.assertEqual(int(np.count_nonzero(self.win._last_top[0])), 0)

    def test_no_blanking_control_left(self):
        """Emission blanking was removed on 06/10 (spec 5.7): no control, no session key."""
        self.assertFalse(hasattr(self.win, '_spin_blank'))
        self.win.close()
        with open(_ENV['session']) as f:
            self.assertNotIn('emission_blank', json.load(f))


if __name__ == '__main__':
    unittest.main()
