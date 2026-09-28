# -*- coding: utf-8 -*-
"""
test_focus_tool.py — synthetic SeDaq (sim_sedaq.py) and focus search
(focus_tool.py), task_scanner_phase3.md "Verificación" points 2, 3, 4, 5, 7, 8.

Run from the repo root in the 32-bit production environment:
    conda run -p ~\\anaconda3_32 python -m unittest discover -s acquisition -v
"""
import os
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from sim_sedaq import QUANT, SimParams, SimSeDaq  # noqa: E402
from focus_tool import (  # noqa: E402
    FocusPlan, echo_samples_per_mm, fit_parabola_db, point_flags, sweep_positions,
    window_peak,
)

FS = 100e6
LIMIT = 100.0


def raw_to_float(buf, reclen):
    """Same conversion as ecos_gui.EcosGUI._raw_to_float."""
    arr = np.array(list(buf[:reclen]), dtype=float)
    arr = (arr - QUANT / 2.0) / QUANT
    arr -= arr.mean()
    return arr


def acquire(sim, avg_n):
    """Averaged (ch1, ch2), like ecos_gui._acquire_avg."""
    acc1 = np.zeros(sim.RecLen)
    acc2 = np.zeros(sim.RecLen)
    for _ in range(avg_n):
        sim.GetAScan()
        acc1 += raw_to_float(sim.DataADC1, sim.RecLen)
        acc2 += raw_to_float(sim.DataADC2, sim.RecLen)
    return acc1 / avg_n, acc2 / avg_n


def make_sim(seed=0, beam='Y', pe_side='origin', **params):
    sim = SimSeDaq(SimParams(**params), reclen=8192, seed=seed)
    sim.set_scanner_state({'X': 50.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}, beam, pe_side)
    return sim


def move(sim, beam_pos):
    coords = dict(sim._coords)
    coords[sim._beam_axis] = beam_pos
    sim.set_scanner_state(coords, sim._beam_axis, sim._pe_side)


def measure_at(sim, xs, window, avg_n, margin=0.05):
    out = []
    for x in xs:
        move(sim, x)
        _, pe = acquire(sim, avg_n)
        out.append(window_peak(pe, window[0], window[1], margin))
    return out


def run_focus(sim, center, window, half=5.0, coarse=1.0, fine=0.2, avg_n=10):
    """The whole FocusPlan against the simulator, no Qt: returns (outcome, plan)."""
    plan = FocusPlan(center, half, coarse, fine, LIMIT, window,
                     samples_per_mm=echo_samples_per_mm(sim._pe_side))
    xs = plan.coarse_positions
    fine_xs, outcome = plan.after_coarse(xs, measure_at(sim, xs, window, avg_n))
    if outcome is not None:
        return outcome, plan
    return plan.after_fine(fine_xs, measure_at(sim, fine_xs, window, avg_n)), plan


def tof_samples(sim, x):
    return sim.front_tof(x, sim.params.lat0, sim.params.z0) * FS


# Window wide enough for the echo over ±5 mm around 50 with the focus anywhere in
# 47–54 mm (F = 20 mm: front echo within ~1500–3700 samples, plus the 5 % margin).
WIDE = (1000, 4500)


# ===========================================================================
#  Synthetic SeDaq
# ===========================================================================
class TestSimSeDaq(unittest.TestCase):

    def test_front_echo_time_of_flight(self):
        sim = make_sim(snr_db=80)
        for x in (46.0, 50.0, 53.0):
            move(sim, x)
            _, pe = acquire(sim, 1)
            m = window_peak(pe, *WIDE)
            self.assertAlmostEqual(m.index, tof_samples(sim, x), delta=3)
        # 1 mm on the beam axis moves the echo 2/c_w
        self.assertAlmostEqual(tof_samples(sim, 51.0) - tof_samples(sim, 50.0),
                               2e-3 / sim.params.c_w * FS, places=6)

    def test_pe_side_sign(self):
        sim = make_sim(pe_side='origin')
        self.assertGreater(tof_samples(sim, 52.0), tof_samples(sim, 50.0))
        sim = make_sim(pe_side='max')
        self.assertLess(tof_samples(sim, 52.0), tof_samples(sim, 50.0))

    def test_amplitude_peaks_at_focus(self):
        sim = make_sim(snr_db=80, x_focus=47.0)
        amps = [m.amp for m in measure_at(sim, [43, 45, 47, 49, 51], WIDE, 1)]
        self.assertEqual(int(np.argmax(amps)), 2)
        self.assertAlmostEqual(amps[2], sim.params.A0, delta=0.02)

    def test_tilt_moves_the_focus(self):
        sim = make_sim(theta_lat=2.0)
        coords = {'X': 60.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}      # beam Y, lateral X
        sim.set_scanner_state(coords, 'Y', 'origin')
        expected = 50.0 - np.tan(np.radians(2.0)) * (60.0 - 50.0)
        self.assertAlmostEqual(sim.expected_focus(60.0, 25.0), expected)
        x_beam, lat, z = sim.roles()
        self.assertAlmostEqual(sim.face_distance(expected, lat, z), sim.params.focal_distance)

    def test_gain_scales_and_saturates(self):
        sim = make_sim(snr_db=80)
        _, pe = acquire(sim, 1)
        a_ref = window_peak(pe, *WIDE).amp
        sim.SetGain2(sim.params.gain_ref_ch2 + 6.0)
        _, pe = acquire(sim, 1)
        self.assertAlmostEqual(window_peak(pe, *WIDE).amp / a_ref, 10 ** (6 / 20), delta=0.05)
        sim.SetGain2(sim.params.gain_ref_ch2 + 20.0)
        sim.GetAScan()
        raw = np.asarray(sim.DataADC2)
        self.assertEqual(raw.max(), QUANT - 1)
        self.assertEqual(raw.min(), 0)
        _, pe = acquire(sim, 1)
        self.assertTrue(window_peak(pe, *WIDE).saturated)

    def test_zero_gain_is_noise_not_a_dead_record(self):
        sim = make_sim()
        sim.SetGain1(0)          # 65 dB below the reference, as in a saved session
        sim.GetAScan()
        self.assertFalse(np.all(raw_to_float(sim.DataADC1, sim.RecLen) == 0.0))

    def test_through_transmission_has_structure(self):
        sim = make_sim(snr_db=80)
        amps = []
        for lat in (30.0, 50.0):                  # 50 is the inclusion centre
            sim.set_scanner_state({'X': lat, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}, 'Y', 'origin')
            tt, _ = acquire(sim, 1)
            amps.append(window_peak(tt, 3000, 5000).amp)
        self.assertLess(amps[1], 0.6 * amps[0])

    def test_main_bang_outside_window_is_larger(self):
        """Why the measure must stay inside Smin–Smax."""
        sim = make_sim()
        _, pe = acquire(sim, 1)
        self.assertGreater(np.max(np.abs(pe[:200])), window_peak(pe, *WIDE).amp)

    def test_reclen(self):
        sim = make_sim()
        sim.SetRecLen(4096)
        sim.GetAScan()
        self.assertEqual(len(sim.DataADC1), 4096)
        self.assertEqual(len(sim.DataADC2), 4096)


# ===========================================================================
#  Pure focus helpers
# ===========================================================================
class TestFocusHelpers(unittest.TestCase):

    def test_sweep_positions_symmetric(self):
        xs, clipped = sweep_positions(50.0, 5.0, 1.0, LIMIT)
        self.assertFalse(clipped)
        self.assertEqual(xs, [45.0 + k for k in range(11)])

    def test_sweep_positions_clipped(self):
        xs, clipped = sweep_positions(2.0, 5.0, 1.0, LIMIT)
        self.assertTrue(clipped)
        self.assertEqual(xs[0], 0.0)
        self.assertEqual(xs[-1], 7.0)
        xs, clipped = sweep_positions(98.5, 5.0, 1.0, LIMIT)
        self.assertTrue(clipped)
        self.assertLessEqual(xs[-1], LIMIT)

    def test_parabola_on_exact_gaussian(self):
        xs = list(np.arange(49.0, 51.01, 0.2))
        amps = [np.exp(-(x - 50.07) ** 2 / (2 * 2.0 ** 2)) for x in xs]
        fit = fit_parabola_db(xs, amps, int(np.argmax(amps)))
        self.assertAlmostEqual(fit.x_opt, 50.07, places=6)

    def test_plan_rejects_bad_steps(self):
        with self.assertRaises(ValueError):
            FocusPlan(50, 5, 1.0, 1.0, LIMIT, WIDE)
        with self.assertRaises(ValueError):
            FocusPlan(50, 0.5, 1.0, 0.2, LIMIT, WIDE)


# ===========================================================================
#  Focus search against the simulator (verification points 2, 3, 4, 7)
# ===========================================================================
class TestFocusSearch(unittest.TestCase):

    def test_finds_focus_within_fine_step(self):
        """Point 2: error < fine step for several x_focus and SNR."""
        fine = 0.2
        for seed, (x_focus, snr) in enumerate([(50.0, 30), (47.3, 30), (53.66, 30),
                                               (48.9, 40), (51.25, 50), (50.5, 35)]):
            with self.subTest(x_focus=x_focus, snr=snr):
                sim = make_sim(seed=seed, x_focus=x_focus, snr_db=snr)
                outcome, _ = run_focus(sim, 50.0, WIDE, fine=fine)
                self.assertTrue(outcome.move, outcome.text)
                self.assertLess(abs(outcome.fit.x_opt - x_focus), fine, outcome.text)

    def test_finds_focus_with_pe_on_max_side_and_tilt(self):
        sim = make_sim(seed=7, x_focus=51.0, pe_side='max', theta_lat=3.0, theta_z=-2.0)
        sim.set_scanner_state({'X': 55.0, 'Y': 50.0, 'Z': 22.0, 'R': 0.0}, 'Y', 'max')
        truth = sim.expected_focus(55.0, 22.0)
        outcome, _ = run_focus(sim, 50.0, WIDE)
        self.assertTrue(outcome.move, outcome.text)
        self.assertLess(abs(outcome.fit.x_opt - truth), 0.2)

    def test_focus_outside_range_does_not_move(self):
        """Point 3."""
        sim = make_sim(x_focus=58.0)
        outcome, _ = run_focus(sim, 50.0, (500, 5000))
        self.assertFalse(outcome.move)
        self.assertIn('widen the range', outcome.text)

    def test_range_clipped_to_session_limits(self):
        """Point 4: clipped with a notice (here the focus is still found)."""
        sim = make_sim(x_focus=3.0)
        sim.params.focal_distance = 20.0
        outcome, plan = run_focus(sim, 1.0, (100, 4000))
        self.assertTrue(plan.clipped)
        self.assertEqual(plan.coarse_positions[0], 0.0)
        self.assertTrue(any('clipped' in n for n in outcome.notices))
        self.assertTrue(outcome.move, outcome.text)
        self.assertLess(abs(outcome.fit.x_opt - 3.0), 0.2)

    def test_narrow_window_flags_points(self):
        """Point 7: the echo leaves Smin–Smax → those points flagged, no move."""
        sim = make_sim(seed=3, x_focus=50.0)
        t_focus = int(tof_samples(sim, 50.0))
        window = (t_focus - 400, t_focus + 400)    # ±3 mm of echo travel, margin 40 samples
        xs = sweep_positions(50.0, 5.0, 1.0, LIMIT)[0]
        flags = point_flags(xs, measure_at(sim, xs, window, 10), window,
                            samples_per_mm=echo_samples_per_mm('origin'))
        self.assertEqual([x for x, f in zip(xs, flags) if f], [45, 46, 47, 53, 54, 55])
        outcome, _ = run_focus(sim, 50.0, window)
        self.assertFalse(outcome.move)
        self.assertIn('widen smin–smax', outcome.text.lower())

    def test_edge_pinned_echo_is_flagged(self):
        """The literal spec criterion: envelope peak within the margin of a window edge."""
        sim = make_sim(snr_db=60)
        t = int(tof_samples(sim, 50.0))
        move(sim, 50.0)
        _, pe = acquire(sim, 1)
        m = window_peak(pe, t - 1000, t + 10)       # echo half out on the right
        self.assertTrue(m.at_edge)
        m = window_peak(pe, t - 1000, t + 1000)
        self.assertFalse(m.at_edge)

    def test_saturation_blocks_the_move(self):
        sim = make_sim(seed=5)
        sim.SetGain2(sim.params.gain_ref_ch2 + 12.0)     # A0 0.2 → 0.8: clips at 0.5
        outcome, _ = run_focus(sim, 50.0, WIDE)
        self.assertFalse(outcome.move)
        self.assertIn('lower the gain', outcome.text.lower())


# ===========================================================================
#  Qt integration: FocusTool on the real ScanSequencer (points 5, 8)
# ===========================================================================
from PyQt5.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import pyqtgraph as pg  # noqa: E402
from scan_sequencer import ScanSequencer  # noqa: E402
from focus_tool import FocusTool  # noqa: E402


class FakeWorker(QObject):
    """Stands in for ScannerWorker: 'move_point' moves instantly (next event loop turn)."""
    point_moved = pyqtSignal(int, bool)
    error = pyqtSignal(str)
    disconnected = pyqtSignal()

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.moves = []

    def enqueue(self, cmd):
        if cmd[0] != 'move_point':
            return
        _, token, targets = cmd
        for axis, value in targets:
            self.panel.coords[axis] = value
            self.moves.append(value)
        self.panel.push()
        QTimer.singleShot(0, lambda: self.point_moved.emit(token, True))


class FakePanel:
    def __init__(self, sim, beam_pos=50.0):
        self.sim = sim
        self.coords = {'X': 50.0, 'Y': beam_pos, 'Z': 25.0, 'R': 0.0}
        self.push()

    def push(self):
        self.sim.set_scanner_state(self.coords, 'Y', 'origin')

    def sequence_blocker(self):
        return None

    def role_axis(self, role):
        return {'beam': 'Y', 'lateral': 'X'}.get(role, role)

    def pe_side(self):
        return 'origin'

    def current_coords(self):
        return dict(self.coords)

    def axis_limit(self, axis):
        return LIMIT

    def validate_position(self, pos):
        return None if all(0 <= v <= LIMIT for v in pos.values()) else 'out of range'


class TestFocusToolQt(unittest.TestCase):

    def setUp(self):
        self.sim = make_sim(seed=11, x_focus=51.3)
        self.panel = FakePanel(self.sim)
        self.worker = FakeWorker(self.panel)
        self.live = {'on': True, 'restarts': 0}

        def leave():
            self.live['on'] = True
            self.live['restarts'] += 1

        self.seq = ScanSequencer(
            self.worker, self.sim, lambda n: acquire(self.sim, n),
            coords_fn=self.panel.current_coords,
            enter_exclusive=lambda: self.live.update(on=False),
            leave_exclusive=leave)
        self.window = WIDE
        self.window_reads = 0

        def window_fn():
            self.window_reads += 1
            return self.window

        self.plot = pg.PlotWidget()
        self.tool = FocusTool(self.seq, self.panel, window_fn, self.plot)
        self.results = []
        self.tool.done.connect(self.results.append)
        self.statuses = []
        self.tool.status.connect(self.statuses.append)

    def wait_done(self, timeout_ms=20000):
        loop = QEventLoop()
        self.tool.done.connect(loop.quit)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec_()

    def test_full_run_moves_to_optimum(self):
        reason = self.tool.run(5.0, 1.0, 0.2, avg_n=10, settle_ms=0)
        self.assertIsNone(reason)
        self.wait_done()
        self.assertEqual(self.results, [True], self.tool.last_outcome and self.tool.last_outcome.text)
        x_opt = self.tool.last_outcome.fit.x_opt
        self.assertLess(abs(x_opt - 51.3), 0.2)
        self.assertAlmostEqual(self.panel.coords['Y'], x_opt)      # final move done
        self.assertTrue(self.live['on'])                           # live refresh back
        self.assertEqual(self.window, WIDE)                        # window untouched (point 8)

    def test_stop_midway_does_not_move_to_optimum(self):
        """Point 5: STOP during the coarse sweep."""
        count = {'n': 0}

        def on_point(*_):
            count['n'] += 1
            if count['n'] == 3:
                self.seq.abort()
        self.seq.point_done.connect(on_point)
        self.assertIsNone(self.tool.run(5.0, 1.0, 0.2, avg_n=2, settle_ms=0))
        self.wait_done()
        self.assertEqual(self.results, [False])
        self.assertEqual(len(self.worker.moves), 3)               # nothing after the 3rd point:
        self.assertEqual(self.panel.coords['Y'], 47.0)            # no return to the start either
        self.assertIn('Scanner at Y = 47.00 mm', self.statuses[-1])
        self.assertTrue(self.live['on'])
        self.assertFalse(self.seq.active)

    def test_stop_during_return_does_not_move_again(self):
        self.sim.params.x_focus = 58.0
        self.window = (500, 5000)

        def on_point(*_):
            if self.tool._phase == 'return':
                self.seq.abort()                                  # STOP while going back
        self.seq.point_done.connect(on_point)
        self.assertIsNone(self.tool.run(5.0, 1.0, 0.2, avg_n=2, settle_ms=0))
        self.wait_done()
        self.assertEqual(self.results, [False])
        self.assertIn('stopped during the return phase', self.statuses[-1])
        self.assertEqual(len(self.worker.moves), 12)              # the return move, nothing after

    def test_focus_out_of_range_does_not_move(self):
        self.sim.params.x_focus = 58.0
        self.window = (500, 5000)
        self.assertIsNone(self.tool.run(5.0, 1.0, 0.2, avg_n=2, settle_ms=0))
        self.wait_done()
        self.assertEqual(self.results, [False])
        self.assertIn('widen the range', self.statuses[-1])
        self.assertEqual(self.worker.moves[:11], [45.0 + k for k in range(11)])
        self.assertEqual(self.worker.moves[11:], [50.0])          # back to the start, no optimum
        self.assertEqual(self.panel.coords['Y'], 50.0)
        self.assertIn('Back at the start position (Y = 50.00 mm)', self.statuses[-1])

    def test_edge_warning_is_emitted_during_the_sweep(self):
        t = int(tof_samples(self.sim, 51.3))
        self.window = (t - 400, t + 400)
        warnings = []
        points_at_warning = []
        self.tool.warning.connect(lambda text: (warnings.append(text),
                                                points_at_warning.append(len(self.seq.results))))
        self.assertIsNone(self.tool.run(5.0, 1.0, 0.2, avg_n=2, settle_ms=0))
        self.wait_done()
        self.assertTrue(warnings)
        # During the coarse sweep (11 points), as soon as a clear echo gives the reference
        self.assertLess(points_at_warning[0], 11)
        self.assertIn('widen Smin–Smax', warnings[0])
        self.assertEqual(self.window, (t - 400, t + 400))
        # Window warning: no move to the optimum, back to the start position
        self.assertEqual(self.results, [False])
        self.assertEqual(self.worker.moves[-1], 50.0)
        self.assertEqual(len(self.worker.moves), 12)
        self.assertIn('Back at the start position', self.statuses[-1])


if __name__ == '__main__':
    unittest.main()
