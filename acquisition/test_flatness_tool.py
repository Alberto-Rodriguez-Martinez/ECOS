# -*- coding: utf-8 -*-
"""
test_flatness_tool.py — flatness tool (flatness_tool.py) against the synthetic
SeDaq, task_scanner_phase4.md "Verificación" points 1–6.

Run from the repo root with the 32-bit interpreter of the machine (CLAUDE.md):
    python -m unittest discover -s acquisition
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import test_focus_tool as tf  # noqa: E402  (module import: its tests are not collected twice)
from echo_tracking import PeakMeasure  # noqa: E402
from flatness_tool import (  # noqa: E402
    FlatnessPlan, FlatnessTool, analyse_line, line_flags,
)

FS = tf.FS
LIMITS = {'X': tf.LIMIT, 'Z': tf.LIMIT}
CENTER = {'X': 50.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}


def run_lines(sim, lat_half=10.0, lat_step=2.0, z_half=5.0, z_step=1.0, avg_n=4,
              window=tf.WIDE, tolerance=0.1):
    """Both lines through FlatnessPlan against the simulator, no Qt: {line: LineResult}."""
    coords = dict(CENTER)
    sim.set_scanner_state(coords, 'Y', sim._pe_side)
    plan = FlatnessPlan(coords, 'Y', 'X', LIMITS, lat_half, lat_step, z_half, z_step, window,
                        tolerance, c_w=sim.params.c_w, cw_source='synthetic SeDaq')
    out = {}
    for line in ('lateral', 'z'):
        tracker = plan.new_tracker()
        tracker.new_sweep()
        xs = []
        for pos in plan.positions(line):
            c = dict(coords)
            c.update(pos)
            sim.set_scanner_state(c, 'Y', sim._pe_side)
            _, pe = tf.acquire(sim, avg_n)
            tracker.measure(pe, plan.beam_x)
            xs.append(pos['X'] if line == 'lateral' else pos['Z'])
        out[line] = plan.analyse(line, xs, tracker.measures)
    sim.set_scanner_state(coords, 'Y', sim._pe_side)
    return out


def apply_correction(sim, line, corr, fraction=1.0):
    """
    What the user does by hand, in the simulator's geometry: bringing the +
    end of the face CLOSER to the PE transducer shortens the path there, so
    the tilt θ (path grows with the + side) decreases; moving it away increases it.
    """
    change = fraction * corr.amount_deg * (-1.0 if corr.plus_end_toward_pe else 1.0)
    name = 'theta_lat' if line == 'lateral' else 'theta_z'
    setattr(sim.params, name, getattr(sim.params, name) + change)


# ===========================================================================
#  Pure part against the simulator (points 1, 2, 3, 5)
# ===========================================================================
class TestFlatnessMeasure(unittest.TestCase):

    CASES = [(0.0, 0.0, 'origin'), (1.5, -0.8, 'origin'), (-2.0, 0.5, 'origin'),
             (0.3, 3.0, 'origin'), (-0.7, -1.2, 'max'), (0.05, -0.05, 'origin'),
             (4.0, -4.0, 'max')]

    def test_sim_tilt_geometry_is_the_tools(self):
        """ToF slope 2·tanθ/c_w along each line, independent of the PE side."""
        for side in ('origin', 'max'):
            sim = tf.make_sim(pe_side=side, theta_lat=2.0, theta_z=-1.0)
            c_w = sim.params.c_w
            t = lambda lat, z: sim.front_tof(50.0, lat, z)
            self.assertAlmostEqual((t(51.0, 25.0) - t(50.0, 25.0)) * c_w / 2 * 1e3,
                                   np.tan(np.radians(2.0)), places=9)
            self.assertAlmostEqual((t(50.0, 26.0) - t(50.0, 25.0)) * c_w / 2 * 1e3,
                                   np.tan(np.radians(-1.0)), places=9)

    def test_recovers_angles_within_declared_uncertainty(self):
        """
        Point 1. A 1σ is exceeded ~32 % of the time by definition, so the check
        is statistical over 14 estimates: every error below 3σ and at least 60 %
        below 1σ, with σ itself small (< 0.1°) so it cannot pass by being huge.
        """
        within, n = 0, 0
        for seed, (tl, tz, side) in enumerate(self.CASES):
            sim = tf.make_sim(seed=40 + seed, pe_side=side, theta_lat=tl, theta_z=tz)
            res = run_lines(sim)
            for line, truth in (('lateral', tl), ('z', tz)):
                with self.subTest(line=line, truth=truth, pe_side=side):
                    r = res[line]
                    self.assertNotEqual(r.status, 'no_result')
                    err = r.angle_deg - truth
                    self.assertLess(abs(err), 3 * r.sigma_deg,
                                    f'{r.angle_deg:.4f} ± {r.sigma_deg:.4f} vs {truth}')
                    self.assertLess(r.sigma_deg, 0.1)
                    within += abs(err) < r.sigma_deg
                    n += 1
        self.assertGreaterEqual(within / n, 0.6, f'{within}/{n} within 1σ')

    def test_zero_tilt_is_not_significant(self):
        sim = tf.make_sim(seed=50)
        for line, r in run_lines(sim).items():
            with self.subTest(line=line):
                self.assertIn('not distinguishable from 0', r.angle_text())
                self.assertIsNone(r.correction)

    def test_correction_direction_reduces_the_tilt(self):
        """Point 2: turning as indicated reduces the measured tilt (partly, then fully)."""
        sim = tf.make_sim(seed=51, theta_lat=1.2, theta_z=-0.9, snr_db=40)
        before = run_lines(sim)
        for line in ('lateral', 'z'):
            self.assertIsNotNone(before[line].correction)
        lat_corr, z_corr = before['lateral'].correction, before['z'].correction
        self.assertTrue(lat_corr.plus_end_toward_pe)          # θ_lat > 0: X+ end too far
        self.assertIn('X+ end of the face comes closer to the PE transducer', lat_corr.text)
        self.assertFalse(z_corr.plus_end_toward_pe)           # θ_z < 0: lower edge too close
        self.assertIn('lower edge of the face (Z+', z_corr.text)
        self.assertIn('moves away from the PE transducer', z_corr.text)

        apply_correction(sim, 'lateral', lat_corr, 0.5)
        apply_correction(sim, 'z', z_corr, 0.5)
        half = run_lines(sim)
        for line in ('lateral', 'z'):
            with self.subTest(step='half', line=line):
                self.assertLess(abs(half[line].angle_deg), 0.6 * abs(before[line].angle_deg))
                # same side: the next instruction points the same way
                self.assertEqual(half[line].correction.plus_end_toward_pe,
                                 before[line].correction.plus_end_toward_pe)
        apply_correction(sim, 'lateral', half['lateral'].correction)
        apply_correction(sim, 'z', half['z'].correction)
        after = run_lines(sim)
        for line in ('lateral', 'z'):
            with self.subTest(step='full', line=line):
                r = after[line]
                self.assertLess(abs(r.angle_deg), 3 * r.sigma_deg + 0.05)

    def test_face_ends_are_flagged_and_left_out(self):
        """Point 3: the beam leaves the face at the ends of the lateral line."""
        sim = tf.make_sim(seed=52, theta_lat=1.0, face_half_lat=6.0)
        r = run_lines(sim, lat_step=1.0)['lateral']
        self.assertTrue(r.ends_lost)
        self.assertTrue(all(abs(x - 50.0) > 6.0 for x in r.ends_lost))
        for x, f, used in zip(r.xs, r.flags, r.used):
            if x in r.ends_lost:
                self.assertIn('weak', f)
                self.assertFalse(used)
        self.assertTrue(r.span[0] >= 43.0 and r.span[1] <= 57.0)
        self.assertAlmostEqual(r.suggested_half, 6.0, delta=1.0)
        self.assertTrue(any('Reduce the lateral range' in m for m in r.messages))
        self.assertLess(abs(r.angle_deg - 1.0), 3 * r.sigma_deg)

    def test_no_result_when_the_face_is_missing(self):
        sim = tf.make_sim(seed=53, face_half_z=0.5, z0=100.0)   # no face along the Z line
        r = run_lines(sim)['z']
        self.assertEqual(r.status, 'no_result')
        self.assertIsNone(r.correction)
        self.assertEqual(r.angle_text(), 'no result')

    def test_positions_never_use_r_nor_the_beam_axis(self):
        """Point 5: the lines move lateral and Z only; R is never involved."""
        plan = FlatnessPlan(CENTER, 'Y', 'X', LIMITS, 10, 1, 5, 0.5, tf.WIDE)
        for pos in plan.all_positions():
            self.assertTrue(set(pos) <= {'X', 'Z'}, pos)
        self.assertEqual(plan.return_position, {'X': 50.0, 'Z': 25.0})


class TestFlatnessHelpers(unittest.TestCase):

    def measures(self, n, **bad):
        ms = [PeakMeasure(0.1, 2000 + k, False, False, 60.0, 'tracked', index_frac=2000.0 + k)
              for k in range(n)]
        for k, kind in bad.items():
            k = int(k[1:])
            if kind == 'edge':
                ms[k].at_edge = True
            elif kind == 'weak':
                ms[k].contrast = 2.0
            elif kind == 'weak_elsewhere':
                ms[k].contrast = 2.0
                ms[k].echo_elsewhere = True
        return ms

    def test_lost_and_narrow_window_messages_differ(self):
        xs = [45.0 + k for k in range(11)]
        r = analyse_line('lateral', 'X', 50.0, xs, self.measures(11, k2='edge', k5='weak'),
                         tf.WIDE, 1497.0, 0.1)
        text = ' '.join(r.messages)
        self.assertIn('window is too narrow', text)
        self.assertIn('tracking lost at 50 mm', text)
        self.assertFalse(r.used[2] or r.used[5])
        r2 = analyse_line('lateral', 'X', 50.0, xs, self.measures(11, k5='weak_elsewhere'),
                          tf.WIDE, 1497.0, 0.1)
        self.assertIn('exceeds the band', ' '.join(r2.messages))
        self.assertNotIn('too narrow', ' '.join(r2.messages))

    def test_line_flags_weak(self):
        ms = self.measures(3, k1='weak')
        self.assertEqual(line_flags([0, 1, 2], ms, tf.WIDE), [[], ['weak'], []])

    def test_undetermined_when_sigma_is_large_for_the_tolerance(self):
        xs = [45.0 + k for k in range(11)]
        rng = np.random.default_rng(1)
        ms = self.measures(11)
        for m in ms:
            m.index_frac += rng.normal(0, 30.0)      # very noisy timing
        r = analyse_line('lateral', 'X', 50.0, xs, ms, tf.WIDE, 1497.0, 0.1)
        self.assertEqual(r.status, 'undetermined')
        text = next(m for m in r.messages if 'too large to judge' in m)
        self.assertLess(text.index('more points'), text.index('more averages'))
        self.assertNotIn('range', text)
        self.assertNotIn('\n', text)


# ===========================================================================
#  Qt: FlatnessTool on the real ScanSequencer (points 4, 5, 6)
# ===========================================================================
from PyQt5.QtCore import QEventLoop, QTimer  # noqa: E402

import pyqtgraph as pg  # noqa: E402
from scan_sequencer import ScanSequencer  # noqa: E402


class AxisWorker(tf.FakeWorker):
    """FakeWorker that also records which axes every move touched."""

    def __init__(self, panel):
        super().__init__(panel)
        self.axes = []

    def enqueue(self, cmd):
        if cmd[0] == 'move_point':
            self.axes.extend(a for a, _ in cmd[2])
        super().enqueue(cmd)


class TestFlatnessToolQt(unittest.TestCase):

    def setUp(self):
        self.sim = tf.make_sim(seed=60, theta_lat=0.8, theta_z=-0.6)
        self.panel = tf.FakePanel(self.sim)
        self.worker = AxisWorker(self.panel)
        self.live = {'on': True}
        self.seq = ScanSequencer(
            self.worker, self.sim, lambda n: tf.acquire(self.sim, n),
            coords_fn=self.panel.current_coords,
            enter_exclusive=lambda: self.live.update(on=False),
            leave_exclusive=lambda: self.live.update(on=True), top_fn=tf.last_top)
        self.dump_dir = tempfile.mkdtemp(prefix='flatness_debug_test_')
        self.addCleanup(shutil.rmtree, self.dump_dir, ignore_errors=True)
        self.tool = FlatnessTool(self.seq, self.panel, lambda: tf.WIDE, pg.PlotWidget(),
                                 cw_fn=lambda: (self.sim.params.c_w, 'synthetic SeDaq'),
                                 dump_dir=self.dump_dir, acq_time_fn=lambda: 0.01)
        self.results, self.statuses, self.outcomes = [], [], []
        self.tool.done.connect(self.results.append)
        self.tool.status.connect(self.statuses.append)
        self.tool.result.connect(self.outcomes.append)
        self.params = dict(lat_half=6.0, lat_step=2.0, z_half=3.0, z_step=1.0, avg_n=4,
                           settle_ms=0)

    def wait_done(self, timeout_ms=30000):
        loop = QEventLoop()
        self.tool.done.connect(loop.quit)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec_()

    def test_full_run_returns_to_centre_and_reports(self):
        self.assertIsNone(self.tool.run(**self.params))
        self.wait_done()
        self.assertEqual(self.results, [True], self.statuses[-1])
        self.assertEqual((self.panel.coords['X'], self.panel.coords['Z']), (50.0, 25.0))
        self.assertEqual(self.panel.coords['Y'], 50.0)                    # beam never moved
        self.assertTrue(set(self.worker.axes) <= {'X', 'Z'}, set(self.worker.axes))  # no R
        out = self.outcomes[-1]
        for line, truth in (('lateral', 0.8), ('z', -0.6)):
            r = out.lines[line]
            self.assertLess(abs(r.angle_deg - truth), 3 * r.sigma_deg)
            self.assertEqual(r.status, 'out')
        final = self.statuses[-1]
        for word in ('Lateral (X)', 'Z (Z)', '± ', 'RMS residual', 'rotation stage', 'Tilt by',
                     'Back at the centre'):
            self.assertIn(word, final)
        self.assertNotIn(' R ', final)
        # verdict and action first, then the angle, the RMS residual last (spec 5.5, scope)
        lateral = final[final.index('Lateral (X)'):final.index('Z (Z)')]
        order = [lateral.index(w) for w in ('OUT of tolerance', '→ Turn the rotation stage',
                                            'Angle: θ', 'RMS residual')]
        self.assertEqual(order, sorted(order), lateral)
        self.assertTrue(self.live['on'])

    def test_debug_dump_measurement_parameters(self):
        tool = FlatnessTool(self.seq, self.panel, lambda: tf.WIDE, pg.PlotWidget(),
                            dump_dir=self.dump_dir, gains_fn=lambda: (65.0, 35.0),
                            temp_fn=lambda: {'T1': 24.5, 'T2': 24.7, 'time': 1.0, 'source': 'PT100'})
        tool.done.connect(self.results.append)
        self.assertIsNone(tool.run(**dict(self.params, avg_n=3, settle_ms=4)))
        loop = QEventLoop()
        tool.done.connect(loop.quit)
        QTimer.singleShot(30000, loop.quit)
        loop.exec_()
        meta = json.loads(str(np.load(tool.last_dump_path)['meta_json']))
        self.assertEqual((meta['settle_ms'], meta['avg_n']), (4, 3))
        self.assertEqual((meta['gain_ch1_db'], meta['gain_ch2_db']), (65.0, 35.0))
        self.assertEqual(meta['temperature']['T2'], 24.7)

    def test_debug_dump_holds_both_lines(self):
        """Point 6: both lines with their ToF (and the return point)."""
        self.assertIsNone(self.tool.run(**self.params))
        self.wait_done()
        files = os.listdir(self.dump_dir)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].startswith('flatness_debug_'))
        d = np.load(os.path.join(self.dump_dir, files[0]))
        phases = list(d['phase'])
        self.assertEqual(phases.count('lateral'), 7)
        self.assertEqual(phases.count('z'), 7)
        self.assertEqual(phases[-1], 'return')
        lat = d['phase'] == 'lateral'
        np.testing.assert_allclose(d['line_offset'][lat], [-6, -4, -2, 0, 2, 4, 6])
        np.testing.assert_allclose(d['tof_us'], d['tof_samples'] / FS * 1e6)
        lat_x = d['line_position'][lat]
        truth = [self.sim.front_tof(50.0, x, 25.0) * FS for x in lat_x]
        np.testing.assert_allclose(d['tof_samples'][lat], truth, atol=3.0)
        meta = json.loads(str(d['meta_json']))
        self.assertEqual(meta['tool'], 'flatness')
        self.assertIn('lateral', meta['lines'])

    def test_stop_midway_does_not_move(self):
        """Point 4."""
        count = {'n': 0}

        def on_point(*_):
            count['n'] += 1
            if count['n'] == 3:
                self.seq.abort()
        self.seq.point_done.connect(on_point)
        self.assertIsNone(self.tool.run(**self.params))
        self.wait_done()
        self.assertEqual(self.results, [False])
        self.assertEqual(len(self.worker.moves), 3)                     # nothing after the STOP
        self.assertEqual(self.panel.coords['X'], 48.0)                  # 3rd point, not back to the centre
        self.assertIn('stopped', self.statuses[-1])
        self.assertIn('Not moved', self.statuses[-1])
        self.assertTrue(self.live['on'])
        self.assertFalse(self.seq.active)

    def test_repeat_uses_the_same_parameters(self):
        self.assertEqual(self.tool.repeat(), 'Nothing to repeat yet.')
        self.assertIsNone(self.tool.run(**self.params))
        self.wait_done()
        n_moves = len(self.worker.moves)
        self.sim.params.theta_lat = 0.0                                 # "corrected by hand"
        self.assertIsNone(self.tool.repeat())
        self.wait_done()
        self.assertEqual(self.results, [True, True])
        self.assertEqual(len(self.worker.moves), 2 * n_moves)
        self.assertIn('not distinguishable from 0', self.outcomes[-1].lines['lateral'].angle_text())

    def test_time_estimate_before_starting(self):
        seconds, text = self.tool.estimate(10.0, 1.0, 5.0, 0.5, avg_n=100, settle_ms=5000)
        # 21 + 21 points + return, 5 s + 100 × 10 ms each; travel X 10 + 20 + 10, Z 5 + 10 + 5
        self.assertAlmostEqual(seconds, 43 * 6.0 + 60.0 / 6.7)
        self.assertIn('Estimated time', text)
        self.assertIn('lateral 21 pts + Z 21 pts', text)

    def test_group_defaults(self):
        from flatness_tool import FlatnessGroup
        g = FlatnessGroup(self.tool, self.seq)
        self.assertEqual((g._spin_settle.value(), g._spin_avg.value()), (5000, 100))
        self.assertIn('Estimated time', g._lbl_estimate.text())
        self.assertFalse(g._btn_repeat.isEnabled())

    def test_axis_labels_lead_with_verdict_and_action(self):
        from flatness_tool import FlatnessGroup
        g = FlatnessGroup(self.tool, self.seq)
        self.assertIsNone(self.tool.run(**self.params))
        self.wait_done()
        lines = g._lbl_axis['lateral'].text().split('\n')
        self.assertEqual(lines[0], 'OUT of tolerance')
        self.assertTrue(lines[1].startswith('Turn the rotation stage'), lines)
        self.assertTrue(lines[2].startswith('Angle: θ ='), lines)
        self.assertNotIn('RMS', g._lbl_axis['lateral'].text())


if __name__ == '__main__':
    unittest.main()
