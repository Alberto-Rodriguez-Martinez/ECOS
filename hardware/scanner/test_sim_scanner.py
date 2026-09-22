# -*- coding: utf-8 -*-
"""
test_sim_scanner.py — Tests for FakeSerial (hardware/scanner/sim_scanner.py),
exercised through the real Scanner class (hardware/scanner/Scanner.py), so
that the driver's own command formatting/parsing is covered too.

Run: python -m unittest hardware/scanner/test_sim_scanner.py
(or, from hardware/scanner: python -m unittest test_sim_scanner)
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Scanner import Scanner
from sim_scanner import FakeSerial, DEFAULT_LIMIT_STEPS, BASE_STEPS_PER_SEC_AT_SPEED_100


def make_scanner(**fake_serial_kwargs):
    """Scanner wired to a fresh FakeSerial, ready to use in tests."""
    fs = FakeSerial(**fake_serial_kwargs)
    sc = Scanner(port='SIM', ser=fs)
    return sc, fs


class TestCoordsAndLimits(unittest.TestCase):

    def test_read_coords_and_limits(self):
        sc, _fs = make_scanner()
        self.assertEqual(sc.getCoords(), (0.0, 0.0, 0.0, 0.0))
        # DEFAULT_LIMIT_STEPS (10000) converted through each axis' uStep:
        # X/Y -> 100 mm, Z -> 50 mm, R -> 18000 deg.
        self.assertEqual(sc.getLimits(), (100.0, 100.0, 50.0, 18000.0))


class TestRejection(unittest.TestCase):

    def test_reject_below_zero(self):
        sc, _fs = make_scanner()
        sc.moveX(0)
        sc.moveX(-0.5)
        self.assertEqual(sc.X, 0.0)

    def test_reject_above_limit(self):
        sc, _fs = make_scanner()
        limit = sc.XLimit  # 100 mm by default
        sc.moveX(0)
        sc.moveX(limit + 0.5)
        self.assertEqual(sc.X, 0.0)


class TestMoveDuration(unittest.TestCase):

    def test_20mm_move_takes_about_3s(self):
        # Real duration: 20 mm / 0.01 mm-per-step = 2000 steps, at
        # BASE_STEPS_PER_SEC_AT_SPEED_100 (670) steps/s -> ~2.985 s.
        # time_scale=10 speeds this test up to ~0.3 s of wall-clock time.
        scale = 10.0
        expected_real_s = 2000 / BASE_STEPS_PER_SEC_AT_SPEED_100
        expected_scaled_s = expected_real_s / scale

        sc, _fs = make_scanner(time_scale=scale)
        sc.moveX(0)
        t0 = time.time()
        sc.moveX(20)
        elapsed = time.time() - t0

        self.assertEqual(sc.X, 20.0)
        # Loose bound: Scanner.write polls every 0.2 s after an initial
        # 0.1 s sleep, so elapsed is quantized; just check it is in the
        # right ballpark and clearly not near-instant nor near move_timeout.
        self.assertGreater(elapsed, expected_scaled_s * 0.5)
        self.assertLess(elapsed, expected_scaled_s * 2.0 + 0.3)


class TestStop(unittest.TestCase):

    def test_stop_from_another_thread_mid_move(self):
        # Real duration for 20 mm ~2.985 s; time_scale=5 -> ~0.6 s.
        scale = 5.0
        sc, fs = make_scanner(time_scale=scale)
        sc.moveX(0)

        def stop_soon():
            time.sleep(0.25)
            # Mirrors the panel's STOP button: writes 'SSF\r' directly to the
            # port, bypassing Scanner.write entirely (see scanner_panel.py).
            fs.write(b'SSF\r')

        stopper = threading.Thread(target=stop_soon)
        t0 = time.time()
        stopper.start()
        sc.moveX(20)  # blocks inside Scanner.write's polling loop
        elapsed = time.time() - t0
        stopper.join()

        # Returned early: well under the undisturbed ~0.6 s move and light
        # years under move_timeout (120 s default).
        self.assertLess(elapsed, 0.55)
        # Position is wherever the move got to, not 0 and not the target.
        self.assertGreater(sc.X, 0.0)
        self.assertLess(sc.X, 20.0)


class TestPowerCycle(unittest.TestCase):

    def test_power_cycle_resets_limits_keeps_position(self):
        sc, fs = make_scanner()
        sc.XLimit = 50
        sc.moveX(10)
        self.assertEqual(sc.XLimit, 50.0)
        self.assertEqual(sc.X, 10.0)

        fs.power_cycle()

        self.assertEqual(sc.getLimits(), (100.0, 100.0, 50.0, 18000.0))
        self.assertEqual(sc.X, 10.0)  # position is conserved


class TestValue2uSteps(unittest.TestCase):

    def test_value2uSteps_rounding(self):
        sc, _fs = make_scanner()
        self.assertEqual(sc.value2uSteps('X', 0.29), 29)


if __name__ == '__main__':
    unittest.main()
