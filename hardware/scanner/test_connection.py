# -*- coding: utf-8 -*-
"""
test_connection.py — Minimal connection test for the XYZR scanner.

Location: hardware/scanner/test_connection.py (next to Scanner.py)

Stage 1 (read-only): raw pyserial, no motion. Sends coordinate (SC*) and
limit (SG*) queries and prints the raw responses, to verify port, baudrate
and the reply format.

Stage 2 (optional, motion): uses the Scanner class. Moves one axis by a
small relative distance and returns to the start. Asks for confirmation.
NOTE: Scanner.__init__ enables ALL motors and sends directions, speed types
and speeds (100) to the controller as soon as it is instantiated.

Run: python test_connection.py
"""
import os
import sys
import time

import serial

PORT = 'COM3'        # Arduino PT100 is on COM3; check in Device Manager
BAUDRATE = 19200
TIMEOUT = 0.1        # s, same as Scanner class
REPLY_WAIT = 3.0     # s, max wait for SG* replies

TEST_AXIS = 'X'
TEST_DIST = 1.0      # mm (relative). Keep small.


def raw_query(ser, cmd, wait_max=0.0):
    """Send cmd + CR, return raw bytes (waits up to wait_max for a reply)."""
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write((cmd + '\r').encode('utf-8'))
    time.sleep(0.1)
    resp = ser.read(32)
    t0 = time.time()
    while resp == b'' and time.time() - t0 < wait_max:
        time.sleep(0.2)
        resp = ser.read(32)
    return resp


def stage1_readonly():
    print(f'=== Stage 1: read-only queries on {PORT} @ {BAUDRATE} ===')
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
    except serial.SerialException as e:
        print(f'Cannot open {PORT}: {e}')
        return False
    ok = True
    try:
        for ax in 'XYZR':
            r = raw_query(ser, f'SC{ax}')
            print(f'SC{ax} -> {r!r}')
            ok &= r != b''
        for ax in 'XYZR':
            r = raw_query(ser, f'SG{ax}', wait_max=REPLY_WAIT)
            print(f'SG{ax} -> {r!r}')
            ok &= r != b''
    finally:
        ser.close()
    print('Stage 1:', 'OK (all queries answered)' if ok else 'FAILED (empty replies)')
    return ok


def stage2_motion():
    ans = input(f'\nStage 2 will ENABLE all motors and move {TEST_AXIS} by '
                f'+{TEST_DIST} mm and back. Area clear? [y/N] ')
    if ans.strip().lower() != 'y':
        print('Stage 2 skipped.')
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from Scanner import Scanner

    sc = Scanner(port=PORT, baudrate=BAUDRATE, timeout=TIMEOUT)
    try:
        print('Coords (X, Y, Z, R):', sc.getCoords())
        print('Limits (X, Y, Z, R):', sc.getLimits())
        start = sc.getAxis(TEST_AXIS)
        target = round(start + TEST_DIST, 3)
        print(f'Moving {TEST_AXIS}: {start} -> {target} mm')
        t0 = time.time()
        sc.moveAxis(TEST_AXIS, target)
        print(f'  done in {time.time() - t0:.2f} s, now {sc.getAxis(TEST_AXIS)} mm')
        sc.moveAxis(TEST_AXIS, start)
        print(f'Back at {sc.getAxis(TEST_AXIS)} mm')
    except KeyboardInterrupt:
        print('Interrupted (stop command sent by Scanner.write).')
    finally:
        sc.close()


if __name__ == '__main__':
    if stage1_readonly():
        stage2_motion()
