# -*- coding: utf-8 -*-
"""
test_scan_tool.py — line scan, water references and saving (scan_tool.py,
BD_Experimentos_PVA.save_scan_raw_32), task_scanner_phase5.md "Verificación" 1–6.

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
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, '..', 'database'))

import numpy as np  # noqa: E402

import test_focus_tool as tf  # noqa: E402  (module import: its tests are not collected twice)
from BD_Experimentos_PVA import (  # noqa: E402
    experiment_name, load_scan_raw_32, save_scan_raw_32,
)
from scan_tool import (  # noqa: E402
    LONG_SCAN_S, MAGNITUDES, PointContext, ScanParams, ScanPlan, compute_magnitudes,
    estimate_scan_s, line_positions, register_magnitude,
)
from sim_sedaq import SimParams, SimSeDaq  # noqa: E402

FS = tf.FS
LIMIT = tf.LIMIT
OFFSET = 0.003          # the fake scanner lands this far from every target (real ≠ requested)


# ===========================================================================
#  Pure part
# ===========================================================================
class TestLineAndMagnitudes(unittest.TestCase):

    def test_line_positions(self):
        self.assertEqual(line_positions(45.0, 47.0, 0.5, LIMIT)[0], [45.0, 45.5, 46.0, 46.5, 47.0])
        self.assertEqual(line_positions(47.0, 45.0, 1.0, LIMIT)[0], [47.0, 46.0, 45.0])
        xs, clipped = line_positions(-1.0, 2.0, 1.0, LIMIT)
        self.assertEqual((xs, clipped), ([0.0, 1.0, 2.0], True))
        with self.assertRaises(ValueError):
            line_positions(0.0, 1.0, 0.0, LIMIT)

    def test_plan_relative_and_absolute(self):
        coords = {'X': 50.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}
        rel = ScanPlan(ScanParams(axis_role='lateral', start=-2, end=2, step=1), coords, 'X', 'Y',
                       {'X': LIMIT, 'Z': LIMIT})
        self.assertEqual(rel.xs, [48.0, 49.0, 50.0, 51.0, 52.0])
        self.assertEqual(rel.positions()[0], {'X': 48.0})
        ab = ScanPlan(ScanParams(axis_role='z', mode='absolute', start=20, end=22, step=1), coords,
                      'X', 'Y', {'X': LIMIT, 'Z': LIMIT})
        self.assertEqual((ab.axis, ab.xs), ('Z', [20.0, 21.0, 22.0]))
        self.assertEqual(ab.home, {'Z': 25.0})

    def test_estimate_and_long_scan(self):
        coords = {'X': 50.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}
        plan = ScanPlan(ScanParams(start=-1, end=1, step=1, settle_ms=500, avg_n=20), coords,
                        'X', 'Y', {'X': LIMIT, 'Z': LIMIT})
        # 49 → 50 → 51, from 50 and back: 1 + 1 + 1 + 1 mm; 3 × (0.5 s + 20 × 10 ms)
        self.assertAlmostEqual(estimate_scan_s(plan, 0.01, 6.7), 4 / 6.7 + 3 * 0.7)
        long_plan = ScanPlan(ScanParams(start=-50, end=40, step=0.05, settle_ms=1000, avg_n=20),
                             coords, 'X', 'Y', {'X': LIMIT, 'Z': LIMIT})
        self.assertGreater(estimate_scan_s(long_plan, 0.01), LONG_SCAN_S)

    def test_magnitudes_are_extensible(self):
        self.assertEqual(list(MAGNITUDES)[:3], ['amplitude', 'tof', 'energy'])
        from echo_tracking import PeakMeasure
        seg = np.sin(np.arange(100) / 3.0)
        ctx = PointContext(PeakMeasure(1.0, 150, False, False, 50.0, 'tracked', index_frac=150.5),
                           seg, np.abs(seg), seg, FS, 0)
        register_magnitude('peak_to_peak', 'Peak to peak (PE)', '',
                           lambda c: float(np.ptp(c.seg)))
        try:
            vals = compute_magnitudes(ctx)
            self.assertAlmostEqual(vals['tof'], 1.505)
            self.assertAlmostEqual(vals['peak_to_peak'], np.ptp(seg))
            self.assertTrue(np.isnan(compute_magnitudes(ctx, lost=True)['tof']))
        finally:
            del MAGNITUDES['peak_to_peak']


class TestScanSaveFormat(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='scan_save_test_')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_experiment_name_keeps_the_us_convention(self):
        self.assertEqual(experiment_name('10', '5', 'P3A', '5', 'US', '20261002_091500'),
                         'PVA_10_PG_05_A_C005_US_20261002_091500')
        self.assertEqual(experiment_name('', 'x', '', '', 'SCAN', '20261002_091500'),
                         'PVA_XX_PG_YY_X_CNNN_SCAN_20261002_091500')

    def test_roundtrip_and_validation(self):
        ch = np.random.default_rng(0).normal(size=(1, 3, 50))
        kw = dict(specimen={'pieza': 'A'}, protocol={}, equipment1={'params': {'Smin': 100,
                                                                               'Smax': 150}},
                  equipment2={}, scanner_session={'beam_axis': 'Y'}, scan={'type': 'line'},
                  signals_ch1=ch, signals_ch2=ch * 2, coords=np.zeros((1, 3, 4)),
                  point_time=np.arange(3.0).reshape(1, 3),
                  temperatures=[{'label': 'start', 'point': -1, 'time': 1.0, 'T1': float('nan'),
                                 'T2': 24.0}],
                  operator='Ana', base_dir=self.dir, exp_name='PVA_10_PG_05_A_C005_SCAN_x')
        path = save_scan_raw_32(**kw)
        meta, data = load_scan_raw_32(path)
        self.assertEqual(meta['schema_version'], 'scan-32-1.0')
        self.assertEqual(meta['experiment']['operator'], 'Ana')
        self.assertFalse(os.path.exists(os.path.join(path, 'results.json')))
        np.testing.assert_allclose(data['signals_ch2'], (ch * 2).astype(np.float32))
        self.assertTrue(np.isnan(data['temp_T1'][0]))
        with self.assertRaises(FileExistsError):
            save_scan_raw_32(**kw)
        bad = dict(kw, exp_name='other', signals_ch2=ch[:, :2])
        with self.assertRaises(ValueError):
            save_scan_raw_32(**bad)


# ===========================================================================
#  Qt: ScanTool on the real ScanSequencer
# ===========================================================================
from PyQt5.QtCore import QEventLoop, QObject, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

import pyqtgraph as pg  # noqa: E402
from scan_sequencer import ScanSequencer  # noqa: E402
from scan_tool import ScanGroup, ScanTool  # noqa: E402


class GainLogSim(SimSeDaq):
    """SimSeDaq that logs every gain call (Gain2 must follow every Gain1)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.gain_log = []

    def SetGain1(self, g):
        self.gain_log.append(('G1', g))
        super().SetGain1(g)

    def SetGain2(self, g):
        self.gain_log.append(('G2', g))
        super().SetGain2(g)


class Panel(QObject):
    """Scanner panel stand-in: emits scanner_state_changed like the real one."""
    scanner_state_changed = pyqtSignal()

    def __init__(self, sim):
        super().__init__()
        self.sim = sim
        self.coords = {'X': 50.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}
        self.is_busy = False
        self.push()

    def push(self):
        self.sim.set_scanner_state(self.coords, 'Y', 'origin')
        self.scanner_state_changed.emit()

    def manual_move(self, axis, value):
        self.coords[axis] = value
        self.push()

    def sequence_blocker(self):
        return None

    def role_axis(self, role):
        return {'beam': 'Y', 'lateral': 'X', 'Z': 'Z', 'R': 'R'}[role]

    def current_coords(self):
        return dict(self.coords)

    def axis_limit(self, axis):
        return LIMIT

    def pe_side(self):
        return 'origin'

    def validate_position(self, pos):
        return None if all(0 <= v <= LIMIT for v in pos.values()) else 'out of range'

    def session_dict(self):
        return {'beam_axis': 'Y', 'pe_side': 'origin', 'limits': {'X': LIMIT}}


class Worker(QObject):
    """Moves instantly but lands OFFSET mm past the target (read back ≠ requested);
    with speed set, it takes |Δ|/speed seconds like the real one."""
    point_moved = pyqtSignal(int, bool)
    error = pyqtSignal(str)
    disconnected = pyqtSignal()

    def __init__(self, panel, speed=None):
        super().__init__()
        self.panel, self.speed = panel, speed
        self.moves = []          # (axis, target)

    def enqueue(self, cmd):
        if cmd[0] != 'move_point':
            return
        _, token, targets = cmd
        travel = 0.0
        for axis, value in targets:
            travel += abs(value - self.panel.coords[axis])
            self.panel.coords[axis] = round(value + OFFSET, 6)
            self.moves.append((axis, value))
        self.panel.push()
        delay = int(1000 * travel / self.speed) if self.speed else 0
        QTimer.singleShot(delay, lambda: self.point_moved.emit(token, True))


class FakeArduino:
    instances = 0

    def __init__(self):
        FakeArduino.instances += 1
        self.reads = 0
        self.closed = False

    def getTemperatures(self):
        self.reads += 1
        return 24.5, 24.7

    def close(self):
        self.closed = True


class ScanHarness(unittest.TestCase):

    def make(self, worker_speed=None, temp=True, **sim_params):
        sim_params.setdefault('snr_db', 40.0)
        self.sim = GainLogSim(SimParams(**sim_params), reclen=8192, seed=3)
        self.panel = Panel(self.sim)
        self.worker = Worker(self.panel, worker_speed)
        self.live = {'on': True}
        self.seq = ScanSequencer(
            self.worker, self.sim, lambda n: tf.acquire(self.sim, n),
            coords_fn=self.panel.current_coords,
            enter_exclusive=lambda: self.live.update(on=False),
            leave_exclusive=lambda: self.live.update(on=True))
        self.base = tempfile.mkdtemp(prefix='scan_db_test_')
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.arduinos = []

        def factory():
            a = FakeArduino()
            self.arduinos.append(a)
            return a

        self.scan_gains = (65.0, 35.0)

        def set_gains(g1, g2):
            self.sim.SetGain1(g1)
            self.sim.SetGain2(g2)

        self.locks = []
        self.tool = ScanTool(
            self.seq, self.panel, lambda: tf.WIDE, pg.PlotWidget(),
            acquire_fn=lambda n: tf.acquire(self.sim, n), gains_fn=lambda: self.scan_gains,
            set_gains_fn=set_gains, temp_factory=factory if temp else None,
            sos_fn=lambda T: 1402.7 + 4.88 * T - 0.0482 * T ** 2,
            cw_fn=lambda: (self.sim.params.c_w, 'synthetic SeDaq'),
            info_fn=lambda: {'specimen': {'pieza': 'P3A'}, 'protocol': {},
                             'equipment1': {'nombre': 'SEDAQ', 'params': {'Voltaje': '100'}},
                             'equipment2': {},
                             'name_parts': {'pva': '10', 'additive': '5', 'sample_id': 'P3A',
                                            'cycles': '5'}},
            base_dir=self.base, lock_fn=self.locks.append,
            acq_time_fn=getattr(self, 'acq_time', None))
        self.statuses, self.warnings, self.dones, self.states = [], [], [], []
        self.tool.status.connect(self.statuses.append)
        self.tool.warning.connect(self.warnings.append)
        self.tool.done.connect(self.dones.append)
        self.tool.state_changed.connect(self.states.append)

    def wait(self, cond, timeout_ms=30000):
        loop = QEventLoop()
        t0 = time.monotonic()
        timer = QTimer()
        timer.timeout.connect(lambda: (cond() or time.monotonic() - t0 > timeout_ms / 1000.0)
                              and loop.quit())
        timer.start(5)
        if not cond():
            loop.exec_()
        timer.stop()
        self.assertTrue(cond(), f'timeout; state={self.tool.state}, last status: '
                                f'{self.statuses[-1:]}')

    def load_saved(self):
        folders = os.listdir(self.base)
        self.assertEqual(len(folders), 1, folders)
        self.assertRegex(folders[0], r'^PVA_10_PG_05_A_C005_SCAN_\d{8}_\d{6}$')
        return load_scan_raw_32(os.path.join(self.base, folders[0]))


class TestLineScan(ScanHarness):

    def test_full_scan_both_axes(self):
        """Point 1 and 4: map point by point, real coordinates, saved and read back."""
        for role, axis in (('lateral', 'X'), ('z', 'Z')):
            with self.subTest(axis=role):
                self.make()
                counts = []
                self.tool.echo_used.connect(lambda _m: counts.append(len(self.tool.data.coords)))
                p = ScanParams(axis_role=role, start=-2, end=2, step=0.5, settle_ms=0, avg_n=2)
                self.assertIsNone(self.tool.start(p))
                self.wait(lambda: self.dones)
                self.assertEqual(self.dones, ['completed'], self.statuses[-1])
                self.assertEqual(counts, list(range(1, 10)))            # one map update per point
                meta, d = self.load_saved()
                n_samp = tf.WIDE[1] - tf.WIDE[0]
                self.assertEqual(d['signals_ch1'].shape, (1, 9, n_samp))
                self.assertEqual(d['signals_ch2'].shape, (1, 9, n_samp))
                self.assertEqual(d['coords'].shape, (1, 9, 4))
                k = 'XYZR'.index(axis)
                np.testing.assert_allclose(d['positions_requested'][0],
                                           np.arange(-2, 2.01, 0.5) + (50.0 if axis == 'X' else 25.0))
                np.testing.assert_allclose(d['coords'][0, :, k],          # read back, not requested
                                           d['positions_requested'][0] + OFFSET)
                self.assertEqual(meta['scan']['axis'], axis)
                self.assertEqual(meta['scan']['n_acquired'], 9)
                self.assertTrue(meta['scan']['completed'])
                self.assertEqual(meta['scanner_session']['beam_axis'], 'Y')
                self.assertEqual(meta['specimen']['pieza'], 'P3A')
                self.assertEqual(list(d['temp_label']), ['start', 'end'])
                self.assertEqual(list(d['temp_point']), [-1, 8])
                self.assertEqual(list(d['temp_T1']), [24.5, 24.5])
                self.assertEqual(len(self.arduinos), 1)                 # one instance…
                self.assertTrue(self.arduinos[0].closed)                # …closed at the end
                # the stored PE signal is what the simulator produced at that real position
                pe = d['signals_ch2'][0, 4]
                self.assertGreater(np.max(np.abs(pe)), 0.1)
                self.assertEqual(self.locks, [True, False])
                self.assertTrue(self.live['on'])
                self.assertAlmostEqual(self.panel.coords[axis],
                                       (50.0 if axis == 'X' else 25.0) + OFFSET)   # back home
                self.assertEqual(self.tool.state, 'idle')
                self.assertIsNone(self.seq.reserved_reason())

    def test_pause_resume_stop_and_save_offer(self):
        """Point 2."""
        self.make()
        seen = {'n': 0}
        paused_states = []

        def resume():
            paused_states.append(self.seq.state)
            self.tool.resume()

        def on_point(*_):
            seen['n'] += 1
            if seen['n'] == 2:
                self.tool.pause()
                QTimer.singleShot(50, resume)
            if seen['n'] == 5:
                self.tool.stop()
        self.seq.point_done.connect(on_point)
        p = ScanParams(start=-4, end=4, step=0.5, settle_ms=0, avg_n=2)
        self.assertIsNone(self.tool.start(p))
        self.wait(lambda: self.tool.state == 'stopped')
        self.assertEqual(paused_states, ['paused'])            # it really paused, then resumed
        n_moves = len(self.worker.moves)
        self.assertEqual(self.tool.data.n, 5)
        self.assertIn('save them', self.statuses[-1])
        self.assertIn('Not moved', self.statuses[-1])
        QApplication.processEvents()
        self.assertEqual(len(self.worker.moves), n_moves)          # nothing moves after STOP
        self.assertEqual(os.listdir(self.base), [])                # nothing saved yet
        self.assertIsNone(self.tool.save_acquired())
        self.assertEqual(self.dones, ['stopped'])
        meta, d = self.load_saved()
        self.assertEqual(d['signals_ch1'].shape[1], 5)
        self.assertFalse(meta['scan']['completed'])
        self.assertEqual(meta['scan']['n_points'], 17)
        self.assertEqual(len(self.worker.moves), n_moves)          # saving does not move

    def test_stop_then_discard(self):
        self.make()
        self.seq.point_done.connect(lambda i, *_: i == 2 and self.tool.stop())
        self.assertIsNone(self.tool.start(ScanParams(start=-2, end=2, step=0.5, settle_ms=0,
                                                     avg_n=1)))
        self.wait(lambda: self.tool.state == 'stopped')
        self.assertIsNone(self.tool.discard())
        self.assertEqual(self.dones, ['discarded'])
        self.assertEqual(os.listdir(self.base), [])

    def test_lost_echo_is_marked_and_the_scan_goes_on(self):
        self.make(face_half_lat=2.0)
        self.assertIsNone(self.tool.start(ScanParams(start=-5, end=5, step=1, settle_ms=0,
                                                     avg_n=2)))
        self.wait(lambda: self.dones)
        self.assertEqual(self.dones, ['completed'])
        d = self.tool.data
        lost = [k for k, f in enumerate(d.flags) if 'weak' in f]
        self.assertTrue(lost)
        self.assertTrue(all(abs(d.coords[k][0] - 50.0) > 2.0 for k in lost))
        self.assertTrue(all(np.isnan(d.magnitudes[k]['tof']) for k in lost))
        self.assertFalse(np.isnan(d.magnitudes[5]['tof']))
        self.assertTrue(any('tracking lost' in w for w in self.warnings))
        self.assertIn('Front-echo tracking lost', self.statuses[-1])

    def test_no_pt100_nan_and_warning_without_dialogs(self):
        """Point 5."""
        self.make(temp=False)
        modal = []
        self.seq.point_done.connect(lambda *_: modal.append(QApplication.activeModalWidget()))
        self.assertIsNone(self.tool.start(ScanParams(start=-1, end=1, step=1, settle_ms=0,
                                                     avg_n=1)))
        self.assertTrue(any('PT100 not available' in w for w in self.warnings))
        self.wait(lambda: self.dones)
        self.assertGreaterEqual(len(modal), 3)                    # 3 points + the way back
        self.assertTrue(all(w is None for w in modal))
        meta, d = self.load_saved()
        self.assertTrue(np.all(np.isnan(d['temp_T1'])) and np.all(np.isnan(d['temp_T2'])))
        self.assertEqual(meta['scan']['c_w_source'], 'synthetic SeDaq')

    def test_other_tools_refused_during_the_session(self):
        from focus_tool import FocusTool
        self.make()
        focus = FocusTool(self.seq, tf.FakePanel(self.sim), lambda: tf.WIDE, pg.PlotWidget())
        self.assertIsNone(self.tool.start(ScanParams(start=-1, end=1, step=1, settle_ms=0,
                                                     avg_n=1, references=True)))
        self.assertEqual(self.tool.state, 'ref_out')               # between sequences
        self.assertIn('scan session', focus.run(5.0, 1.0))
        self.tool.cancel_reference()
        self.assertIsNone(self.seq.reserved_reason())


class TestWaterReferences(ScanHarness):

    def params(self, **kw):
        base = dict(start=-1, end=1, step=1, settle_ms=0, avg_n=2, references=True,
                    ref_gain1=20.0, ref_gain2=10.0, ref_avg_n=3)
        base.update(kw)
        return ScanParams(**base)

    def take_out(self):
        """The user lifts Z first, then moves X out: order [Z, X]."""
        self.panel.manual_move('Z', 5.0)
        self.panel.manual_move('Z', 4.0)
        self.panel.manual_move('X', 90.0)

    def test_full_reference_flow(self):
        """Point 3: order recorded, reverse way back, gains restored, both references saved."""
        self.make()
        self.assertIsNone(self.tool.start(self.params()))
        self.assertEqual(self.tool.state, 'ref_out')
        self.take_out()
        self.assertEqual(self.tool.data.axis_order, ['Z', 'X'])
        self.sim.gain_log.clear()
        self.assertIsNone(self.tool.continue_reference())
        self.assertEqual(self.tool.state, 'ref_review')
        self.assertEqual(self.sim.gain_log, [('G1', 20.0), ('G2', 10.0)])   # Gain2 after Gain1
        self.assertEqual((self.sim.gain1, self.sim.gain2), (20.0, 10.0))
        self.assertIsNone(self.tool.repeat_reference())
        self.assertIsNone(self.tool.accept_reference())
        self.assertEqual((self.sim.gain1, self.sim.gain2), self.scan_gains)   # restored
        self.assertEqual(self.sim.gain_log[-2:], [('G1', 65.0), ('G2', 35.0)])
        self.wait(lambda: self.tool.state == 'ref_review')                    # final reference
        self.assertEqual(self.tool._review, 'final')
        moves = list(self.worker.moves)
        # back to start: reverse order (X then Z); scan; X home, then reference in order (Z, X)
        self.assertEqual(moves[:2], [('X', 50.0), ('Z', 25.0)])
        self.assertEqual(moves[2:5], [('X', 49.0), ('X', 50.0), ('X', 51.0)])
        self.assertEqual(moves[5:], [('X', 50.0), ('Z', 4.0), ('X', 90.0)])
        self.assertEqual((self.sim.gain1, self.sim.gain2), (20.0, 10.0))
        self.assertIsNone(self.tool.accept_reference())
        self.wait(lambda: self.dones)
        self.assertEqual(self.dones, ['completed'])
        self.assertEqual(self.worker.moves[8:], [('X', 50.0), ('Z', 25.0)])  # reverse again
        self.assertEqual((self.sim.gain1, self.sim.gain2), self.scan_gains)
        meta, d = self.load_saved()
        n_samp = tf.WIDE[1] - tf.WIDE[0]
        for which in ('initial', 'final'):
            self.assertEqual(d[f'ref_{which}_ch1'].shape, (n_samp,))
            self.assertEqual(d[f'ref_{which}_ch2'].shape, (n_samp,))
            np.testing.assert_allclose(d[f'ref_{which}_gains'], [20.0, 10.0])
            self.assertAlmostEqual(d[f'ref_{which}_coords'][0], 90.0, delta=0.01)
            self.assertEqual(int(d[f'ref_{which}_avg_n']), 3)
            self.assertEqual(float(d[f'ref_{which}_T1']), 24.5)
        self.assertEqual(list(d['temp_label']), ['start', 'ref_initial', 'ref_final', 'end'])
        self.assertEqual(meta['scan']['manual_axis_order'], ['Z', 'X'])
        self.assertEqual(sorted(meta['scan']['references_taken']), ['final', 'initial'])
        # in water (sample out) there is no front echo: the reference PE channel is quiet there
        self.assertLess(np.max(np.abs(d['ref_initial_ch2'])), np.max(np.abs(d['signals_ch2'])))
        self.assertEqual(len(self.arduinos), 1)

    def test_stop_mid_scan_asks_for_the_final_reference(self):
        """Spec 7: after a STOP, the final reference is offered; taking it goes on normally."""
        self.make()
        self.assertIsNone(self.tool.start(self.params(start=-3, end=3)))
        self.take_out()
        self.tool.continue_reference()
        self.seq.point_done.connect(
            lambda i, *_: self.tool.state == 'scan' and i == 2 and self.tool.stop())
        self.tool.accept_reference()
        self.wait(lambda: self.tool.state == 'stopped')
        self.assertIn('take the final reference first', self.statuses[-1])
        self.assertIsNone(self.tool.save_acquired(final_reference=True))
        self.wait(lambda: self.tool.state == 'ref_review')
        self.tool.accept_reference()
        self.wait(lambda: self.dones)
        self.assertEqual(self.dones, ['stopped'])
        meta, d = self.load_saved()
        self.assertEqual(d['signals_ch1'].shape[1], 3)
        self.assertIn('ref_final_ch1', d)
        self.assertFalse(meta['scan']['completed'])

    def test_cancel_initial_reference_moves_nothing(self):
        self.make()
        self.tool.start(self.params())
        self.take_out()
        self.tool.continue_reference()
        self.assertIsNone(self.tool.cancel_reference())
        self.assertEqual(self.dones, ['cancelled'])
        self.assertEqual(self.worker.moves, [])
        self.assertEqual((self.sim.gain1, self.sim.gain2), self.scan_gains)
        self.assertEqual(os.listdir(self.base), [])


class TestEstimateMatchesReality(ScanHarness):

    def test_estimate_vs_elapsed(self):
        """Point 6: real moves at 6.7 mm/s, real settle, timed acquisitions."""
        sim = SimSeDaq(SimParams(), reclen=8192, seed=0)
        t0 = time.perf_counter()
        for _ in range(20):
            tf.acquire(sim, 1)                     # same path as the scan acquisitions
        per_scan = (time.perf_counter() - t0) / 20
        self.acq_time = lambda: per_scan           # what ecos_gui times on the live acquisitions
        self.make(worker_speed=6.7)
        p = ScanParams(start=-3, end=3, step=1, settle_ms=150, avg_n=5)
        estimate, text, long_ = self.tool.estimate(p)
        self.assertFalse(long_)
        t0 = time.monotonic()
        self.assertIsNone(self.tool.start(p))
        self.wait(lambda: self.dones, 60000)
        elapsed = time.monotonic() - t0
        self.assertLess(abs(elapsed - estimate) / estimate, 0.35,
                        f'estimate {estimate:.2f} s, elapsed {elapsed:.2f} s')


class TestScanGroup(ScanHarness):

    def test_defaults_estimate_and_buttons(self):
        self.make()
        g = ScanGroup(self.tool, self.seq)
        p = g.params()
        self.assertEqual((p.settle_ms, p.avg_n), (500, 20))          # not the focus ones
        self.assertEqual(p.operator, 'Sebas')
        self.assertIn('Estimated time', g._lbl_estimate.text())
        before = g._lbl_estimate.text()
        g._spin_avg.setValue(200)
        self.assertNotEqual(g._lbl_estimate.text(), before)          # updates with the params
        g._spin_start.setValue(-45.0)
        g._spin_end.setValue(45.0)
        g._spin_step.setValue(0.05)
        self.assertIn('half an hour', g._lbl_estimate.text())
        self.assertTrue(g._btn_start.isEnabled())
        self.assertFalse(g._btn_continue.isEnabled())


if __name__ == '__main__':
    unittest.main()
