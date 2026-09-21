# -*- coding: utf-8 -*-
"""
check_behaviour.py — Hardware behaviour checks for the XYZR scanner.

Location: hardware/scanner/check_behaviour.py
Run from hardware/scanner:  python check_behaviour.py

Each check asks for confirmation and can be skipped. Keep the tank area clear.
  1. Out-of-range moves are rejected by the firmware (< 0 and > limit).
  2. Z direction: small +Z move, you observe whether it goes up or down.
  3. Stop with Ctrl+C during a 20 mm X move.
All motions are <= 20 mm.
  4. Limit persistence: sets XLimit, you power-cycle the controller, re-read.
"""
import time
from Scanner import Scanner

PORT = 'COM3'


def ask(msg):
    return input(f'\n{msg} [y/N] ').strip().lower() == 'y'


def connect():
    sc = Scanner(port=PORT)
    print('Coords:', sc.getCoords(), '| Limits:', sc.getLimits())
    return sc


def check_range(sc):
    if not ask('1) Out-of-range test: temporary XLimit = 10 mm; X at 0 -> request '
               '-0.5 mm and 10.5 mm. Worst case if not rejected: 10.5 mm. Go?'):
        return
    sc.moveX(0)
    old_lim = sc.XLimit
    sc.XLimit = 10          # small temporary limit: bounds the damage if not enforced
    print('  Temporary XLimit =', sc.XLimit)
    try:
        for target in (-0.5, 10.5):
            print(f'Requesting X = {target} mm ...')
            sc.moveX(target)
            print(f'  X now = {sc.X} mm (expected 0.0, no motion)')
    finally:
        sc.moveX(0)
        sc.XLimit = old_lim
        print('  XLimit restored =', sc.XLimit)


def check_z_direction(sc):
    if not ask('2) Z direction: move Z by +2 mm (from current, within limits). WATCH the axis. Go?'):
        return
    z0 = sc.Z
    sc.moveZ(round(z0 + 2, 3))
    print(f'  Z: {z0} -> {sc.Z} mm. Did it go UP or DOWN? (note it)')
    if ask('   Return Z to start?'):
        sc.moveZ(z0)


def check_stop(sc):
    if not ask('3) Stop test: X 0 -> 20 mm (~3 s); press Ctrl+C at ~1.5 s. Go?'):
        return
    sc.moveX(0)
    t0 = time.time()
    try:
        sc.moveX(20)
        print('  Move finished without interruption.')
    except KeyboardInterrupt:
        print(f'  Interrupted after {time.time() - t0:.2f} s.')
    time.sleep(1)
    try:
        print(f'  X reported = {sc.X} mm (check vs. physical position/display)')
    except Exception as e:
        print(f'  Could not read X after stop: {e!r}')


def check_limit_persistence(sc):
    if not ask('4) Limit persistence: set XLimit = 80 mm, then you power-cycle the controller. Go?'):
        return sc
    sc.XLimit = 80
    print('  XLimit now =', sc.XLimit)
    sc.close()
    input('  Power the controller OFF and ON, then press Enter...')
    sc = connect()
    print('  XLimit after power cycle =', sc.XLimit,
          '(80 -> persistent; 100 -> reset to default)')
    print('  Coords after power cycle =', sc.getCoords())
    return sc


if __name__ == '__main__':
    sc = connect()
    try:
        check_range(sc)
        check_z_direction(sc)
        check_stop(sc)
        sc = check_limit_persistence(sc)
    finally:
        sc.close()
