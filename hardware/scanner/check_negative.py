# -*- coding: utf-8 -*-
"""
check_negative.py — Lab check: what happens below 0 with unlimited moves (SN).

Location: hardware/scanner/check_negative.py
Run from hardware/scanner:  python check_negative.py [COMx]

Uses RAW pyserial (no Scanner class) to see the exact reply bytes.
All moves are 0.1 mm (10 steps) on X. Keep the area clear anyway.

Questions answered:
  A. Does 'SNX-10' (negative value) move X below 0?
  B. What does SCX return below 0? (sign? length? 10 or 11 bytes?)
  C. If A fails: does flipping direction ('SWX-') + 'SNX10' go below 0?
  D. Does SD (limited relative) accept a negative value inside the range?
"""
import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else 'COM3'
BAUD = 19200


def q(ser, cmd, wait_max=5.0):
    """Send cmd, return ALL raw bytes received (up to 32), waiting for a reply."""
    ser.reset_input_buffer()
    ser.write((cmd + '\r').encode())
    time.sleep(0.1)
    r = ser.read(32)
    t0 = time.time()
    while r == b'' and time.time() - t0 < wait_max:
        time.sleep(0.2)
        r = ser.read(32)
    time.sleep(0.1)
    r += ser.read(32)          # catch any trailing bytes
    print(f'  {cmd:<8} -> {r!r}  ({len(r)} bytes)')
    return r


def ask(msg):
    return input(f'\n{msg} [y/N] ').strip().lower() == 'y'


ser = serial.Serial(PORT, BAUD, timeout=0.1)
try:
    print(f'Port {PORT}. Current state:')
    q(ser, 'SCX')
    q(ser, 'SEX+')             # make sure X is enabled
    q(ser, 'SWX+')             # known direction
    if not ask('Set current X as 0 (SAX0, no motion)?'):
        sys.exit()
    q(ser, 'SAX0')
    q(ser, 'SCX')

    if ask('A) Send SNX-10 (0.1 mm towards negative)? Watch the axis and the display.'):
        q(ser, 'SNX-10')
        r = q(ser, 'SCX')
        print('  -> Did X move? What does the display show?')
        if ask('   Move back with SNX10?'):
            q(ser, 'SNX10')
            q(ser, 'SCX')

    if ask('C) Try direction flip: SWX-, SNX10, read, then SWX+, SNX10 back?'):
        q(ser, 'SWX-')
        q(ser, 'SNX10')
        q(ser, 'SCX')
        print('  -> Did X move? Which way? Display value?')
        q(ser, 'SWX+')
        if ask('   Move back with SNX10 (direction restored to +)?'):
            q(ser, 'SNX10')
            q(ser, 'SCX')

    if ask('D) SD negative inside range: SMX100 (to 1 mm), then SDX-10 (expect 0.9 mm)?'):
        q(ser, 'SMX100')
        q(ser, 'SDX-10')
        q(ser, 'SCX')
        q(ser, 'SMX0')
        q(ser, 'SCX')
finally:
    ser.write(b'SWX+\r')       # leave direction as the Scanner class expects
    time.sleep(0.2)
    ser.close()
    print('\nDone. Port closed, X direction left as +.')
