# -*- coding: utf-8 -*-
"""

Sample characterization:
    Cl: Longitudinal speed of sound
    Cs: Shear speed of sound
    L = Thickness

@author: Alberto
"""

import sys

sys.path.insert(0, r"D:\Dropbox\00 INVESTIGACION\30 CODIGO\PYTHON_CODE\TOOLBOXES")
sys.path.insert(0, r"D:\Dropbox\00 INVESTIGACION\30 CODIGO\PYTHON_CODE\TOOLBOXES\ultrasound_velocity_tools_package")

from scipy import signal
from scipy import interpolate
import time
import numpy as np
import matplotlib.pylab as plt
import matplotlib.animation as animation
import SeDaq as SD
# import SeDaq_arnau as SD
import UserFunct as uf
import ACQ_ToolBox as ACQ
import US_ToolBox_2025 as US
import ultrasound_velocity_tools as UVT
import GenCode_ToolBox as gc
import os


#%% 
########################################################
# constants
########################################################

Fs = 100.0e6 #D sampling frequency
ProgGenCLKfreqMHz=200.0 # CLK of the gencodes generator (internal CLOK, my guess)
ADC_CLKfreqMHz=100.0 # sampling CLOK (sampling frequency of the ACQ, my guess)


# Make dir to save data of the experiment
CurrentDir = r'D:\Prueba'
RootDir = "/PVA_Characterization"
Experiment = "\Pulse_5MHz"
Experiment = "\Thin_PVA"
SaveDir = "/Prueba_"+time.strftime("%Y_%m_%d")+"_"+time.strftime("%H_%M_%S")
MyDir = CurrentDir + RootDir + Experiment + SaveDir
if not os.path.exists(MyDir):
    os.makedirs(MyDir)

# save Ascan length    
#file_handle = file(MyDir + "/ADClength.txt", "w")
#np.savetxt(file_handle, [Smax-Smin], fmt='%i') #save Ascan length
#file_handle.close()    
########################################################



#%%
########################################################################
# Initialize ACQ equipment, GenCode to use, and set all parameters
########################################################################
#RecLen = 32*1024 # max range of ACQ
RecLen = 16*1024 # max range of ACQ
# Gain_Ch2 = 0 #gain of channel 2 in dB
# Gain_Ch1 = 80 #gain of channel 1 in dB

Fp=5.0*1e6# Central frequency of the US pulse, MHz



# connect ACQ (32-bit architecture only)
SeDaq = SD.SeDaqDLL() 
_sleep_time = 1
print('Connected.')
print(f'Sleeping for {_sleep_time} s...')
time.sleep(_sleep_time) # wait to be sure
print("------------------------------------------------------------------------")
Reset_Relay = False             # Reset delay: ON>OFF>ON - bool
if Reset_Relay:
    print('Resetting relay...')
    SeDaq.SetRelay(1)
    time.sleep(1) # wait to be sure
    SeDaq.SetRelay(0)
    time.sleep(1) # wait to be sure
    SeDaq.SetRelay(1)
    time.sleep(1) # wait to be sure
    print("------------------------------------------------------------------------")
SeDaq.SetRecLen(RecLen) # initialize record length
# SeDaq.SetExtVoltage(Excitation_voltage) - DOESN'T WORK
# SeDaq.SetGain1(Gain_Ch1)
# SeDaq.SetGain2(Gain_Ch2)
# print(f'Gain of channel 1 set to {SeDaq.GetGain(1)} dB') # return gain of channel 1
# print(f'Gain of channel 2 set to {SeDaq.GetGain(2)} dB') # return gain of channel 2
print("------------------------------------------------------------------------")
# Make gencode using 5MHz pulse
# GenCode = gc.MakeGenCode(Excitation='Pulse', Param='frequency',ParamVal = Fp, SignalPolarity = 2,
#                          Fs = ProgGenCLKfreqMHz, DeadTime_Samples=0, CancelDuration=0, AddZerosInFront_Samples=0)
# SeDaq.UpdateGenCode(GenCode)
print('Generator code created and updated.')
print("========================================================================\n")


########################################################

#%%
########################################################
# acquire and check signals
########################################################


Gain_Ch1 = 75 #gain of channel 1 in dB
Gain_Ch2 = 0 #gain of channel 2 in dB
SeDaq.SetGain1(Gain_Ch1)
SeDaq.SetGain2(Gain_Ch2)



# set acq length, acquire and plot
Smin = 0# starting point of the analysis (ACQ range)
Smax = RecLen # Last point of the analysis (ACQ range)
# Smax = 6000  # Last point of the analysis (ACQ range)
Ascan_Ch2 = ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
Ascan_Ch1 = ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan

# fix fft lentgh
N = int(np.ceil(np.log2(np.abs(len(Ascan_Ch1)))))+2
nfft = 2**N

# plot
US.Plot2Ascans_TimeFreq(Ascan_Ch2,Ascan_Ch1, nfft=nfft, FreqScale= 1e6, TimeScale=1, Fmax = 15,Fs=100e6,FigNum = 2)
# uf.Plot_Ascan_tf(Ascan_Ch2 , Units_t = 1e8, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 15, FigNum=1, FigTitle=SaveDir) #plot Ascan
plt.show()


#%% plot in real time

# Gain_Ch2 = 20
# SeDaq.SetGain1(Gain_Ch1)
# SeDaq.SetGain2(Gain_Ch2)

Smin = 0# starting point of the analysis (ACQ range)
# Smax = RecLen # Last point of the analysis (ACQ range)
Smax = 8000  # Last point of the analysis (ACQ range)
ArrayLen = Smax-Smin  
# Parámetros

SAMPLING_RATE = Fs  # en Hz, ajusta según tu dispositivo

# Eje X (puede ser tiempo en microsegundos, o muestras o distancia si ponemos velocidad)
Cw = 1500 # velocidad sonido en agua


x_axis_samples = np.arange(ArrayLen) # en muestras
x_axis_mus = x_axis_samples / Fs * 1e6 # en microsegundos
x_axis_mm = x_axis_samples / Fs * Cw / 2 * 1e3# en mm, asumiento que es pulso-eco

TipoEje = 'samples'

if TipoEje == 'mm':
    Label_x_axis = 'distance [mm]'
    x_axis = x_axis_mm
elif TipoEje == 'mus':
    Label_x_axis = 'time [μs]'
    x_axis = x_axis_mus
elif TipoEje == 'samples':
    Label_x_axis = 'samples'
    x_axis = x_axis_samples
        

# Inicialización del buffer de datos
signal_buffer_Ch2 = np.zeros(ArrayLen)
signal_buffer_Ch1 = np.zeros(ArrayLen)

# Configuración de la gráfica
fig, ax = plt.subplots()
line_Ch2, = ax.plot(x_axis, signal_buffer_Ch2)
line_Ch1, = ax.plot(x_axis, signal_buffer_Ch1)
ax.set_ylim(-0.5, 0.5)
ax.set_xlim(x_axis[0], x_axis[-1])


# Etiquetas eje principal
ax.set_xlabel(Label_x_axis)
ax.set_ylabel("Amplitude")
plt.title("Real-Time Signal Plot")


def update_Ch2(frame):
    global signal_buffer_Ch2
    new_data_Ch2 = ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
    # Desplazamiento del buffer: eliminamos los datos antiguos y añadimos los nuevos
    signal_buffer_Ch2 = np.roll(signal_buffer_Ch2, -len(new_data_Ch2))
    signal_buffer_Ch2[-len(new_data_Ch2):] = new_data_Ch2
    line_Ch2.set_ydata(signal_buffer_Ch2)
    return line_Ch2, 

def update_Ch1(frame):
    global signal_buffer_Ch1
    new_data_Ch1 = ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
    # Desplazamiento del buffer: eliminamos los datos antiguos y añadimos los nuevos
    signal_buffer_Ch1 = np.roll(signal_buffer_Ch1, -len(new_data_Ch1))
    signal_buffer_Ch1[-len(new_data_Ch1):] = new_data_Ch1
    line_Ch1.set_ydata(signal_buffer_Ch1)
    return line_Ch1, 

def update_Ch1_Ch2(frame):
    global signal_buffer_Ch1, signal_buffer_Ch2
    new_data_Ch1 = ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
    new_data_Ch2 = ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
    # Desplazamiento del buffer: eliminamos los datos antiguos y añadimos los nuevos
    signal_buffer_Ch1 = np.roll(signal_buffer_Ch1, -len(new_data_Ch1))
    signal_buffer_Ch1[-len(new_data_Ch1):] = new_data_Ch1
    line_Ch1.set_ydata(signal_buffer_Ch1)
    signal_buffer_Ch2 = np.roll(signal_buffer_Ch2, -len(new_data_Ch2))
    signal_buffer_Ch2[-len(new_data_Ch2):] = new_data_Ch2
    line_Ch2.set_ydata(signal_buffer_Ch2)
    return line_Ch1, line_Ch2,


# Animación: actualiza cada intervalo de tiempo igual al necesario para adquirir un bloque
interval_ms = int(1000 * ArrayLen / Fs)

ani = animation.FuncAnimation(fig, update_Ch1_Ch2, interval=interval_ms, blit=True)
plt.tight_layout()
plt.show()


#%% Take WP
Win_Len = 10000
Smin = 0# starting point of the analysis (ACQ range)
# Smax = RecLen # Last point of the analysis (ACQ range)
Smax = Smin+Win_Len  # Last point of the analysis (ACQ range)

Ascan_Ch2 = ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
Ascan_Ch1 = ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan

# plot
US.Plot2Ascans_TimeFreq(Ascan_Ch2,Ascan_Ch1, nfft=nfft, FreqScale= 1e6, TimeScale=1, Fmax = 15,Fs=100e6,FigNum = 2)
# uf.Plot_Ascan_tf(Ascan_Ch2 , Units_t = 1e8, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 15, FigNum=1, FigTitle=SaveDir) #plot Ascan
plt.show()
#%% get WP_Ascan
Win_Len = 4000
Smin = 4250# starting point of the analysis (ACQ range)
# Smax = RecLen # Last point of the analysis (ACQ range)
Smax = Smin+Win_Len # Last point of the analysis (ACQ range)
Ascan_Ch2 = ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
Ascan_Ch1 = ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan

# plot
US.Plot2Ascans_TimeFreq(Ascan_Ch2,Ascan_Ch1, nfft=nfft, FreqScale= 1e6, TimeScale=1, Fmax = 15,Fs=100e6,FigNum = 2)
# uf.Plot_Ascan_tf(Ascan_Ch2 , Units_t = 1e8, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 15, FigNum=1, FigTitle=SaveDir) #plot Ascan
plt.show()

WP = ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan

#%% Window signals to isolate TT - PE not needed in this scenario
# 1. Choose length os pulse
# 2. Find maximum of envelope of pulses
# 3. Make tukey window according to pulse length, ans span it to record length. Delay windows to pulse location
# 4. Window the pulse
MyWinLen = 301

PE_Ascan = Ascan_Ch2
# plt.plot(UVT.Envelope(Ascan_Ch1))
Env_Max_Loc = np.argmax( UVT.Envelope(Ascan_Ch1) )
# print(Env_Max_Loc)
MyWinDelay = Env_Max_Loc - MyWinLen/2
MyWin = UVT.MakeWindow(SortofWin='Tukey', WinLen=MyWinLen, param1=0.2, param2=1, Span=Win_Len, Delay=MyWinDelay)
# plt.plot(MyWin*np.max(abs(Ascan_Ch1)))
# plt.plot(Ascan_Ch1)
TT_Ascan = Ascan_Ch1 * MyWin
plt.plot(UVT.NormSig(TT_Ascan))

#%%
# Repeat for WP
WP = ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
uf.Plot_Ascan_tf(WP , Units_t = 1e8, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 15, FigNum=1, FigTitle=SaveDir) #plot Ascan
Env_Max_Loc = np.argmax( UVT.Envelope(WP) )
# print(Env_Max_Loc)
MyWinDelay = Env_Max_Loc - MyWinLen/2
MyWin = UVT.MakeWindow(SortofWin='Tukey', WinLen=MyWinLen, param1=0.2, param2=1, Span=Win_Len, Delay=MyWinDelay)
plt.plot(MyWin*np.max(abs(WP)))
plt.plot(WP)
WP_Ascan = WP * MyWin
plt.plot(WP_Ascan)


#%% Repeat to get Ref_PE
Env_Max_Loc = np.argmax( UVT.Envelope(PE_Ascan) )
# print(Env_Max_Loc)
MyWinDelay = Env_Max_Loc - MyWinLen/2
MyWin = UVT.MakeWindow(SortofWin='Tukey', WinLen=MyWinLen, param1=0.2, param2=1, Span=Win_Len, Delay=MyWinDelay)
# plt.plot(MyWin*np.max(abs(Ascan_Ch1)))
# plt.plot(Ascan_Ch1)
Ref_PE = PE_Ascan * MyWin
plt.plot(UVT.NormSig(Ref_PE))

#%% check signals
plt.plot(UVT.NormSig(TT_Ascan))
plt.plot(UVT.NormSig(PE_Ascan))
plt.plot(UVT.NormSig(WP_Ascan))


#%%

UseHilbEnv = True
Cl, L = UVT.LongVelocity_Thickness(PE_Ascan, TT_Ascan, WP_Ascan, Ref_PE, Fs, Cw, UseHilbEnv)
print(Cl)
print(L*1000)



