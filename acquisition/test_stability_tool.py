# -*- coding: utf-8 -*-
"""
test_stability_tool.py — stability test (stability_tool.py) and the sequencer's
no_move option, against the synthetic SeDaq.

Run from the repo root with the 32-bit interpreter of the machine (CLAUDE.md):
    python -m unittest discover -s acquisition
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import test_focus_tool as tf  # noqa: E402  (module import: its tests are not collected twice)
from stability_tool import (  # noqa: E402
    DEFAULT_AVG_N, DEFAULT_INTERVAL_S, DEFAULT_N, StabilityParams, drift_fit,
    estimate_stability_s, temp_every,
)
from sim_sedaq import SimParams, SimSeDaq  # noqa: E402

FS = tf.FS


class TestStabilityPure(unittest.TestCase):

    def test_defaults_twenty_minutes(self):
        p = StabilityParams()
        self.assertEqual((p.n, p.interval_s, p.avg_n), (240, 5.0, 20))
        self.assertEqual((DEFAULT_N, DEFAULT_INTERVAL_S, DEFAULT_AVG_N), (240, 5.0, 20))
        self.assertAlmostEqual(estimate_stability_s(p, 0.0), 20 * 60)
        self.assertAlmostEqual(estimate_stability_s(p, 0.01, 0.2), 240 * (5 + 0.2 + 0.2))

    def test_temp_every(self):
        self.assertEqual(temp_every(0.1), 1)
        self.assertEqual(temp_every(0.5), 1)
        self.assertEqual(temp_every(0.6), 2)
        self.assertEqual(temp_every(2.1), 5)

    def test_drift_fit(self):
        t = np.arange(10) / 2.0
        s, r = drift_fit(t, -2.46 * t + 3.0)
        self.assertAlmostEqual(s, -2.46)
        self.assertAlmostEqual(r, 0.0)
        y = np.full(10, np.nan)
        self.assertTrue(np.isnan(drift_fit(t, y)[0]))


from PyQt5.QtCore import QEventLoop, QTimer  # noqa: E402

import pyqtgraph as pg  # noqa: E402
from scan_sequencer import ScanSequencer  # noqa: E402
from stability_tool import StabilityGroup, StabilityTool  # noqa: E402


class FakeArduino:
    def __init__(self, delay=0.0):
        self.delay, self.reads, self.closed = delay, 0, False

    def getTemperatures(self):
        self.reads += 1
        if self.delay:
            time.sleep(self.delay)
        return 24.0 + 0.01 * self.reads, 24.2

    def close(self):
        self.closed = True


class TestStabilityTool(unittest.TestCase):

    def make(self, arduino_delay=0.0, temp=True, **sim):
        sim.setdefault('snr_db', 60.0)
        self.sim = SimSeDaq(SimParams(**sim), reclen=8192, seed=2)
        self.panel = tf.FakePanel(self.sim)
        self.worker = tf.FakeWorker(self.panel)
        self.enqueued = []
        orig = self.worker.enqueue
        self.worker.enqueue = lambda cmd: (self.enqueued.append(cmd), orig(cmd))
        self.live = {'on': True}
        self.seq = ScanSequencer(
            self.worker, self.sim, lambda n: tf.acquire(self.sim, n),
            coords_fn=self.panel.current_coords,
            enter_exclusive=lambda: self.live.update(on=False),
            leave_exclusive=lambda: self.live.update(on=True))
        self.dump_dir = tempfile.mkdtemp(prefix='stability_test_')
        self.addCleanup(shutil.rmtree, self.dump_dir, ignore_errors=True)
        self.arduinos = []

        def factory():
            a = FakeArduino(arduino_delay)
            self.arduinos.append(a)
            return a

        self.tool = StabilityTool(
            self.seq, self.panel, lambda: tf.WIDE, pg.GraphicsLayoutWidget(),
            temp_factory=factory if temp else None,
            sos_fn=lambda T: 1402.7 + 4.88 * T - 0.0482 * T ** 2,
            cw_fn=lambda: (self.sim.params.c_w, 'synthetic SeDaq'),
            gains_fn=lambda: (65.0, 35.0), dump_dir=self.dump_dir)
        self.statuses, self.warnings, self.dones = [], [], []
        self.tool.status.connect(self.statuses.append)
        self.tool.warning.connect(self.warnings.append)
        self.tool.done.connect(self.dones.append)

    def run_test(self, n=6, avg_n=4, on_point=None, timeout_ms=60000):
        if on_point is not None:
            self.seq.point_done.connect(on_point)
        self.assertIsNone(self.tool.run(StabilityParams(n=n, interval_s=0.0, avg_n=avg_n)))
        loop = QEventLoop()
        self.tool.done.connect(loop.quit)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec_()
        files = os.listdir(self.dump_dir)
        self.assertEqual(len(files), 1, files)
        d = np.load(os.path.join(self.dump_dir, files[0]))
        return json.loads(str(d['meta_json'])), d

    def test_nothing_moves_and_the_dump_has_everything(self):
        self.make()
        meta, d = self.run_test(n=6)
        self.assertEqual(self.dones, ['done'])
        self.assertEqual(self.enqueued, [])                 # not even a null move
        self.assertEqual(self.worker.moves, [])
        self.assertTrue(self.live['on'])
        # metadata: position, interval, number of measures, and the common block
        self.assertEqual(meta['tool'], 'stability')
        self.assertEqual(meta['position'], {'X': 50.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0})
        self.assertEqual((meta['interval_s'], meta['n_requested'], meta['n_measured']),
                         (0.0, 6, 6))
        self.assertEqual((meta['settle_ms'], meta['avg_n']), (0, 4))
        self.assertEqual((meta['gain_ch1_db'], meta['gain_ch2_db']), (65.0, 35.0))
        self.assertAlmostEqual(meta['temperature']['T2'], 24.2)
        self.assertEqual(meta['temp_every'], 1)
        # full records of both channels on every point
        self.assertEqual(d['record'].shape, (6, 8192))           # Ch2 (PE)
        self.assertEqual(d['record_ch1'].shape, (6, 8192))       # Ch1 (transmission)
        # temperature on every point (one Arduino, closed at the end)
        self.assertTrue(np.all(np.isfinite(d['T1'])))
        self.assertEqual(len(self.arduinos), 1)
        self.assertTrue(self.arduinos[0].closed)
        for key in ('t_s', 'face_um', 'ch1_dtof_ns', 'amp_ch2_db', 'amp_ch1_db', 'T2'):
            self.assertEqual(d[key].shape, (6,), key)
        # nothing changed: no drift
        self.assertLess(np.max(np.abs(d['face_um'])), 0.3)
        self.assertLess(np.max(np.abs(d['ch1_dtof_ns'])), 0.3)

    def test_holder_drift_seen_by_ch2_not_ch1(self):
        """The face comes 2 µm closer per measure and the thickness stays: Ch1 flat."""
        self.make()

        def drift(*_):
            self.sim.params.x_focus += 0.002          # PE side 'origin': d decreases
        meta, d = self.run_test(n=8, on_point=drift)
        k = np.arange(8)
        slope = np.polyfit(k, d['face_um'], 1)[0]
        self.assertAlmostEqual(slope, -2.0, delta=0.3)              # closer: negative
        self.assertLess(abs(np.polyfit(k, d['ch1_dtof_ns'], 1)[0]), 0.05)

    def test_swelling_seen_by_ch1(self):
        """The sample swells 50 µm per measure: Ch1 transmission ToF changes."""
        self.make()

        def swell(*_):
            self.sim.params.thickness += 0.05
        meta, d = self.run_test(n=6, on_point=swell)
        p = self.sim.params
        expected = 0.05e-3 * (1 / p.c_sample - 1 / p.c_w) * 1e9   # ns per measure (< 0)
        slope = np.polyfit(np.arange(6), d['ch1_dtof_ns'], 1)[0]
        self.assertAlmostEqual(slope, expected, delta=0.15 * abs(expected))

    def test_slow_temperature_read_every_few_points(self):
        self.make(arduino_delay=0.6)
        meta, d = self.run_test(n=6, avg_n=1)
        self.assertEqual(meta['temp_every'], 2)
        self.assertIn('every 2 points', meta['temp_note'])
        self.assertTrue(all(r > 0.5 for r in meta['temp_read_s']))
        np.testing.assert_array_equal(np.isfinite(d['T1']), [True, False] * 3)
        self.assertTrue(any('every 2 points' in w for w in self.warnings))

    def test_no_pt100(self):
        self.make(temp=False)
        meta, d = self.run_test(n=4)
        self.assertIsNone(meta['temperature'])
        self.assertTrue(np.all(np.isnan(d['T1'])))
        self.assertTrue(any('PT100 not available' in w for w in self.warnings))

    def test_stop_keeps_what_was_measured(self):
        self.make()
        meta, d = self.run_test(
            n=20, on_point=lambda i, *_: i == 3 and self.tool.stop())
        self.assertEqual(self.dones, ['stopped'])
        self.assertEqual(meta['n_measured'], 4)
        self.assertEqual(d['record_ch1'].shape[0], 4)
        self.assertEqual(self.enqueued[:1], [('stop',)] if self.enqueued else [])
        self.assertIn('stopped', self.statuses[-1])

    def test_group_defaults_and_estimate(self):
        self.make()
        g = StabilityGroup(self.tool, self.seq)
        self.assertEqual(g.params(), StabilityParams())
        self.assertIn('Total', g._lbl_estimate.text())
        self.assertIn('21 min 36 s', g._lbl_estimate.text())   # 20 min + 240 × 20 × 20 ms
        self.assertIn('No axis moves', g._lbl_estimate.text())


if __name__ == '__main__':
    unittest.main()
