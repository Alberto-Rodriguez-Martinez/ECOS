# -*- coding: utf-8 -*-
"""
Created on Mon Mar 07 19:11:44 2016

@author: Alberto
"""
import sys
import matplotlib.pyplot as plt
from matplotlib import gridspec,axes
import numpy as np
from scipy.signal import hilbert

       
def PlotSignal_Time(Signal, Xaxis, Xlabel='Samples', Ylabel='Amplitude', Format='b'):
    #----------------------------------------------
    # Plots a single signal in time domain
    #
    # Inputs:
    #   Xaxis: Axis of the signal to plot, default
    #   Signal: Signal to plot
    #   XLabel = label of Xaxis, default 'Samples'
    #   YLabel = label of Yaxis, default 'Amplitude'
    #   Format = Format of line, default 'b'
    #
    # Outputs:
    #   None
    #
    # Alberto
    # 25/12/2017
    #----------------------------------------------
    try:                 
        plt.plot(Xaxis, Signal, Format)
        plt.xlabel(Xlabel)
        plt.ylabel(Ylabel)
    except Exception as ex:
        print ex
        
def PlotSignal_TimeFreq(Signal, Xaxis, Faxis, fs, Flims, Xlabel='Samples', 
                        FXlabel='Hz', Ylabel='Amplitude', Format='b'):
    #----------------------------------------------
    # Plots a single signal in time domain and in frequency FFT
    #
    # Inputs:
    #   Xaxis: Axis of the signal to plot, default
    #   Signal: Signal to plot
    #   XLabel = label of Xaxis, default 'Samples'
    #   FXLabel = label of Freq Xaxis, default 'Hz'
    #   YLabel = label of Yaxis, default 'Amplitude'
    #   Format = Format of line, default 'b'
    #
    # Outputs:
    #   None
    #
    # Alberto
    # 25/12/2017
    #----------------------------------------------
    try:
        # Plot figure with subplots of different sizes
        fig = plt.figure(1)
        # set up subplot grid
        gridspec.GridSpec(3,1)
        # time subplot
        plt.subplot2grid((3,1), (0,0)) 
        plt.plot(Xaxis, Signal, Format)
        plt.Axes.autoscale
        plt.xlabel(Xlabel)
        plt.ylabel(Ylabel)
        # calculate fft
        MyFFT = np.fft.fft(Signal)
        # time subplot
        plt.subplot2grid((3,1), (1,0), rowspan=3) 
        axes.Axes.magnitude_spectrum(Signal, Fs=fs) 
#        plt.plot(Faxis, np.abs(MyFFT), Format)
#        plt.xlim(Flims)
#        plt.xlabel(FXlabel)
#        plt.ylabel('FFT Magnitude')
    except Exception as ex:
        print ex
       
       
def Plot3Ascans_Time(Ascan1,Ascan2,Ascan3, name1, name2, name3,Normalized,ArrowLabel):
    #----------------------------------------------
    # Plots 3 Ascans in time domain
    #
    # Inputs:
    #   Ascan1 to plot 
    #   Ascan2 to plot
    #   Ascan3 to plot
    #   name1 = label to Ascan1
    #   name2 = label to Ascan2
    #   name3 = label to Ascan3
    #
    # Outputs:
    #   None
    #
    # Alberto
    # 23/05/2017
    #----------------------------------------------
    try:
        if Normalized==1:
            Ascan1 = Ascan1 / np.max(np.abs(Ascan1))
            Ascan2 = Ascan2 / np.max(np.abs(Ascan2))
            Ascan3 = Ascan3 / np.max(np.abs(Ascan3))        #time axis
        Time_Axis = np.arange(0,len(Ascan1),1)
        
        fig = plt.figure()
        #plot Ascan1
        ax1 = fig.add_subplot(311) #plot in time domain
        ax1.plot(Time_Axis,Ascan1, c='b', label=name1)
        ax1.set_xlabel('time (samples)')
        ax1.set_ylabel(name1)
        #ax1.legend()
        ax1.set_xlim(Time_Axis[0],Time_Axis[-1])
        ax1.set_ylim(np.min(Ascan1)*1.1,np.max(Ascan1)*1.1)
        ax1.grid()
        #plot Ascan2
        ax2 = fig.add_subplot(312) #plot in time domain
        ax2.plot(Time_Axis,Ascan2, c='b', label=name2)
        ax2.set_xlabel('time (samples)')
        ax2.set_ylabel(name2)
        #ax2.legend()
        ax2.set_xlim(Time_Axis[0],Time_Axis[-1])
        ax2.set_ylim(np.min(Ascan2)*1.1,np.max(Ascan2)*1.1)
        ax2.grid() 
        #plot Ascan2
        ax3 = fig.add_subplot(313) #plot in time domain
        ax3.plot(Time_Axis,Ascan3, c='b', label=name3)
        ax3.set_xlabel('time (samples)')
        ax3.set_ylabel(name3)
        #ax3.legend()
        ax3.set_xlim(Time_Axis[0],Time_Axis[-1])
        ax3.set_ylim(np.min(Ascan3)*1.1,np.max(Ascan3)*1.1)
        ax3.grid()
#        if np.not_equal(ArrowLabel," "):
#            annotate_point_pair(ax3, ArrowLabel, [0,np.max(Ascan3)], [np.argmax(np.abs(Ascan3)),np.max(Ascan3)], xycoords='data', text_offset=6, arrowprops = None)
        plt.show()
        
    except Exception as ex:
        print ex


def Plot2Ascans_TimeFrec(PE_Ascan,TT_Ascan,Fs,nfft,Cw,TimeUnits,FreqUnits,FRange,Normalize,PSD,Magnitude,Name1,Name2):    
    #----------------------------------------------
    # plot 2 Ascans and their spectrum
    # 
    # Inputs:
    #   PE_Ascan = PE Ascan
    #   PE_Ascan = PE Ascan
    #   Fs = Samplig frequency in Hz
    #   Cw = speed of sound in propagation path
    #   TimeUnits = time units for axis "smp","sec","ms","us","cm","mm"
    #   FreqUnits = frequency units for axis "smp","Hz",MHz"
    #   FRange = Frange to plot, array two elements, min and max frequency
    #   Normalize = 1 to normalize to 1 or o to leave it real gain
    #   PSD = 1 to plot PSD, 0 to plot spectral magnitude
    #   Magnitude = 0 plot spectrum mag. in natural units, or 1 in dB
    #
    #
    # Outputs
    #   None
    #
    # Alberto, 24/05/2017
    #----------------------------------------------
    
    FFT_TT_Ascan = np.absolute(np.fft.fft(TT_Ascan,nfft)) # FT of TT Ascan
    FFT_PE_Ascan = np.absolute(np.fft.fft(PE_Ascan,nfft)) # FT of PE Ascan
    
    XlabelText2 = 'Magnitude' # label for frequency spectrum
    MyYlim12=[0,np.max(FFT_PE_Ascan)*1.1] # ylims
    MyYlim22=[0,np.max(FFT_TT_Ascan)*1.1] # ylims
    MyYlim11=[np.min(PE_Ascan)*1.1,np.max(PE_Ascan)*1.1] # ylims
    MyYlim21=[np.min(TT_Ascan)*1.1,np.max(TT_Ascan)*1.1] # ylims
    
    if PSD==1: #plot PSD
        XlabelText2 = 'PSD'
        FFT_TT_Ascan = np.power(FFT_TT_Ascan,2)
        FFT_PE_Ascan = np.power(FFT_PE_Ascan,2)       
        MyYlim12=[0,np.max(FFT_PE_Ascan)*1.1] # ylims
        MyYlim22=[0,np.max(FFT_TT_Ascan)*1.1] # ylims
    if Normalize==1: # Normalize signals in time to plot
        PE_Ascan = PE_Ascan / np.max(np.abs(PE_Ascan))
        TT_Ascan = TT_Ascan / np.max(np.abs(TT_Ascan))
        FFT_PE_Ascan = FFT_PE_Ascan / np.max(FFT_PE_Ascan)
        FFT_TT_Ascan = FFT_TT_Ascan / np.max(FFT_TT_Ascan)
        MyYlim12=[0,1.1]
        MyYlim22=[0,1.1]
        MyYlim21=[-1.1,1.1]
        MyYlim11=[-1.1,1.1]
    if Magnitude==1: #plot in dB
        FFT_TT_Ascan = 10*np.log10(FFT_TT_Ascan)
        FFT_PE_Ascan = 10*np.log10(FFT_PE_Ascan)
        XlabelText2 = XlabelText2 + " (dB)"
        MyYlim12=[-100,np.max(FFT_PE_Ascan)]
        MyYlim22=[-100,np.max(FFT_TT_Ascan)]
    
    Time_Axis = np.arange(0,len(TT_Ascan),1.0) # time axis in samples
    xdata=Time_Axis
    XlabelText1='time (samples)'
    if TimeUnits=="sec":
        xdata=Time_Axis/Fs
        XlabelText1='time (sec)'
    elif TimeUnits=="ms":
        xdata=Time_Axis/Fs*1000
        XlabelText1='time (ms)'
    elif TimeUnits=="us":
        xdata=Time_Axis/Fs*Cw/2*1000
        XlabelText1='time ($\mu$s)'
    elif TimeUnits=="cm":
        xdata=Time_Axis/Fs*Cw*1000
        XlabelText1='distance (cm)'    
    elif TimeUnits=="mm":
        xdata=Time_Axis/Fs*Cw*1000
        XlabelText1='distance (mm)'
        
    Freq_Axis = np.arange(0,nfft,1.0) # Frequency axes in samples    
    xdata_2 = Freq_Axis 
    XlabelText2='frequency (samples)'
    if FreqUnits=="Hz":
        xdata_2=Freq_Axis * Fs / nfft # Frequency axes in Hz
        XlabelText2='frequency (MHz)'
    elif FreqUnits=="MHz":
        xdata_2=Freq_Axis * Fs / nfft /1e6 # Frequency axes in MHz
        XlabelText2='frequency (MHz)'
    
    fig = plt.figure()
    #plot PE_Ascan in time
    ax1 = fig.add_subplot(221) #plot in time domain
    ax1.plot(xdata,PE_Ascan, c='b', label=Name1)
    ax1.set_xlabel(XlabelText1)
    ax1.set_ylabel('Amplitude')
    ax1.legend()
    ax1.set_xlim(xdata[0],xdata[-1])
    ax1.set_ylim(MyYlim11)
    ax1.grid()
    #plot TT_Ascan in time
    ax2 = fig.add_subplot(223) #plot in time domain
    ax2.plot(xdata,TT_Ascan, c='b', label=Name2)
    ax2.set_xlabel(XlabelText1)
    ax2.set_ylabel('Amplitude')
    ax2.legend()
    ax2.set_xlim(xdata[0],xdata[-1])
    ax2.set_ylim(MyYlim21)
    ax2.grid()    
    #plot PE_Ascan in frequency
    ax3 = fig.add_subplot(222) #plot in time domain
    ax3.plot(xdata_2,FFT_PE_Ascan, c='b', label=Name1+' Spectrum')
    ax3.set_xlabel(XlabelText2)
    ax3.set_ylabel('Magnitude')
    ax3.legend()
    ax3.set_xlim(FRange[0],FRange[1])
    ax3.set_ylim(MyYlim12)
    ax3.grid()
    #plot PE_Ascan in frequency
    ax4 = fig.add_subplot(224) #plot in time domain
    ax4.plot(xdata_2,FFT_TT_Ascan, c='b', label=Name2+' Spectrum')
    ax4.set_xlabel(XlabelText2)
    ax4.set_ylabel('Magnitude')
    ax4.legend()
    ax4.set_xlim(FRange[0],FRange[1])
    ax4.set_ylim(MyYlim22)
    ax4.grid()    
    plt.show()
    return xdata, ax1    
    
