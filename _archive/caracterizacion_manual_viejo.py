# -*- coding: utf-8 -*-
"""

Sample characterization:
    Cl: Longitudinal speed of sound
    Cs: Shear speed of sound
    L = Thickness

@author: Alberto
"""

import sys

sys.path.insert(0, r"D:\PROJECTS_US\TOOLBOXES")
sys.path.insert(0, r"D:\PROJECTS_US\TOOLBOXES\ultrasound_velocity_tools_package")

# import sys
# print("\n".join(sys.path))



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

Ruta_dll = r"D:\PROJECTS_US\TOOLBOXES\SeDaqDLL.dll"

#%
########################################################
# constants
########################################################
Cw = 1500  # velocidad del sonido en m/s
Fs = 100.0e6 #D sampling frequency
ProgGenCLKfreqMHz=200.0 # CLK of the gencodes generator (internal CLOK, my guess)
ADC_CLKfreqMHz=100.0 # sampling CLOK (sampling frequency of the ACQ, my guess)


# Make dir to save data of the experiment
CurrentDir = r'D:\Prueba\MEDIDAS'
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



#%
########################################################################
# Initialize ACQ equipment, GenCode to use, and set all parameters
########################################################################
#RecLen = 32*1024 # max range of ACQ
RecLen = 16*1024 # max range of ACQ
# Gain_Ch2 = 0 #gain of channel 2 in dB
# Gain_Ch1 = 80 #gain of channel 1 in dB

Fp=5.0*1e6# Central frequency of the US pulse, MHz



# connect ACQ (32-bit architecture only)
SeDaq = SD.SeDaqDLL(Ruta_dll) 
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

#%
########################################################
# acquire and check signals
########################################################

# set gain. 
# Beware, if you change Ch1, Ch2 have to be reset again, this is a firmware bug
Gain_Ch1 = 65 #gain of channel 1 in dB
Gain_Ch2 = 32 #gain of channel 2 in dB
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

#%%
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import animation
from matplotlib.widgets import Slider, RadioButtons, Button
import matplotlib.gridspec as gridspec

# Estas variables deben estar definidas en tu entorno:
# Fs = frecuencia de muestreo (Hz)
# RecLen = longitud total de muestras
# Cw = velocidad del sonido (m/s)
# ACQ = objeto con métodos GetAscan_Ch1 y GetAscan_Ch2
# SeDaq = objeto con métodos SetGain1 y SetGain2

TipoEje = {'value': 'mus'}
Label_x_axis = 'Time [μs]'
N_SAMPLES_TOTAL = RecLen - 1
Gain_Ch1 = 65
Gain_Ch2 = 32

def units_to_samples(val):
    if TipoEje['value'] == 'mus':
        return int(round(val * 1e-6 * Fs))
    elif TipoEje['value'] == 'mm':
        return int(round(val * 2 / (Cw * 1e-3) * Fs))
    else:
        return int(round(val))

def samples_to_units(samples):
    if TipoEje['value'] == 'mus':
        return samples / Fs * 1e6
    elif TipoEje['value'] == 'mm':
        return samples / Fs * Cw / 2 * 1e3
    else:
        return samples

Smin_init = 0
Smax_init = 8500
MIN_RANGE_SAMPLES = 100
MIN_RANGE_UNITS = samples_to_units(MIN_RANGE_SAMPLES)

FullData_Ch1 = ACQ.GetAscan_Ch1(0, N_SAMPLES_TOTAL, AvgSamplesNumber=25, Quantiz_Levels=1024)
FullData_Ch2 = ACQ.GetAscan_Ch2(0, N_SAMPLES_TOTAL, AvgSamplesNumber=25, Quantiz_Levels=1024)
x_full_unit = samples_to_units(np.arange(len(FullData_Ch1)))
FullMin = min(np.min(FullData_Ch1), np.min(FullData_Ch2))
FullMax = max(np.max(FullData_Ch1), np.max(FullData_Ch2))

fig = plt.figure(figsize=(14, 7))
gs = gridspec.GridSpec(3, 1, height_ratios=[6, 0.8, 1])
plt.subplots_adjust(bottom=0.18, left=0.08, right=0.85, hspace=0.35)

ax_main = fig.add_subplot(gs[0])
ax_overview = fig.add_subplot(gs[1])

ArrayLen = Smax_init - Smin_init
x_axis_unit = samples_to_units(np.arange(ArrayLen) + Smin_init)

line_Ch1, = ax_main.plot(x_axis_unit, np.zeros(ArrayLen), label='Ch1', color='coral')
line_Ch2, = ax_main.plot(x_axis_unit, np.zeros(ArrayLen), label='Ch2', color='blue')
ax_main.set_ylim(-0.5, 0.5)
ax_main.set_xlim(x_axis_unit[0], x_axis_unit[-1])
ax_main.set_xlabel(Label_x_axis)
ax_main.set_ylabel("Amplitude")
ax_main.set_title("Real-Time Signal Plot")
ax_main.legend()

ax_overview.plot(x_full_unit, FullData_Ch1, color='coral', alpha=0.3, label='Ch1')
ax_overview.plot(x_full_unit, FullData_Ch2, color='blue', alpha=0.3, label='Ch2')
ax_overview.set_xlim(x_full_unit[0], x_full_unit[-1])
ax_overview.set_ylim(FullMin, FullMax)
line_vmin = ax_overview.axvline(samples_to_units(Smin_init), color='red', linestyle='--')
line_vmax = ax_overview.axvline(samples_to_units(Smax_init), color='red', linestyle='--')
ax_overview.set_ylabel("Overview")
ax_overview.set_xlabel(Label_x_axis)
ax_overview.set_yticks([])
ax_overview.legend(loc='upper right', fontsize='small')

# Sombreado del rango seleccionado en ax_main
shade_range = ax_main.axvspan(slider_smin.val, slider_smax.val, color='gray', alpha=0.1)

def update_shade():
    shade_range.set_xy([[slider_smin.val, ax_main.get_ylim()[0]],
                        [slider_smin.val, ax_main.get_ylim()[1]],
                        [slider_smax.val, ax_main.get_ylim()[1]],
                        [slider_smax.val, ax_main.get_ylim()[0]],
                        [slider_smin.val, ax_main.get_ylim()[0]]])

# Sliders de zoom horizontal
ax_smin = plt.axes([0.08, 0.10, 0.77, 0.03])
ax_smax = plt.axes([0.08, 0.05, 0.77, 0.03])
unit_min = samples_to_units(0)
unit_max = samples_to_units(N_SAMPLES_TOTAL)
slider_smin = Slider(ax_smin, f'Start ({Label_x_axis})', unit_min, unit_max - MIN_RANGE_UNITS, valinit=samples_to_units(Smin_init), valstep=1)
slider_smax = Slider(ax_smax, f'End ({Label_x_axis})', unit_min + MIN_RANGE_UNITS, unit_max, valinit=samples_to_units(Smax_init), valstep=1)

def validate_slider_range(val):
    smin = slider_smin.val
    smax = slider_smax.val
    if smin >= smax - MIN_RANGE_UNITS:
        if val == smin:
            slider_smin.set_val(smax - MIN_RANGE_UNITS)
        else:
            slider_smax.set_val(smin + MIN_RANGE_UNITS)
    line_vmin.set_xdata(samples_to_units(units_to_samples(slider_smin.val)))
    line_vmax.set_xdata(samples_to_units(units_to_samples(slider_smax.val)))
    update_shade()

slider_smin.on_changed(validate_slider_range)
slider_smax.on_changed(validate_slider_range)

# Menú desplegable de unidades
ax_radio = plt.axes([0.92, 0.12, 0.07, 0.1])
radio_buttons = RadioButtons(ax_radio, ('samples', 'mus', 'mm'), active=1)

def on_axis_change(label):
    tipo_anterior = TipoEje['value']
    TipoEje['value'] = tipo_anterior
    Smin_samples = units_to_samples(slider_smin.val)
    Smax_samples = units_to_samples(slider_smax.val)

    TipoEje['value'] = label
    smin_unit = samples_to_units(Smin_samples)
    smax_unit = samples_to_units(Smax_samples)

    global Label_x_axis, MIN_RANGE_UNITS
    if label == 'mm':
        Label_x_axis = 'Distance [mm]'
    elif label == 'mus':
        Label_x_axis = 'Time [μs]'
    else:
        Label_x_axis = 'Samples'

    ax_main.set_xlabel(Label_x_axis)
    ax_overview.set_xlabel(Label_x_axis)
    slider_smin.label.set_text(f'Start ({Label_x_axis})')
    slider_smax.label.set_text(f'End ({Label_x_axis})')

    MIN_RANGE_UNITS = samples_to_units(MIN_RANGE_SAMPLES)
    unit_min = samples_to_units(0)
    unit_max = samples_to_units(N_SAMPLES_TOTAL)

    slider_smin.valmin = unit_min
    slider_smin.valmax = unit_max - MIN_RANGE_UNITS
    slider_smax.valmin = unit_min + MIN_RANGE_UNITS
    slider_smax.valmax = unit_max

    slider_smin.set_val(smin_unit)
    slider_smax.set_val(smax_unit)
    ax_main.set_xlim(smin_unit, smax_unit)
    fig.canvas.draw_idle()

radio_buttons.on_clicked(on_axis_change)

# Sliders verticales de ganancia
ax_gain1 = plt.axes([0.92, 0.38, 0.015, 0.5])
ax_gain2 = plt.axes([0.945, 0.38, 0.015, 0.5])
slider_gain1 = Slider(ax_gain1, "Ch1\nGain", 20, 90, valinit=Gain_Ch1, orientation='vertical')
slider_gain2 = Slider(ax_gain2, "Ch2\nGain", 20, 90, valinit=Gain_Ch2, orientation='vertical')

def update_gain1(val):
    global Gain_Ch1, Gain_Ch2
    Gain_Ch1 = int(val)
    SeDaq.SetGain1(Gain_Ch1)
    SeDaq.SetGain2(Gain_Ch2)

def update_gain2(val):
    global Gain_Ch2
    Gain_Ch2 = int(val)
    SeDaq.SetGain2(Gain_Ch2)

slider_gain1.on_changed(update_gain1)
slider_gain2.on_changed(update_gain2)

# Botones PE-TT y WaterPath
ax_button_pett = plt.axes([0.92, 0.28, 0.07, 0.045])
ax_button_wp = plt.axes([0.92, 0.22, 0.07, 0.045])
button_pett = Button(ax_button_pett, 'PE-TT')
button_wp = Button(ax_button_wp, 'WaterPath')

def on_click_pett(event):
    global PE_Ascan, TT_Ascan
    Smin = units_to_samples(slider_smin.val)
    Smax = units_to_samples(slider_smax.val)
    PE_Ascan = np.array(ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber=25, Quantiz_Levels=1024))
    TT_Ascan = np.array(ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber=25, Quantiz_Levels=1024))
    print(f"PE_Ascan and TT_Ascan saved: {len(PE_Ascan)} samples")

def on_click_wp(event):
    global WP_Ascan
    Smin = units_to_samples(slider_smin.val)
    Smax = units_to_samples(slider_smax.val)
    WP_Ascan = np.array(ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber=25, Quantiz_Levels=1024))
    print(f"WP_Ascan saved: {len(WP_Ascan)} samples")

button_pett.on_clicked(on_click_pett)
button_wp.on_clicked(on_click_wp)

# Animación en tiempo real
def update(frame):
    Smin = units_to_samples(slider_smin.val)
    Smax = units_to_samples(slider_smax.val)
    ArrayLen = Smax - Smin
    if ArrayLen <= 0 or ArrayLen > 50000:
        return line_Ch1, line_Ch2

    offset_units = samples_to_units(Smin)
    x_axis_unit = offset_units + samples_to_units(np.arange(ArrayLen))

    signal_buffer_Ch1 = np.array(ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber=25, Quantiz_Levels=1024))
    signal_buffer_Ch2 = np.array(ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber=25, Quantiz_Levels=1024))

    line_Ch1.set_xdata(x_axis_unit)
    line_Ch1.set_ydata(signal_buffer_Ch1)
    line_Ch2.set_xdata(x_axis_unit)
    line_Ch2.set_ydata(signal_buffer_Ch2)
    ax_main.set_xlim(x_axis_unit[0], x_axis_unit[-1])
    ax_main.set_xlabel(Label_x_axis)
    line_vmin.set_xdata(x_axis_unit[0])
    line_vmax.set_xdata(x_axis_unit[-1])
    update_shade()
    return line_Ch1, line_Ch2

interval_ms = int(1000 * ArrayLen / Fs)
ani = animation.FuncAnimation(fig, update, interval=interval_ms, blit=False)

# Cursor
cursor_line = ax_main.axvline(x=0, color='gray', linestyle='--', linewidth=0.8, alpha=0.6)
cursor_text = ax_main.text(0.02, 0.95, '', transform=ax_main.transAxes, fontsize=9,
                           verticalalignment='top', bbox=dict(facecolor='white', edgecolor='gray', alpha=0.6))

def on_mouse_move(event):
    if event.inaxes != ax_main:
        cursor_line.set_visible(False)
        cursor_text.set_visible(False)
        fig.canvas.draw_idle()
        return

    x_val = event.xdata
    if x_val is None:
        return

    cursor_line.set_xdata(x_val)
    cursor_line.set_visible(True)

    if TipoEje['value'] == 'mus':
        label = f"t = {x_val:.1f} μs"
    elif TipoEje['value'] == 'mm':
        label = f"d = {x_val:.2f} mm"
    else:
        label = f"s = {x_val:.0f} samples"

    cursor_text.set_text(label)
    cursor_text.set_visible(True)
    fig.canvas.draw_idle()

fig.canvas.mpl_connect('motion_notify_event', on_mouse_move)

plt.show()

#%%

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import TextBox, Button

# Estas funciones deben estar definidas en tu entorno:
# - UVT.Envelope(signal): calcula la envolvente
# - UVT.MakeWindow(...): genera la ventana de Tukey personalizada

# Señales de entrada (asegúrate de tenerlas cargadas en tu entorno)
# TT_Ascan = ...
# PE_Ascan = ...
# WP_Ascan = ...

# Valor inicial de longitud de ventana
MyWinLen = 200

fig, axs = plt.subplots(3, 1, figsize=(10, 7), sharex=True)
plt.subplots_adjust(left=0.1, bottom=0.25, hspace=0.35)

# Función para normalizar y graficar señales y ventanas
def plot_signals(win_len):
    axs[0].cla()
    axs[1].cla()
    axs[2].cla()

    signals = [TT_Ascan, PE_Ascan, WP_Ascan]
    titles = ['TT_Ascan', 'PE_Ascan', 'WP_Ascan']

    for ax, signal, title in zip(axs, signals, titles):
        env = UVT.Envelope(signal)
        max_loc = np.argmax(env)
        delay = max_loc - win_len // 2
        win = UVT.MakeWindow('Tukey', WinLen=win_len, param1=0.2, param2=1, Span=len(signal), Delay=delay)

        # Normalización para visualización
        signal_norm = signal / np.max(np.abs(signal))
        win_norm = win / np.max(win)

        ax.plot(signal_norm, label='Señal normalizada', alpha=0.6)
        ax.plot(win_norm, label='Ventana Tukey', linestyle='--')
        ax.set_title(f'{title} (max env @ {max_loc})')
        ax.set_ylabel('Amplitud')
        ax.legend()
        ax.grid(True)

    axs[2].set_xlabel('Muestras')
    fig.canvas.draw_idle()

# Función al cambiar el texto del TextBox
def submit_text(text):
    global MyWinLen
    try:
        val = int(text)
        if val > 0:
            MyWinLen = val
            plot_signals(MyWinLen)
    except ValueError:
        pass

# Función al pulsar el botón "Enventanar"
def on_click_enventanar(event):
    global TT_Ascan_win, PE_Ascan_win, WP_Ascan_win

    Env_Max_TT = np.argmax(UVT.Envelope(TT_Ascan))
    Delay_TT = Env_Max_TT - MyWinLen // 2
    Win_TT = UVT.MakeWindow('Tukey', WinLen=MyWinLen, param1=0.2, param2=1, Span=len(TT_Ascan), Delay=Delay_TT)
    TT_Ascan_win = TT_Ascan * Win_TT

    Env_Max_PE = np.argmax(UVT.Envelope(PE_Ascan))
    Delay_PE = Env_Max_PE - MyWinLen // 2
    Win_PE = UVT.MakeWindow('Tukey', WinLen=MyWinLen, param1=0.2, param2=1, Span=len(PE_Ascan), Delay=Delay_PE)
    PE_Ascan_win = PE_Ascan * Win_PE

    Env_Max_WP = np.argmax(UVT.Envelope(WP_Ascan))
    Delay_WP = Env_Max_WP - MyWinLen // 2
    Win_WP = UVT.MakeWindow('Tukey', WinLen=MyWinLen, param1=0.2, param2=1, Span=len(WP_Ascan), Delay=Delay_WP)
    WP_Ascan_win = WP_Ascan * Win_WP

    print(f"Enventanado con ventana de {MyWinLen} muestras.")

# TextBox para entrada de longitud de ventana
axbox = plt.axes([0.1, 0.12, 0.3, 0.05])
text_box = TextBox(axbox, 'Longitud de ventana:', initial=str(MyWinLen))
text_box.on_submit(submit_text)

# Botón para enventanar
ax_button = plt.axes([0.45, 0.12, 0.15, 0.05])
button = Button(ax_button, 'Enventanar')
button.on_clicked(on_click_enventanar)

# Dibujo inicial
plot_signals(MyWinLen)
plt.show()



#%% Get PE and TT Ascans to analyse before windowing
Smin = 4620# starting point of the analysis (ACQ range)
# Smax = RecLen # Last point of the analysis (ACQ range)
Smax = 8500  # Last point of the analysis (ACQ range)
ArrayLen = Smax-Smin # lentgh of the Ascans

Ascan_Ch2 = ACQ.GetAscan_Ch2(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
Ascan_Ch1 = ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan

# plot
US.Plot2Ascans_TimeFreq(Ascan_Ch2,Ascan_Ch1, nfft=nfft, FreqScale= 1e6, TimeScale=1, Fmax = 15,Fs=100e6,FigNum = 2)
# uf.Plot_Ascan_tf(Ascan_Ch2 , Units_t = 1e8, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 15, FigNum=1, FigTitle=SaveDir) #plot Ascan
plt.show()

#%% Window signals to isolate TT - PE not needed in this scenario
# 1. Choose length os pulse, fot this, select the length of the main echo in the PE signal
# 2. Find maximum of envelope of pulses
# 3. Make tukey window according to pulse length, ans span it to record length. Delay windows to pulse location
# 4. Window the pulse
MyWinLen = 200

PE_Ascan = Ascan_Ch2
# plt.plot(UVT.Envelope(Ascan_Ch1))
Env_Max_Loc = np.argmax( UVT.Envelope(TT_Ascan) )
MyWinDelay = Env_Max_Loc - MyWinLen/2
MyWin = UVT.MakeWindow(SortofWin='Tukey', WinLen=MyWinLen, param1=0.2, param2=1, Span=len(TT_Ascan), Delay=MyWinDelay)


# print(Env_Max_Loc)
# plt.plot(MyWin*np.max(abs(Ascan_Ch1)))
# plt.plot(Ascan_Ch1)
TT_Ascan = Ascan_Ch1 * MyWin


# plot resulting wondowed PE and TT siognals includnig windows, to check if all is correct
fig, axs = plt.subplots(2, 1)  # 1 fila, 2 columnas

# Primer subplot
axs[0].plot(UVT.NormSig(Ascan_Ch1))
axs[0].plot(UVT.NormSig(MyWin))
axs[0].set_title('TT')

# Segundo subplot
axs[1].plot(UVT.NormSig(TT_Ascan))

axs[1].set_title('Windowed TT')

# Ajustar diseño
plt.tight_layout()
plt.show()



#%%
# Repeat for WP
WP = ACQ.GetAscan_Ch1(Smin, Smax, AvgSamplesNumber = 25, Quantiz_Levels = 1024) #acq Ascan
uf.Plot_Ascan_tf(WP , Units_t = 1e8, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 15, FigNum=1, FigTitle=SaveDir) #plot Ascan
Env_Max_Loc = np.argmax( UVT.Envelope(WP) )
# print(Env_Max_Loc)
MyWinDelay = Env_Max_Loc - MyWinLen/2
MyWin = UVT.MakeWindow(SortofWin='Tukey', WinLen=MyWinLen, param1=0.2, param2=1, Span=ArrayLen, Delay=MyWinDelay)
WP_Ascan = WP * MyWin


fig, axs = plt.subplots(2, 1)  # 1 fila, 2 columnas

# Primer subplot
axs[0].plot(UVT.NormSig(WP))
axs[0].plot(UVT.NormSig(MyWin))
axs[0].set_title('WP')

# Segundo subplot
axs[1].plot(UVT.NormSig(WP_Ascan))

axs[1].set_title('Windowed WP')

# Ajustar diseño
plt.tight_layout()
plt.show()


#%% Repeat to get Ref_PE
Env_Max_Loc = np.argmax( UVT.Envelope(PE_Ascan) )
# print(Env_Max_Loc)
MyWinDelay = Env_Max_Loc - MyWinLen/2
MyWin = UVT.MakeWindow(SortofWin='Tukey', WinLen=MyWinLen, param1=0.2, param2=1, Span=ArrayLen, Delay=MyWinDelay)
# plt.plot(MyWin*np.max(abs(Ascan_Ch1)))
# plt.plot(Ascan_Ch1)
Ref_PE = PE_Ascan * MyWin


fig, axs = plt.subplots(2, 1)  # 1 fila, 2 columnas

# Primer subplot
axs[0].plot(UVT.NormSig(PE_Ascan))
axs[0].plot(UVT.NormSig(MyWin))
axs[0].set_title('WP')

# Segundo subplot
axs[1].plot(UVT.NormSig(Ref_PE))

axs[1].set_title('Windowed WP')

# Ajustar diseño
plt.tight_layout()
plt.show()

#%% check signals
# plt.plot(UVT.NormSig(TT_Ascan))
# plt.plot(UVT.NormSig(PE_Ascan))
# plt.plot(UVT.NormSig(WP_Ascan))
# plt.plot(UVT.NormSig(Ref_PE))

fig, axs = plt.subplots(4, 1)  # 1 fila, 2 columnas

# Primer subplot
axs[0].plot(UVT.NormSig(PE_Ascan))
axs[0].set_title('PE')

# Segundo subplot
axs[1].plot(UVT.NormSig(TT_Ascan_win))
axs[1].set_title('TT')


# Segundo subplot
axs[2].plot(UVT.NormSig(WP_Ascan_win))
axs[2].set_title('WP')

# Segundo subplot
axs[3].plot(UVT.NormSig(PE_Ascan_win))
axs[3].set_title('Ref')

# Ajustar diseño
plt.tight_layout()
plt.show()

#%%

UseHilbEnv = True
Cl, L = UVT.LongVelocity_Thickness(PE_Ascan, TT_Ascan_win, WP_Ascan_win, PE_Ascan_win, Fs, Cw, UseHilbEnv)
print(Cl)
print(L*1000)

