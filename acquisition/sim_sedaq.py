# -*- coding: utf-8 -*-
"""
sim_sedaq.py — synthetic SeDaq digitizer for developing without hardware.
ECOS project - Universidad Miguel Hernandez - Dpto. Ingenieria de Comunicaciones

See task_scanner_phase3.md section 1 and scanner_tab_spec.md sections 2-3.

SimSeDaq has the interface ecos_gui.py uses from tools/SeDaq.py (GetAScan,
SetRecLen, SetGain1/2, DataADC1/2, RecLen, UpdateGenCode, SetExtVoltage,
SetRelay, Close) and generates echoes from a known physical model, so the
scanner tools (focus, flatness) can be checked against a ground truth.

Model
-----
The host injects the scanner position after every move (set_scanner_state).

Pulse-echo channel (PE_CHANNEL = Ch2, as everywhere in ecos_gui.py):
    d        = F + s·(x_beam − x_focus) + tan(θ_lat)·(lat − lat0) + tan(θ_z)·(z − z0)
               + shift(t)   (the sample's own movement: drift and jumps, phase 6)
               s = +1 with PE side 'origin' (moving + takes the face away),
               s = −1 with PE side 'max'.  F is the focal distance, so the
               front face sits exactly at the focus when x_beam = x_focus
               (at lat0, z0).
    Tilt sign convention, the one the flatness tool measures (phase 4):
    θ > 0 means the face gets FARTHER from the PE transducer as the lateral
    (resp. Z) counter grows, so dt/dlat = 2·tan(θ_lat)/c_w and
    θ = atan(c_w·Δt / (2·Δx)) returns θ_lat and θ_z exactly. Z grows downwards
    (spec section 1). It does not depend on the PE side: it is the face as the
    PE transducer sees it.
    t_front  = 2·d / c_w
    A_front  = A0·exp(−(d − F)² / (2σ²))   (= exp(−(x_beam − x_focus)²/(2σ²))
               at lat0, z0; with tilt the focus position moves accordingly,
               see expected_focus())
    plus, to make "measure only inside Smin–Smax" matter: the excitation
    main bang near t = 0 (saturating), the back-wall echo and the first
    water-path reverberation (at 2·t_front).
    Face extent: the sample face covers |lat − lat0| ≤ face_half_lat and
    |z − z0| ≤ face_half_z. Beyond, the echoes fade out over ~beam_radius (the
    beam leaves the face), which is how "the face can end" along a flatness line.
    Back-wall echo: t_back = t_front + 2·h/c_sample, with its own focal gain,
    A_back = back_ratio·A0·exp(−(d_back − F)² / (2σ²)), where
    d_back = d + h·c_sample/c_w is the water-equivalent (paraxial) distance of
    the back face. So each face peaks at its own beam position, as with a real
    focused transducer: with a thin sample and back_ratio > 1 the back echo is
    inside the window and larger than the front one, and the maximum of the
    window jumps between them along a sweep (SimParams.thin_sample()).

Through-transmission channel (Ch1): a pulse crossing the sample, with its
own time of flight and an amplitude that depends on lateral and Z (an
inclusion plus a mild lateral ripple), so a scan gives a structured map.

Waveform: carrier at f0 under a Gaussian envelope with fractional -6 dB
bandwidth `bw`. The carrier phase (carrier_phase, degrees) sets its shape:
0° is a sine (odd: inverting it leaves its signed maximum unchanged), 90° a
cosine with a dominant central half-cycle, like a real transducer pulse.
Polarity: every PE echo can be inverted on its own (invert_front,
invert_back, invert_reverb), relative to its default sign (front and
reverberation +, back wall −). A measure that takes the signed maximum of the
signal instead of the envelope gives a different value for an inverted echo;
SimParams.inverted_front() is that case. Noise: Gaussian, SNR (dB) relative to the in-focus front echo A0.
Gain: SetGain1/2 scale each channel by 10^((g − g_ref)/20) (noise included:
it is receiver noise) and the 10-bit quantizer saturates at full scale. The
ADC adds its own noise floor (adc_noise_lsb) whatever the gain, as a real
one does: with a very low gain a channel is noise, never a constant record
(ecos_gui._acquire_avg rejects all-zero captures as a dead digitizer).

Amplitudes are in the units of ecos_gui._raw_to_float: full scale is ±0.5.
"""
from __future__ import annotations

import time
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
    carrier_phase: float = 0.0   # degrees: 0 sine (odd pulse), 90 cosine (dominant central lobe)
    fs: float = 100e6            # Hz, acquisition sampling rate
    # -- amplitudes (full scale = 0.5) at the reference gains --------------------
    A0: float = 0.2              # front echo at the focus
    back_ratio: float = 0.4      # back-wall echo / front echo, each at its own focus
    reverb_ratio: float = 0.15   # first water-path reverberation / front echo
    # -- polarity of each PE echo, relative to its default sign ------------------
    invert_front: bool = False   # default +
    invert_back: bool = False    # default − (back wall)
    invert_reverb: bool = False  # default +
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
    # -- sample face extent (flatness lines can run off it) -----------------------
    face_half_lat: float = 1000.0  # half width of the face along lateral, around lat0
    face_half_z: float = 1000.0    # half height along Z, around z0
    beam_radius: float = 1.0       # the echo fades over ~this when the beam leaves the face
    # -- movement of the sample itself (phase 6, witness point) ------------------
    # The whole sample moves along the beam (both faces together, thickness
    # unchanged), + = away from the PE transducer: a steady rate since the
    # simulator was created (or restart_drift()), plus a step that can be changed
    # at any time (a jump). Measured on PVA on 05/10: −4.34 µm/min, in jerks.
    drift_um_per_min: float = 0.0
    face_offset_um: float = 0.0

    @classmethod
    def thin_sample(cls, **overrides):
        """
        Thin sample whose back-face echo is inside any window that holds the
        front one (2·h/c_sample ≈ 1.95 µs later) and larger than it (e.g. a
        sample resting on a strong reflector): the case where the global
        maximum of Smin–Smax jumps from the front face to the back face.
        The back face peaks h·c_sample/c_w ≈ 1.5 mm before x_focus (PE side
        'origin'), well beyond a fine step.
        """
        values = dict(thickness=1.5, back_ratio=2.5)
        values.update(overrides)
        return cls(**values)

    @classmethod
    def inverted_front(cls, **overrides):
        """
        Front-face echo with inverted polarity and a cosine carrier (dominant
        central half-cycle, now negative): its positive excursion is only the
        side lobes, so a signed maximum under-reads it and lands half a period
        off the envelope peak, while the Hilbert envelope is unchanged.
        """
        values = dict(invert_front=True, carrier_phase=90.0)
        values.update(overrides)
        return cls(**values)


class SimSeDaq:
    """Drop-in replacement for tools/SeDaq.SeDaqDLL, driven by SimParams."""

    def __init__(self, params: SimParams | None = None, reclen: int = 16384, seed=None):
        self.params = params if params is not None else SimParams()
        self.RecLen = int(reclen)
        self.gain1 = self.params.gain_ref_ch1
        self.gain2 = self.params.gain_ref_ch2
        self._rng = np.random.default_rng(seed)
        self.clock = time.monotonic          # replaceable (tests)
        self._drift_t0 = self.clock()
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

    def restart_drift(self):
        """The steady drift of the sample counts from now."""
        self._drift_t0 = self.clock()

    def sample_shift_mm(self):
        """Movement of the sample along the beam now [mm], + away from the PE transducer."""
        p = self.params
        minutes = (self.clock() - self._drift_t0) / 60.0
        return (p.face_offset_um + p.drift_um_per_min * minutes) * 1e-3

    def face_distance(self, x_beam, lat, z):
        """PE transducer to front face distance [mm] (with the movement of the sample)."""
        p = self.params
        return (p.focal_distance + self._sign() * (x_beam - p.x_focus) + self._tilt_mm(lat, z)
                + self.sample_shift_mm())

    def expected_focus(self, lat=None, z=None):
        """Beam-axis position that puts the face at the focus, at (lat, z)."""
        p = self.params
        lat = p.lat0 if lat is None else lat
        z = p.z0 if z is None else z
        return p.x_focus - self._sign() * self._tilt_mm(lat, z)

    def front_tof(self, x_beam, lat, z):
        """Front-face echo time of flight [s]."""
        return 2.0 * self.face_distance(x_beam, lat, z) * 1e-3 / self.params.c_w

    def back_tof(self, x_beam, lat, z):
        """Back-face echo time of flight [s]."""
        p = self.params
        return self.front_tof(x_beam, lat, z) + 2.0 * p.thickness * 1e-3 / p.c_sample

    def expected_back_focus(self, lat=None, z=None):
        """Beam-axis position where the back-face echo peaks (the wrong answer)."""
        p = self.params
        return self.expected_focus(lat, z) - self._sign() * p.thickness * p.c_sample / p.c_w

    # -- signal generation -------------------------------------------------------
    def face_coverage(self, lat, z):
        """Fraction of the beam on the sample face (1 inside, → 0 beyond its edges)."""
        p = self.params
        w = max(p.beam_radius, 1e-6) / 4.0

        def edge(u, half):
            return 1.0 / (1.0 + np.exp(np.clip((abs(u) - half) / w, -50.0, 50.0)))
        return float(edge(lat - p.lat0, p.face_half_lat) * edge(z - p.z0, p.face_half_z))

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
        d_back = d + p.thickness * p.c_sample / p.c_w
        a_back = p.back_ratio * p.A0 * np.exp(-((d_back - p.focal_distance) ** 2)
                                              / (2.0 * p.sigma ** 2))
        on_face = self.face_coverage(lat, z)
        a_front *= on_face
        a_back *= on_face
        pe = self._pulse(t, 0.3e-6, p.bang_amp)
        if d > 0:
            s_front = -1.0 if p.invert_front else 1.0
            s_back = 1.0 if p.invert_back else -1.0
            s_reverb = -1.0 if p.invert_reverb else 1.0
            pe += self._pulse(t, t_front, s_front * a_front)
            pe += self._pulse(t, t_back, s_back * a_back)
            pe += self._pulse(t, 2.0 * t_front, s_reverb * p.reverb_ratio * a_front)

        # TT (Ch1): through the sample, amplitude mapped over (lat, z).
        t_tt = ((p.tt_separation - p.thickness) * 1e-3 / p.c_w
                + p.thickness * 1e-3 / p.c_sample)
        r2 = (lat - p.incl_lat) ** 2 + (z - p.incl_z) ** 2
        a_tt = p.tt_amp * (1.0 - p.incl_contrast * np.exp(-r2 / (2.0 * p.incl_radius ** 2)))
        a_tt *= 0.85 + 0.15 * np.cos(2.0 * np.pi * lat / 15.0)
        tt = self._pulse(t, t_tt, a_tt)

        return tt * self._gain_scale(1), pe * self._gain_scale(2)

    def _pulse(self, t, t0, amp):
        """Carrier at f0 (phase carrier_phase) under a Gaussian envelope of
        fractional −6 dB bandwidth bw. The sign of amp is the echo polarity."""
        p = self.params
        sigma_f = p.bw * p.f0 / (2.0 * np.sqrt(2.0 * np.log(2.0)))
        tau = 1.0 / (2.0 * np.pi * sigma_f)
        out = np.zeros_like(t)
        # Only evaluate where the envelope is not negligible (±6 τ).
        i0 = max(0, int((t0 - 6 * tau) * p.fs))
        i1 = min(len(t), int((t0 + 6 * tau) * p.fs) + 2)
        if i1 > i0:
            tt = t[i0:i1] - t0
            carrier = np.sin(2.0 * np.pi * p.f0 * tt + np.radians(p.carrier_phase))
            out[i0:i1] = amp * np.exp(-tt ** 2 / (2.0 * tau ** 2)) * carrier
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
    ('back_ratio', 'Back / front echo', '', 0.0, 10.0, 2, 0.1),
    ('carrier_phase', 'Carrier phase', '°', -180.0, 180.0, 0, 15.0),
    ('f0', 'f₀', 'MHz', 0.5, 50.0, 2, 0.5),
    ('A0', 'A₀ (FS = 0.5)', '', 0.0, 2.0, 3, 0.01),
    ('snr_db', 'SNR', 'dB', -20.0, 100.0, 1, 1.0),
    ('face_half_lat', 'Face half width (lat)', 'mm', 0.5, 1000.0, 1, 1.0),
    ('face_half_z', 'Face half height (Z)', 'mm', 0.5, 1000.0, 1, 1.0),
    ('drift_um_per_min', 'Sample drift', 'µm/min', -1000.0, 1000.0, 2, 1.0),
    ('face_offset_um', 'Sample offset (jump)', 'µm', -5000.0, 5000.0, 1, 5.0),
)


# (field, label) of the boolean fields shown as check boxes.
_PANEL_FLAGS = (
    ('invert_front', 'Invert front-face echo'),
    ('invert_back', 'Invert back-wall echo'),
    ('invert_reverb', 'Invert reverberation'),
)


def make_params_widget(sedaq: SimSeDaq, parent=None):
    """QGroupBox editing sedaq.params in place; every change applies at once."""
    from PyQt5.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox

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
    for name, label in _PANEL_FLAGS:
        chk = QCheckBox(label)
        chk.setChecked(bool(getattr(sedaq.params, name)))
        chk.toggled.connect(lambda on, name=name: setattr(sedaq.params, name, bool(on)))
        form.addRow(chk)
    return box
