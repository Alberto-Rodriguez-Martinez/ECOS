# -*- coding: utf-8 -*-
"""
test_temperature_logger.py — continuous PT100 log (temperature_logger.py) on a
simulated serial port: lines every period, malformed lines in between, a port that
fails half-way, a silent port (stale samples) and a read stuck in the driver.

FakeSerial / FakeArduino are also used by test_scan_tool (module import).

Run from the repo root with the 32-bit interpreter of the machine (CLAUDE.md):
    python -m unittest discover -s acquisition
"""
import os
import sys
import threading
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import numpy as np  # noqa: E402

from temperature_logger import (  # noqa: E402
    PROBE_WIRES, TemperatureLogger, parse_line, probe_fields,
)

GOOD = b'24.5\t24.7\r\n'


class FakeSerial:
    """
    serial.Serial stand-in (timeout = period): each readline() waits one period and
    hands out the next scripted item (bytes, or an exception instance to raise), then
    `steady` forever (b'' when steady is None: a silent port, every read times out).
    close() makes a pending or later readline() raise, as a closed port does.
    stuck=True: readline() blocks until close() (a read stuck in the driver).
    """

    def __init__(self, script=(), steady=GOOD, period=0.01, baudrate=115200, stuck=False):
        self.script = list(script)
        self.steady = steady
        self.period = period
        self.baudrate = baudrate
        self.stuck = stuck
        self.reads = 0
        self._closed = threading.Event()

    @property
    def is_open(self):
        return not self._closed.is_set()

    def readline(self):
        if self._closed.wait(None if self.stuck else self.period):
            raise OSError('port closed')
        self.reads += 1
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        return self.steady or b''

    def close(self):
        self._closed.set()


class FakeArduino:
    """hardware/temperature_Alberto_temporal.Arduino as the logger uses it: `ser` and
    close(). getTemperatures() must not be called while the logger owns the port."""
    instances = 0

    def __init__(self, ser=None):
        FakeArduino.instances += 1
        self.ser = ser if ser is not None else FakeSerial()
        self.closed = False

    def getTemperatures(self):
        raise AssertionError('the port is read only by the TemperatureLogger')

    def close(self):
        self.closed = True
        self.ser.close()


def wait_until(cond, timeout=5.0):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < timeout:
        time.sleep(0.005)
    return cond()


class TestParseLine(unittest.TestCase):

    def test_valid_and_malformed(self):
        self.assertEqual(parse_line(b'24.5\t24.7\r\n'), (24.5, 24.7))
        self.assertEqual(parse_line(b'24.5000 24.7000\n'), (24.5, 24.7))   # 9600-baud sketch
        for bad in (b'\r\n', b'24.5\r\n', b'24.5\t24.7\t1\r\n', b'abc def\r\n',
                    b'nan\t24.7\r\n', b'24.5\tinf\r\n', b'\xff\xfe 1\r\n', b''):
            with self.subTest(line=bad):
                self.assertIsNone(parse_line(bad))


class TestTemperatureLogger(unittest.TestCase):

    def make(self, **kw):
        stale = kw.pop('stale_after_s', 1.0)
        self.port = FakeSerial(**kw)
        self.arduino = FakeArduino(self.port)
        log = TemperatureLogger(self.arduino, stale_after_s=stale)
        self.addCleanup(log.stop, 0.5)
        return log

    def test_every_line_logged_malformed_dropped_and_counted(self):
        script = [GOOD, b'\r\n', b'24.6\t24.8\r\n', b'24.', b'7\t24.9\r\n',   # split line
                  b'abc def\r\n', b'25.0\r\n', b'nan\t24.0\r\n', b'25.1\t25.2\r\n']
        log = self.make(script=script, steady=None)
        log.start()
        self.assertTrue(wait_until(lambda: not self.port.script))
        time.sleep(0.05)
        self.assertTrue(log.stop())
        s = log.series()
        np.testing.assert_array_equal(s['T1'], [24.5, 24.6, 24.7, 25.1])
        np.testing.assert_array_equal(s['T2'], [24.7, 24.8, 24.9, 25.2])
        self.assertEqual(s['discarded'], 4)                 # empty, non-numeric, truncated, nan
        self.assertEqual(len(log.discarded_examples), 4)
        self.assertTrue(np.all(np.diff(s['mono']) >= 0))    # never backwards
        self.assertTrue(np.all(np.diff(s['wall']) >= 0))
        self.assertEqual(s['wall'].dtype, np.float64)
        # stamped when received, with both clocks of this PC
        self.assertLess(abs(s['wall'][-1] - time.time()), 5.0)
        self.assertLess(abs(s['mono'][-1] - time.monotonic()), 5.0)
        m = log.meta()
        self.assertEqual((m['n_lines'], m['n_discarded'], m['complete']), (4, 4, True))

    def test_garbage_without_newline_is_dropped(self):
        log = self.make(script=[b'x' * 200, b'y' * 100, GOOD], steady=None)
        log.start()
        self.assertTrue(wait_until(lambda: len(log.series()['T1']) == 1))
        self.assertEqual(log.series()['discarded'], 1)

    def test_latest_and_stale(self):
        log = self.make(script=[GOOD, GOOD], steady=None, stale_after_s=0.1)
        self.assertTrue(log.latest()['stale'])               # nothing yet
        self.assertTrue(np.isnan(log.latest()['T1']))
        log.start()
        self.assertTrue(log.wait_first(2.0))
        s = log.latest()
        self.assertEqual((s['T1'], s['T2']), (24.5, 24.7))
        self.assertFalse(s['stale'])
        self.assertGreaterEqual(s['age_s'], 0.0)
        # the port goes silent: the same sample ages and turns stale, never "current"
        self.assertTrue(wait_until(lambda: log.latest()['stale'], 2.0))
        self.assertGreater(log.latest()['age_s'], 0.1)

    def test_port_failure_half_way_ends_the_thread_and_keeps_the_series(self):
        log = self.make(script=[GOOD, GOOD, OSError('device disconnected')])
        log.start()
        self.assertTrue(wait_until(lambda: not log.running))
        self.assertIn('device disconnected', log.failure['error'])
        self.assertEqual(len(log.series()['T1']), 2)
        self.assertTrue(log.stop())
        m = log.meta()
        self.assertFalse(m['complete'])
        self.assertIn('device disconnected', m['failure']['error'])

    def test_stop_is_clean_and_closes_the_port(self):
        log = self.make()
        log.start()
        self.assertTrue(log.wait_first(2.0))
        self.assertTrue(log._thread.daemon)                  # never keeps the program alive
        t0 = time.monotonic()
        self.assertTrue(log.stop())
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertFalse(log.running)
        self.assertTrue(self.arduino.closed)
        self.assertIsNone(log.failure)                       # closing on stop is not a failure
        n = len(log.series()['T1'])
        time.sleep(0.05)
        self.assertEqual(len(log.series()['T1']), n)          # nothing logged after stop

    def test_stop_unblocks_a_read_stuck_in_the_driver(self):
        log = self.make(stuck=True)
        log.start()
        time.sleep(0.05)
        t0 = time.monotonic()
        self.assertTrue(log.stop(timeout=0.2))               # the close unblocks the read
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertIsNone(log.failure)

    def test_not_a_serial_arduino(self):
        class NoPort:
            def getTemperatures(self):
                return 24.0, 24.0
        with self.assertRaises(AttributeError):
            TemperatureLogger(NoPort())

    def test_baudrate_of_the_port(self):
        self.assertEqual(self.make(baudrate=115200).baudrate, 115200)


class TestProbeFields(unittest.TestCase):

    def test_empty_but_present_never_guessed(self):
        p = probe_fields()
        for name in ('T1', 'T2'):
            self.assertEqual((p[name]['id'], p[name]['position'], p[name]['class']), ('', '', ''))
            self.assertEqual(p[name]['wires'], PROBE_WIRES)
            self.assertEqual(PROBE_WIRES, 4)
            self.assertEqual((p[name]['element'], p[name]['converter']), ('PT100', 'MAX31865'))

    def test_given_values_kept(self):
        p = probe_fields({'T1': {'id': ' S1 ', 'position': 'bottom, left', 'class': 'A'}})
        self.assertEqual((p['T1']['id'], p['T1']['position'], p['T1']['class']),
                         ('S1', 'bottom, left', 'A'))
        self.assertEqual(p['T2']['id'], '')


if __name__ == '__main__':
    unittest.main()
