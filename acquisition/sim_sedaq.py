# -*- coding: utf-8 -*-
"""
sim_sedaq.py — synthetic SeDaq digitizer for developing without hardware.
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See task_scanner_phase3.md section 1 and scanner_tab_spec.md sections 2-3.

SimSeDaq has the interface ecos_gui.py uses from tools/SeDaq.py (GetAScan,
SetRecLen, SetGain1/2, DataADC1/2, RecLen, UpdateGenCode, SetExtVoltage,
SetRelay, Close) and generates echoes from a known physical model, so the
scanner tools (focus, later flatness) can be checked against a ground truth.

Model
-----
The host injects the scanner position after every move (set_scanner_state).

Pulse-echo channel (PE_CHANNEL = Ch2, as everywhere in ecos_gui.py):
    d        = F + s·(x_beam − x_focus) + tan(θ_lat)·(lat − lat0) + tan(θ_z)·(z − z0)
               s = +1 with PE side 'origin' (moving + takes the face away),
               s = −1 with PE side 'max'.  F is the focal distance, so the
               front face sits exactly at the focus when x_beam = x_focus
               (at lat0, z0).
    t_front  = 2·d / c_w
    A_front  = A0·exp(−(d − F)² / (2σ²))   (= exp(−(x_beam − x_focus)²/(2σ²))
               at lat0, z0; with tilt the focus position moves accordingly,
               see expected_focus())
    plus, to make "measure only inside Smin–Smax" matter: the excitation
    main bang near t = 0 (saturating), the back-wall echo and the first
    water-path reverberation (at 2·t_front).

Through-transmission channel (Ch1): a pulse crossing the sample, with its
own time of flight and an amplitude that depends on lateral and Z (an
inclusion plus a mild lateral ripple), so a scan gives a structured map.

Waveform: sine at f0 under a Gaussian envelope with fractional -6 dB bandwidth
`bw`. Noise: Gaussian, SNR (dB) relative to the in-focus front echo A0.
Gain: SetGain1/2 scale each channel by 10^((g − g_ref)/20) (noise included:
it is receiver noise) and the 10-bit quantizer saturates at full scale. The
ADC adds its own noise floor (adc_noise_lsb) whatever the gain, as a real
one does: with a very low gain a channel is noise, never a constant record
(ecos_gui._acquire_avg rejects all-zero captures as a dead digitizer).

Amplitudes are in the units of ecos_gui._raw_to_float: full scale is ±0.5.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

QUANT = 1024          # 10-bit ADC, as hard-coded in ecos_gui (_update_plots, _acquire_avg)
PE_CHANNEL = 2        # ecos_gui.py: s_PE is Ch2, s_TT / s_W are Ch1
TT_CHANNEL = 1


@dataclass
class SimParams:
    """Every parameter of the synthetic model. Lengths in mm, angles in degrees."""
    # -- focus (PE, front face) ------------------------------------------------
    x_focus: float = 50.0        # beam-axis position (session mm) with the face at the focus
    sigma: float = 2.0           # axial width of the focal zone (−6 dB full width ≈ 2.35σ)
    focal_distance: float = 20.0 # F: PE transducer to face distance at the focus
    # -- flatness (tilt of the front face) --------------------------------------
    theta_lat: float = 0.0
    theta_z: float = 0.0
    lat0: float = 50.0           # tilt reference point (session mm)
    z0: float = 25.0
    # -- medium / sample --------------------------------------------------------
    c_w: float = 1497.0          # m/s, water at ~25 °C
    c_sample: float = 1540.0     # m/s, PVA
    thickness: float = 10.0
    tt_separation: float = 60.0  # PE-to-TT transducer distance (through-transmission path)
    # -- pulse ------------------------------------------------------------------
    f0: float = 5e6              # Hz
    bw: float = 0.6              # fractional −6 dB bandwidth
    fs: float = 100e6            # Hz, acquisition sampling rate
    # -- amplitudes (full scale = 0.5) at the reference gains --------------------
    A0: float = 0.2              # front echo at the focus
    back_ratio: float = 0.4      # back-wall echo / front echo
    reverb_ratio: float = 0.15   # first water-path reverberation / front echo
    bang_amp: float = 0.6        # excitation main bang (saturates on purpose)
    tt_amp: float = 0.15         # through-transmission pulse
    snr_db: float = 30.0         # A0 over the noise standard deviation
    adc_noise_lsb: float = 0.7   # ADC noise floor (std, LSB), independent of the gain
    gain_ref_ch1: float = 65.0   # gains at which the amplitudes above hold
    gain_ref_ch2: float = 35.0
    # -- through-transmission map structure --------------------------------------
    incl_lat: float = 50.0       # inclusion centre (session mm)
    incl_z: float = 25.0
    incl_radius: float = 4.0
    incl_contrast: float = 0.6   # fractional amplitude loss at the inclusion centre


class SimSeDaq:
    """Drop-in replacement for tools/SeDaq.SeDaqDLL, driven by SimParams."""

    def __init__(self, params: SimParams | None = None, reclen: int = 16384, seed=None):
        self.params = params if params is not None else SimParams()
        self.RecLen = int(reclen)
        self.gain1 = self.params.gain_ref_ch1
        self.gain2 = self.params.gain_ref_ch2
        self._rng = np.random.default_rng(seed)
        # Scanner state, injected by the host (set_scanner_state). With no
        # scanner connected the sample sits at the reference point (in focus).
        self._coords = None
        self._beam_axis = 'Y'
        self._pe_side = 'origin'
        mid = np.full(self.RecLen, QUANT // 2, dtype=np.int32)
        self.DataADC1 = mid.copy()
        self.DataADC2 = mid.copy()

    # -- SeDaq interface -------------------------------------------------------
    def GetAScan(self):
        ch1, ch2 = self.clean_signals()
        p = self.params
        noise_sd = p.A0 / (10.0 ** (p.snr_db / 20.0))
        n = self.RecLen
        adc_sd = p.adc_noise_lsb / QUANT
        ch1 = ch1 + self._rng.normal(0.0, noise_sd, n) * self._gain_scale(1)
        ch2 = ch2 + self._rng.normal(0.0, noise_sd, n) * self._gain_scale(2)
        ch1 = ch1 + self._rng.normal(0.0, adc_sd, n)
        ch2 = ch2 + self._rng.normal(0.0, adc_sd, n)
        self.DataADC1 = self._quantize(ch1)
        self.DataADC2 = self._quantize(ch2)

    def SetRecLen(self, n):
        self.RecLen = int(n)
        mid = np.full(self.RecLen, QUANT // 2, dtype=np.int32)
        self.DataADC1 = mid.copy()
        self.DataADC2 = mid.copy()

    def SetGain1(self, g):
        self.gain1 = float(g)

    def SetGain2(self, g):
        self.gain2 = float(g)

    def UpdateGenCode(self, gencode):
        pass

    def SetExtVoltage(self, v):
        pass

    def SetRelay(self, m):
        pass

    def Close(self):
        pass

    # -- scanner state (injected by the host after every move) -----------------
    def set_scanner_state(self, coords, beam_axis='Y', pe_side='origin'):
        """coords: {'X','Y','Z','R': value} in session units, or None (no scanner)."""
        self._coords = None if coords is None else dict(coords)
        self._beam_axis = 'X' if beam_axis == 'X' else 'Y'
        self._pe_side = 'max' if pe_side == 'max' else 'origin'

    def roles(self):
        """(x_beam, lat, z) of the current position; the reference point without a scanner."""
        p = self.params
        if self._coords is None:
            return p.x_focus, p.lat0, p.z0
        lat_axis = 'X' if self._beam_axis == 'Y' else 'Y'
        return (float(self._coords.get(self._beam_axis, 0.0)),
                float(self._coords.get(lat_axis, 0.0)),
                float(self._coords.get('Z', 0.0)))

    # -- ground truth ------------------------------------------------------------
    def _sign(self):
        return 1.0 if self._pe_side == 'origin' else -1.0

    def _tilt_mm(self, lat, z):
        p = self.params
        return (np.tan(np.radians(p.theta_lat)) * (lat - p.lat0)
                + np.tan(np.radians(p.theta_z)) * (z - p.z0))

    def face_distance(self, x_beam, lat, z):
        """PE transducer to front face distance [mm]."""
        p = self.params
        return p.focal_distance + self._sign() * (x_beam - p.x_focus) + self._tilt_mm(lat, z)

    def expected_focus(self, lat=None, z=None):
        """Beam-axis position that puts the face at the focus, at (lat, z)."""
        p = self.params
        lat = p.lat0 if lat is None else lat
        z = p.z0 if z is None else z
        return p.x_focus - self._sign() * self._tilt_mm(lat, z)

    def front_tof(self, x_beam, lat, z):
        """Front-face echo time of flight [s]."""
        return 2.0 * self.face_distance(x_beam, lat, z) * 1e-3 / self.params.c_w

    # -- signal generation -------------------------------------------------------
    def clean_signals(self):
        """Noise-free, unquantized (ch1, ch2) at the current position and gains."""
        p = self.params
        t = np.arange(self.RecLen) / p.fs
        x_beam, lat, z = self.roles()

        # PE (Ch2): main bang, front face, back wall, reverberation.
        d = self.face_distance(x_beam, lat, z)
        a_front = p.A0 * np.exp(-((d - p.focal_distance) ** 2) / (2.0 * p.sigma ** 2))
        t_front = 2.0 * d * 1e-3 / p.c_w
        t_back = t_front + 2.0 * p.thickness * 1e-3 / p.c_sample
        pe = self._pulse(t, 0.3e-6, p.bang_amp)
        if d > 0:
            pe += self._pulse(t, t_front, a_front)
            pe += self._pulse(t, t_back, -p.back_ratio * a_front)
            pe += self._pulse(t, 2.0 * t_front, p.reverb_ratio * a_front)

        # TT (Ch1): through the sample, amplitude mapped over (lat, z).
        t_tt = ((p.tt_separation - p.thickness) * 1e-3 / p.c_w
                + p.thickness * 1e-3 / p.c_sample)
        r2 = (lat - p.incl_lat) ** 2 + (z - p.incl_z) ** 2
        a_tt = p.tt_amp * (1.0 - p.incl_contrast * np.exp(-r2 / (2.0 * p.incl_radius ** 2)))
        a_tt *= 0.85 + 0.15 * np.cos(2.0 * np.pi * lat / 15.0)
        tt = self._pulse(t, t_tt, a_tt)

        return tt * self._gain_scale(1), pe * self._gain_scale(2)

    def _pulse(self, t, t0, amp):
        """Sine at f0 under a Gaussian envelope of fractional −6 dB bandwidth bw."""
        p = self.params
        sigma_f = p.bw * p.f0 / (2.0 * np.sqrt(2.0 * np.log(2.0)))
        tau = 1.0 / (2.0 * np.pi * sigma_f)
        out = np.zeros_like(t)
        # Only evaluate where the envelope is not negligible (±6 τ).
        i0 = max(0, int((t0 - 6 * tau) * p.fs))
        i1 = min(len(t), int((t0 + 6 * tau) * p.fs) + 2)
        if i1 > i0:
            tt = t[i0:i1] - t0
            out[i0:i1] = amp * np.exp(-tt ** 2 / (2.0 * tau ** 2)) * np.sin(2.0 * np.pi * p.f0 * tt)
        return out

    def _gain_scale(self, channel):
        p = self.params
        g, ref = (self.gain1, p.gain_ref_ch1) if channel == 1 else (self.gain2, p.gain_ref_ch2)
        return 10.0 ** ((g - ref) / 20.0)

    @staticmethod
    def _quantize(sig):
        raw = np.round(sig * QUANT + QUANT / 2.0)
        return np.clip(raw, 0, QUANT - 1).astype(np.int32)


# ===========================================================================
#  Debug panel (simulator mode only): edit SimParams live
# ===========================================================================
# (field, label, unit, min, max, decimals, step) per field shown in the panel.
_PANEL_FIELDS = (
    ('x_focus', 'x_focus', 'mm', -1000.0, 1000.0, 2, 0.5),
    ('sigma', 'σ focal zone', 'mm', 0.05, 50.0, 2, 0.1),
    ('focal_distance', 'Focal distance F', 'mm', 1.0, 200.0, 1, 1.0),
    ('theta_lat', 'θ lateral', '°', -45.0, 45.0, 2, 0.1),
    ('theta_z', 'θ Z', '°', -45.0, 45.0, 2, 0.1),
    ('lat0', 'lat₀', 'mm', -1000.0, 1000.0, 1, 1.0),
    ('z0', 'z₀', 'mm', -1000.0, 1000.0, 1, 1.0),
    ('c_w', 'c_w', 'm/s', 1300.0, 1700.0, 1, 1.0),
    ('thickness', 'Thickness', 'mm', 0.1, 100.0, 2, 0.5),
    ('f0', 'f₀', 'MHz', 0.5, 50.0, 2, 0.5),
    ('A0', 'A₀ (FS = 0.5)', '', 0.0, 2.0, 3, 0.01),
    ('snr_db', 'SNR', 'dB', -20.0, 100.0, 1, 1.0),
)


def make_params_widget(sedaq: SimSeDaq, parent=None):
    """QGroupBox editing sedaq.params in place; every change applies at once."""
    from PyQt5.QtWidgets import QDoubleSpinBox, QFormLayout, QGroupBox

    box = QGroupBox('Debug: synthetic SeDaq model (simulator only)', parent)
    form = QFormLayout(box)
    for name, label, unit, lo, hi, dec, step in _PANEL_FIELDS:
        scale = 1e6 if name == 'f0' else 1.0
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setDecimals(dec)
        spin.setSingleStep(step)
        if unit:
            spin.setSuffix(' ' + unit)
        spin.setValue(getattr(sedaq.params, name) / scale)

        def _apply(value, name=name, scale=scale):
            setattr(sedaq.params, name, value * scale)
        spin.valueChanged.connect(_apply)
        form.addRow(label + ':', spin)
    return box
