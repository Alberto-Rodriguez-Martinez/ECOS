# -*- coding: utf-8 -*-
"""
Created on Thu Mar 28 08:56:01 2019

@author: Alberto
"""
#%%
import sys
#sys.path.insert(0, r"D:\Pruebas\PYTHON_CODE\TOOLBOXES")

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
Transducer = "/Transductor_Inmersion_5MHz_Focused_UnGated"
SSPDir = "/SSP_Pruebas"

#DataFolder = CurrentDir + RootDir + Transducer + SaveDir

# Folder with gencodes
GenCodeFolder = CurrentDir + RootDir + ExperimentDir + GenCodesDir
ReferencesFolder = CurrentDir + RootDir + ExperimentDir + ReferencesDir


###############################################################################
#%% 
###############################################################################
# Initialize ACQ equipmen
###############################################################################

# constants
Smin = 5300 # starting point of the analysis (ACQ range)
Smax = 8500 # Last point of the analysis (ACQ range)
Fs = 100.0e6 #D sampling frequency
ProgGenCLKfreqMHz=200.0 # CLK of the gencodes generator (internal CLOK, my guess)
ADC_CLKfreqMHz=100.0 # sampling CLOK (sampling frequency of the ACQ, my guess)
#RecLen = 32*1024 # max range of ACQ
RecLen = 18*1024 # max range of ACQ
Gain_Ch2 = 21 #gain of channel 2 in dB
Gain_Ch1 = 0 #gain of channel 1 in dB

# list of gencodes
gencode = ("GC_GT_Chirp_3us_2_8",       #1
           "GC_GT_Chirp_5us_2_8",       #2
           "GC_GT_Chirp_10us_2_8",      #3
           "GC_TIFU_APWP_2_8_3us_2_8",  #4
           "GC_TIFU_APWP_2_8_3us_3_5",  #5
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

References = ("Ref_TIFU_Chirp_3us_2_8",       #1
           "Ref_TIFU_Chirp_5us_2_8",       #2
           "Ref_TIFU_Chirp_10us_2_8",      #3
           "Ref_TIFU_APWP_2_8_3us_2_8",  #4
           "Ref_TIFU_APWP_2_8_3us_3_5",  #5
           "Ref_TIFU_APWP_2_8_3us_3_7",  #5
           "Ref_TIFU_APWP_2_8_3us_4_6",  #6
           "Ref_TIFU_APWP_2_8_5us_2_8",  #7
           "Ref_TIFU_APWP_2_8_5us_3_7",  #8
           "Ref_TIFU_APWP_2_8_5us_4_6",  #9
           "Ref_TIFU_APWP_2_8_10us_2_8", #10
           "Ref_TIFU_APWP_2_8_10us_3_7", #11
           "Ref_TIFU_APWP_2_8_10us_4_6", #12
           "Ref_TIFU_Pulse_5M",             #13
           "Ref_TIFU_Burst_5M_4Cyc")           #14

GNo = 3 #select GenCode to use
MyGenCode = US.genCode(gencode[GNo])
MyGenCode.loadGenCode(GenCodeFolder)

###############################################################################
#%%

###############################################################################
# initiate ACQ 
###############################################################################
print("============================================================================")
print("Connecting to ACQ device...")
SeDaq = SeDaqDLL() # connect ACQ
time.sleep(3) # wait to be sure
print("ACQ device connected OK")
print("============================================================================")
SeDaq.SetRecLen(RecLen) # initialize record length

MyGenCode = US.genCode(gencode[GNo])
MyGenCode.loadGenCode(GenCodeFolder)
SeDaq.UpdateGenCode(MyGenCode.Gencode)


## upload to ACQ available gencodes
#SeDaq.AddGenCode(MyGenCode.FileName) 
#SeDaq.SetGenCode(1) # upload active gencode
## upload to ACQ available gencodes



#SeDaq.SetGenCode(GNo) # upload active gencode
MyAscan = uf.GatAscan_Ch2 #get Ascan, just to check
time.sleep(1) # wait to be sure

SeDaq.SetGain2(Gain_Ch2) #set gain of CH2
time.sleep(1) # wait to be sure

SeDaq.SeDaqDLL_SetRelay(0) #activate relay for Ch2, not working properly... 
time.sleep(1) # wait to be sure
###############################################################################


#ProbingGencode = np.fromfile(CurrentDir + gencode1, dtype=float, count=-1, sep='\n') # load gencode
#SeDaq.UpdateGenCode(ProbingGencode)

########################################################
# Acquire Ascan
########################################################
#%%
Smin = 5300 # starting point of the analysis (ACQ range)
Smax = 8500 # Last point of the analysis (ACQ range)
#NumberOfFilters = 15
GNo = 14 #select GenCode to use
MyGenCode = US.genCode(gencode[GNo],PulseBandwidthRatio = 0.25)
print("selected GenCode: " + MyGenCode.Name)
MyGenCode.loadGenCode(GenCodeFolder)
SeDaq.UpdateGenCode(MyGenCode.Gencode)

#ProbingGencode = np.fromfile(CurrentDir + gencode1, dtype=float, count=-1, sep='\n') # load gencode
#SeDaq.UpdateGenCode(ProbingGencode)

ReceivedSignal = uf.GatAscan_Ch2(Smin, Smax, AvgSamplesNumber = 50, Quantiz_Levels = 1024) #acq Ascan
uf.Plot_Ascan_tf(ReceivedSignal , Units_t = 1e8, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 15, FigNum=1, FigTitle=MyGenCode.Name) #plot Ascan

#%
#file_handle = open(CurrentDir + RootDir + ExperimentDir + "/SSP_Ascans" + "/Ascan_" + MyGenCode.Name + ".txt", "w")
#np.savetxt(file_handle, ReceivedSignal, fmt='%f') #save Ascan length
#file_handle.close()

#%

Ref = np.loadtxt(ReferencesFolder + '/' + References[GNo] + '.txt', dtype=float) # load reference signal




# % 
###############################################################################
# Make reference signal
###############################################################################
Ascan = ReceivedSignal # Signal to be used
AscanLength = len(Ascan) #length of the original Ascan
nfft = np.power(2,US.nextpow2(AscanLength)) #assign number of points of analysis to the next power of 2
Ascan = np.append(Ascan,np.zeros(nfft-AscanLength)) # zeropadding Ascan
Ref = np.append(Ref,np.zeros(nfft-AscanLength))

# Uncoment the following in case reference has to be made
#Ref = np.copy(Ascan) # copy Ascan to reference
#Ref[1280:]=0 # gate reference to avoid big echoes. Reference could be loaded from optimization procedure.
#
#
################################################################################
## Make window, tukey, according to length of the pulse
#SortofWin = 'tukey'
#ExcessWin = 35 # % of excess length of the window to prevent distortion
#WinLen = int(MyGenCode.Dur * Fs * (1 + ExcessWin/100.)) # window length, 30% more than Gencode duration
#WinParam1 = 0.3
##WinParam2 = 6
#RefDelay = US.Centroid(Ref)
#Delay = int(RefDelay-WinLen/2)
##print(Delay)
#Span = len(Ref) # make window Ascan as long as input Ascan
#MyWin = US.MakeWindow(SortofWin = SortofWin, WinLen = WinLen, param1 = WinParam1, Span = Span, Delay = Delay)
################################################################################
#
#Ref = Ref * MyWin # window the Ascan (reference now) to obtain the reference

fig = plt.figure(num=2, clear=True) 
fig.suptitle(MyGenCode.Name)               
axs1 = plt.subplot(211)
axs1.plot(Ascan)
#axs1.plot(MyWin*np.max(np.abs(Ascan)))
axs1.set_title('Orioginal Ascan')
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
axs2.plot(Faxis,np.abs(FT_w_Ascan)/np.max(np.abs(FT_w_Ascan)),label='Compressed')
axs2.plot(Faxis,np.abs(FT_Ascan)/np.max(np.abs(FT_Ascan)),label='Original')
axs2.legend(loc='upper right')
axs2.set_xlim(0, 15)

#% 
###############################################################################
# Bank of filters
###############################################################################
BandOverlap = 0.5
NumberOfFilters = 15
PulseCutPower = -6
PulseDecayTime = -60
#SamplingFrequency = 100e6
ScanLength = nfft
CentralFrequency = MyGenCode.Fc 
#CentralFrequency =4.0e6 
BandWidth = 1.25*(MyGenCode.Fh-MyGenCode.Fl)
#BandWidth = 4.0e6 
MyFilterBank = US.GaussFilterBank(ScanLength = ScanLength, SamplingFrequency = Fs,
                 CentralFrerquency = CentralFrequency, BandWidth = BandWidth, PulseCutPower = PulseCutPower, PulseDecayTime = PulseDecayTime,
                 BandOverlap = BandOverlap, NumberOfFilters = NumberOfFilters)


MyFilterBank.make_bank_ft(ZeroPhase = True, Expand = False)
#MyFilterBank.plot_bank_ft(Nfft = 4096, FigNum = 1,fscale =1e-6, Logaritmic = False, Normalized = True,
#                          MinF = 0, MaxF = 10e6, labelX = 'Frequency (MHz)', ZeroPhase = True)


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
    
#%
###############################################################################
# Recombination
###############################################################################
Cs = 2700 #•speed of sound in m/S
T_Axis = np.arange(nfft) # time in samples
T_Axis_us = T_Axis / Fs * 1e6 # time in microseconds
T_Axis_mm = (T_Axis / Fs * Cs /2 * 1000) - (ZeroLoc/ Fs * Cs /2 * 1000) # distance in mm from front-surface

X_Axis = T_Axis_mm
X_axis_text = 'Distance (mm)'
MyXlim = X_Axis[AscanLength]
MyXlimMin = X_Axis[0]
fm_w = US.fm_raw(w_OutPut, Normalized = True, Absolute = True) #Apply fm to wienered signal
fm = US.fm_raw(OutPut, Normalized = True, Absolute = True) # Apply fm to raw input signal
pt_w = US.pt_raw(w_OutPut, w_Ascan, Scaled = False, ZeroCounts = True, Absolute = True, Normalized = True) #Apply pt to wienered signal
pt_w_mask = US.pt_raw(w_OutPut, Scaled = False, ZeroCounts = True, Absolute = True, Normalized = True) #Apply pt to wienered signal
pt = US.pt_raw(OutPut, Ascan, Scaled = False, ZeroCounts = True, Absolute = True, Normalized = True) # Apply pt to raw input signal
pt_mask = US.pt_raw(OutPut, Scaled = False, ZeroCounts = True, Absolute = True, Normalized = False) # Apply pt to raw input signal

#min_raw = US.min_raw(OutPut, Normalized = True,)
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
axs6.plot(X_Axis, np.log10(m))
axs6.set_xlim(MyXlimMin,MyXlim)
axs6.set_title('pt to compressed Ascan')
#axs6.plot(np.abs(pt_w))
#print(np.max(np.abs(pt_w)))
#print(np.min(np.abs(pt_w)))
#%%
#amplitude_envelope, instantaneous_phase, instantaneous_frequency = US.cp_raw(w_OutPut)
#fig = plt.figure(num=7, clear=True)
#axs1 = plt.subplot(311)
#axs1.plot(Ascan)
##axs1.set_xlim(0,nfft/2)
#axs2 = plt.subplot(312)
#axs2.plot(instantaneous_phase)
##axs2.set_xlim(0,nfft/2)
#axs3 = plt.subplot(313)
#axs3.plot(np.log10(np.abs(w_Ascan/np.var(instantaneous_phase,axis=1))))
##axs3.set_xlim(0,nfft/2)
