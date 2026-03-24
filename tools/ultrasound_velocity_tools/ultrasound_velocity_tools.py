# --------------------------------------------------------------
# Ultrasound Signal Processing Toolkit
# Enhanced versions of core functions for subsample TOF estimation
# Author: Alberto [annotated and structured for public release]
# Version: 1.0
# License: MIT
# --------------------------------------------------------------

import numpy as np
from scipy import signal

def pad_to_pow2(sig):
    """
    Zero-pad signal to the next power-of-2 length.
    """
    N = len(sig)
    next_pow2 = 2 ** int(np.ceil(np.log2(N)))
    padded = np.zeros(next_pow2)
    padded[:N] = sig
    return padded

def ShiftSubsampleByfft(MySignal, Delay):
    """
    Shifts a signal in time by a fractional number of samples using frequency-domain modulation.
    """
    N = MySignal.size
    freqs = np.fft.fftfreq(N)
    modulation = np.exp(1j * 2 * np.pi * freqs * Delay)
    shifted_fft = np.fft.fft(MySignal) * modulation
    return np.real(np.fft.ifft(shifted_fft))

def CosineInterpMax(MySignal, UseHilbEnv=False):
    """
    Subsample peak estimation using cosine interpolation.
    """
    if UseHilbEnv:
        MySignal = np.abs(signal.hilbert(MySignal))

    MaxLoc = np.argmax(np.abs(MySignal))
    N = MySignal.size
    A = MaxLoc - 1
    B = MaxLoc + 1

    if MaxLoc == 0:
        A = N - 1
    elif MaxLoc == N - 1:
        B = 0

    ratio = (MySignal[A] + MySignal[B]) / (2 * MySignal[MaxLoc])
    ratio = np.clip(ratio, -1.0, 1.0)
    alpha = np.arccos(ratio)
    beta = np.arctan((MySignal[A] - MySignal[B]) / (2 * MySignal[MaxLoc] * np.sin(alpha)))
    Px = beta / alpha

    DeltaToF = MaxLoc - Px
    if MaxLoc > N / 2:
        DeltaToF = -(N - DeltaToF)

    return DeltaToF

def CalcToFAscanCosine_XCRFFT(Data, Ref, UseHilbEnv=False):
    """
    Calculates TOF between Data and Ref using cross-correlation and cosine interpolation.
    """
    try:
        Data = pad_to_pow2(Data)
        Ref = pad_to_pow2(Ref)
        Xcor = np.real(np.fft.ifft(np.fft.fft(Data) * np.conj(np.fft.fft(Ref))))
        DeltaToF = CosineInterpMax(Xcor, UseHilbEnv=UseHilbEnv)
        AlignedData = ShiftSubsampleByfft(Data, DeltaToF)
        return DeltaToF, Xcor, AlignedData
    except Exception as ex:
        print(f"Error in CalcToFAscanCosine_XCRFFT: {ex}")
        raise

def LongVelocity_Thickness(PE_Ascan, TT_Ascan, WP_Ascan, Ref_PE, Fs, Cw, UseHilbEnv):
    """
    Computes longitudinal velocity and thickness from A-scans.
    """
    try:
        dt = 1 / Fs
        TOF_TW = -CalcToFAscanCosine_XCRFFT(TT_Ascan, WP_Ascan, UseHilbEnv=UseHilbEnv)[0]
        TOF_PE = np.zeros(2)
        ref_energy = np.mean(Ref_PE ** 2)
        TOF_PE[0] = CalcToFAscanCosine_XCRFFT(PE_Ascan, Ref_PE, UseHilbEnv=True)[0]
        shifted_ref = ShiftSubsampleByfft(Ref_PE, -TOF_PE[0])
        amp = np.mean(PE_Ascan * shifted_ref) / ref_energy
        stripped_signal = PE_Ascan - shifted_ref * amp
        TOF_PE[1] = CalcToFAscanCosine_XCRFFT(stripped_signal, Ref_PE, UseHilbEnv=True)[0]
        t_tw = TOF_TW * dt
        t_pe = np.abs(TOF_PE[1] - TOF_PE[0]) * dt
        Cl = Cw * (1 + (2 * t_tw / t_pe))
        L = (Cw / 2) * (2 * t_tw + t_pe)
        return Cl, L
    except Exception as ex:
        print(f"Error in LongVelocity_Thickness: {ex}")
        return None, None

def MyThick_Vel(PE_Ascan, TT_Ascan, TT45_Ascan, WP_Ascan, Ref_PE, Fs, Cw, Angle, UseHilbEnv):
    """
    Computes longitudinal and shear velocities and sample thickness from A-scans.
    """
    try:
        dt = 1 / Fs
        TOF_TW = -CalcToFAscanCosine_XCRFFT(TT_Ascan, WP_Ascan, UseHilbEnv=UseHilbEnv)[0]
        TOF_PE = np.zeros(2)
        ref_energy = np.mean(Ref_PE ** 2)
        TOF_PE[0] = CalcToFAscanCosine_XCRFFT(PE_Ascan, Ref_PE, UseHilbEnv=True)[0]
        shifted_ref = ShiftSubsampleByfft(Ref_PE, -TOF_PE[0])
        amp = np.mean(PE_Ascan * shifted_ref) / ref_energy
        stripped_signal = PE_Ascan - shifted_ref * amp
        TOF_PE[1] = CalcToFAscanCosine_XCRFFT(stripped_signal, Ref_PE, UseHilbEnv=True)[0]
        t_pe = np.abs(TOF_PE[1] - TOF_PE[0]) * dt
        t_tw = TOF_TW * dt
        Cl = Cw * (1 + (2 * t_tw / t_pe))
        L = (Cw / 2) * (2 * t_tw + t_pe)
        TOF_TW_45 = -CalcToFAscanCosine_XCRFFT(TT45_Ascan, WP_Ascan, UseHilbEnv=UseHilbEnv)[0]
        t_tw_45 = TOF_TW_45 * dt
        theta = np.deg2rad(Angle)
        term = (t_tw_45 * Cw / L) - np.cos(theta)
        Cs = Cw / np.sqrt(np.sin(theta)**2 + term**2)
        return Cl, Cs, L
    except Exception as ex:
        print(f"Error in MyThick_Vel: {ex}")
        return None, None, None

# Additional Utilities

def Centroid(x):
    """
    Calculates the centroid (energy-weighted mean index) of a vector.
    """
    n = np.arange(len(x))
    return np.sum(n * (x**2)) / np.sum(x**2)


def Envelope(MySignal):
    """
    Calculates the envelope of a signal using the Hilbert transform.
    """
    return np.abs(signal.hilbert(MySignal))


def NormSig(x):
    """
    Normalizes a signal to unit maximum.

    Parameters:
        x (np.ndarray): Input signal

    Returns:
        np.ndarray: Signal normalized by its maximum absolute value
    """
    max_val = np.max(np.abs(x))
    return x / max_val if max_val > 0 else x

def MakeWindow(SortofWin='boxcar', WinLen=512, param1=1, param2=1, Span=0, Delay=0):
    """
    Creates a window of a given type and applies optional zero-padding and delay.

    Parameters:
        SortofWin (str): Name of the window (e.g., 'hann', 'gaussian')
        WinLen (int): Base length of the window
        param1 (float): Main parameter (e.g., beta, std)
        param2 (float): Second parameter (for general_gaussian)
        Span (int): Final total length after zero-padding (must be >= WinLen)
        Delay (float): Delay in samples (can be fractional)

    Returns:
        np.ndarray: Windowed signal
    """
    lstWinWithParameter = ['barthannkaiser', 'gaussian', 'slepian', 'dpss', 'chebwin', 'exponential', 'tukey', 'general_gaussian']
    if any(SortofWin.lower() in x for x in lstWinWithParameter):
        if SortofWin.lower() == 'general_gaussian':
            MyWin = signal.get_window(('general_gaussian', param1, param2), WinLen)
        else:
            MyWin = signal.get_window((SortofWin.lower(), param1), WinLen)
    else:
        MyWin = signal.get_window(SortofWin.lower(), WinLen)

    if Span > 0:
        if Span < WinLen:
            raise ValueError("Span must be greater than or equal to WinLen.")
        MyWin = np.append(MyWin, np.zeros(Span - WinLen))

    if Delay != 0:
        if float(Delay).is_integer():
            MyWin = np.roll(MyWin, int(Delay))
        else:
            MyWin = ShiftSubsampleByfft(MyWin, -Delay)

    return MyWin