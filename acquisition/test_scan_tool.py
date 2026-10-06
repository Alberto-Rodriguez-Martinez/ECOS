# -*- coding: utf-8 -*-
"""
test_scan_tool.py — line scan, water references and saving (scan_tool.py,
BD_Experimentos_PVA.save_scan_raw_32), task_scanner_phase5.md "Verificación" 1–6,
and the integer storage of task_scan_int16.md (exact rebuild, size, conversion
metadata, gains per channel) with the reference drift comparison.

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
from dataclasses import replace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, '..', 'database'))

import numpy as np  # noqa: E402

import test_focus_tool as tf  # noqa: E402  (module import: its tests are not collected twice)
from BD_Experimentos_PVA import (  # noqa: E402
    experiment_name, load_scan_raw_32, save_scan_raw_32,
)
from scan_counts import counts_to_float, sum_dtype, top_mask  # noqa: E402
from scan_tool import (  # noqa: E402
    LONG_SCAN_S, MAGNITUDES, PointContext, ScanParams, ScanPlan, compute_magnitudes,
    estimate_scan_s, line_positions, reference_drift, register_magnitude, scan_schedule,
    witness_correction, witness_doubt, witness_jumps, witness_position, witness_threshold,
)
from sim_sedaq import SimParams, SimSeDaq  # noqa: E402
from echo_tracking import (  # noqa: E402
    EchoDelay, FrontEchoTracker, band_samples, echo_pair_delay,
)
from ECOS_US_ToolBox import CalcToFAscanCosine_XCRFFT, Envelope  # noqa: E402

FS = tf.FS
LIMIT = tf.LIMIT
MID = 512               # 10-bit quantizer midpoint (the assumed resolution)


LAST_TOP = None     # raw samples at the quantizer top in the last acquire_counts()


def acquire_counts(sim, avg_n):
    """What ecos_gui._acquire_counts does: Σ(raw − midpoint) over avg_n captures,
    whole record, both channels (constant captures skipped), and the raw samples at
    the quantizer top in any capture (LAST_TOP)."""
    global LAST_TOP
    s1 = np.zeros(sim.RecLen, dtype=np.int64)
    s2 = np.zeros(sim.RecLen, dtype=np.int64)
    t1 = np.zeros(sim.RecLen, dtype=bool)
    t2 = np.zeros(sim.RecLen, dtype=bool)
    k = 0
    while k < avg_n:
        sim.GetAScan()
        r1 = np.asarray(sim.DataADC1[:sim.RecLen], dtype=np.int64)
        r2 = np.asarray(sim.DataADC2[:sim.RecLen], dtype=np.int64)
        if np.all(r1 == r1[0]) or np.all(r2 == r2[0]):
            continue
        s1 += r1 - MID
        s2 += r2 - MID
        t1 |= top_mask(r1)
        t2 |= top_mask(r2)
        k += 1
    LAST_TOP = (t1, t2)
    return s1, s2
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
        plan = ScanPlan(ScanParams(start=-1, end=1, step=1, settle_ms=500, line_settle_ms=800,
                                   avg_n=20, witness=False), coords,
                        'X', 'Y', {'X': LIMIT, 'Z': LIMIT})
        # 49 → 50 → 51, from 50 and back: 1 + 1 + 1 + 1 mm; 3 × (20 × 10 ms) and the
        # settles: the first point after the long move (0.8 s), then 2 × 0.5 s
        self.assertAlmostEqual(estimate_scan_s(plan, 0.01, 6.7), 4 / 6.7 + 3 * 0.2 + 0.8 + 1.0)
        # the witness at the first point: visited before and after the line, +2 × (0.8 s
        # + 20 × 10 ms) and the travel 51 → 49 → 50 instead of 51 → 50: +2 mm
        wit = ScanPlan(ScanParams(start=-1, end=1, step=1, settle_ms=500, line_settle_ms=800,
                                  avg_n=20, witness=True), coords, 'X', 'Y',
                       {'X': LIMIT, 'Z': LIMIT})
        self.assertAlmostEqual(estimate_scan_s(wit, 0.01, 6.7) - estimate_scan_s(plan, 0.01, 6.7),
                               2 * (0.8 + 0.2) + 2 / 6.7)
        long_plan = ScanPlan(ScanParams(start=-50, end=40, step=0.05, settle_ms=1000, avg_n=20),
                             coords, 'X', 'Y', {'X': LIMIT, 'Z': LIMIT})
        self.assertGreater(estimate_scan_s(long_plan, 0.01), LONG_SCAN_S)

    def test_magnitudes_are_extensible(self):
        # thickness first: the default of the map (phase 6)
        self.assertEqual(list(MAGNITUDES)[:4], ['thickness', 'tof', 'amplitude', 'energy'])
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
            self.assertTrue(np.isnan(vals['thickness']))          # no echo pair given
            pair = EchoDelay(True, '', 150, 540, 389.61, 0.99, -1)
            ctx.pair, ctx.c_sample = pair, 1540.0
            self.assertAlmostEqual(compute_magnitudes(ctx)['thickness'], 3.0, places=4)
            self.assertAlmostEqual(compute_magnitudes(ctx)['thickness_corr'], 0.99)
            self.assertTrue(np.isnan(compute_magnitudes(ctx, lost=True)['tof']))
        finally:
            del MAGNITUDES['peak_to_peak']


class TestWitnessPure(unittest.TestCase):
    """Schedule with witness visits, jumps off the trend and the live correction."""

    coords = {'X': 50.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}

    def plan(self, **kw):
        base = dict(start=-1, end=1, step=1, settle_ms=100, line_settle_ms=1000)
        base.update(kw)
        return ScanPlan(ScanParams(**base), self.coords, 'X', 'Y', {'X': LIMIT, 'Z': LIMIT})

    def test_line_schedule(self):
        sched = scan_schedule(self.plan())
        self.assertEqual([e.kind for e in sched], ['witness', 'point', 'point', 'point', 'witness'])
        self.assertEqual([e.pos for e in sched], [{'X': 49.0}, {'X': 49.0}, {'X': 50.0},
                                                  {'X': 51.0}, {'X': 49.0}])
        self.assertEqual([e.settle_ms for e in sched], [1000, 1000, 100, 100, 1000])
        self.assertEqual([(e.line, e.j) for e in sched if e.kind == 'witness'], [(0, 0), (1, 1)])
        self.assertEqual([e.j for e in sched if e.kind == 'point'], [0, 1, 2])

    def test_witness_positions(self):
        self.assertEqual(witness_position(self.plan(witness_mode='start')), {'X': 50.0, 'Z': 25.0})
        custom = self.plan(witness_mode='custom', witness_lat=47.0, witness_z=30.0)
        sched = scan_schedule(custom)
        # the other axis moves first to the witness, and first again back to the line
        self.assertEqual(list(sched[0].pos.items()), [('Z', 30.0), ('X', 47.0)])
        self.assertEqual(list(sched[1].pos.items()), [('Z', 25.0), ('X', 49.0)])
        self.assertEqual(list(sched[2].pos.items()), [('X', 50.0)])
        z = ScanPlan(ScanParams(axis_role='z', start=-1, end=1, step=1, witness_mode='custom',
                                witness_lat=47.0, witness_z=30.0), self.coords, 'X', 'Y',
                     {'X': LIMIT, 'Z': LIMIT})
        self.assertEqual(witness_position(z), {'Z': 30.0, 'X': 47.0})
        with self.assertRaises(ValueError):
            witness_position(self.plan(witness_mode='custom', witness_lat=LIMIT + 1))

    def test_jumps_off_the_trend(self):
        t = np.arange(7) * 30.0                         # a visit every 30 s
        face = -0.07 * t                                # −4.2 µm/min, steady …
        face[4:] -= 6.0                                 # … and a 6 µm jerk: visits 3 → 4
        dev, rate = witness_jumps(t, face)
        self.assertAlmostEqual(rate, -0.07)
        np.testing.assert_allclose(dev, [0, 0, 0, -6.0, 0, 0], atol=1e-9)
        visits = [{'after_line': k} for k in range(7)]
        self.assertEqual(witness_doubt(visits, dev, 3.0), {3: 'witness jump -6.0 µm'})
        face[2] = np.nan                                # an echo lost: drift unknown around it
        dev, _ = witness_jumps(t, face)
        doubt = witness_doubt(visits, dev, 3.0)
        self.assertEqual(sorted(doubt), [1, 2, 3])
        self.assertEqual(doubt[1], 'witness echo lost')

    def test_surface_schedule_axis_order_and_settle(self):
        """Fixed order: the other axis first at every line change and witness visit; the
        long-move settle on the first point of each line and on the witness."""
        for path in ('zigzag', 'same'):
            with self.subTest(path=path):
                sched = scan_schedule(self.plan(surface=True, start2=-1, end2=1, step2=1,
                                                path=path))
                kinds = ''.join('w' if e.kind == 'witness' else 'p' for e in sched)
                self.assertEqual(kinds, 'wpppwpppwpppw')
                lines = [[e for e in sched if e.kind == 'point' and e.line == k] for k in range(3)]
                firsts = [ln[0] for ln in lines]
                for e in sched:
                    keys = list(e.pos)
                    if len(keys) == 2:
                        self.assertEqual(keys, ['Z', 'X'])
                    long_move = e.kind == 'witness' or any(e is f for f in firsts)
                    self.assertEqual(e.settle_ms, 1000 if long_move else 100)
                self.assertEqual([e.pos['X'] for e in lines[1]],
                                 [51.0, 50.0, 49.0] if path == 'zigzag' else [49.0, 50.0, 51.0])
                self.assertEqual([e.j for e in lines[1]],
                                 [2, 1, 0] if path == 'zigzag' else [0, 1, 2])
                self.assertEqual(lines[1][0].pos.get('Z'), 25.0)
        every2 = scan_schedule(self.plan(surface=True, start2=-2, end2=2, step2=1,
                                         witness_every=2))
        self.assertEqual([e.line for e in every2 if e.kind == 'witness'], [0, 2, 4, 5])

    def test_jump_threshold_from_the_series(self):
        """3 × the robust scatter of the deviations, never below the 4 µm floor."""
        rng = np.random.default_rng(7)
        t = np.arange(41) * 30.0
        for jitter, expect_floor in ((0.41, True), (2.5, False)):     # steel-like, noisy PVA
            with self.subTest(jitter=jitter):
                face = -0.07 * t + rng.normal(0.0, jitter, t.size)
                dev, _ = witness_jumps(t, face)
                thr, sigma = witness_threshold(dev)
                self.assertAlmostEqual(sigma, jitter * np.sqrt(2), delta=0.35 * jitter * np.sqrt(2))
                if expect_floor:
                    self.assertEqual(thr, 4.0)
                else:
                    self.assertAlmostEqual(thr, 3 * sigma)
                    self.assertGreater(thr, 4.0)
        # a 40 µm jump among five intervals is still found (a plain std would hide it)
        face = -0.07 * t[:6] + np.array([0, 0.5, -0.4, 0.3, -40.0, -40.2])
        dev, _ = witness_jumps(t[:6], face)
        thr, _ = witness_threshold(dev)
        self.assertGreater(3 * np.std(dev), 40.0)                   # the naive rule
        self.assertLess(thr, 10.0)
        self.assertEqual(sorted(witness_doubt([{'after_line': k} for k in range(6)], dev, thr)),
                         [3])
        self.assertEqual(witness_threshold(dev[:2])[0], 4.0)      # too few: the floor
        self.assertEqual(witness_threshold(dev, floor_um=50.0)[0], 50.0)

    def test_live_correction(self):
        t, v = [0.0, 10.0, 20.0], [5.0, 6.0, 8.0]
        np.testing.assert_allclose(witness_correction([-5.0, 5.0, 15.0, 30.0], t, v),
                                   [0.0, 0.5, 2.0, 3.0])
        np.testing.assert_allclose(witness_correction([5.0], t, [np.nan] * 3), [0.0])


class TestScanSaveFormat(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='scan_save_test_')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_experiment_name_keeps_the_us_convention(self):
        self.assertEqual(experiment_name('10', '5', 'P3A', '5', 'US', '20261002_091500'),
                         'PVA_10_PG_05_A_C005_US_20261002_091500')
        self.assertEqual(experiment_name('', 'x', '', '', 'SCAN', '20261002_091500'),
                         'PVA_XX_PG_YY_X_CNNN_SCAN_20261002_091500')

    def kwargs(self, n_avg=20, n_point=3, n_samp=50, seed=0, **over):
        rng = np.random.default_rng(seed)
        s = rng.integers(-MID * n_avg, MID * n_avg, size=(1, n_point, n_samp))
        kw = dict(specimen={'pieza': 'A'}, protocol={},
                  equipment1={'params': {'Smin': 100, 'Smax': 100 + n_samp}},
                  equipment2={}, scanner_session={'beam_axis': 'Y'}, scan={'type': 'line'},
                  signals_ch1=s, signals_ch2=-s, offsets_ch1=rng.normal(size=(1, n_point)) * 1e-3,
                  offsets_ch2=rng.normal(size=(1, n_point)) * 1e-3, n_avg=n_avg,
                  gains=(65.0, 35.0), coords=np.zeros((1, n_point, 4)),
                  point_time=np.arange(float(n_point)).reshape(1, n_point),
                  temperatures=[{'label': 'start', 'point': -1, 'time': 1.0, 'T1': float('nan'),
                                 'T2': 24.0}],
                  operator='Ana', base_dir=self.dir, exp_name='PVA_10_PG_05_A_C005_SCAN_x')
        kw.update(over)
        return kw

    def test_roundtrip_and_validation(self):
        kw = self.kwargs()
        path = save_scan_raw_32(**kw)
        meta, data = load_scan_raw_32(path)
        self.assertEqual(meta['schema_version'], 'scan-32-3.1')
        self.assertEqual(meta['experiment']['operator'], 'Ana')
        self.assertFalse(os.path.exists(os.path.join(path, 'results.json')))
        np.testing.assert_array_equal(data['signals_ch2_sum'], -kw['signals_ch1'])
        self.assertEqual(data['signals_ch1_sum'].dtype, np.int16)
        self.assertEqual(data['signals_ch1'].dtype, np.float64)
        self.assertTrue(np.isnan(data['temp_T1'][0]))
        with self.assertRaises(FileExistsError):
            save_scan_raw_32(**kw)
        for bad in (dict(signals_ch2=kw['signals_ch2'][:, :2]),               # shapes
                    dict(signals_ch1=kw['signals_ch1'] * 0.5),                # not integer
                    dict(signals_ch1=kw['signals_ch1'] * 0 + MID * 20 + 1)):  # not a sum of 20
            with self.subTest(bad=list(bad)):
                with self.assertRaises(ValueError):
                    save_scan_raw_32(**dict(kw, exp_name='other', **bad))

    def test_dtype_follows_the_averages(self):
        """int16 while |Σ| ≤ 512·N fits (N ≤ 63 at 10 bits), int32 beyond: no limit on N."""
        self.assertIs(sum_dtype(63), np.int16)
        self.assertIs(sum_dtype(64), np.int32)
        self.assertIs(sum_dtype(100), np.int32)
        path = save_scan_raw_32(**self.kwargs(n_avg=100))
        meta, data = load_scan_raw_32(path)
        self.assertEqual(meta['conversion']['dtype'], 'int32')
        self.assertEqual(data['signals_ch1_sum'].dtype, np.int32)

    def test_conversion_metadata_and_gains_per_channel(self):
        """Points 3 and 4: midpoint, bits, averages, dtype and the gain of each channel."""
        ref = {'sum1': np.arange(50) * 3, 'sum2': -np.arange(50), 'offset1': 0.01,
               'offset2': -0.02, 'avg_n': 100, 'gains': [20.0, 10.0], 'coords': [1, 2, 3, 0],
               'time': 1.0, 'T1': 24.0, 'T2': 24.1}
        path = save_scan_raw_32(**self.kwargs(references={'initial': ref}))
        meta, data = load_scan_raw_32(path)
        c = meta['conversion']
        self.assertEqual((c['quantizer_bits'], c['quantizer_midpoint'], c['full_scale_counts']),
                         (10, 512, 1024))
        self.assertEqual((c['n_avg'], c['dtype']), (20, 'int16'))
        self.assertEqual(c['gain_db'], {'ch1': 65.0, 'ch2': 35.0})
        r = c['references']['initial']
        self.assertEqual((r['n_avg'], r['dtype']), (100, 'int32'))
        self.assertEqual(r['gain_db'], {'ch1': 20.0, 'ch2': 10.0})
        # each channel rebuilt with its own sums and offset, the reference with its own N
        np.testing.assert_array_equal(data['ref_initial_ch1'],
                                      counts_to_float(ref['sum1'], 100, 10, 0.01)[0])
        np.testing.assert_array_equal(data['ref_initial_ch2'],
                                      counts_to_float(ref['sum2'], 100, 10, -0.02)[0])

    def test_size_about_half_of_float32(self):
        """Point 2, on realistic data: an averaged simulated scan, 41 points × 3500 samples."""
        sim = SimSeDaq(SimParams(snr_db=30.0), reclen=8192, seed=4)
        sums1, sums2, f1, f2, o1, o2 = [], [], [], [], [], []
        smin, smax = tf.WIDE
        for k in range(41):
            sim.set_scanner_state({'X': 40.0 + 0.5 * k, 'Y': 50.0, 'Z': 25.0, 'R': 0.0})
            s1, s2 = acquire_counts(sim, 20)
            x1, a1 = counts_to_float(s1, 20)
            x2, a2 = counts_to_float(s2, 20)
            sums1.append(s1[smin:smax]); sums2.append(s2[smin:smax])
            f1.append(x1[smin:smax]); f2.append(x2[smin:smax]); o1.append(a1); o2.append(a2)
        n_samp = smax - smin
        kw = self.kwargs(n_point=41, n_samp=n_samp,
                         signals_ch1=np.array(sums1).reshape(1, 41, n_samp),
                         signals_ch2=np.array(sums2).reshape(1, 41, n_samp),
                         offsets_ch1=np.array(o1).reshape(1, 41),
                         offsets_ch2=np.array(o2).reshape(1, 41),
                         equipment1={'params': {'Smin': smin, 'Smax': smax}})
        path = save_scan_raw_32(**kw)
        new = os.path.getsize(os.path.join(path, 'scan.npz'))
        f32 = os.path.join(self.dir, 'float32.npz')
        np.savez_compressed(f32, signals_ch1=np.array(f1, dtype=np.float32),
                            signals_ch2=np.array(f2, dtype=np.float32))
        old = os.path.getsize(f32)
        raw_new = sum(np.asarray(a).nbytes for a in (kw['signals_ch1'].astype(np.int16),
                                                     kw['signals_ch2'].astype(np.int16)))
        raw_old = 2 * np.array(f1, dtype=np.float32).nbytes
        print(f'\n[size] signals uncompressed: int16 {raw_new / 1e6:.2f} MB, float32 '
              f'{raw_old / 1e6:.2f} MB; compressed scan.npz {new / 1e6:.2f} MB vs float32 .npz '
              f'{old / 1e6:.2f} MB (ratio {new / old:.2f})')
        self.assertEqual(raw_new * 2, raw_old)            # exactly half before compression
        self.assertLess(new / old, 0.7)                   # deflate also shrinks float32
        import zipfile
        with zipfile.ZipFile(os.path.join(path, 'scan.npz')) as z:     # still compressed
            self.assertTrue(all(i.compress_type == zipfile.ZIP_DEFLATED for i in z.infolist()))
        # exact: the floats read back are the very ones computed when "measuring"
        _, data = load_scan_raw_32(path)
        np.testing.assert_array_equal(data['signals_ch1'][0], np.array(f1))
        np.testing.assert_array_equal(data['signals_ch2'][0], np.array(f2))

    def test_schema_2_still_read(self):
        """A 2.0 file (phase-5 line scans on the real equipment) is still read: a line,
        every point acquired."""
        path = save_scan_raw_32(**self.kwargs())
        meta_path = os.path.join(path, 'meta.json')
        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)
        meta['schema_version'] = 'scan-32-2.0'
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        _, data = load_scan_raw_32(path)
        self.assertTrue(data['point_valid'].all())
        self.assertEqual(data['point_valid'].shape, (1, 3))

    def test_old_float32_schema_is_refused(self):
        path = save_scan_raw_32(**self.kwargs())
        meta_path = os.path.join(path, 'meta.json')
        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)
        meta['schema_version'] = 'scan-32-1.0'
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f)
        with self.assertRaises(ValueError):
            load_scan_raw_32(path)


class TestReferenceDrift(unittest.TestCase):

    def refs(self, **change):
        sim = SimSeDaq(SimParams(snr_db=60.0), reclen=8192, seed=5)
        sim.set_scanner_state({'X': 90.0, 'Y': 50.0, 'Z': 4.0, 'R': 0.0})
        out = []
        for params in ({}, change):
            for k, v in params.items():
                setattr(sim.params, k, v)
            s1, s2 = acquire_counts(sim, 20)
            smin, smax = 1000, 7000
            out.append({'ch1': counts_to_float(s1, 20)[0][smin:smax],
                        'ch2': counts_to_float(s2, 20)[0][smin:smax]})
        return out

    def test_no_drift(self):
        a, b = self.refs()
        d = reference_drift(a, b)
        self.assertTrue(d['ch1']['clear'])
        self.assertLess(abs(d['ch1']['d_db']), 0.05)
        self.assertLess(abs(d['ch1']['d_tof_ns']), 1.0)
        self.assertEqual(d['exceeds'], [])

    def test_amplitude_and_tof_drift_detected(self):
        """Water 1 m/s slower (≈ −0.3 °C) and 10 % less transmission on Ch1."""
        sim_cw = SimParams().c_w
        a, b = self.refs(c_w=sim_cw - 1.0, tt_amp=SimParams().tt_amp * 0.9)
        d = reference_drift(a, b, tol_db=0.5, tol_ns=20.0)
        self.assertAlmostEqual(d['ch1']['d_db'], 20 * np.log10(0.9), delta=0.05)
        # TT path in water: (tt_separation − thickness) = 50 mm → Δt = 50 mm · Δc / c²
        expected_ns = 50e-3 * 1.0 / sim_cw ** 2 * 1e9
        self.assertAlmostEqual(d['ch1']['d_tof_ns'], expected_ns, delta=2.0)   # later: positive
        self.assertIn('ch1 amplitude', d['exceeds'])
        self.assertIn('ch1 ToF', d['exceeds'])

    def test_only_the_transmission_channel_is_compared(self):
        """A change of the pulse-echo channel alone (Ch2) does not count as drift."""
        a, b = self.refs(A0=SimParams().A0 * 0.5)       # PE echo −6 dB, Ch1 untouched
        d = reference_drift(a, b, tol_db=0.5, tol_ns=20.0)
        self.assertEqual(d['channel'], 'ch1')
        self.assertNotIn('ch2', d)
        self.assertEqual(d['exceeds'], [])
        self.assertLess(abs(d['ch1']['d_db']), 0.05)
        # and both channels are still there to be saved
        self.assertTrue(np.max(np.abs(b['ch2'])) < 0.7 * np.max(np.abs(a['ch2'])))


# A sample whose back face is in the window and clear: 3 mm, a focal zone wide
# enough for both faces (σ = 6 mm) and averaged-like SNR.
THICK = dict(thickness=3.0, sigma=6.0, snr_db=45.0)


def true_delay_samples(p):
    return 2.0 * p.thickness * 1e-3 / p.c_sample * FS


class TestSaturationDetection(unittest.TestCase):
    """scan_counts.top_mask / count_at_top: the one saturation detection of ECOS."""

    def test_top_codes_only(self):
        from scan_counts import count_at_top
        raw = np.array([0, 1, 511, 512, 1022, 1023])
        np.testing.assert_array_equal(top_mask(raw), [True, False, False, False, False, True])
        self.assertEqual(count_at_top(top_mask(raw)), 2)
        self.assertEqual(count_at_top(top_mask(raw), (1, 5)), 0)            # the range is the caller's
        self.assertEqual(count_at_top(top_mask(raw), (4, 6)), 1)
        self.assertEqual(count_at_top(top_mask(np.array([0, 4095]), bits=12)), 2)
        self.assertEqual(count_at_top(None), 0)

    def test_one_clipped_capture_is_not_hidden_by_the_average(self):
        """The old flag (|x| ≥ 0.49 on the averaged float) misses it; the raw count does not."""
        from scan_counts import count_at_top
        n, rec = 10, 200
        captures = [np.full(rec, MID + 100) for _ in range(n)]
        for c in captures:
            c[::2] = MID - 100                       # not constant, mean ≈ midpoint
        captures[3][50] = 1023                       # one sample, one capture, at the top
        top = np.zeros(rec, dtype=bool)
        s = np.zeros(rec, dtype=np.int64)
        for c in captures:
            top |= top_mask(c)
            s += c - MID
        x, _ = counts_to_float(s, n)
        self.assertLess(np.max(np.abs(x)), 0.49)     # the averaged float stays far below
        self.assertEqual(count_at_top(top), 1)


class TestEchoPair(unittest.TestCase):
    """Echo 1 → echo 2 by cross-correlation (echo_tracking.echo_pair_delay)."""

    def pair(self, window=tf.WIDE, seed=1, **kw):
        sim = SimSeDaq(SimParams(**dict(THICK, **kw)), reclen=8192, seed=seed)
        sim.set_scanner_state({'X': 50.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0})
        s1, s2 = acquire_counts(sim, 4)
        sig = counts_to_float(s2, 4)[0]
        tr = FrontEchoTracker(window, 0.0, band_samples(0.5))
        m = tr.measure(sig, 0.0)
        seg, env = tr.point_signals()
        return sim, echo_pair_delay(seg, env, m.index - window[0], tr.band, smin=window[0])

    def test_delay_and_polarity(self):
        """The simulator's 2h/c_sample, with the back wall inverted (default) or not."""
        for invert_back, polarity in ((False, -1), (True, 1)):
            with self.subTest(invert_back=invert_back):
                sim, p = self.pair(invert_back=invert_back)
                self.assertTrue(p.found, p.reason)
                self.assertAlmostEqual(p.delay_samples, true_delay_samples(sim.params), delta=0.1)
                self.assertEqual(p.polarity, polarity)
                self.assertGreater(p.corr, 0.99)

    def test_thin_and_thick_samples(self):
        for kw in (dict(thickness=1.5), dict(thickness=10.0, sigma=20.0)):
            with self.subTest(**kw):
                sim, p = self.pair(**kw)
                self.assertTrue(p.found, p.reason)
                self.assertAlmostEqual(p.delay_samples, true_delay_samples(sim.params), delta=0.1)

    def test_echo_2_outside_the_window_gives_no_number(self):
        """Smax just before the back echo, or just after it: never a delay against the edge."""
        sim = SimSeDaq(SimParams(**THICK))
        front = int(round(sim.front_tof(50.0, 50.0, 25.0) * FS))
        back = int(round(sim.back_tof(50.0, 50.0, 25.0) * FS))
        for smax, reason in ((back - 100, 'no_back'), (back + 60, 'back_at_edge')):
            with self.subTest(smax=smax):
                _, p = self.pair(window=(front - 600, smax))
                self.assertFalse(p.found)
                self.assertEqual(p.reason, reason)
                self.assertTrue(np.isnan(p.delay_samples))


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
        self.window = tf.WIDE
        self.live = {'on': True}
        self.measured = []                  # every float pair handed to the tools

        def acquire(n):
            s1, s2 = acquire_counts(self.sim, n)
            x1, o1 = counts_to_float(s1, n)
            x2, o2 = counts_to_float(s2, n)
            self.last_counts = {'sum': (s1, s2), 'offset': (o1, o2), 'n': n}
            self.measured.append((x1, x2))
            return x1, x2

        self.seq = ScanSequencer(
            self.worker, self.sim, acquire,
            coords_fn=self.panel.current_coords,
            enter_exclusive=lambda: self.live.update(on=False),
            leave_exclusive=lambda: self.live.update(on=True),
            top_fn=lambda: LAST_TOP)
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
        self.holds = []
        self.tool = ScanTool(
            self.seq, self.panel, lambda: self.window, pg.PlotWidget(),
            acquire_fn=acquire, gains_fn=lambda: self.scan_gains,
            set_gains_fn=set_gains, counts_fn=lambda: self.last_counts,
            temp_factory=factory if temp else None,
            sos_fn=lambda T: 1402.7 + 4.88 * T - 0.0482 * T ** 2,
            cw_fn=lambda: (self.sim.params.c_w, 'synthetic SeDaq'),
            info_fn=lambda: {'specimen': {'pieza': 'P3A'}, 'protocol': {},
                             'equipment1': {'nombre': 'SEDAQ', 'params': {'Voltaje': '100'}},
                             'equipment2': {},
                             'name_parts': {'pva': '10', 'additive': '5', 'sample_id': 'P3A',
                                            'cycles': '5'}},
            base_dir=self.base, lock_fn=self.locks.append, hold_live_fn=self.holds.append,
            dump_dir=os.path.join(self.base, '_debug'),
            acq_time_fn=getattr(self, 'acq_time', None),
            move_overhead_s=0.0)                    # the fake worker answers at once
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
                p = ScanParams(axis_role=role, start=-2, end=2, step=0.5, settle_ms=0,
                               line_settle_ms=0, avg_n=2, witness=False)
                self.assertIsNone(self.tool.start(p))
                self.wait(lambda: self.dones)
                self.assertEqual(self.dones, ['completed'], self.statuses[-1])
                self.assertEqual(counts, list(range(1, 10)))            # one map update per point
                meta, d = self.load_saved()
                n_samp = tf.WIDE[1] - tf.WIDE[0]
                # exact rebuild of what was measured (task_scan_int16 point 1)
                smin, smax = tf.WIDE
                # the thickness check at Start, the 9 points, one acquisition on the way back
                scanned = self.measured[1:10]
                np.testing.assert_array_equal(
                    d['signals_ch1'][0], np.array([m[0][smin:smax] for m in scanned]))
                np.testing.assert_array_equal(
                    d['signals_ch2'][0], np.array([m[1][smin:smax] for m in scanned]))
                self.assertEqual(meta['conversion']['gain_db'], {'ch1': 65.0, 'ch2': 35.0})
                self.assertEqual(meta['conversion']['dtype'], 'int16')
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
        p = ScanParams(start=-4, end=4, step=0.5, settle_ms=0, line_settle_ms=0, avg_n=2,
                       witness=False)
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
        # the whole line, padded: the 5 acquired points are marked, the line is partial
        self.assertEqual(d['signals_ch1'].shape[:2], (1, 17))
        self.assertEqual(int(d['point_valid'].sum()), 5)
        self.assertTrue(d['point_valid'][0, :5].all())
        self.assertTrue(np.isnan(d['signals_ch1'][0, 5:]).all())
        self.assertTrue(np.isnan(d['coords'][0, 5:]).all())
        self.assertEqual(meta['scan']['line_status'], ['partial'])
        self.assertTrue(d['line_partial'][0])
        self.assertFalse(meta['scan']['completed'])
        self.assertEqual(meta['scan']['n_points'], 17)
        self.assertEqual(len(self.worker.moves), n_moves)          # saving does not move

    def test_stop_then_discard(self):
        self.make()
        self.seq.point_done.connect(lambda i, *_: i == 2 and self.tool.stop())
        self.assertIsNone(self.tool.start(ScanParams(start=-2, end=2, step=0.5, settle_ms=0,
                                                     line_settle_ms=0, avg_n=1)))
        self.wait(lambda: self.tool.state == 'stopped')
        self.assertIsNone(self.tool.discard())
        self.assertEqual(self.dones, ['discarded'])
        self.assertEqual(os.listdir(self.base), [])

    def test_lost_echo_is_marked_and_the_scan_goes_on(self):
        self.make(face_half_lat=2.0)
        self.assertIsNone(self.tool.start(ScanParams(start=-5, end=5, step=1, settle_ms=0,
                                                     line_settle_ms=0, avg_n=2)))
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
                                                     line_settle_ms=0, avg_n=1)))
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
                                                     line_settle_ms=0, avg_n=1, references=True)))
        self.assertEqual(self.tool.state, 'ref_out')               # between sequences
        self.assertIn('scan session', focus.run(5.0, 1.0))
        self.tool.cancel_reference()
        self.assertIsNone(self.seq.reserved_reason())


class TestScanSaturationFlag(ScanHarness):
    """The 'saturated' flag from raw counts, Smin–Smax only (from 06/10)."""

    def scan(self, gain2):
        self.make()
        self.scan_gains = (65.0, gain2)
        self.sim.SetGain2(gain2)
        self.assertIsNone(self.tool.start(ScanParams(start=-1, end=1, step=1, settle_ms=0,
                                                     line_settle_ms=0, avg_n=2, witness=False)))
        self.wait(lambda: self.dones)
        return self.tool.data

    def test_main_bang_outside_the_window_does_not_flag(self):
        from scan_counts import count_at_top
        d = self.scan(35.0)                                    # reference gain
        self.assertGreater(count_at_top(LAST_TOP[1]), 0)        # the bang clips (sample ~30) …
        self.assertEqual(count_at_top(LAST_TOP[1], tf.WIDE), 0)   # … outside Smin–Smax
        self.assertFalse(any('saturated' in f for f in d.flags))
        self.assertTrue(all(m.n_top == 0 for m in d.measures))   # checked, nothing there
        meta, _ = self.load_saved()
        self.assertIn('any single capture', meta['scan']['saturation_criterion'].lower())
        self.assertIn('Smin-Smax', meta['scan']['saturation_criterion'])
        self.assertEqual(meta['schema_version'], 'scan-32-3.1')

    def test_clipped_echo_flags_the_points(self):
        d = self.scan(35.0 + 12.0)                             # front echo 0.2 → 0.8: clips
        self.assertTrue(all('saturated' in f for f in d.flags))
        self.assertTrue(all(m.n_top > 0 for m in d.measures))
        self.assertTrue(any('lower the gain' in w for w in self.warnings))


class TestThickness(ScanHarness):
    """Phase 6, section 2 and verification 3."""

    def test_thickness_matches_the_simulator(self):
        self.make(**THICK)
        offered = []
        self.tool.thickness_available.connect(lambda on, why: offered.append(on))
        self.assertIsNone(self.tool.start(ScanParams(start=-2, end=2, step=1, settle_ms=0,
                                                     line_settle_ms=0, avg_n=4,
                                                     c_sample=self.sim.params.c_sample)))
        self.assertEqual(offered, [True])
        self.assertEqual(self.tool.magnitude, 'thickness')          # the default of the map
        self.wait(lambda: self.dones)
        d = self.tool.data
        th = [m['thickness'] for m in d.magnitudes]
        np.testing.assert_allclose(th, 3.0, atol=0.003)            # 3 µm on 3 mm
        self.assertTrue(all(m['thickness_corr'] > 0.95 for m in d.magnitudes))
        self.assertFalse(any('no_back' in f or 'low_corr' in f for f in d.flags))
        meta, s = self.load_saved()
        self.assertTrue(meta['scan']['thickness']['enabled'])
        self.assertEqual(s['live_thickness'].shape, (1, 5))
        np.testing.assert_allclose(s['echo_delay_us'][0],
                                   true_delay_samples(self.sim.params) / FS * 1e6, atol=2e-3)
        self.assertTrue(np.all(s['echo_polarity'] == -1))          # PVA back face: inverted
        np.testing.assert_allclose(s['live_thickness_corr'][0], [m['thickness_corr']
                                                                 for m in d.magnitudes])

    def test_echo_2_outside_the_window_warns_before_starting(self):
        self.make(**THICK)
        front = int(round(self.sim.front_tof(50.0, 50.0, 25.0) * FS))
        back = int(round(self.sim.back_tof(50.0, 50.0, 25.0) * FS))
        self.window = (front - 600, back - 100)                     # echo 2 beyond Smax
        g = ScanGroup(self.tool, self.seq)
        self.assertEqual(g._cmb_mag.currentData(), 'thickness')
        moves_at_warning = []
        self.tool.warning.connect(lambda w: 'Thickness NOT available' in w
                                  and moves_at_warning.append(len(self.worker.moves)))
        self.assertIsNone(self.tool.start(ScanParams(start=-1, end=1, step=1, settle_ms=0,
                                                     line_settle_ms=0, avg_n=4)))
        self.assertEqual(moves_at_warning, [0])                     # before anything moved
        self.assertNotEqual(self.tool.magnitude, 'thickness')
        i = g._cmb_mag.findData('thickness')
        self.assertFalse(g._cmb_mag.model().item(i).isEnabled())    # not offered
        self.assertEqual(g._cmb_mag.currentData(), 'amplitude')
        self.assertIn('beyond Smax', g._lbl_thick.text())
        self.wait(lambda: self.dones)
        self.assertEqual(self.dones, ['completed'])                # the scan itself goes on
        meta, s = self.load_saved()
        self.assertFalse(meta['scan']['thickness']['enabled'])
        self.assertIn('beyond Smax', meta['scan']['thickness']['reason_off'])
        self.assertTrue(np.all(np.isnan(s['live_thickness'])))
        self.assertTrue(np.all(np.isnan(s['echo_delay_us'])))
        self.assertFalse(np.any(np.isnan(s['live_tof'])))           # the rest is measured


class TestWitness(ScanHarness):
    """Phase 6, section 3 and verification 4, on a line (two visits)."""

    def test_drift_recorded_raw_and_thickness_unaffected(self):
        self.make(**THICK)
        rate = -50.0                                     # µm/s: well above the jitter
        self.sim.params.drift_um_per_min = rate * 60.0
        self.sim.restart_drift()
        self.assertIsNone(self.tool.start(ScanParams(
            start=-2, end=2, step=1, settle_ms=150, line_settle_ms=150, avg_n=4,
            c_sample=self.sim.params.c_sample)))
        self.wait(lambda: self.dones)
        meta, s = self.load_saved()
        w = meta['scan']['witness']
        self.assertTrue(w['enabled'])
        self.assertEqual((w['mode'], w['n_visits']), ('first', 2))
        self.assertEqual(list(s['witness_line']), [0, 1])
        self.assertEqual(s['witness_ch2'].shape, (2, tf.WIDE[1] - tf.WIDE[0]))
        self.assertEqual(s['witness_coords'].shape, (2, 4))
        np.testing.assert_allclose(s['witness_coords'][:, 0], 48.0 + OFFSET)   # real, first point
        dt = s['witness_time'][1] - s['witness_time'][0]
        self.assertGreater(dt, 0.5)
        c_w = meta['scan']['c_w']
        # the saved series rebuilds the drift: cross-correlation of the saved witness
        # signals (what the analysis does), around the front echo of the first visit
        k = int(np.argmax(Envelope(s['witness_ch2'][0])))
        gates = s['witness_ch2'][:, k - 60:k + 61]
        shift, _, _ = CalcToFAscanCosine_XCRFFT(gates[1], gates[0])
        self.assertAlmostEqual(c_w * shift / FS / 2.0 * 1e6, rate * dt,
                               delta=1.0 + 0.03 * abs(rate * dt))
        # the live value (envelope peak, the scan estimator: ±0.3 samples in the simulator)
        self.assertAlmostEqual(s['witness_face_um'][1] - s['witness_face_um'][0], rate * dt,
                               delta=5.0 + 0.1 * abs(rate * dt))
        # the scan points are stored raw: their ToF follows the drift (not corrected) …
        tof = s['live_tof'][0]
        face = (tof - tof[0]) * c_w / 2.0
        span = rate * (s['point_time'][0, -1] - s['point_time'][0, 0])
        self.assertLess(face[-1] - face[0], 0.5 * span)
        # … while the thickness does not move
        np.testing.assert_allclose(s['live_thickness'][0], 3.0, atol=0.003)
        np.testing.assert_allclose(s['witness_thickness_mm'], 3.0, atol=0.003)
        self.assertIn('never the thickness', meta['scan']['witness']['note'])

    def test_no_witness(self):
        self.make()
        self.assertIsNone(self.tool.start(ScanParams(start=-1, end=1, step=1, settle_ms=0,
                                                     line_settle_ms=0, avg_n=1, witness=False)))
        self.wait(lambda: self.dones)
        meta, s = self.load_saved()
        self.assertEqual(meta['scan']['witness'], {'enabled': False})
        self.assertNotIn('witness_sum1', s)


class TestSurfaceMapDrawing(unittest.TestCase):
    """The 2-D map is really painted, where the scan is (pyqtgraph 0.11 + numpy 1.24:
    the stock ImageItem raised inside paint() and stayed blank)."""

    LAT = np.array([49.0, 49.5, 50.0, 50.5, 51.0])
    Z = np.array([24.0, 25.0, 26.0])

    def setUp(self):
        from scan_tool import SurfaceMap, _LUT
        self.lut = _LUT
        self.w = pg.GraphicsLayoutWidget()
        self.w.resize(700, 400)
        self.w.show()
        self.addCleanup(self.w.close)
        self.map = SurfaceMap(self.w)
        self.map.reset(['thickness'], {'thickness': 'Thickness'}, {'thickness': 'mm'},
                       self.LAT, self.Z)

    def pixel(self, lat, z):
        from PyQt5.QtCore import QPointF
        QApplication.processEvents()
        img = self.w.grab().toImage()
        vb = self.map.panels['thickness'][0].getViewBox()
        p = self.w.mapFromScene(vb.mapViewToScene(QPointF(lat, z)))
        c = img.pixelColor(p.x(), p.y())
        return np.array([c.red(), c.green(), c.blue()])

    def test_rect_is_the_scan_with_half_a_step_each_side(self):
        img = self.map.panels['thickness'][1]
        self.map.set_data('thickness', np.zeros((5, 3)), np.ones((5, 3), bool))
        r = img.mapRectToParent(img.boundingRect())
        self.assertAlmostEqual(r.left(), 49.0 - 0.25)
        self.assertAlmostEqual(r.right(), 51.0 + 0.25)
        self.assertAlmostEqual(r.top(), 24.0 - 0.5)
        self.assertAlmostEqual(r.bottom(), 26.0 + 0.5)
        self.assertIn(img, self.map.panels['thickness'][0].items)

    def test_painted_in_place_and_oriented(self):
        grid = np.zeros((5, 3))
        grid[4, 0] = 1.0                                    # lateral 51, Z 24: the maximum
        self.map.set_data('thickness', grid, np.ones((5, 3), bool))
        np.testing.assert_allclose(self.pixel(51.0, 24.0), self.lut[-1], atol=12)
        np.testing.assert_allclose(self.pixel(49.0, 26.0), self.lut[0], atol=12)
        np.testing.assert_allclose(self.pixel(50.0, 25.0), self.lut[0], atol=12)

    def test_says_when_there_is_nothing_to_draw(self):
        note = self.map.notes['thickness']
        self.map.set_data('thickness', np.full((5, 3), np.nan), np.zeros((5, 3), bool))
        self.assertIn('No point measured yet', note.textItem.toPlainText())
        measured = np.zeros((5, 3), bool)
        measured[:2] = True
        self.map.set_data('thickness', np.full((5, 3), np.nan), measured,
                          empty_reason='thickness not available in this scan')
        self.assertIn('No valid value', note.textItem.toPlainText())
        self.assertIn('not available', note.textItem.toPlainText())
        grid = np.full((5, 3), np.nan)
        grid[0, 0] = 3.0
        self.map.set_data('thickness', grid, measured)
        self.assertEqual(note.textItem.toPlainText(), '')
        # NaN cells are drawn grey, not left blank
        np.testing.assert_allclose(self.pixel(49.5, 24.0), (120, 120, 120), atol=12)


class TestSurface(ScanHarness):
    """Phase 6 verification 1, 2, 4–8 on the simulator."""

    def surf(self, **kw):
        base = dict(start=-1, end=1, step=1, surface=True, start2=-1, end2=1, step2=1,
                    settle_ms=0, line_settle_ms=0, avg_n=2, c_sample=SimParams().c_sample)
        base.update(kw)
        return ScanParams(**base)

    def test_full_surface_both_paths(self):
        """1 and 2: map drawn as the lines come in, real coordinates, spatial order."""
        n_samp = tf.WIDE[1] - tf.WIDE[0]
        for path in ('zigzag', 'same'):
            with self.subTest(path=path):
                self.make(**THICK)
                shown = []
                self.seq.point_done.connect(
                    lambda *_: self.tool._phase == 'scan' and shown.append(
                        int(np.isfinite(self.tool._map.last['thickness'][0]).sum())
                        if 'thickness' in self.tool._map.last else 0))
                self.assertIsNone(self.tool.start(self.surf(path=path)))
                self.assertEqual(self.tool._map_names, ['thickness', 'amplitude'])
                self.wait(lambda: self.dones)
                self.assertEqual(self.dones, ['completed'], self.statuses[-1])
                # 4 witness visits (no new cell) around 3 lines of 3 points, one cell per point
                self.assertEqual(shown, [0, 1, 2, 3, 3, 4, 5, 6, 6, 7, 8, 9, 9])
                grid, levels = self.tool._map.last['thickness']
                self.assertEqual(grid.shape, (3, 3))                    # lateral × Z
                for name in ('thickness', 'amplitude'):                 # the scan, ± half a step
                    img = self.tool._map.panels[name][1]
                    r = img.mapRectToParent(img.boundingRect())
                    self.assertEqual((r.left(), r.right(), r.top(), r.bottom()),
                                     (48.5, 51.5, 23.5, 26.5))
                np.testing.assert_allclose(grid, 3.0, atol=0.003)
                meta, d = self.load_saved()
                self.assertEqual(meta['scan']['type'], 'surface')
                self.assertEqual(meta['scan']['path'], path)
                self.assertEqual(meta['scan']['n_lines'], 3)
                self.assertEqual(d['signals_ch2'].shape, (3, 3, n_samp))  # N_line = 3
                self.assertTrue(d['point_valid'].all())
                self.assertEqual(meta['scan']['line_status'], ['complete'] * 3)
                # real coordinates, in spatial order whatever the path
                for k, z in enumerate((24.0, 25.0, 26.0)):
                    np.testing.assert_allclose(d['coords'][k, :, 0],
                                               np.array([49.0, 50.0, 51.0]) + OFFSET)
                    np.testing.assert_allclose(d['coords'][k, :, 2], z + OFFSET)
                order = d['acq_index'][1]
                self.assertTrue(np.all(np.diff(order) < 0) if path == 'zigzag'
                                else np.all(np.diff(order) > 0))
                np.testing.assert_allclose(d['live_thickness'], 3.0, atol=0.003)
                self.assertEqual(d['live_thickness_corr'].shape, (3, 3))
                # back home: X, then Z
                self.assertEqual(self.worker.moves[-2:], [('X', 50.0), ('Z', 25.0)])
                self.assertIn('witness', meta['scan']['axis_order'])
                self.assertIn('NOT in the beam path', meta['scan']['temperature_note'])

    def test_witness_rebuilds_drift_and_marks_the_jump(self):
        """4 and 5: steady drift + a jump during line 2; thickness unaffected."""
        self.make(**THICK)
        rate = -50.0                                          # µm/s
        self.sim.params.drift_um_per_min = rate * 60.0
        self.sim.restart_drift()
        jump = {'t': None}

        def on_point(*_):
            d = self.tool.data
            if jump['t'] is None and d.line and d.line[-1] == 2:
                self.sim.params.face_offset_um = -40.0         # a jerk towards the PE
                jump['t'] = time.time()
        self.seq.point_done.connect(on_point)
        p = self.surf(start2=-2, end2=2, settle_ms=20, line_settle_ms=50)   # 4 µm limit
        self.assertIsNone(self.tool.start(p))
        self.wait(lambda: self.dones)
        meta, s = self.load_saved()
        w = meta['scan']['witness']
        self.assertEqual(w['n_visits'], 6)
        self.assertEqual(list(s['witness_line']), [0, 1, 2, 3, 4, 5])
        self.assertEqual(list(w['doubtful_lines']), ['2'])               # only that line
        self.assertIn('jump', w['doubtful_lines']['2'])
        self.assertEqual(list(s['line_doubtful']), [False, False, True, False, False])
        self.assertTrue(any('doubtful' in x for x in self.warnings))
        # the saved series rebuilds the drift (cross-correlation, as the analysis would)
        c_w = meta['scan']['c_w']
        k = int(np.argmax(Envelope(s['witness_ch2'][0])))
        g = s['witness_ch2'][:, k - 60:k + 61]
        face = np.array([CalcToFAscanCosine_XCRFFT(g[i], g[0])[0] for i in range(6)])
        face = c_w * face / FS / 2.0 * 1e6
        t = s['witness_time'] - s['witness_time'][0]
        truth = rate * t + np.where(s['witness_time'] > jump['t'], -40.0, 0.0)
        np.testing.assert_allclose(face, truth, atol=1.5 + 0.03 * np.max(np.abs(truth)))
        # stored raw, and the thickness never sees the drift nor the jump
        self.assertTrue(np.isfinite(s['live_tof']).all())
        np.testing.assert_allclose(s['live_thickness'], 3.0, atol=0.003)
        # the live ToF map can show it corrected, saying so
        self.tool.set_magnitude('tof')
        raw = self.tool._map.last['tof'][0]
        self.tool.set_drift_corrected(True)
        corrected = self.tool._map.last['tof'][0]
        self.assertIn('drift-corrected', self.tool._map.panels['tof'][0].titleLabel.text)
        self.assertLess(np.std(corrected), 0.5 * np.std(raw))
        np.testing.assert_array_equal(np.sort(s['live_tof'].ravel()), np.sort(raw.ravel()))

    def test_pause_resume_stop_mid_line(self):
        """6: the partial line is saved and marked."""
        self.make()
        seen = {'n': 0}
        paused = []

        # sequence: witness, line 0 (5 points), witness, line 1 …
        def on_point(*_):
            seen['n'] += 1
            if seen['n'] == 8:                     # 1st point of line 1: pause, then resume
                self.tool.pause()
                QTimer.singleShot(50, lambda: (paused.append(self.seq.state),
                                               self.tool.resume()))
            if seen['n'] == 9:                     # 2nd point of line 1: stop there
                self.tool.stop()
        self.seq.point_done.connect(on_point)
        self.assertIsNone(self.tool.start(self.surf(start=-2, end=2)))     # 5 points per line
        self.wait(lambda: self.tool.state == 'stopped')
        self.assertEqual(paused, ['paused'])
        self.assertIn('save them', self.statuses[-1])
        self.assertIsNone(self.tool.save_acquired())
        meta, d = self.load_saved()
        self.assertEqual(d['signals_ch1'].shape[:2], (2, 5))
        self.assertEqual(meta['scan']['line_status'], ['complete', 'partial'])
        self.assertEqual(meta['scan']['partial_line'], 1)
        self.assertEqual(d['point_valid'][0].tolist(), [True] * 5)
        # zigzag: line 1 runs backwards, so its acquired points are the last ones
        self.assertEqual(d['point_valid'][1].tolist(), [False, False, False, True, True])
        self.assertTrue(np.isnan(d['signals_ch1'][1, 0]).all())
        self.assertEqual(meta['scan']['witness']['lines_after_last_visit'], [1])
        self.assertFalse(meta['scan']['completed'])

    def test_temperature_per_line(self):
        """7: one temperature per line with its index; without PT100, NaN, a warning, no
        dialog."""
        for temp in (True, False):
            with self.subTest(pt100=temp):
                self.make(temp=temp)
                modal = []
                self.seq.point_done.connect(lambda *_: modal.append(
                    QApplication.activeModalWidget()))
                self.assertIsNone(self.tool.start(self.surf(witness=False)))
                self.wait(lambda: self.dones)
                meta, d = self.load_saved()
                self.assertEqual(list(d['temp_label']),
                                 ['start', 'line_end', 'line_end', 'line_end', 'end'])
                self.assertEqual(list(d['temp_line']), [-1, 0, 1, 2, 2])
                self.assertEqual(list(d['temp_point']), [-1, 2, 5, 8, 8])
                self.assertTrue(all(w is None for w in modal))
                if temp:
                    self.assertEqual(list(d['temp_T1']), [24.5] * 5)
                    self.assertEqual(len(self.arduinos), 1)
                else:
                    self.assertTrue(np.isnan(d['temp_T1']).all())
                    self.assertTrue(any('PT100 not available' in w for w in self.warnings))

    def test_estimate_with_witness_vs_elapsed(self):
        """8: line changes with their settle and the witness visits, real moves at 6.7 mm/s."""
        sim = SimSeDaq(SimParams(), reclen=8192, seed=0)
        t0 = time.perf_counter()
        for _ in range(20):
            tf.acquire(sim, 1)
        per_scan = (time.perf_counter() - t0) / 20
        self.acq_time = lambda: per_scan
        self.make(worker_speed=6.7)
        p = self.surf(start=-2, end=2, start2=-1, end2=1, settle_ms=60, line_settle_ms=300,
                      avg_n=3)
        estimate, text, _ = self.tool.estimate(p)
        self.assertIn('witness point × 4', text)
        no_wit, _, _ = self.tool.estimate(replace(p, witness=False))
        self.assertGreater(estimate - no_wit, 4 * 0.3)               # the visits are counted
        t0 = time.monotonic()
        self.assertIsNone(self.tool.start(p))
        self.wait(lambda: self.dones, 60000)
        elapsed = time.monotonic() - t0
        print(f'\n[estimate] surface with witness: estimated {estimate:.2f} s, '
              f'elapsed {elapsed:.2f} s')
        self.assertLess(abs(elapsed - estimate) / estimate, 0.35,
                        f'estimate {estimate:.2f} s, elapsed {elapsed:.2f} s')


class TestWaterReferences(ScanHarness):

    def params(self, **kw):
        base = dict(start=-1, end=1, step=1, settle_ms=0, line_settle_ms=0, avg_n=2,
                    references=True, witness=False, ref_gain1=20.0, ref_gain2=10.0, ref_avg_n=3)
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
            self.assertEqual(meta['conversion']['references'][which]['gain_db'],
                             {'ch1': 20.0, 'ch2': 10.0})
            self.assertEqual(float(d[f'ref_{which}_T1']), 24.5)
        self.assertEqual(list(d['temp_label']), ['start', 'ref_initial', 'ref_final', 'end'])
        self.assertEqual(meta['scan']['manual_axis_order'], ['Z', 'X'])
        drift = meta['scan']['reference_drift']                # compared, shown and saved
        self.assertEqual(drift['channel'], 'ch1')                   # transmission only
        self.assertNotIn('ch2', drift)
        for key in ('ch1', 'exceeds', 'tol_db', 'tol_ns'):          # (3 averages at low gains:
            self.assertIn(key, drift)                               #  values are noise here;
                                                                    #  TestDriftOnScreen checks them)
        self.assertTrue(any('Reference drift (Ch1' in st for st in self.statuses))
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
        self.assertEqual(int(d['point_valid'].sum()), 3)
        self.assertIn('ref_final_ch1', d)
        self.assertFalse(meta['scan']['completed'])

    def test_repeat_with_new_gains_and_approve_what_is_saved(self):
        """Repeat can change the reference gains; what is shown is the averaged signal saved."""
        self.make()
        self.assertIsNone(self.tool.start(self.params(ref_avg_n=5)))
        self.take_out()
        self.assertEqual(self.holds, [])                       # live view while moving out
        self.tool.continue_reference()
        self.assertEqual(self.holds, [True])                   # held while up for approval
        self.sim.gain_log.clear()
        self.assertIsNone(self.tool.repeat_reference(30.0, 25.0))   # "the gain was wrong"
        self.assertEqual(self.sim.gain_log, [('G1', 30.0), ('G2', 25.0)])
        shown = self.tool._plot.shown_reference
        self.tool.accept_reference()
        self.assertEqual(self.holds, [True, False])            # live again after OK
        self.assertEqual((self.sim.gain1, self.sim.gain2), self.scan_gains)
        self.wait(lambda: self.tool.state == 'ref_review')     # final: with the new gains too
        self.assertEqual(self.sim.gain_log[-2:], [('G1', 30.0), ('G2', 25.0)])
        self.tool.accept_reference()
        self.wait(lambda: self.dones)
        meta, d = self.load_saved()
        np.testing.assert_allclose(d['ref_initial_gains'], [30.0, 25.0])
        self.assertEqual(meta['conversion']['references']['initial']['gain_db'],
                         {'ch1': 30.0, 'ch2': 25.0})
        # bit-identical: the approved A-scan is the saved, averaged one (5 captures)
        np.testing.assert_array_equal(d['ref_initial_ch1'], shown[0])
        np.testing.assert_array_equal(d['ref_initial_ch2'], shown[1])
        self.assertEqual(int(d['ref_initial_avg_n']), 5)

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


class TestScanDebugDump(ScanHarness):

    def test_measurement_parameters_in_meta(self):
        """Settle, averages, both gains and the start temperature in meta_json."""
        for temp in (True, False):
            with self.subTest(pt100=temp):
                self.make(temp=temp)
                self.assertIsNone(self.tool.start(ScanParams(start=-1, end=1, step=1, settle_ms=3,
                                                             avg_n=2, debug_dump=True)))
                self.wait(lambda: self.dones)
                meta = json.loads(str(np.load(self.tool.last_dump_path)['meta_json']))
                self.assertEqual((meta['settle_ms'], meta['avg_n']), (3, 2))
                self.assertEqual((meta['gain_ch1_db'], meta['gain_ch2_db']), (65.0, 35.0))
                if temp:
                    self.assertEqual((meta['temperature']['T1'], meta['temperature']['T2']),
                                     (24.5, 24.7))
                else:
                    self.assertIsNone(meta['temperature'])


class TestDriftOnScreen(ScanHarness):

    def test_drift_warning_when_water_changes(self):
        """The final reference after the water got 2 m/s slower: warned and shown."""
        self.make()
        drifts = []
        self.tool.drift.connect(drifts.append)
        self.assertIsNone(self.tool.start(ScanParams(
            start=-1, end=1, step=1, settle_ms=0, line_settle_ms=0, avg_n=2, references=True,
            ref_gain1=65.0, ref_gain2=35.0, ref_avg_n=10, drift_tol_db=0.5, drift_tol_ns=20.0)))
        self.panel.manual_move('X', 90.0)
        self.tool.continue_reference()
        self.tool.accept_reference()
        self.wait(lambda: self.tool.state == 'ref_review')
        self.sim.params.c_w -= 2.0
        self.tool.repeat_reference()                     # the final one, in the slower water
        self.tool.accept_reference()
        self.wait(lambda: self.dones)
        self.assertEqual(len(drifts), 1)
        self.assertIn('ch1 ToF', drifts[0]['exceeds'])
        self.assertGreater(drifts[0]['ch1']['d_tof_ns'], 20.0)
        self.assertTrue(any('Drift above the limits' in w for w in self.warnings))
        self.assertIn('Reference drift (Ch1', self.statuses[-1])
        meta, _ = self.load_saved()
        self.assertIn('ch1 ToF', meta['scan']['reference_drift']['exceeds'])


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


class TestSurfacePrepared(unittest.TestCase):
    """«Surface» only prepares phase 6: plan, paths and estimate; no acquisition yet."""

    coords = {'X': 50.0, 'Y': 50.0, 'Z': 25.0, 'R': 0.0}

    def plan(self, **kw):
        base = dict(axis_role='lateral', start=-1, end=1, step=1, surface=True, start2=-1,
                    end2=1, step2=1, witness=False)
        base.update(kw)
        return ScanPlan(ScanParams(**base), self.coords, 'X', 'Y', {'X': LIMIT, 'Z': LIMIT})

    def test_zigzag_and_same_direction(self):
        zig = self.plan(path='zigzag')
        self.assertEqual(zig.axis2, 'Z')
        self.assertEqual([y for y, _ in zig.lines], [24.0, 25.0, 26.0])
        self.assertEqual([xs for _, xs in zig.lines],
                         [[49.0, 50.0, 51.0], [51.0, 50.0, 49.0], [49.0, 50.0, 51.0]])
        same = self.plan(path='same')
        self.assertTrue(all(xs == [49.0, 50.0, 51.0] for _, xs in same.lines))
        self.assertEqual(same.n_points, 9)
        self.assertEqual(same.all_positions()[3], {'Z': 25.0, 'X': 49.0})
        z_lines = self.plan(axis_role='z')
        self.assertEqual((z_lines.axis, z_lines.axis2), ('Z', 'X'))

    def test_a_line_is_one_line(self):
        line = self.plan(surface=False)
        self.assertEqual(line.lines, [(None, [49.0, 50.0, 51.0])])
        self.assertEqual(line.all_positions(), line.positions())

    def test_estimate_counts_every_line(self):
        line, surf = self.plan(surface=False), self.plan(path='same')
        self.assertGreater(estimate_scan_s(surf, 0.01), 2.9 * estimate_scan_s(line, 0.01))


class TestScanGroup(ScanHarness):

    def test_surface_checkbox_starts_a_surface(self):
        self.make()
        g = ScanGroup(self.tool, self.seq)
        self.assertEqual(g._cmb_path.currentData(), 'zigzag')           # the default path
        self.assertEqual(g.params().line_settle_ms, 1000)
        self.assertTrue(g.params().witness)
        self.assertEqual((g.params().witness_mode, g.params().witness_every), ('first', 1))
        self.assertFalse(g._spin_start2.isEnabled())
        self.assertFalse(g._cmb_path.isEnabled())
        g._chk_surface.setChecked(True)
        self.assertTrue(g._spin_start2.isEnabled() and g._cmb_path.isEnabled())
        self.assertEqual(g._lbl_axis2.text(), 'Z')
        g._cmb_axis.setCurrentIndex(1)
        self.assertEqual(g._lbl_axis2.text(), 'Lateral')
        p = g.params()
        self.assertTrue(p.surface)
        self.assertIn('lines along', g._lbl_estimate.text())
        self.assertIn('witness point ×', g._lbl_estimate.text())
        g._spin_start.setValue(-1.0)
        g._spin_end.setValue(1.0)
        g._spin_step.setValue(1.0)
        g._spin_start2.setValue(-1.0)
        g._spin_end2.setValue(1.0)
        g._spin_step2.setValue(1.0)
        self.assertIsNone(self.tool.start(replace(g.params(), settle_ms=0, line_settle_ms=0,
                                                  avg_n=1)))
        self.assertEqual(self.tool.state, 'scan')
        self.tool.stop()
        self.wait(lambda: self.tool.state in ('stopped', 'idle'))
        if self.tool.state == 'stopped':
            self.tool.discard()

    def test_ref_gain_ch2_prefilled_from_acquisition(self):
        self.make()
        g = ScanGroup(self.tool, self.seq)
        self.assertEqual(g._spin_rg2.value(), 35.0)              # Acquisition gain of Ch2
        self.assertIn('opposite transducer', g._lbl_rg2_note.text())
        self.assertIn('saturate', g._lbl_rg2_note.text())
        g._spin_rg2.setValue(12.0)                              # the user's choice stays
        self.scan_gains = (65.0, 40.0)
        g._chk_refs.setChecked(True)
        self.assertEqual(g._spin_rg2.value(), 12.0)
        g2 = ScanGroup(self.tool, self.seq)
        self.assertEqual(g2._spin_rg2.value(), 40.0)

    def test_thickness_quality_name_and_tooltip(self):
        from PyQt5.QtCore import Qt
        self.make()
        g = ScanGroup(self.tool, self.seq)
        i = g._cmb_mag.findData('thickness_corr')
        self.assertEqual(g._cmb_mag.itemText(i), 'Thickness quality (r)')
        tip = g._cmb_mag.itemData(i, Qt.ToolTipRole)
        for words in ('correlation coefficient between echoes 1 and 2', 'no units',
                      'from 0 to 1', 'trust'):
            self.assertIn(words, tip.lower() if words.islower() else tip)
        self.assertEqual(g.params().witness_jump_floor_um, 4.0)

    def test_defaults_estimate_and_buttons(self):
        self.make()
        g = ScanGroup(self.tool, self.seq)
        p = g.params()
        self.assertEqual((p.settle_ms, p.avg_n), (100, 20))          # not the focus ones
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


class TestScannerSubTabs(unittest.TestCase):
    """Spec 4: three sub-tabs (movement, calibration, scans) under a header with the
    position, the STOP and the state."""

    def test_layout(self):
        sys.path.insert(0, os.path.join(_HERE, '..'))
        from scanner_panel import ScannerPanel
        from PyQt5.QtWidgets import QLabel
        panel = ScannerPanel(use_sim=True)
        try:
            self.assertEqual(panel._tabs.count(), 1)              # standalone: no empty tab
            panel.add_tool_widget(QLabel('scan'), tab='scans')      # added out of order…
            panel.add_tool_widget(QLabel('focus'), tab='calibration')
            panel.add_tool_widget(QLabel('sim'))
            self.assertEqual([panel._tabs.tabText(i) for i in range(panel._tabs.count())],
                             ['Motion', 'Calibration', 'Scans'])    # …shown in order
            self.assertEqual(panel._tabs.currentIndex(), 0)         # movement first
            for widget in (panel._btn_stop, panel._lbl_state, panel._lbl_pos['beam']):
                w = widget
                while w is not None:                                # header: outside all tabs
                    self.assertIsNot(w, panel._tabs)
                    w = w.parentWidget()
            for i, name in enumerate(('motion', 'calibration', 'scans')):
                panel.show_tab(name)
                self.assertEqual(panel._tabs.currentIndex(), i)
                self.assertTrue(panel._btn_stop.isVisibleTo(panel))
            with self.assertRaises(ValueError):
                panel.add_tool_widget(QLabel('x'), tab='other')
        finally:
            panel.close()
            if hasattr(panel, 'shutdown'):
                panel.shutdown()


if __name__ == '__main__':
    unittest.main()
