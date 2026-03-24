# -*- coding: utf-8 -*-
"""
Created on Fri Apr 5 

Apply SSP analysis to signals acquiered from metacrylate sample cilinder
Aprox 15.15 mm thickness
Defect 0.5 mm thick aprox 8mm from front-surface

Analysis performed with all excitations

NO GATING excitations

This particular code made for the Inmersion Transdcuer 5 MHz Focused


@author: Alberto
"""
#%%
import sys
sys.path.insert(0, r"D:\Dropbox\00 INVESTIGACION\30 CODIGO\PYTHON_CODE\TOOLBOXES")

#ToolBoxDir = r"D:\Pruebas\PYTHON_CODE\TOOLBOXES"
#execfile(ToolBoxDir + "\SeDaq.py") #User functions from separate file in root dir
#execfile(ToolBoxDir + "\UserFunct.py") #User functions from separate file in root dir
#execfile(ToolBoxDir + "\ACQ_ToolBox.py") #User functions from separate file in root dir
#execfile(ToolBoxDir + "\US_ToolBox_2019.py") #User functions from separate file in root dir



from scipy import signal
from scipy import interpolate
import time
import numpy as np
import matplotlib.pylab as plt
from SeDaq import *
import UserFunct as uf
import ACQ_ToolBox as ACQ
import US_ToolBox_2019 as US
import os
####################################################################

###############################################################################
# Folders and workspace
###############################################################################
# Make dir to save data of the experiment
CurrentDir = r'D:\Dropbox\00 INVESTIGACION\30 CODIGO\PYTHON_CODE\APWPOPTIM\01 NEW CODE'
RootDir = "/UltrasonicData"
ExperimentDir = "/Metacrilato_Cilindro"
GenCodesDir = "/Result_GenCodes"
ReferencesDir = "/Result_References"
AscansDir = "/SSP_Ascans"
Transducer = "/Transductor_Inmersion_5MHz_Focused_UnGated"

#DataFolder = CurrentDir + RootDir + Transducer + SaveDir

# Folder with gencodes
GenCodeFolder = CurrentDir + RootDir + ExperimentDir + GenCodesDir
ReferencesFolder = CurrentDir + RootDir + ExperimentDir + ReferencesDir
AscansFolder = CurrentDir + RootDir + ExperimentDir + AscansDir


###############################################################################
#%% 


# list of gencodes
gencode = ("GC_GT_Chirp_3us_2_8",       #0
           "GC_GT_Chirp_5us_2_8",       #1
           "GC_GT_Chirp_10us_2_8",      #2
           "GC_TIFU_APWP_2_8_3us_2_8",  #3
           "GC_TIFU_APWP_2_8_3us_3_5",  #4
           "GC_TIFU_APWP_2_8_3us_3_7",  #5
           "GC_TIFU_APWP_2_8_3us_4_6",  #6
           "GC_TIFU_APWP_2_8_5us_2_8",  #7
           "GC_TIFU_APWP_2_8_5us_3_7",  #8
           "GC_TIFU_APWP_2_8_5us_4_6",  #9
           "GC_TIFU_APWP_2_8_10us_2_8", #10
           "GC_TIFU_APWP_2_8_10us_3_7", #11
           "GC_TIFU_APWP_2_8_10us_4_6", #12
           "GC_GT_Pulse_5",             #13
           "GC_GT_Burst_5_4")           #14

References = ("Ref_TIFU_Chirp_3us_2_8",  #0
           "Ref_TIFU_Chirp_5us_2_8",     #1
           "Ref_TIFU_Chirp_10us_2_8",    #2
           "Ref_TIFU_APWP_2_8_3us_2_8",  #3
           "Ref_TIFU_APWP_2_8_3us_3_5",  #4
           "Ref_TIFU_APWP_2_8_3us_3_7",  #5
           "Ref_TIFU_APWP_2_8_3us_4_6",  #6
           "Ref_TIFU_APWP_2_8_5us_2_8",  #7
           "Ref_TIFU_APWP_2_8_5us_3_7",  #8
           "Ref_TIFU_APWP_2_8_5us_4_6",  #9
           "Ref_TIFU_APWP_2_8_10us_2_8", #10
           "Ref_TIFU_APWP_2_8_10us_3_7", #11
           "Ref_TIFU_APWP_2_8_10us_4_6", #12
           "Ref_TIFU_Pulse_5M",          #13
           "Ref_TIFU_Burst_5M_4Cyc")     #14

AscansList = ("Ascan_TIFU_Chirp_3us_2_8",  #0
           "Ascan_TIFU_Chirp_5us_2_8",     #1
           "Ascan_TIFU_Chirp_10us_2_8",    #2
           "Ascan_TIFU_APWP_2_8_3us_2_8",  #3
           "Ascan_TIFU_APWP_2_8_3us_3_5",  #4
           "Ascan_TIFU_APWP_2_8_3us_3_7",  #5
           "Ascan_TIFU_APWP_2_8_3us_4_6",  #6
           "Ascan_TIFU_APWP_2_8_5us_2_8",  #7
           "Ascan_TIFU_APWP_2_8_5us_3_7",  #8
           "Ascan_TIFU_APWP_2_8_5us_4_6",  #9
           "Ascan_TIFU_APWP_2_8_10us_2_8", #10
           "Ascan_TIFU_APWP_2_8_10us_3_7", #11
           "Ascan_TIFU_APWP_2_8_10us_4_6", #12
           "Ascan_TIFU_Pulse_5",           #13
           "Ascan_TIFU_Burst_5_4")         #14



###############################################################################
#%%
###############################################################################
# Initialize constants and load signals
###############################################################################
Fs = 100.0e6 #D sampling frequency
GNo = 13 #select GenCode to use

MyGenCode = US.genCode(gencode[GNo],PulseBandwidthRatio = 0.25)
print("selected Excitation: " + MyGenCode.Name)
MyGenCode.loadGenCode(GenCodeFolder)

BandOverlap = 0.5 # overlap of the filters in the filter bank, in %
NumberOfFilters = 9 # number of filters of the bank
PulseCutPower = -6 # cuit power for the gaussian pulse filter
PulseDecayTime = -60 # decay power time for the gaussian pulse filter
SamplingFrequency = Fs # sampling frecuency

CentralFrequency = MyGenCode.Fc  # central frecuency of the band to analyse
#CentralFrequency =4.0e6 
BandWidth = (MyGenCode.Fh-MyGenCode.Fl) # bandwidth of the band to analyse 
#BandWidth = 4.0e6 
print('Central Frequency = ' + str(MyGenCode.Fc) + ' MHz')
print('Bandwidth = ' + str((MyGenCode.Fh-MyGenCode.Fl)) + ' MHz')

Ref = np.loadtxt(ReferencesFolder + '/' + References[GNo] + '.txt', dtype=float) # load reference signal
Ascan = np.loadtxt(AscansFolder + '/' + AscansList[GNo] + '.txt', dtype=float) # load Ascan signal

ScanLength = len(Ascan) # Original Number of samples of the Ascan
nfft = np.power(2,US.nextpow2(ScanLength)) #assign number of points of analysis to the next power of 2
Ascan = np.append(Ascan,np.zeros(nfft-ScanLength)) # zeropadding Ascan
Ref = np.append(Ref,np.zeros(nfft-ScanLength)) # zeropadding Reference

ScanLength = len(Ascan) #update scan length

uf.Plot_Ascan_tf(Ascan , Units_t = 1e8, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 15, FigNum=1, FigTitle=MyGenCode.Name) #plot Ascan
uf.Plot_Ascan_tf(Ref, Units_t = 1e8, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 15, FigNum=2, FigTitle='Reference') #plot Ascan

fig = plt.figure(num=3, clear=True) 
fig.suptitle(MyGenCode.Name)               
axs1 = plt.subplot(211)
axs1.plot(Ascan)
#axs1.plot(MyWin*np.max(np.abs(Ascan)))
axs1.set_title('Original Ascan')
axs2 = plt.subplot(212)
axs2.plot(Ref)
axs2.set_title('Reference')


#%
###############################################################################
# wiener filter - pulse compression
###############################################################################
FT_Ref = np.fft.fft(Ref,nfft) #spectrum of reference signal
FT_Ascan = np.fft.fft(Ascan,nfft) # spectrum of Ascan
Faxis = np.arange(0, Fs, Fs/nfft) / 1e6 #frequency axes

fig = plt.figure(num=3, clear=True)                
axs1 = plt.subplot(211)
axs1.plot(Faxis, np.abs(FT_Ascan))
axs1.set_xlim(0, 15)
axs2 = plt.subplot(212)
axs2.plot(Faxis, np.abs(FT_Ref))
axs2.set_xlim(0, 15)

RefDelay = US.Centroid(Ref) # centroid of reference signal, to recover position when filtering
FT_w_Ascan =  FT_Ascan*np.conj(FT_Ref)/(np.abs(FT_Ref)**2 + 00.1 )
w_Ascan = np.real(np.fft.ifft(FT_w_Ascan))
w_Ascan = US.ShiftSubsampleByfft(w_Ascan,-RefDelay)
FT_w_Ascan = np.fft.fft(w_Ascan)

fig = plt.figure(num=4, clear=True)                
axs1 = plt.subplot(211)
axs1.plot(Ascan,label='Original')
axs1.plot(w_Ascan,label='Compressed')
axs1.legend(loc='upper right')
axs2 = plt.subplot(212)
axs2.plot(Faxis,np.abs(FT_Ascan)/np.max(np.abs(FT_Ascan)),label='Original')
axs2.plot(Faxis,np.abs(FT_w_Ascan)/np.max(np.abs(FT_w_Ascan)),label='Compressed')
axs2.legend(loc='upper right')
axs2.set_xlim(0, 15)

#% 
###############################################################################
# Bank of filters
###############################################################################

MyFilterBank = US.GaussFilterBank(ScanLength = len(Ascan), SamplingFrequency = Fs,
                 CentralFrerquency = CentralFrequency, BandWidth = BandWidth, PulseCutPower = PulseCutPower, PulseDecayTime = PulseDecayTime,
                 BandOverlap = BandOverlap, NumberOfFilters = NumberOfFilters)

MyFilterBank.make_bank_ft(ZeroPhase = True, Expand = False)

#%
###############################################################################
# filtering process
###############################################################################
fig = plt.figure(num=5, clear=True)                
axs1 = plt.subplot(111)
#axs1.plot(Faxis,np.abs(FT_Ascan)/np.max(np.abs(FT_Ascan)),'k')
axs1.plot(Faxis,np.abs(FT_Ref)/np.max(np.abs(FT_Ref)),'k')
#axs1.plot(Faxis,np.abs(FT_w_Ascan)/np.max(np.abs(FT_w_Ascan)),'k--',label='Compressed')
axs1.plot(Faxis,np.abs(MyFilterBank.FTBank)/np.max(np.abs(MyFilterBank.FTBank)))
TotalBW = np.sum(np.abs(MyFilterBank.FTBank),axis=1)
axs1.plot(Faxis,np.abs(MyFilterBank.FTBank)/np.max(np.abs(MyFilterBank.FTBank)))
axs1.plot(Faxis,TotalBW/np.max(TotalBW),'--')

axs1.set_xlim(0, 15)

w_OutPut = US.SS_filter_ZeroPhase(FT_w_Ascan, MyFilterBank.FTBank, ScanLength)
OutPut = US.SS_filter_ZeroPhase(FT_Ascan, MyFilterBank.FTBank, ScanLength)
ZeroLoc = np.argmax(w_Ascan)

#fig, axs = plt.subplots(NumberOfFilters+1, 1, num=6, clear=True)
#axs[0].plot(w_Ascan)
#for i in np.arange(NumberOfFilters):
#    axs[i+1].plot(w_OutPut[:,i])
#
#fig, axs = plt.subplots(NumberOfFilters+1, 1, num=7, clear=True)
#axs[0].plot(Ascan)
#for i in np.arange(NumberOfFilters):
#    axs[i+1].plot(OutPut[:,i])
    
#%%
###############################################################################
# Recombination
###############################################################################
Cs = 2700 #•speed of sound in m/S
T_Axis = np.arange(nfft) # time in samples
T_Axis_us = T_Axis / Fs * 1e6 # time in microseconds
T_Axis_mm = (T_Axis / Fs * Cs /2 * 1000) - (ZeroLoc/ Fs * Cs /2 * 1000) # distance in mm from front-surface

X_Axis = T_Axis_mm
X_axis_text = 'Distance (mm)'
MyXlim = X_Axis[ScanLength-1]
MyXlimMin = X_Axis[0]
fm_w = US.fm_raw(w_OutPut, Normalized = True, Absolute = True) #Apply fm to wienered signal
fm = US.fm_raw(OutPut, Normalized = True, Absolute = True) # Apply fm to raw input signal
pt_w = US.pt_raw(w_OutPut, w_Ascan, Scaled = False, ZeroCounts = False, Absolute = True, Normalized = True) #Apply pt to wienered signal
pt_w_mask = US.pt_raw(w_OutPut, Scaled = False, ZeroCounts = False, Absolute = True, Normalized = True) #Apply pt to wienered signal
pt = US.pt_raw(OutPut, Ascan, Scaled = False, ZeroCounts = True, Absolute = True, Normalized = True) # Apply pt to raw input signal
pt_mask = US.pt_raw(OutPut, Scaled = False, ZeroCounts = True, Absolute = True, Normalized = False) # Apply pt to raw input signal
#%
#min_raw = US.min_raw(OutPut, Normalized = True,)


pt_w_clipped = np.clip(pt_w, 1e-5, None)
pt_w_clipped_dB = np.log10(pt_w_clipped)
PP_pt_w = US.movingAverage(pt_w_clipped_dB-min(pt_w_clipped_dB), SortofWin='tukey',param1 = 0.2, WinLen = 9)
fig = plt.figure(num=7, clear=True)
plt.plot(X_Axis, PP_pt_w)
plt.plot(X_Axis, pt_w_mask,color=(0.8,0.8,0.8))


#PP_pt_w = pt_w_clipped_dB
#%%
fig = plt.figure(num=6, clear=True)
axs1 = plt.subplot(321)
axs1.plot(X_Axis, Ascan)
axs1.set_xlim(MyXlimMin,MyXlim)
axs1.set_title('Ascan')
axs3 = plt.subplot(323)
axs3.plot(X_Axis, fm)
axs3.set_xlim(MyXlimMin,MyXlim)
axs3.set_title('fm to Ascan')
axs5 = plt.subplot(325)
m = np.clip(pt, 1e-5, None)
axs5.plot(X_Axis, pt_mask,color=(0.8,0.8,0.8))
axs5.plot(X_Axis, m)
axs5.set_xlim(MyXlimMin,MyXlim)
axs5.set_title('pt to Ascan')


axs2 = plt.subplot(322)
axs2.plot(X_Axis, w_Ascan)
axs2.set_xlim(MyXlimMin,MyXlim)
axs2.set_title('Compressed Ascan')
axs4 = plt.subplot(324)
axs4.plot(X_Axis, fm_w)
axs4.set_xlim(MyXlimMin,MyXlim)
axs4.set_title('fm to compressed Ascan')
axs6 = plt.subplot(326)
m = np.clip(pt_w, 1e-5, None)
axs6.plot(X_Axis, pt_w_mask,color=(0.8,0.8,0.8))
#axs6.plot(X_Axis,m)
axs6.plot(X_Axis, PP_pt_w)
axs6.set_xlim(MyXlimMin,MyXlim)
axs6.set_title('pt to compressed Ascan')
#axs6.plot(np.abs(pt_w))
#print(np.max(np.abs(pt_w)))
#print(np.min(np.abs(pt_w)))

#%%
#amplitude_envelope, instantaneous_phase, instantaneous_frequency = US.cp_raw(w_OutPut)
#
#fig = plt.figure(num=7, clear=True)
#axs1 = plt.subplot(111)
##axs1.plot(w_OutPut[1530:1555,:])
#axs1.plot(pt_w_mask[1430:1655])
##axs1.plot(np.diff(w_OutPut[1530:1555,:]))
#axs1.plot(instantaneous_phase[1430:1655,:])
##for i in range(w_OutPut.shape[1]):
#    axs1.plot(pt_w_mask*w_OutPut[:,i])
    
#%%

#fig = plt.figure(num=7, clear=True)
#axs1 = plt.subplot(311)
#axs1.plot(X_Axis,Ascan)
#axs1.plot(X_Axis,w_Ascan)
##axs1.set_xlim(0,nfft/2)
#axs2 = plt.subplot(312)
#axs2.plot(X_Axis,instantaneous_phase)
##axs2.set_xlim(0,nfft/2)
#axs3 = plt.subplot(313)
#axs3.plot(X_Axis,np.log10(np.abs(w_Ascan/np.var(instantaneous_phase,axis=1))))
##axs3.set_xlim(0,nfft/2)

