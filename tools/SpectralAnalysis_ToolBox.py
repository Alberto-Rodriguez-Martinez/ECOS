# -*- coding: utf-8 -*-
"""
Created on Tue Jan 21 09:12:54 2020

@author: alrom
"""

from scipy import signal
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.axes_grid1.inset_locator import inset_axes

def Plot_Specgram(x, Fs=1.0, window=('tukey', 0.25), WinSize=None, Overlap=None,
                  nfft=None, detrend='constant', return_onesided=True, scaling='density',Units='dB',
                  axis=-1, mode='psd', Time_Scale=1, Time_OffSet=0, FreqUnits = 'Hz',Fmin=0,Fmax=0,
                  time_Label = 'time (s)',FigNum = 1, FigTitle='Spectrogram',Imshow=False,ColorMap = 'plasma'):
    """
    calculates and plot spectrogramo af a 1D signal
    inputs
        x =input 1D signal
        fs = sampling frecuency in Hz
        window = (sort of window in text, parameter), defsault ('tukey', 0.25)
        WinSize = window size in samples, default 256 to None
        Overlap = windows overlap in number of samples, default WinSize//8 to None
        nfft = number of points of the fft, default WinSize to None
        detrend = function for detren segments {'linear','constant',False}, default 'constant', which removes mean of data
        return_onesided = if True return one-sided spectrum, if false two sided (unless complex data, then always twosided)
        scaling = {‘density’, ‘spectrum’ }, default density as V**2/Hz
        Units = {'dB','linear'}, units of the output, default dB
        axis = axis along which spectrogram is computed, default last axis (-1)
        mode =  [‘psd’, ‘complex’, ‘magnitude’, ‘angle’, ‘phase’]
         ‘complex’ is equivalent to the output of stft with no padding or boundary extension. 
         ‘magnitude’ returns the absolute magnitude of the STFT. 
         ‘angle’ and ‘phase’ return the complex angle of the STFT, with and without unwrapping, respectively.
        Time_Scale = scale factor to change time axis, default 1
        Time_OffSet = time offset to be substracted from time axis, in same units, default 0
        FreqUnits = units of frequency axis, {'Hz','KHz','MHz','GHz'}
        Fmin = min frequency to be ploted, same units as FreqUnits
        Fmax = max frequency to be ploted, same units as FreqUnits, if 0 (default) Fs/2
        FigNum = figure number, default 1
        FigTitle = figure title, default 'Spectrogram'
        ImShow = boolean, True to plot imshow, False (default) to plot pcolormesh
        ColorMap = text, colormap to use, default 'plasma'
     outputs
         f = array of sample frequencies
         t = array of segment times
         Sxx = Spectrogram of x
    """

    f, t, Sxx = signal.spectrogram(x, fs=Fs, window=window,
                                   nperseg=WinSize, noverlap=Overlap, nfft=nfft,
                                   detrend=detrend, return_onesided=return_onesided,
                                   scaling=scaling, axis=axis, mode=mode)
    
    
#    Time_Axis = np.arange(0, Bscan.shape[1])*Time_Scale - Time_OffSet
#    Xaxis = np.arange(0, Bscan.shape[0])*Xaxis_Scale
    if Units.lower()=='db':
        Sxx=np.log10(Sxx)
        FigTitle = FigTitle + 'dB'
    freq_label = 'frequency (Hz)'
    if FreqUnits.lower()=='khz':
        f = f/1e3
        freq_label = 'frequency (KHz)'
    elif FreqUnits.lower()=='mhz':
        f = f/1e6
        freq_label = 'frequency (MHz)'
    elif FreqUnits.lower()=='ghz':
        f = f/1e9
        freq_label = 'frequency (GHz)'
    F1 = int(np.min(np.argwhere(f>Fmin)))
    F2 = (np.max(np.argwhere(f<Fmax)))
    
    fig = plt.figure(num=FigNum, clear=True)    
    fig.suptitle(FigTitle)            
    ax1 = plt.subplot(2,1,1)
    if Imshow:
        ax1.imshow(Sxx[F1:F2,:], cmap=ColorMap,interpolation = 'bilinear')
    else:
        im=ax1.pcolormesh(t*Fs*Time_Scale - Time_OffSet, f[F1:F2] ,Sxx[F1:F2,:], cmap=ColorMap,shading = 'gouraud')
        axins1 = inset_axes(ax1, width="2%", height="100%",loc='lower left',
                            bbox_to_anchor=(1.01, -0.01,1,1),bbox_transform=ax1.transAxes)
        fig.colorbar(im, cax=axins1, orientation="vertical")
#        axins1.xaxis.set_ticks_position("right")
    ax1.set_ylabel(freq_label)
    ax1.set_xlabel(time_Label)
    ax2 = plt.subplot(2,1,2)
    Time_Axis = np.arange(0, len(x))*Time_Scale - Time_OffSet
    ax2.plot(Time_Axis, x)
    plt.xlim(Time_Axis[0],Time_Axis[-1])
    ax2.set_ylabel('Amplitude')
    ax2.set_xlabel(time_Label)