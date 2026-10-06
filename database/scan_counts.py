# -*- coding: utf-8 -*-
"""
scan_counts.py — integer storage of averaged A-scans and its exact conversion.
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See task_scan_int16.md and scanner_tab_spec.md section 5.6.

The SeDaq delivers integer counts (0 .. 2**bits − 1). ECOS turns every capture
into a float as (raw − midpoint) / full_scale and removes its mean over the
whole record (ecos_gui._raw_to_float), then averages N captures. That average
is NOT an integer: averaging gives resolution below one count, which is real
information. What is stored instead is exact and integer:

    sum      = Σ over the N captures of (raw − midpoint)      per sample
    offset   = mean over the WHOLE record of sum / (full_scale · N)
    x        = sum / (full_scale · N) − offset                 (the ECOS float)

This is mathematically the same as averaging the mean-removed captures. The
offset is kept per point and channel because the record is stored only in the
Smin–Smax window, so it cannot be recomputed from the stored samples.

Exactness: counts_to_float is the one function that computes x, both when
measuring (ecos_gui._seq_acquire) and when reading a file (load_scan_raw_32):
same inputs, same float64 operations, elementwise, so the float read back is
bit-identical to the one used at measurement time.

dtype: |raw − midpoint| ≤ midpoint, so |sum| ≤ midpoint · N. int16 when that
fits (N ≤ 63 at 10 bits), int32 otherwise (e.g. water references with 100
averages). The number of averages is never limited by the format.

ADC resolution: SeDaqDLL exposes no way to read it (uint16 buffers, no query
function), so ECOS assumes 10 bits (midpoint 512, full scale 1024), the value
hard-coded until now. It is a parameter and goes into the metadata of every scan.
"""
import numpy as np

ADC_BITS_DEFAULT = 10      # assumed: cannot be read from the SeDaq (see the docstring)


def quantizer(bits=ADC_BITS_DEFAULT):
    """(full_scale, midpoint) in counts for an ADC of `bits` bits."""
    full = 2 ** int(bits)
    return full, full // 2


# ---------------------------------------------------------------------------
#  Saturation: the ONE detection of ECOS (live indicator, and the 'saturated'
#  flag of focus, flatness, stability and scans), from 2026-10-06.
# ---------------------------------------------------------------------------
SATURATION_CRITERION = ('raw counts: at least one sample at the top of the quantizer '
                        '(code 0 or full_scale - 1) in ANY single capture, before any mean '
                        'is removed or captures averaged')


def top_mask(raw, bits=ADC_BITS_DEFAULT):
    """
    Samples of ONE capture at the top of the quantizer, code 0 or full_scale − 1:
    raw counts, before removing the mean or averaging, so it is certain (a sample
    there has clipped) and a clipped capture is never hidden by the average.
    Accumulate over the captures of an acquisition with |=.
    """
    full, _ = quantizer(bits)
    r = np.asarray(raw)
    return (r <= 0) | (r >= full - 1)


def count_at_top(mask, span=None):
    """
    Samples marked in `mask` (top_mask, accumulated over captures) within the sample
    range span = (lo, hi), end exclusive; the whole record when None. ECOS passes
    Smin–Smax everywhere (live indicator and measurement marks): what lies outside
    the window is neither measured nor saved, e.g. the main bang before Smin.
    """
    if mask is None:
        return 0
    m = np.asarray(mask, dtype=bool)
    if span is not None:
        lo, hi = max(0, int(span[0])), min(m.size, int(span[1]))
        m = m[lo:hi]
    return int(np.count_nonzero(m))


def sum_dtype(n_avg, bits=ADC_BITS_DEFAULT):
    """Smallest integer type holding Σ(raw − midpoint) over n_avg captures."""
    _, mid = quantizer(bits)
    bound = mid * int(n_avg)
    if bound <= np.iinfo(np.int16).max:
        return np.int16
    if bound <= np.iinfo(np.int32).max:
        return np.int32
    return np.int64


def counts_to_float(sum_centered, n_avg, bits=ADC_BITS_DEFAULT, offset=None):
    """
    ECOS float from the integer sum. offset None: computed as the mean of the
    given array (pass the WHOLE record) and returned; otherwise subtracted as
    given (a stored per-point offset). Returns (x, offset).
    """
    full, _ = quantizer(bits)
    x = np.asarray(sum_centered, dtype=np.float64) / float(full * int(n_avg))
    if offset is None:
        offset = float(np.mean(x))
    return x - offset, offset


def counts_to_float_rows(sums, n_avg, offsets, bits=ADC_BITS_DEFAULT):
    """Vectorised counts_to_float for (..., N_samples) sums and (...) offsets. Elementwise the
    same operations as counts_to_float, so the result is bit-identical point by point."""
    full, _ = quantizer(bits)
    x = np.asarray(sums, dtype=np.float64) / float(full * int(n_avg))
    return x - np.asarray(offsets, dtype=np.float64)[..., None]
