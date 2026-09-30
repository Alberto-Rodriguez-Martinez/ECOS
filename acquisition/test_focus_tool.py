# -*- coding: utf-8 -*-
"""
test_focus_tool.py — synthetic SeDaq (sim_sedaq.py), front-echo tracking
(echo_tracking.py) and focus search (focus_tool.py), task_scanner_phase3.md
"Verificación" points 2, 3, 4, 5, 7, 8, plus the thin-sample case (back-face
echo inside Smin–Smax and larger than the front one), the inverted-polarity
front echo (the measure must be the Hilbert envelope, never the signed signal)
and the phase-3 closing changes (fit on the coarse points within 3 dB, focal
zone, vertex uncertainty, flat curve, ToF at the optimum and its slope, lost
echo message, time estimate).

Run from the repo root in the 32-bit production environment:
    conda run -p ~\\anaconda3_32 python -m unittest discover -s acquisition -v
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

from sim_sedaq import QUANT, SimParams, SimSeDaq  # noqa: E402
from echo_tracking import FrontEchoTracker  # noqa: E402
from focus_tool import (  # noqa: E402
    FocusOutcome, FocusPlan, PeakMeasure, echo_samples_per_mm, estimate_duration_s,
    fit_focus_db, fit_select, point_flags, sweep_positions,
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


def make_sim(seed=0, beam='Y', pe_side='origin', thin=False, inverted=False, **params):
    if thin:
        params = dict(dict(thickness=1.5, back_ratio=2.5), **params)
    sim_params = SimParams.inverted_front(**params) if inverted else SimParams(**params)
    sim = SimSeDaq(sim_params, reclen=8192, seed=seed)
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


def measure_tracked(sim, xs, tracker, avg_n):
    """One sweep through the front-echo tracker, as FocusTool does."""
    tracker.new_sweep()
    for x in xs:
        move(sim, x)
        _, pe = acquire(sim, avg_n)
        tracker.measure(pe, x)
    return list(tracker.measures)


def run_focus(sim, center, window, half=5.0, coarse=1.0, fine=None, avg_n=10, tracking=True,
              pe_side=None, emission_sample=0):
    """
    The whole FocusPlan against the simulator, no Qt: returns (outcome, plan).
    fine: fine step of the optional fine sweep (None: none). c_w is the
    simulator's (as the GUI does in simulator mode). pe_side: the side declared
    to the tool (default the simulator's). tracking=False measures the global
    maximum of the window (the behaviour before front-echo tracking), only to
    show that the thin-sample case fails with it.
    """
    c_w = sim.params.c_w
    plan = FocusPlan(center, half, coarse, fine, LIMIT, window,
                     samples_per_mm=echo_samples_per_mm(pe_side or sim._pe_side, c_w),
                     c_w=c_w, cw_source='synthetic SeDaq', emission_sample=emission_sample)

    def sweep(xs):
        if tracking:
            return measure_tracked(sim, xs, plan.tracker, avg_n)
        return measure_at(sim, xs, window, avg_n)

    xs = plan.coarse_positions
    fine_xs, outcome = plan.after_coarse(xs, sweep(xs))
    if fine_xs is None:
        return outcome, plan
    return plan.after_fine(fine_xs, sweep(fine_xs)), plan


def all_text(outcome):
    return ' '.join([outcome.text] + outcome.notices + outcome.report)


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
        xs = [45.0 + k for k in range(11)]
        amps = [np.exp(-(x - 50.07) ** 2 / (2 * 2.0 ** 2)) for x in xs]
        fit = fit_focus_db(xs, amps)
        self.assertAlmostEqual(fit.x_opt, 50.07, places=6)
        self.assertAlmostEqual(fit.rms_db, 0.0, places=9)
        # focal zone: within 1 dB of the vertex, σ·sqrt(2/8.686) on each side
        half = 2.0 * np.sqrt(2.0 * 1.0 / (20.0 / np.log(10.0)))
        self.assertAlmostEqual(fit.zone[0], 50.07 - half, places=6)
        self.assertAlmostEqual(fit.zone[1], 50.07 + half, places=6)

    def test_fit_uses_only_points_within_3_db(self):
        xs = [45.0 + k for k in range(11)]
        amps = [np.exp(-(x - 50.2) ** 2 / (2 * 2.0 ** 2)) for x in xs]
        dbs = [20 * np.log10(a) for a in amps]
        fit = fit_focus_db(xs, amps)
        self.assertEqual(fit.fit_x, [x for x, d in zip(xs, dbs) if d >= max(dbs) - 3.0])
        self.assertEqual(fit.fit_x, [49.0, 50.0, 51.0])
        # an isolated point within 3 dB, away from the peak, is not taken
        amps[0] = 0.9 * max(amps)
        self.assertNotIn(45.0, fit_focus_db(xs[:], amps).fit_x)

    def test_fit_select_at_least_three_points(self):
        # a sharp peak: only the maximum within 3 dB → it and its neighbours
        self.assertEqual(fit_select([0.1, 0.2, 1.0, 0.2, 0.1]), [1, 2, 3])
        fit = fit_focus_db([1.0, 2.0, 3.0, 4.0, 5.0], [0.1, 0.2, 1.0, 0.2, 0.1])
        self.assertIn('only 1 point', fit.note)

    def test_vertex_uncertainty_from_the_noise(self):
        """More noise (lower contrast) → larger vertex 1σ; with 3 points (no dof) too."""
        xs = [48.0, 49.0, 50.0, 51.0, 52.0]
        amps = [np.exp(-(x - 50.0) ** 2 / (2 * 2.0 ** 2)) for x in xs]
        low = fit_focus_db(xs, amps, [0.05] * 5)
        high = fit_focus_db(xs, amps, [0.5] * 5)
        self.assertGreater(high.sigma_x, 5 * low.sigma_x)
        three = fit_focus_db(xs[1:4], amps[1:4], [0.1] * 3)
        self.assertTrue(np.isfinite(three.sigma_x) and three.sigma_x > 0)

    def test_estimate_duration(self):
        # 3 points 1 mm apart from 0: 3 mm of travel, 3 × (5 s settle + 100 × 10 ms)
        t = estimate_duration_s([1.0, 2.0, 3.0], 0.0, 5000, 100, acq_s=0.01, move_mm_s=6.7)
        self.assertAlmostEqual(t, 3.0 / 6.7 + 3 * (5.0 + 1.0))

    def test_measured_defaults(self):
        from scan_sequencer import DEFAULT_AVG_N, DEFAULT_SETTLE_MS
        self.assertEqual((DEFAULT_SETTLE_MS, DEFAULT_AVG_N), (5000, 100))

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

    def test_focal_zone_and_uncertainty(self):
        """Zone within −1 dB: 2·σ·sqrt(2/8.686) wide around x_focus; vertex 1σ reported."""
        sim = make_sim(seed=12, x_focus=50.4, snr_db=35)
        outcome, _ = run_focus(sim, 50.0, WIDE)
        self.assertTrue(outcome.move, outcome.text)
        fit = outcome.fit
        width = 2 * sim.params.sigma * np.sqrt(2.0 / (20.0 / np.log(10.0)))
        self.assertAlmostEqual(fit.zone_width, width, delta=0.1 * width)
        self.assertLess(abs(0.5 * (fit.zone[0] + fit.zone[1]) - 50.4), 0.2)
        self.assertTrue(0 < fit.sigma_x < 0.2)
        self.assertLess(abs(fit.x_opt - 50.4), max(3 * fit.sigma_x, 0.05))
        text = all_text(outcome)
        for word in ('Focal zone', 'RMS residual', 'vertex 1σ', '±'):
            self.assertIn(word, text)

    def test_tof_at_the_optimum(self):
        """ToF from the emission instant: 2F/c_w, i.e. F mm from the transducer."""
        for side in ('origin', 'max'):
            with self.subTest(pe_side=side):
                sim = make_sim(seed=13, pe_side=side, x_focus=50.0, snr_db=40)
                outcome, _ = run_focus(sim, 50.0, WIDE)
                self.assertTrue(outcome.move, outcome.text)
                tof = outcome.tof
                F, c_w = sim.params.focal_distance, sim.params.c_w
                x_opt = outcome.fit.x_opt
                t_true = sim.front_tof(x_opt, sim.params.lat0, sim.params.z0)
                self.assertAlmostEqual(tof.samples, t_true * FS, delta=1.0)
                self.assertAlmostEqual(tof.us, t_true * 1e6, delta=0.01)
                self.assertAlmostEqual(tof.mm, F, delta=0.2)
                self.assertAlmostEqual(tof.mm, c_w * tof.us * 1e-6 / 2 * 1e3, places=9)
                # slope check against 2/c_w, with the PE-side sign
                self.assertLess(abs(tof.slope_error), 0.01)
                self.assertAlmostEqual(tof.theory_us_mm, (1 if side == 'origin' else -1) * 2e3 / c_w,
                                       places=9)
                self.assertIn('2/c_w', all_text(outcome))

    def test_tof_emission_reference(self):
        sim0 = make_sim(seed=14, snr_db=40)
        sim1 = make_sim(seed=14, snr_db=40)
        o0, _ = run_focus(sim0, 50.0, WIDE)
        o1, _ = run_focus(sim1, 50.0, WIDE, emission_sample=150)
        self.assertAlmostEqual(o0.tof.samples - o1.tof.samples, 150.0, places=6)

    def test_fine_sweep_is_optional_and_not_in_the_fit(self):
        sim_a = make_sim(seed=15, x_focus=50.6)
        sim_b = make_sim(seed=15, x_focus=50.6)
        without, _ = run_focus(sim_a, 50.0, WIDE)
        with_fine, plan = run_focus(sim_b, 50.0, WIDE, fine=0.1)
        self.assertEqual(without.fit.x_opt, with_fine.fit.x_opt)     # same coarse data, same fit
        self.assertTrue(any('Fine sweep (not used in the fit)' in r for r in with_fine.report))
        self.assertFalse(any('Fine sweep' in r for r in without.report))
        # configurable range, centred on the optimum
        xs = plan.fine_positions_around(with_fine.fit.x_opt)
        self.assertAlmostEqual(xs[-1] - xs[0], 2 * plan.fine_range, delta=0.1 + 1e-9)

    def test_flat_curve_does_not_move(self):
        """A curve that barely changes: vertex undetermined → warned, no move."""
        xs = [45.0 + k for k in range(11)]
        rng = np.random.default_rng(3)
        for shape in ('flat', 'convex'):
            with self.subTest(shape=shape):
                if shape == 'flat':
                    dbs = -0.002 * (np.array(xs) - 50.0) ** 2 + rng.normal(0, 0.15, 11)
                    dbs[5] = dbs.max() + 0.05
                else:
                    dbs = 0.05 * (np.array(xs) - 50.0) ** 2
                    dbs[5] = dbs.max() + 0.01
                ms = [PeakMeasure(10 ** (d / 20) * 0.1, 2000 + 133 * k, False, False, 50.0,
                                  'tracked', index_frac=2000.0 + 133 * k)
                      for k, d in enumerate(dbs)]
                plan = FocusPlan(50.0, 5.0, 1.0, None, LIMIT, WIDE,
                                 samples_per_mm=echo_samples_per_mm('origin'))
                fine, outcome = plan.after_coarse(xs, ms)
                self.assertIsNone(fine)
                self.assertFalse(outcome.move)
                self.assertIn('too flat', outcome.text)

    def test_lost_echo_message_suggests_pe_side(self):
        """Wrong PE side: the loss of the echo is reported as such, not as a narrow window."""
        for sim_side, declared in (('origin', 'max'), ('max', 'origin')):
            with self.subTest(sim=sim_side, declared=declared):
                sim = make_sim(seed=16, pe_side=sim_side, x_focus=50.0)
                outcome, _ = run_focus(sim, 50.0, WIDE, pe_side=declared)
                self.assertIn('PE side', all_text(outcome))

    def test_lost_and_narrow_messages_differ(self):
        edge = PeakMeasure(0.1, 1010, True, False, 50.0, 'tracked')
        lost = PeakMeasure(0.01, 900, False, False, 1.0, 'tracked', outside=True,
                           echo_elsewhere=True)
        plan = FocusPlan(50.0, 5.0, 1.0, None, LIMIT, WIDE)
        good = [PeakMeasure(0.1, 2000, False, False, 50.0, 'tracked')] * 4
        _, o_edge = plan.after_coarse([48.0, 49.0, 50.0, 51.0, 52.0], good[:2] + [edge] + good[2:])
        _, o_lost = plan.after_coarse([48.0, 49.0, 50.0, 51.0, 52.0], good[:2] + [lost] + good[2:])
        self.assertIn('too narrow', o_edge.text)
        self.assertNotIn('PE side', o_edge.text)
        self.assertIn('front echo lost', o_lost.text.lower())
        self.assertIn('PE side', o_lost.text)
        self.assertNotIn('too narrow', o_lost.text)

    def test_saturation_blocks_the_move(self):
        sim = make_sim(seed=5)
        sim.SetGain2(sim.params.gain_ref_ch2 + 12.0)     # A0 0.2 → 0.8: clips at 0.5
        outcome, _ = run_focus(sim, 50.0, WIDE)
        self.assertFalse(outcome.move)
        self.assertIn('lower the gain', outcome.text.lower())


# ===========================================================================
#  Thin sample: back-face echo inside Smin–Smax and larger than the front one
# ===========================================================================
class TestThinSample(unittest.TestCase):

    def echo_amp(self, pe, t):
        """Envelope peak within ±60 samples of t."""
        return window_peak(pe, int(t) - 60, int(t) + 60).amp

    def test_back_echo_inside_window_and_larger(self):
        """The simulator case itself, at the front-face focus."""
        sim = make_sim(thin=True, snr_db=80, x_focus=50.0)
        move(sim, 50.0)
        lat, z = sim.params.lat0, sim.params.z0
        t_front, t_back = sim.front_tof(50.0, lat, z) * FS, sim.back_tof(50.0, lat, z) * FS
        for t in (t_front, t_back):
            self.assertTrue(WIDE[0] + 200 < t < WIDE[1] - 200)
        _, pe = acquire(sim, 1)
        a_front, a_back = self.echo_amp(pe, t_front), self.echo_amp(pe, t_back)
        self.assertAlmostEqual(a_front, sim.params.A0, delta=0.01)
        self.assertGreater(a_back, 1.5 * a_front)
        # ...so the maximum of the window is the back echo
        self.assertAlmostEqual(window_peak(pe, *WIDE).index, t_back, delta=3)
        # and the back face peaks at its own beam position, > 1 mm away
        self.assertGreater(abs(sim.expected_back_focus() - 50.0), 1.0)

    def test_global_maximum_misses_the_focus(self):
        """Control: without tracking, the curve follows the back echo."""
        sim = make_sim(seed=2, thin=True, x_focus=50.0)
        outcome, _ = run_focus(sim, 50.0, WIDE, tracking=False)
        self.assertTrue(outcome.move, outcome.text)
        self.assertLess(abs(outcome.fit.x_opt - sim.expected_back_focus()), 0.3)
        self.assertGreater(abs(outcome.fit.x_opt - 50.0), 1.0)

    def test_tracked_focus_is_the_front_face_focus(self):
        fine = 0.2
        cases = [(50.0, 30, 'origin'), (48.4, 30, 'origin'), (52.7, 40, 'origin'),
                 (50.0, 30, 'max'), (51.3, 35, 'max')]
        for seed, (x_focus, snr, side) in enumerate(cases):
            with self.subTest(x_focus=x_focus, snr=snr, pe_side=side):
                sim = make_sim(seed=20 + seed, thin=True, pe_side=side,
                               x_focus=x_focus, snr_db=snr)
                outcome, _ = run_focus(sim, 50.0, WIDE, fine=fine)
                self.assertTrue(outcome.move, outcome.text)
                self.assertLess(abs(outcome.fit.x_opt - x_focus), fine, outcome.text)

    def test_tracker_follows_front_echo(self):
        """Every point of the sweep measured on the front face, not the back one."""
        for side in ('origin', 'max'):
            with self.subTest(pe_side=side):
                sim = make_sim(seed=4, thin=True, pe_side=side, x_focus=50.0)
                tracker = FrontEchoTracker(WIDE, echo_samples_per_mm(side))
                xs = [45.0 + k for k in range(11)]
                lat, z = sim.params.lat0, sim.params.z0
                for x, m in zip(xs, measure_tracked(sim, xs, tracker, 10)):
                    t_front = tof_samples(sim, x)
                    # Far out of focus the front echo is barely above the noise and its
                    # peak wanders inside the band; it must still be the front, not the back.
                    delta = 5 if m.confident else tracker.band
                    self.assertAlmostEqual(m.index, t_front, delta=delta, msg=f'x={x}')
                    self.assertLess(abs(m.index - t_front),
                                    abs(m.index - sim.back_tof(x, lat, z) * FS), msg=f'x={x}')

    def test_relock_when_front_too_weak_on_the_first_point(self):
        """
        5 mm out of focus the front echo is below the threshold and the back one
        is not: the first point locks on the back echo. When the front appears
        before the band the tracker re-locks and re-measures the earlier points.
        """
        sim = make_sim(seed=1, thin=True, x_focus=50.0)
        tracker = FrontEchoTracker(WIDE, echo_samples_per_mm('origin'))
        tracker.new_sweep()
        move(sim, 45.0)
        _, pe = acquire(sim, 10)
        first = tracker.measure(pe, 45.0)
        self.assertEqual(first.mode, 'first')
        lat, z = sim.params.lat0, sim.params.z0
        self.assertAlmostEqual(first.index, sim.back_tof(45.0, lat, z) * FS, delta=5)
        xs = [46.0 + k for k in range(5)]
        for x in xs:
            move(sim, x)
            _, pe = acquire(sim, 10)
            tracker.measure(pe, x)
        self.assertTrue(tracker.relocks)
        for x, m in zip([45.0] + xs, tracker.measures):
            self.assertAlmostEqual(m.index, tof_samples(sim, x), delta=5, msg=f'x={x}')

    def test_tracker_on_lateral_moves_with_tilt(self):
        """Flatness (phase 4) use: beam position fixed, the band absorbs the tilt shift."""
        sim = make_sim(seed=6, thin=True, theta_lat=3.0, snr_db=40)
        tracker = FrontEchoTracker(WIDE, echo_samples_per_mm('origin'))
        tracker.new_sweep()
        for lat in np.arange(40.0, 60.1, 1.0):
            sim.set_scanner_state({'X': lat, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}, 'Y', 'origin')
            _, pe = acquire(sim, 10)
            m = tracker.measure(pe, 50.0)
            self.assertAlmostEqual(m.index, sim.front_tof(50.0, lat, 25.0) * FS, delta=5,
                                   msg=f'lat={lat}')


# ===========================================================================
#  Echo polarity: inverted front-face echo (regression, hardware 29/09)
# ===========================================================================
class TestEchoPolarity(unittest.TestCase):
    """
    Every amplitude and every threshold decision must use the Hilbert envelope
    (always positive), never the signed signal: an inverted echo has the same
    envelope, but its signed maximum is only a side lobe (lower, and half a
    period off). SimParams.inverted_front() uses a cosine carrier so that the
    difference is real (with the default sine, an odd pulse, it is not).
    """

    def pe_at_focus(self, **params):
        sim = make_sim(seed=9, snr_db=60, x_focus=50.0, **params)
        move(sim, 50.0)
        _, pe = acquire(sim, 1)
        return sim, pe

    def test_sim_inverts_each_echo_separately(self):
        sim = make_sim(thin=True, carrier_phase=90.0)
        move(sim, 50.0)
        lat, z = sim.params.lat0, sim.params.z0
        spans = {'front': sim.front_tof(50.0, lat, z) * FS,
                 'back': sim.back_tof(50.0, lat, z) * FS,
                 'reverb': 2.0 * sim.front_tof(50.0, lat, z) * FS}
        _, ref = sim.clean_signals()
        for echo in spans:
            with self.subTest(echo=echo):
                setattr(sim.params, 'invert_' + echo, True)
                _, pe = sim.clean_signals()
                setattr(sim.params, 'invert_' + echo, False)
                for other, t in spans.items():
                    sl = slice(int(t) - 60, int(t) + 60)
                    expected = -ref[sl] if other == echo else ref[sl]
                    np.testing.assert_allclose(pe[sl], expected, atol=1e-12, err_msg=other)

    def test_scenario_signed_maximum_differs(self):
        """The scenario is only a regression case if the signed maximum is wrong in it."""
        sim, pe = self.pe_at_focus(inverted=True)
        t = tof_samples(sim, 50.0)
        seg = pe[int(t) - 60:int(t) + 60]
        self.assertLess(np.max(seg), 0.8 * sim.params.A0)
        self.assertGreater(abs(int(np.argmax(seg)) + int(t) - 60 - t), 5)

    def test_inverted_front_echo_measures_like_the_upright_one(self):
        """Regression: same amplitude and same position whatever the polarity."""
        for thin in (False, True):
            with self.subTest(thin=thin):
                sim_up, pe_up = self.pe_at_focus(thin=thin, carrier_phase=90.0)
                sim_inv, pe_inv = self.pe_at_focus(thin=thin, inverted=True)
                self.assertTrue(sim_inv.params.invert_front)
                t = tof_samples(sim_inv, 50.0)
                trackers = []
                for pe in (pe_up, pe_inv):
                    tr = FrontEchoTracker(WIDE, echo_samples_per_mm('origin'))
                    tr.new_sweep()
                    trackers.append(tr.measure(pe, 50.0))     # first point: threshold rule
                up, inv = trackers
                self.assertEqual(inv.mode, 'first')
                self.assertAlmostEqual(inv.amp, sim_inv.params.A0, delta=0.02 * sim_inv.params.A0)
                self.assertAlmostEqual(inv.amp, up.amp, delta=0.02 * up.amp)
                self.assertAlmostEqual(inv.index, t, delta=3)
                self.assertAlmostEqual(inv.index, up.index, delta=1)
                if not thin:          # window maximum: the front is the only echo in WIDE
                    w_up, w_inv = window_peak(pe_up, *WIDE), window_peak(pe_inv, *WIDE)
                    self.assertAlmostEqual(w_inv.amp, w_up.amp, delta=0.02 * w_up.amp)
                    self.assertAlmostEqual(w_inv.index, t, delta=3)

    def test_focus_with_inverted_front_echo(self):
        fine = 0.2
        for seed, (thin, x_focus) in enumerate([(False, 50.0), (False, 52.3),
                                                (True, 50.0), (True, 48.7)]):
            with self.subTest(thin=thin, x_focus=x_focus):
                sim = make_sim(seed=30 + seed, thin=thin, inverted=True, x_focus=x_focus)
                outcome, _ = run_focus(sim, 50.0, WIDE, fine=fine)
                self.assertTrue(outcome.move, outcome.text)
                self.assertLess(abs(outcome.fit.x_opt - x_focus), fine, outcome.text)


# ===========================================================================
#  Qt integration: FocusTool on the real ScanSequencer (points 5, 8)
# ===========================================================================
from PyQt5.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import pyqtgraph as pg  # noqa: E402
from scan_sequencer import ScanSequencer  # noqa: E402
from focus_tool import FocusTool  # noqa: E402
from ECOS_US_ToolBox import Envelope  # noqa: E402


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
        self.dump_dir = tempfile.mkdtemp(prefix='focus_debug_test_')
        self.addCleanup(shutil.rmtree, self.dump_dir, ignore_errors=True)
        self.tool = FocusTool(self.seq, self.panel, window_fn, self.plot, dump_dir=self.dump_dir)
        self.results = []
        self.tool.done.connect(self.results.append)
        self.statuses = []
        self.tool.status.connect(self.statuses.append)
        self.echoes = []
        self.tool.echo_used.connect(self.echoes.append)

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

    def test_cw_from_host_and_report(self):
        """c_w comes from the host (PT100 in ecos_gui) with its source; report in the status."""
        tool = FocusTool(self.seq, self.panel, lambda: WIDE, pg.PlotWidget(),
                         cw_fn=lambda: (self.sim.params.c_w, 'PT100 T1 = 25.00 °C'),
                         dump_dir=self.dump_dir)
        tool.status.connect(self.statuses.append)
        done = []
        tool.done.connect(done.append)
        self.assertIsNone(tool.run(5.0, 1.0, avg_n=10, settle_ms=0, debug_dump=False))
        self.assertIn('PT100 T1 = 25.00 °C', self.statuses[-1])        # shown at the start
        loop = QEventLoop()
        tool.done.connect(loop.quit)
        QTimer.singleShot(20000, loop.quit)
        loop.exec_()
        self.assertEqual(done, [True], self.statuses[-1])
        self.assertEqual(tool._plan.c_w, self.sim.params.c_w)
        final = self.statuses[-1]
        for word in ('Focus at', 'Focal zone', 'ToF at the optimum', 'µs', 'from the transducer',
                     '2/c_w', 'Moved there'):
            self.assertIn(word, final)
        self.assertLess(abs(tool.last_outcome.tof.mm - self.sim.params.focal_distance), 0.2)

    def test_time_estimate_before_starting(self):
        tool = FocusTool(self.seq, self.panel, lambda: WIDE, pg.PlotWidget(),
                         acq_time_fn=lambda: 0.01)
        seconds, text = tool.estimate(5.0, 1.0, None, avg_n=100, settle_ms=5000)
        # 11 coarse points + the final move (to the centre), 20 mm of travel
        self.assertAlmostEqual(seconds, 12 * (5.0 + 100 * 0.01) + 20.0 / 6.7)
        self.assertIn('Estimated time', text)
        self.assertIn('timed', text)
        more, _ = tool.estimate(5.0, 1.0, 0.2, fine_range=1.0, avg_n=100, settle_ms=5000)
        self.assertGreater(more, seconds + 10 * 6.0)                    # + 11 fine points

    def test_group_defaults_and_estimate_label(self):
        from focus_tool import FocusGroup
        group = FocusGroup(self.tool, self.seq, lambda: WIDE)
        self.assertEqual(group._spin_settle.value(), 5000)
        self.assertEqual(group._spin_avg.value(), 100)
        self.assertFalse(group._chk_fine.isChecked())
        self.assertFalse(group._spin_fine.isEnabled())
        self.assertIn('Estimated time', group._lbl_estimate.text())
        before = group._lbl_estimate.text()
        group._spin_avg.setValue(10)
        self.assertNotEqual(group._lbl_estimate.text(), before)

    def test_thin_sample_run_follows_front_echo(self):
        """Thin sample through the whole tool: focus on the front face, echo reported per point."""
        self.sim.params.thickness = 1.5
        self.sim.params.back_ratio = 2.5
        self.assertIsNone(self.tool.run(5.0, 1.0, 0.2, avg_n=10, settle_ms=0))
        self.wait_done()
        self.assertEqual(self.results, [True], self.tool.last_outcome and self.tool.last_outcome.text)
        self.assertLess(abs(self.tool.last_outcome.fit.x_opt - 51.3), 0.2)
        # One echo_used per measured point: coarse, fine and the final move
        self.assertEqual(len(self.echoes), len(self.worker.moves))
        self.assertTrue(all(m.band is not None for m in self.echoes if m.mode != 'none'))
        # The last point, at the optimum, is measured on the front face
        last = self.echoes[-1]
        self.assertEqual(last.mode, 'tracked')
        self.assertAlmostEqual(last.index, tof_samples(self.sim, self.panel.coords['Y']), delta=5)

    # -- debug dump --------------------------------------------------------------
    def load_dump(self):
        files = os.listdir(self.dump_dir)
        self.assertEqual(len(files), 1, files)                   # one file per run
        self.assertEqual(os.path.join(self.dump_dir, files[0]), self.tool.last_dump_path)
        return np.load(self.tool.last_dump_path)                 # no pickle needed

    def check_dump_consistent(self, d):
        """Every stored field agrees with the arrays it comes from."""
        n = len(d['x_beam'])
        smin, smax = int(d['smin'][0]), int(d['smax'][0])
        self.assertEqual(d['record'].shape, (n, self.sim.RecLen))
        self.assertEqual(d['window_signal'].shape, (n, smax - smin))
        self.assertEqual(d['envelope'].shape, (n, smax - smin))
        for k in range(n):
            # the exact array of the measure is the window of the stored record
            np.testing.assert_array_equal(d['window_signal'][k], d['record'][k][smin:smax])
            np.testing.assert_allclose(d['envelope'][k], Envelope(d['window_signal'][k]))
            self.assertEqual(d['peak_index_window'][k], d['peak_index'][k] - smin)
            if d['flags'][k].find('outside') < 0:
                self.assertEqual(d['amp'][k], d['envelope'][k][d['peak_index_window'][k]])
            self.assertAlmostEqual(d['amp_db'][k], 20 * np.log10(d['amp'][k]), places=9)
            if d['mode'][k] == 'tracked':
                self.assertTrue(d['band_lo'][k] <= d['peak_index'][k] < d['band_hi'][k])
            if d['mode'][k] in ('first', 'relock'):
                self.assertEqual(d['band_center'][k], d['peak_index'][k])
        self.assertTrue(set(d['mode']) <= {'first', 'tracked', 'relock', 'none'})
        self.assertTrue(np.all(d['smin'] == smin) and np.all(d['smax'] == smax))

    def test_debug_dump_full_run(self):
        self.assertIsNone(self.tool.run(5.0, 1.0, 0.2, avg_n=2, settle_ms=0))
        self.wait_done()
        self.assertEqual(self.results, [True])
        d = self.load_dump()
        self.assertEqual(len(d['x_beam']), len(self.worker.moves))   # every measured point
        self.assertEqual(list(d['x_beam']), self.worker.moves)
        phases = list(d['phase'])
        self.assertEqual(phases[:11], ['coarse'] * 11)
        self.assertEqual(phases[-1], 'move')
        self.assertIn('fine', phases)
        self.assertEqual(tuple(d['smin'][:1]) + tuple(d['smax'][:1]), WIDE)
        self.check_dump_consistent(d)
        # the prediction of a tracked point: previous clear point + 2·Δx/c_w
        k = phases.index('coarse') + 5
        self.assertEqual(d['mode'][k], 'tracked')
        spm = echo_samples_per_mm('origin')
        self.assertAlmostEqual(d['band_center'][k],
                               d['peak_index'][k - 1] + spm * (d['x_beam'][k] - d['x_beam'][k - 1]),
                               delta=1e-6)
        meta = json.loads(str(d['meta_json']))
        self.assertEqual(meta['beam_axis'], 'Y')
        self.assertTrue(meta['moved'])
        self.assertAlmostEqual(meta['x_opt'], self.panel.coords['Y'])
        self.assertIn('Debug dump:', self.statuses[-1])

    def test_debug_dump_records_relock(self):
        """Thin sample, first point far out of focus: re-lock, earlier points revised."""
        self.sim.params.thickness = 1.5
        self.sim.params.back_ratio = 2.5
        self.assertIsNone(self.tool.run(5.0, 1.0, 0.2, avg_n=10, settle_ms=0))
        self.wait_done()
        d = self.load_dump()
        self.check_dump_consistent(d)
        coarse = np.flatnonzero(d['phase'] == 'coarse')
        self.assertIn('relock', list(d['mode'][coarse]))
        self.assertEqual(d['mode_at_measure'][coarse[0]], 'first')
        self.assertTrue(d['revised'][coarse[0]])                   # re-measured on the front
        self.assertNotEqual(d['mode'][coarse[0]], 'first')

    def test_debug_dump_after_stop(self):
        count = {'n': 0}

        def on_point(*_):
            count['n'] += 1
            if count['n'] == 3:
                self.seq.abort()
        self.seq.point_done.connect(on_point)
        self.assertIsNone(self.tool.run(5.0, 1.0, 0.2, avg_n=2, settle_ms=0))
        self.wait_done()
        d = self.load_dump()
        self.assertEqual(list(d['x_beam']), [45.0, 46.0, 47.0])
        self.assertIn('stopped', json.loads(str(d['meta_json']))['result'])

    def test_debug_dump_disabled(self):
        self.assertIsNone(self.tool.run(5.0, 1.0, 0.2, avg_n=2, settle_ms=0, debug_dump=False))
        self.wait_done()
        self.assertEqual(os.listdir(self.dump_dir), [])
        self.assertIsNone(self.tool.last_dump_path)

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
