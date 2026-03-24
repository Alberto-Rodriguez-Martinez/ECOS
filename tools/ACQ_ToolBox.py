'''
Tool Box to control and acquiare signals using KTU hardware
13/02/2019
Alberto Rodriguez
'''

import numpy as np
from SeDaq import *
import matplotlib.pylab as plt
#import winsound

''' Get Ascans '''
#Get Ascans ->
def GetAscan_Ch2(Smin, Smax, AvgSamplesNumber = 10, Quantiz_Levels = 1024):
    '''Get Ascan fomr channel 2 only, and extract data between Smin and Smax
    and normalizes according to quantization levels, and averages according to 
    number of samples acquired at each point
        Inputs
            Sedaq = acq object
            Smin = First sample
            Smax = Last Sample
            AvgSamplesNumber = Number of Ascan to average in each acq
            Quantiz_Levels = Number of levels of acq (2^B)
            
        Outputs
            AscanCh2 = acquired ascans
    '''
    SeDaq = SeDaqDLL()
    Ascan_Ch2 = np.zeros(Smax-Smin)
    Flag = AvgSamplesNumber

    while Flag > 0:
        SeDaq.GetAScan() #get Ascan        
        Aux_Ch2 = np.array(list(map(float,SeDaq.DataADC2[Smin:Smax]))) #get Ascan WP
        Aux_Ch2 = (Aux_Ch2 - Quantiz_Levels/2)/Quantiz_Levels # Normalize 
        Aux_Ch2 = Aux_Ch2 - np.mean(Aux_Ch2) # remove mean
        
        if not(np.all(Aux_Ch2==0.0)):	            
            Ascan_Ch2 = Ascan_Ch2 + Aux_Ch2		
            Flag -= 1
            		
    Ascan_Ch2 = Ascan_Ch2 / AvgSamplesNumber #calculate averaged Ascan
    Ascan_Ch2 = Ascan_Ch2 - np.mean(Ascan_Ch2) #substract mean value
    return Ascan_Ch2

def GetAscan_Ch1(Smin, Smax, AvgSamplesNumber = 10, Quantiz_Levels = 1024):
    '''Get Ascan fomr channel 1 only, and extract data between Smin and Smax
    and normalizes according to quantization levels, and averages according to 
    number of samples acquired at each point
        Inputs
            Sedaq = acq object
            Smin = First sample
            Smax = Last Sample
            AvgSamplesNumber = Number of Ascan to average in each acq
            Quantiz_Levels = Number of levels of acq (2^B)
            
        Outputs
            AscanCh2 = acquired ascans
    '''
    SeDaq = SeDaqDLL()
    Ascan_Ch1 = np.zeros(Smax-Smin)
    Flag = AvgSamplesNumber
    while Flag > 0:
        SeDaq.GetAScan() #get Ascan        
        Aux_Ch1 = np.array(list(map(float,SeDaq.DataADC1[Smin:Smax]))) #get Ascan WP
        Aux_Ch1 = (Aux_Ch1 - Quantiz_Levels/2)/Quantiz_Levels # Normalize 
        Aux_Ch1 = Aux_Ch1 - np.mean(Aux_Ch1) # remove mean
        
        if not(np.all(Aux_Ch1==0.0)):	            
            Ascan_Ch1 = Ascan_Ch1 + Aux_Ch1		
            Flag -= 1
            		
    Ascan_Ch1 = Ascan_Ch1 / AvgSamplesNumber #calculate averaged Ascan
    Ascan_Ch1 = Ascan_Ch1 - np.mean(Ascan_Ch1) #substract mean value
    return Ascan_Ch1

def GetAscan_Ch1_Ch2(Smin, Smax, AvgSamplesNumber = 10, Quantiz_Levels = 1024):
    '''Get Ascans. It checks that Ascans are not zeroes, because sometimes happens...
        Inputs
            Sedaq = acq object
            Smin = First sample
            Smax = Last Sample
            AvgSamplesNumber = Number of Ascan to average in each acq
            Quantiz_Levels = Number of levels of acq (2^B)
            
        Outputs
            AscanCh1, AscanCh2 = acquired ascans
            
    '''
    SeDaq = SeDaqDLL()
    Ascan_Ch2 = np.zeros(Smax-Smin)
    Ascan_Ch1 = np.zeros(Smax-Smin)
    Flag = AvgSamplesNumber
    while Flag > 0:
        SeDaq.GetAScan() #get Ascan        
        Aux_Ch2 = np.array(map(float,SeDaq.DataADC2[Smin:Smax])) #get Ascan PE
        Aux_Ch2 = (Aux_Ch2 - Quantiz_Levels/2)/Quantiz_Levels # Normalize 
        Aux_Ch2 = Aux_Ch2 - np.mean(Aux_Ch2) # remove mean
        Aux_Ch1 = np.array(map(float,SeDaq.DataADC1[Smin:Smax])) #get Ascan TT
        Aux_Ch1 = (Aux_Ch1 - Quantiz_Levels/2)/Quantiz_Levels # Normalize 
        Aux_Ch1 = Aux_Ch1 - np.mean(Aux_Ch2) # remove mean
        
        if not(np.all(Aux_Ch2==0.0)) and not(np.all(Aux_Ch1==0.0)):	            
            Ascan_Ch2 = Ascan_Ch2 + Aux_Ch2
            Ascan_Ch1 = Ascan_Ch1 + Aux_Ch1
            Flag -= 1
            		
    Ascan_Ch2 = Ascan_Ch2 / AvgSamplesNumber #calculate averaged Ascan
    Ascan_Ch2 = Ascan_Ch2 - np.mean(Ascan_Ch2) #substract mean value
    Ascan_Ch1 = Ascan_Ch1 / AvgSamplesNumber #calculate averaged Ascan
    Ascan_Ch1 = Ascan_Ch1 - np.mean(Ascan_Ch1) #substract mean value
    return Ascan_Ch1, Ascan_Ch2
	
def Plot_Ascan_tf(Ascan, Units_t = 1e6, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 50e6, FigNum=1, FigTitle='Original Ascan'):
    '''Plots Ascan in time and frequency, between Fmin and Fmax
    Units_t is constant to normalize time axis
    Units_F is constant to normalize frequency axis
    Fs sampling frequency
    Fmin lower limit, considering Units_F
    Fmax upper limit, considering Units_F
    '''
    Time_Axis = np.arange(0, Ascan.size)/Fs*Units_t
    fig, axs = plt.subplots(2, 1, num=FigNum, clear=True)
    axs[0].plot(Time_Axis, Ascan)
#    axs[0].set_title(FigTitle)
    axs[0].set_xlabel('time (us)')
    axs[0].set_ylabel('Ascan')
    # calculate fft
    MyFFT = np.fft.fft(Ascan)
    Freq_Axis = np.arange(0, MyFFT.size)*Fs/MyFFT.size/Units_F
    # freq subplot
    axs[1].plot(Freq_Axis, np.abs(MyFFT))
    axs[1].set_xlabel('frequency (MHz)')
#    axs[1].set_title('subplot 2')
    axs[1].set_ylabel('FFT')
    axs[1].set_xlim(Fmin,Fmax)    
    fig.suptitle(FigTitle)
    fig.tight_layout()
    plt.show()

def GenCodeList_Info(FileName):
    '''Load information from GenCode list, according to its ionner format
    Input
       FileName: Name of the file, including full path
    Outputs
       Name: Name of the gencode
       Sort: Sort of excitation, text ('chirp','pulse','burst')
       ProgGenCLKfreqMHz: ProgGenCLKfreqMHz, float
       F1: Lower (chirp) or central (burst, pulse) frequency in MHz, float
       F2: higher (chirp) or central (burst, pulse) frequency in MHz, float
       Cycles: number of cycles of the burst, float
       Duration: Duration of the signal, us, float
       Polarity: Polarity of the pulse (-1, 1, 2), integer    
    '''
    try:
        GenCodeList = np.loadtxt(FileName, dtype={'names': ('Name', 'Sort', 'Fclk', 'F1','F2','NCyc','Dur','Pol'),
                     'formats': ('S10', 'S5','f','f','f','f','f','int')}, delimiter=';')
        titulo=[]
        for GNo in range(GenCodeList.size):
            if GenCodeList[GNo][1]=='chirp':
                patata=str(GenCodeList[GNo][0]) + ': ' + str(GenCodeList[GNo][1]) + ' BW(MHz)=[' + str(GenCodeList[GNo][3]) + ',' +\
                str(GenCodeList[GNo][4]) + '] ' + u'\u0394\u03C4=' + str(GenCodeList[GNo][6]) + u'\u03BCs'
            
            elif GenCodeList[GNo][1]=='burst':
                patata = str(GenCodeList[GNo][0]) + ': ' + str(GenCodeList[GNo][1]) + ' Fc=' + str(GenCodeList[GNo][3]) + \
                'MHz NoCycles=' + str(GenCodeList[GNo][5]) + u' \u0394\u03C4=' + str(GenCodeList[GNo][6]) + u'\u03BCs'
            else:
                patata = str(GenCodeList[GNo][0]) + ': ' + str(GenCodeList[GNo][1]) + ' Fc=' + str(GenCodeList[GNo][3])  +\
                'MHz ' + u'\u0394\u03C4=' + str(GenCodeList[GNo][6]) + u'\u03BCs'
            titulo.append(patata)
        return GenCodeList, titulo
    except Exception as e:
        print(e)
        return ''
                