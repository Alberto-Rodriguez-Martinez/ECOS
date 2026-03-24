# -*- coding: utf-8 -*-
"""
Created on Feb 2019

Toolbox for Ultrasonic Signal Processing

@author: Alberto
"""

import numpy as np
from scipy import signal
import matplotlib.pyplot as plt


# Gencode object
class genCode:
    def __init__(self, GenCodeName, PulseBandwidthRatio = 0.5):
        MyGC = GenCodeName
        GC_data = MyGC.split('_')
        self.Name = GenCodeName
        self.Transducer = GC_data[1]
        self.Excitation = GC_data[2]
        if self.Excitation.lower() == 'Chirp'.lower():
            self.Fl = float(GC_data[4]) * 1e6 #lower frequency MHz
            self.Fh = float(GC_data[5]) * 1e6 #higher frequency MHz
            self.Fc = (self.Fl + self.Fh )/2 # central frequency MHz
            LastIndx = GC_data[3].find('us')
            self.Dur = float(GC_data[3][:LastIndx]) * 1e-6 #duration of the pulse in seconds
        elif self.Excitation.lower() == 'APWP'.lower():
            self.Fl = float(GC_data[6]) * 1e6
            self.Fh = float(GC_data[7]) * 1e6
            self.Fc = (self.Fl + self.Fh )/2 # central frequency MHz
            self.Original_Fl = float(GC_data[3]) * 1e6 # original chirp Fl
            self.Original_Fh = float(GC_data[4]) * 1e6 # original chirp Fh
            self.Original_Fc = (self.Original_Fl + self.Original_Fh )/2 # Original chirp central frequency MHz
            LastIndx = GC_data[5].find('us')
            self.Dur = float(GC_data[5][:LastIndx]) * 1e-6 #duration of the pulse in seconds
        elif self.Excitation.lower() == 'Pulse'.lower():
            self.Fc = float(GC_data[3]) * 1e6 # central frequency MHz
            self.Fl = self.Fc - self.Fc * PulseBandwidthRatio #estimated Fl
            self.Fh = self.Fc + self.Fc * PulseBandwidthRatio # estimated Fh
            self.Dur = 1/self.Fl # estimated duration in seconds
        elif self.Excitation.lower() == 'Burst'.lower():
            self.Fc = float(GC_data[3]) * 1e6 # central frequency MHz
            self.Fl = self.Fc - self.Fc * PulseBandwidthRatio #estimated Fl
            self.Fh = self.Fc + self.Fc * PulseBandwidthRatio # estimated Fh
            self.Cyc = float(GC_data[4])
            self.Dur = 1/self.Fc * self.Cyc
        
    def loadGenCode(self, FilePath):
        '''
        load gencode from file
        '''
        self.Gencode = np.fromfile(FilePath + "/" + self.Name + ".txt", dtype=float, count=-1, sep='\n') # load gencode
        self.FileName = FilePath + "/" + self.Name + ".txt"
            
# creates gaussian filter bank, classic, all the same bandwidth
class GaussFilterBank:
    def __init__(self, ScanLength = 1024, SamplingFrequency = 100e6,
                 CentralFrerquency = 5e6, BandWidth = 2.5e6, PulseCutPower = -6, PulseDecayTime = -60,
                 BandOverlap = 0.5, NumberOfFilters = 5):
        self.FilterModel = 'Gaussian' # Model of filter     
        self.SamplingFrequency = SamplingFrequency
        self.ScanLength = ScanLength
        self.MainCentralFrerquency = CentralFrerquency
        self.MainBandWidth = BandWidth
        self.PulseCutPower = PulseCutPower
        self.PulseDecayTime = PulseDecayTime
        self.NumberOfFilters = NumberOfFilters
        self.BandOverlap = BandOverlap
        self.RawBankBandWidth = self.MainBandWidth / self.NumberOfFilters # Bandwidth of each filter
        self.BankCentralFrerquencies = np.arange(self.MainCentralFrerquency - self.MainBandWidth / 2 + self.RawBankBandWidth / 2,
                                                 self.MainCentralFrerquency + self.MainBandWidth / 2 + self.RawBankBandWidth / 2,
                                                 self.RawBankBandWidth)
        self.BankBandWidth = self.RawBankBandWidth * self.BandOverlap / 0.5
        self.RelativeBandBandWidths = self.BankBandWidth / self.BankCentralFrerquencies
        
        self.MyGausPulseRaw = np.zeros((self.ScanLength, self.NumberOfFilters))
#        print self.BankCentralFrerquencies.size
#        print self.RelativeBandBandWidths.size
#        print self.BankCentralFrerquencies
        for i in range(self.NumberOfFilters):
            self.MyGausPulseRaw[:,i], _ = GaussPulseFilter(SigLength=self.ScanLength, Fs=self.SamplingFrequency,
                                                        Fc = self.BankCentralFrerquencies[i], AW = self.RelativeBandBandWidths[i],
                                                        BWR = self.PulseCutPower, TPE = self.PulseDecayTime)
#    def zero_phase_bank(self):
#        if not self.ZeroPhase:
#            self.ZeroPhasedBank = np.zeros_like(self.MyGausPulseRaw)
#            for i in range(self.NumberOfFilters):
#                self.ZeroPhasedBank[:,i], _ = ZeroPhasing(self.MyGausPulseRaw[:,i])
#            self.ZeroPhase = True
            
    def make_bank_ft(self, ZeroPhase = False, Expand = True):        
        self.Expand = Expand
        self.ZeroPhase = ZeroPhase
        
        if self.Expand:
            FTBank = np.concatenate((self.MyGausPulseRaw, np.zeros_like(self.MyGausPulseRaw)))        
        else:
            FTBank = self.MyGausPulseRaw
        self.FTBank = np.zeros_like(FTBank, dtype=np.complex128)
        if ZeroPhase:
            for i in range(self.NumberOfFilters):
                FTBank[:,i], _ = ZeroPhasing(FTBank[:,i])
                self.FTBank[:,i] = np.fft.fft(FTBank[:,i])
        else:
            for i in range(self.NumberOfFilters):
                self.FTBank[:,i] = np.fft.fft(FTBank[:,i])
        

    def plot_bank_ft(self,Nfft = 1024, FigNum = 1,fscale = 1e-6, Logaritmic = False, Normalized = True,
                     MinF = 0, MaxF = 100e6, labelX = 'Frequency (MHz)', ZeroPhase = True, GridOn = True):
        
        if Nfft > self.ScanLength:
            Bank = np.concatenate((self.MyGausPulseRaw, np.zeros((Nfft - self.ScanLength, self.NumberOfFilters))))
        else:
            Nfft = self.ScanLength
            Bank = self.MyGausPulseRaw
        
        Faxis = np.arange(0,self.SamplingFrequency,self.SamplingFrequency / Nfft) * fscale        
        FTBank = np.zeros_like(Bank, dtype=np.complex128)
        FFT_Angle = np.zeros_like(FTBank)
        if ZeroPhase:
            for i in range(self.NumberOfFilters):
                Bank[:,i], _ = ZeroPhasing(Bank[:,i])
                FTBank[:,i] = np.fft.fft(Bank[:,i])
        else:
            for i in range(self.NumberOfFilters):                
                FTBank[:,i] = np.fft.fft(Bank[:,i])
        if Normalized:
            FTBank = FTBank/np.absolute(np.max(np.max(FTBank)))
        FFT_Angle = np.angle(FTBank)
        
        plt.subplot(211)

        for i in range(self.NumberOfFilters):
            plt.plot(Faxis, np.absolute(FTBank[:,i]))  
        plt.xlabel(labelX)
        plt.ylabel('Magnitude Spectrum')    
        plt.xlim( (MinF * fscale,MaxF * fscale) )
        if GridOn:
            plt.grid()   
        
        plt.subplot(212)
        for i in range(self.NumberOfFilters):
            plt.plot(Faxis, FFT_Angle[:,i]) 
        plt.xlabel(labelX)
        plt.ylabel('Phase Spectrum')    
        plt.xlim( (MinF*fscale,MaxF*fscale) )
        if GridOn:
            plt.grid()     
        
        plt.tight_layout()
        plt.show()


# This function shifts a signal (delay) in a subsample basis using the fft. 
# Its is based in the modulation of the frequency domain which results in a delay in time domain
def ShiftSubsampleByfft( MySignal, Delay ): 
    # Signal is the input signal to be delayed
    # Delay is the delay to be aplied in a subsample basis
    N = MySignal.size # signal length
    HalfN = np.floor(N/2) # length of the semi-frequency axis in frequency domain
    FAxis1 = np.arange(HalfN + 1) / N # Positive semi-frequency axis
    FAxis2 = ( np.arange(HalfN+2, N+1, 1) - ( N + 1) )/ N # Negative semi-frequency axis
    FAxis = np.concatenate((FAxis1, FAxis2)) # Full reordered frequency axis
#    FT_Signal = np.fft.fft(Signal) # calculates the fft of the input signal
#    Mod = np.exp(1j*2*np.pi*FAxis*Delay) # creates the modulator
#    Mod_FT = FT_Signal * Mod    # modulates the fft of the input signal
#    Shifted_Signal = np.real( np.fft.ifft( Mod_FT ) ); # calculate the delayed signal intime as the inverse fft of the signal
    
    #Returned value is the delayed or shifted signal
    return np.real( np.fft.ifft( np.fft.fft(MySignal) * np.exp(1j*2*np.pi*FAxis*Delay) ) )


# filtering using fft with all the filters of the bank
def SS_filter_ZeroPhase(FTSignal, FTBank, ScanLength):
    # FTSignal = spectra of the input signal
    # FTSignal = spectra of the filter bank
    # ScanLength = scan length in samples
    FilteredSignal = np.zeros((ScanLength, FTBank.shape[1]))
    for i in range(FTBank.shape[1]):        
        Aux = np.fft.ifft(FTSignal * FTBank[:,i])
        FilteredSignal[:,i] = Aux[0:ScanLength].real
    return FilteredSignal


# This function calculates the maxima location in subsample basis using cosine interpolation
def CosineInterpMax(MySignal, UseHilbEnv = False):
    # MySignal = the input signal    
    # UseHilbEnv, true if to use hilbert envelope to find maxima
    if UseHilbEnv:
        MySignal = np.absolute( signal.hilbert(MySignal) )
    
    MaxLoc = np.argmax(np.abs(MySignal)) # find index of maximum
    N = MySignal.size # signal length
    A = MaxLoc-1 #left proxima
    B = MaxLoc+1 #Right proxima
    if MaxLoc==0: # Check if maxima is in the first of the last sample
        A = MySignal.size-1
    elif MaxLoc==MySignal.size-1:
        B = 0
        # calculate interpolation maxima according to cosine interpolation
    Alpha = np.arccos( (MySignal[A] + MySignal[B]) / (2 * MySignal[MaxLoc]) )
    Beta = np.arctan( (MySignal[A] - MySignal[B]) / (2 * MySignal[MaxLoc] * np.sin(Alpha) ) )
    Px = Beta / Alpha
    
    # Calculate ToF in samples
    DeltaToF = MaxLoc - Px
    # Check wherter if delay is to the right or to the left and correct ToF
    if MaxLoc>N/2:
        DeltaToF = -(N - DeltaToF)
        
    #Returned value is DeltaToF, the location of the maxima in subsample basis
    return DeltaToF


# shift signal to the origin
def ZeroPhasing(MySignal):
    # MySignal = signal to be shifted
    MyDelay = CosineInterpMax(np.absolute(MySignal))
    MySignal = ShiftSubsampleByfft(MySignal, MyDelay)
    return MySignal, MyDelay



def GaussPulseFilter( SigLength=1024, Fs=100e6, Fc = 5e6, AW = 0.5, BWR = -6, TPE = -60): 
#Calculate a Gaussian filter acording to specifications
# The filter is given centered unless zerophase set to true
#
#Inputs
#  Fc Central frequency of the filter (Hz)
#  AW Fractional Bandwidth of the filter
#  BWR Attenuation at fractional bandwidth (dB)
#  TPE Trailing pulse envelope falls below Ast (dB)
#  Fs Sampling Frequency in Hz
#  SigLength Length desired final length of the filer, for zero padding
#Outputs
#  MyGaussPulse -> Gaussian Filter

#
#Alberto, 13/01/2015
#

    Tpulse = (SigLength/2)/Fs
    t = np.linspace(-Tpulse, Tpulse, SigLength, endpoint=False) #Creates time basis (N)
    MyGausPulse = signal.gausspulse(t, Fc, AW, BWR, TPE) #creates gaussian pulse according to spec
        
    return MyGausPulse, t

def fm_raw(InputMatrix, GeoMean = False, Normalized = True, Absolute = True, Envelope = False):
    # Applies raw frequency multiplication (fm_raw) recombinator to input Matrix
    # fm_raw is the result of the raw product of all outputs of the filter bank
    # Geometric mean is calculated if GeoMean is True
    # Output is normalized if Normalized is True
    # Output is unsigned if Absolute is True               
    Result = np.prod(InputMatrix, axis=1)
    if GeoMean:
        Result = np.power(np.abs(Result), 1./InputMatrix.shape[1])
    if Absolute:
        Result = np.abs(Result)
    if Normalized:
        Result = Result / np.max(np.abs(Result))
    if Envelope:
        Result = np.abs(signal.hilbert(Result))
    return Result

def min_raw(InputMatrix, Normalization = False, Normalized = True):
    # Applies minimization (min_raw) recombinator to input Matrix
    # min_raw is the result of the minimum of all outputs of the filter bank
    # if Normalization is True, first each bank is normalized
    # Output is normalized if Normalized is True
    InputMatrix = np.abs(InputMatrix)
    if Normalization:
        InputMatrix = InputMatrix / np.max(InputMatrix,axis=0)
    Result = np.min(InputMatrix, axis=1)
    if Normalized:
        Result = Result / np.max(np.abs(Result))
    return Result


def pt_raw(InputMatrix, Signal2Mask = [], PThreshold = 1, ZeroCounts = True,\
           Scaled = False, Normalized = False, Absolute = False, Envelope=False):
    # Applies polarity thresholding (pt_raw) recombinator to input Matrix
    # pt_raw results in a mask, which is '1' if all banks have the same sign and '0' if not
    # Threshold is the ratio of bands that have to have the same sign, 1=100%
    # ZeroCounts to include all with value zero as with the same sign
    # if Signal2Mask is not empty, result is Signal2Mask masked with the resulting mask
    # if scaled = True, apply pt with scaling, according to eq. (ratio of same sign)
    # Output is normalized if Normalized is True
    # if Absolute, calculate absolute value
    NF = InputMatrix.shape[1] # number of filters in bank
    
    if ZeroCounts:
        InputMatrix = InputMatrix + 1.e-3
    
    Result = np.absolute( ( np.sum( np.sign(InputMatrix), axis=1) /NF) * 1.)
    
    if Scaled:
        Result = np.power(Result/NF, NF/2) * 4 * NF
    else:
        Result = (Result >= PThreshold)    
    if len(Signal2Mask)>0:
        Result = Result * Signal2Mask
    if Absolute:
        Result = np.abs(Result)
    if Normalized:
        Result = Result / np.max(np.abs(Result))
    if Envelope:
        Result = np.abs(signal.hilbert(Result))
    return Result

def cp_raw(InputMatrix, Signal2Mask = [], PThreshold = 1, ZeroCounts = True,\
           Scaled = False, Normalized = False, Absolute = False):
    # Applies complex plane (cp_raw) recombinator to input Matrix
    # cp_raw results in a mask, which is '1' if all banks have the same sign and '0' if not
    # Threshold is the ratio of bands that have to have the same sign, 1=100%
    # ZeroCounts to include all with value zero as with the same sign
    # if Signal2Mask is not empty, result is Signal2Mask masked with the resulting mask
    # if scaled = True, apply pt with scaling, according to eq. (ratio of same sign)
    # Output is normalized if Normalized is True
    analytic_signal = signal.hilbert(InputMatrix,axis=np.argmax(InputMatrix.shape))
    Phases =np.angle(analytic_signal)
    #Phases =np.abs(np.angle(analytic_signal))
    CP = np.abs(np.max(Phases,axis=-1)-np.min(Phases,axis=-1))
    CP =np.abs(CP-np.max(CP))
    return CP



# used to calculated next power of 2  
def nextpow2(i):
    n = int(np.log2(i))
    if 2**n<i:
        n +=1    
    return n



# make window general purpose
    
def MakeWindow(SortofWin = 'boxcar', WinLen = 512, param1 = 1, param2 = 1, Span = 0, Delay = 0):
    '''
    Make window 
    SortofWin can be any of the following, entered as plaintext
        boxcar, triang, blackman, hamming, hann, bartlett, flattop, parzen, bohman, 
        blackmanharris, nuttall, barthannkaiser (needs beta), gaussian (needs standard deviation), 
        general_gaussian (needs power, width), slepian (needs width), dpss (needs normalized half-bandwidth), 
        chebwin (needs attenuation), exponential (needs decay scale), tukey (needs taper fraction)
    WinLen = Length of the desired window
    param1 = beta (kaiser), std (Gaussian), power (general gaussian), width (slepian), norm h-b (dpss),
            attenuation (chebwin), decay scale (exponential), tapper fraction (tukey)
    param2 = width (general gaussian)
    Span = final length of the required window, in case expansion needed
    Delay = Required delay to the right, in samples
    '''
    
    lstWinWithParameter = ['barthannkaiser','gaussian','slepian','dpss','chebwin','exponential','tukey']
    if any(SortofWin.lower() in x for x in lstWinWithParameter):
        if SortofWin.lower() == 'general_gaussian':
            MyWin = signal.get_window(('general_gaussian', param1, param2), WinLen)
        else:
            MyWin = signal.get_window((str(SortofWin.lower()), param1), WinLen)
    else:
        MyWin = signal.get_window(str(SortofWin.lower()), WinLen)
        
    if not(Span==0): # if Span, add zeros to the end
        MyWin = np.append(MyWin,np.zeros(Span-WinLen))
    
    if not(Delay==0): #if Delay, circshift to right Delay samples
        if Delay.is_integer():
            MyWin = np.roll(MyWin, int(Delay)) # if interger use numpy roll
        else:
            MyWin = ShiftSubsampleByfft(MyWin,-Delay) # if float use subsample
        
    return MyWin
    
# calculates centroid of a vector
def Centroid(x):
    '''
    Calculates centorid of a vector
    '''
    n = np.arange(len(x))
    return np.sum(n*(x**2))/np.sum(x**2)


# calculates envelope of a signal
def Envelope(MySignal):
    '''
    Calculates envelope of a signal
    as the absolute value of its Hilbert Transform
    '''
    return np.absolute( signal.hilbert(MySignal) )

# Estimates spectroscopy resosnces
def estimateSpectroscopyParam(Param = 'Fr',Fr=1.,h=1.,v=1.,n=1.):
    '''
    Estimates spectroscopy parameters accorsing to eq:
        Fr = 1/2 · n · v / h
        Fr = resonant frequency (Hz)
        n = order of resonances, can be a vector [1,2,3...]
        v = speed of sound in media (m/s)
        h = thickness (m)
    Note that dimensions of Fr and n must agree
    Input Param = 'Fr','v','h' 
    Output depends of Param
    '''
    if Param.lower() == 'fr':
        return 0.5*n*v/h
    elif Param.lower() == 'v':
        return 2*Fr*h/n
    elif Param.lower() == 'h':
        return 0.5*n*v/Fr

# calculates moving average of a given signal
def movingAverage(Signal, SortofWin = 'boxcar', WinLen = 5, param1 = 1, param2 = 1, ZeroPhase = True):
    '''
    Computes the moving average of a given signal using a window of size WinLen
        Signal = Signal to beprocessed
        Window data:
            SortofWin = can be any of the following, entered as plaintext
                boxcar, triang, blackman, hamming, hann, bartlett, flattop, parzen, bohman, 
                blackmanharris, nuttall, barthannkaiser (needs beta), gaussian (needs standard deviation), 
                general_gaussian (needs power, width), slepian (needs width), dpss (needs normalized half-bandwidth), 
                chebwin (needs attenuation), exponential (needs decay scale), tukey (needs taper fraction)
            WinLen = Length of the desired window
            param1 = beta (kaiser), std (Gaussian), power (general gaussian), width (slepian), norm h-b (dpss),
                attenuation (chebwin), decay scale (exponential), tapper fraction (tukey)
            param2 = width (general gaussian)
            
        ZeroPhase = If window have to be delayed to produce zerophased output
        
    '''
    AuxSig = np.concatenate((Signal,np.zeros(WinLen))) #Add zeros to make convolution consisten    
    if ZeroPhase: #check delay if noncausal
        Delay = WinLen/2.
    else:
        Delay = 0
    MyWin = MakeWindow(SortofWin = SortofWin, WinLen = WinLen, param1 = param1, param2 = param2, Span = len(AuxSig), Delay = -Delay) #make window
#    MyWin = np.roll(MyWin, int(Delay))
    OutSig = (np.real( np.fft.ifft(np.fft.fft(AuxSig)*np.fft.fft(MyWin))))/np.sum(MyWin)
    return OutSig[:len(Signal)]

def CalcToFAscanCosine_XCRFFT(Data, Ref, UseHilbEnv = False):
    #----------------------------------------------
    # used to align one Ascan to a Reference by ToF subsample estimate using cosine
    # also returns ToFmap and Xcorr. Xcoor is calculated using FFT
    # It uses cosine interpolation to approximate peak location
    #
    # Inputs:
    #   Data = Ascan 
    #   Ref = Refference to align
    #   UseHilbEnv = boolean, True if using hilbert trransform
    #   ChangeSignal = boolean, True to mutate input
    # Outputs:
    #   AlignedData = Aligned array to Ref
    #   MyXcor = Result of xcorrelation
    #   DeltaToF = Time of flight between pulses
    #
    # Alberto
    # 23/05/2017
    #----------------------------------------------
    try:
        # Calculates xcorr in frequency domain
        MyXcor = np.real( np.fft.ifft( np.fft.fft( Data ) * np.conj( np.fft.fft( Ref ) ) ) )
        
        # determine time of flight
        DeltaToF=CosineInterpMax(MyXcor, UseHilbEnv = UseHilbEnv)
    
        # Delay to align
        AlignedData = ShiftSubsampleByfft(Data,DeltaToF)
        return DeltaToF, MyXcor, AlignedData
        
    except Exception as ex:
        print(ex)

def MyThick_Vel(PE_Ascan,TT_Ascan,TT45_Ascan,WP_Ascan,Ref_PE,Fs,Cw,Angle,UseHilbEnv,DoIPlot=False):
    #----------------------------------------------
    # Calcutes thickness and velocity os a sample using PE and TT
    # uses refference signal to align signals XCOR in freq domain
    # it aso uses iterative deconvolution
    #
    # Inputs:
    #   PE_Ascan = PE Ascan
    #   TT_Ascan = TT Ascan
    #   TT45_Ascan = TT45  Ascan
    #   WP_Ascan = Water Path Ascan
    #   Ref_PE = Reference Ascan for PE
    #   Fs = sampling frequency
    #   Cw = speed of sound inwater
    #   Angle = Rotation angle for shear wave in degrees
    #   UseHilbEnv = True to use hilber envelope, Falsew for maximum
    #   DoIPlot = to visualiza outputs True, False do not plot
    # Outputs:
    #   Ascan = windowed Ascan
    #
    # Alberto
    # 24/05/2017
    #----------------------------------------------
    try:
        TOF_TW = -CalcToFAscanCosine_XCRFFT(TT_Ascan,WP_Ascan,UseHilbEnv=UseHilbEnv)[0]
        
        RAmp=np.sum(np.power(Ref_PE,2))/len(Ref_PE) # mean power of refference 
        TOF_PE = np.zeros(2) # preallocates TOF_PE
        Stripped1 = np.copy(PE_Ascan)
        TOF_PE[0] = CalcToFAscanCosine_XCRFFT(Stripped1,Ref_PE,UseHilbEnv=True)[0] #time of flight of first echo        
        RefShifted = ShiftSubsampleByfft(Ref_PE,-TOF_PE[0]) #  Shift the ref to the Ascan position
        Amp = np.sum(Stripped1 * RefShifted) / len(RefShifted) / RAmp # Amplitude Ponderation factor
        Stripped2 = Stripped1 - RefShifted*Amp # strip pulse
        TOF_PE[1] = CalcToFAscanCosine_XCRFFT(Stripped2,Ref_PE,UseHilbEnv=True)[0] #time of flight second echo
        
        # TOF for TT00 signal
#        TOF_TW = CalcToFAscanCosine_XCRFFT(TT_Ascan,WP_Ascan)[0]
#        if DoIPlot: #only for visualization purposes
#            patata1,XCOR,patata2 = CalcToFAscanCosine_XCRFFT(TT_Ascan,WP_Ascan,UseHilbEnv=UseHilbEnv) #[0]
#            Plot3Ascans_Time(TT_Ascan,WP_Ascan, XCOR, 'TT_Ascan', 'WP_Ascan', 'XCOR',1,'') 
#            
#        RAmp=np.sum( np.power(Ref_PE,2))/len(Ref_PE) # mean power of refference 
#        stripIterNo = 2 # number of iterations of deconvolution
#        StrippedAscans = np.zeros((stripIterNo+1, len(Ref_PE))) #preallocates stripped
#        TOF_PE = np.zeros(stripIterNo) # preallocates TOF_PE
#        StrippedAscans[0] = PE_Ascan
#               
#        for LayerNo in range(stripIterNo):
#            TOF_PE[LayerNo] = CalcToFAscanCosine_XCRFFT(StrippedAscans[LayerNo],Ref_PE,UseHilbEnv=UseHilbEnv)[0]
#            RefShifted = ShiftSubsampleByfft(Ref_PE,-TOF_PE[LayerNo]) #  Shift the ref to the Ascan position
#            Amp = np.sum(StrippedAscans[LayerNo] * RefShifted) / len(RefShifted) / RAmp # Amplitude Ponderation factor
#            StrippedAscans[LayerNo+1] = StrippedAscans[LayerNo] - RefShifted*Amp # strip puls

        TOF_Aux = np.abs(TOF_PE[1]-TOF_PE[0]) # TOF between echoes in PE

        Cl = Cw * (1 + ( ( 2 * TOF_TW / Fs ) / ( TOF_Aux / Fs ) ) ) # Longitudinal velotity
        L = (Cw / 2) * ( 2 * ( TOF_TW / Fs ) + ( TOF_Aux /Fs ) ) #Thickness
        
        # TOF for TT45 signal
        TOF_TW_45 = -CalcToFAscanCosine_XCRFFT(TT45_Ascan,WP_Ascan,UseHilbEnv=UseHilbEnv)[0]
        if DoIPlot: #only for visualization purposes
            patata1,XCOR,patata2 = CalcToFAscanCosine_XCRFFT(TT45_Ascan,WP_Ascan,UseHilbEnv=UseHilbEnv) 
            Plot3Ascans_Time(TT45_Ascan,WP_Ascan, XCOR, 'TT45_Ascan', 'WP_Ascan', 'XCOR',1,'')
            
        Ang_Crit = (Angle) * 2 * np.pi / 360 #Critical angle in radians
        
        Cs = Cw / np.sqrt( np.power(np.sin(Ang_Crit),2) + np.power( ( ( TOF_TW_45 / Fs * Cw / L ) - np.cos(Ang_Crit) ),2) )

        return Cl, Cs, L

    except Exception as ex:
        print(ex)

def LongVelocity_Thickness(PE_Ascan,TT_Ascan,WP_Ascan,Ref_PE,Fs,Cw,UseHilbEnv):
    """
    Calcutes thickness and velocity of a sample using PE and TT
    uses refference signal to align signals XCOR in freq domain
    it aso uses iterative deconvolution
    
    Inputs:
      PE_Ascan = PE Ascan
      TT_Ascan = TT Ascan    
      WP_Ascan = Water Path Ascan
      Ref_PE = Reference Ascan for PE
      Fs = sampling frequency
      Cw = speed of sound inwater    
      UseHilbEnv = True to use hilber envelope, False for maximum    
    Outputs:
      Cl = longitudinal velocity
      L  = Thickness 
    
    Alberto
    17/12/2019    
    """
    try:
        dt = 1 / Fs  # time resolution

        # TOF from TT and WP
        TOF_TW = -CalcToFAscanCosine_XCRFFT(TT_Ascan, WP_Ascan, UseHilbEnv=UseHilbEnv)[0]

        # First and second echo in PE
        TOF_PE = np.zeros(2)
        ref_energy = np.mean(Ref_PE**2)

        # First echo
        TOF_PE[0] = CalcToFAscanCosine_XCRFFT(PE_Ascan, Ref_PE, UseHilbEnv=True)[0]
        shifted_ref = ShiftSubsampleByfft(Ref_PE, -TOF_PE[0])
        amp = np.mean(PE_Ascan * shifted_ref) / ref_energy
        stripped_signal = PE_Ascan - shifted_ref * amp

        # Second echo
        TOF_PE[1] = CalcToFAscanCosine_XCRFFT(stripped_signal, Ref_PE, UseHilbEnv=True)[0]
        TOF_diff = np.abs(TOF_PE[1] - TOF_PE[0])

        # Time-domain conversion
        t_tw = TOF_TW * dt
        t_pe = TOF_diff * dt

        # Compute results
        Cl = Cw * (1 + (2 * t_tw / t_pe))
        L = (Cw / 2) * (2 * t_tw + t_pe)

        return Cl, L

    except Exception as ex:
        print(f"Error: {ex}")
        return None, None

def Plot3Ascans_Time(Ascan1,Ascan2,Ascan3, name1, name2, name3,Normalized,ArrowLabel):
    #----------------------------------------------
    # used to align one Ascan to a Reference by ToF subsample estimate using cosine
    # also returns ToFmap and Xcorr. Xcoor is calculated using FFT
    # It uses cosine interpolation to approximate peak location
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
        print(ex)


def Plot2Ascans_TimeFreq(Ascan1,Ascan2, nfft, Fs=100e6, name1='PE', name2='TT', TimeScale =1, TimeOffSet1 = 0, TimeOffSet2 = 0, FreqScale=1e6, TimeLabel = 'Samples',FreqLabel = 'Frequency (MHz)',
                          Fmin=0,Fmax=0,Normalized=False, NormalizedMag=False, dB=False, FontA = 12, FontL = 14, FontS = 16, FigNum=1,FigTitle=''):
    """
    ----------------------------------------------
     Inputs:
       Ascan1 to plot 
       Ascan2 to plot
       name1 = label to Ascan1
       name2 = label to Ascan2
       TimeScale = scale of time axis
       TimeOffSet1 = time offset to be applied to axis 1, if any
       TimeOffSet2 = time offset to be applied to axis 2, if any
       FreqScale = scale of freq axis
       TimeLabel = label for xaxos in time
       FreqLabel = label of freqaxis
       Fs = sampling frequency
       Fmin = min frequency to plot
       Fmax = freq max to plot, 0 defect just to plot half Fs
       Normalized to normaliza time axis plot
       dB to plot specturm in dB
       FontS = Font size for subfigure name
       FontL = Font size for labels
       FontA = font size for axis
       NormalizedMag to normalize magnitud of frequency axis 
     Outputs:
       None
    
     Alberto
     13/11/2019
    ----------------------------------------------
    """
    try:
        if Normalized:
            Ascan1 = Ascan1 / np.max(np.abs(Ascan1))
            Ascan2 = Ascan2 / np.max(np.abs(Ascan2))
        
        S_A1 = np.fft.fft(Ascan1,nfft)
        S_A2 = np.fft.fft(Ascan2,nfft)
        
        if NormalizedMag:
            S_A1 = S_A1 / np.max(np.abs(S_A1))    
            S_A2 = S_A2 / np.max(np.abs(S_A2))    
        Time_Axis1 = np.arange(0,len(Ascan1),1.) * TimeScale*1.-TimeOffSet1
        Time_Axis2 = np.arange(0,len(Ascan2),1.) * TimeScale*1.-TimeOffSet2
        Freq_Axis = (np.arange(0,nfft,1.)*Fs/nfft)/FreqScale
        
        fig = plt.figure(num=FigNum)
        

        plt.clf()
        fig.suptitle(FigTitle)
        #plot Ascan1
        ax1 = fig.add_subplot(221) #plot in time domain
        ax1.plot(Time_Axis1,Ascan1, c='k', label=name1)
        ax1.set_xlabel(TimeLabel,fontsize=FontL)
        ax1.set_ylabel(name1,fontsize=FontL)
        #ax1.legend()
        ax1.set_xlim(Time_Axis1[0],Time_Axis1[-1])
        ax1.set_ylim(np.min(Ascan1)*1.1,np.max(Ascan1)*1.1)
        ax1.set_title('a',loc='left',fontsize=FontS)
        ax1.grid()
        ax1.tick_params(axis='both', which='major', labelsize=FontA)
        #plot Ascan2
        ax2 = fig.add_subplot(223) #plot in time domain
        ax2.plot(Time_Axis2,Ascan2, c='b', label=name2)
        ax2.set_xlabel(TimeLabel,fontsize=FontL)
        ax2.set_ylabel(name2,fontsize=FontL)
        #ax2.legend()
        ax2.set_xlim(Time_Axis2[0],Time_Axis2[-1])
        ax2.set_ylim(np.min(Ascan2)*1.1,np.max(Ascan2)*1.1)
        ax2.set_title('b',loc='left',fontsize=FontS)
        ax2.tick_params(axis='both', which='major', labelsize=FontA)

        ax2.grid() 
        #plot Ascan2
        ax3 = fig.add_subplot(122) #plot in time domain
        ax3.plot(Freq_Axis,np.abs(S_A1), c='k', label=name1)        
        ax3.plot(Freq_Axis,np.abs(S_A2), c='b', label=name2)
        ax3.set_xlabel(FreqLabel,fontsize=FontL)
        ax3.set_ylabel('Magnitude',fontsize=FontL)
        ax3.legend(fontsize=FontA)
        ax3.set_title('c',loc='left',fontsize=FontS)
        ax3.tick_params(axis='both', which='major', labelsize=FontA)

        if Fmax ==0:
            Fmax = (Fs) / FreqScale
        ax3.set_xlim(Fmin,Fmax)        
        ax3.grid()
#        if np.not_equal(ArrowLabel," "):
#            annotate_point_pair(ax3, ArrowLabel, [0,np.max(Ascan3)], [np.argmax(np.abs(Ascan3)),np.max(Ascan3)], xycoords='data', text_offset=6, arrowprops = None)
        plt.show()
        return Time_Axis1
    except Exception as ex:
        print(ex)


def Plot_Ascan_tf(Ascan, nfft = 2048, Units_t = 1e6, Units_F = 1e6, Fs=100e6, Fmin = 0,Fmax = 100e6, FigNum=1, FigTitle='Original Ascan'):
    '''Plots Ascan in time and frequency, between Fmin and Fmax
    Units_t is constant to normalize time axis
    Units_F is constant to normalize frequency axis
    Fs sampling frequency
    Fmin lower limit, considering Units_F
    Fmax upper limit, considering Units_F
    '''
    Time_Axis = np.arange(0, Ascan.size)/Fs*Units_t
    fig, axs = plt.subplots(2, 1, num=FigNum, clear=True)
    axs[0].plot(Time_Axis, Ascan,'k')
#    axs[0].set_title(FigTitle)
    axs[0].set_xlabel('time (us)')
    axs[0].set_ylabel('Ascan')

    # calculate fft
    MyFFT = np.fft.fft(Ascan,nfft)
    Freq_Axis = np.arange(0, MyFFT.size)*Fs/MyFFT.size/Units_F
    # freq subplot
    axs[1].plot(Freq_Axis, np.abs(MyFFT),'k')
    axs[1].set_xlabel('frequency (MHz)')
#    axs[1].set_title('subplot 2')
    axs[1].set_ylabel('FFT')
    axs[1].set_xlim(Fmin,Fmax)    
    fig.suptitle(FigTitle)
    plt.show()
    
def Plot_Bscan(Bscan, Xtoplot=1,Time_Scale=1, Time_OffSet=0, Xaxis_Scale=1, FigNum=1, time_Label = 'samples', 
               X_Label = 'X axis', FigTitle='Bscan Ascan', Imshow=False,ColorMap='seismic'):
    '''plots Bscan and Ascan
    inputs
        Bscan, matrix with Bscan data
        Xtoplot = select Ascan from matrix, integer
        Time_Scale = scale factor to apply to time axis
        Xaxis_Scale, scale factor to apply to Xaxis
        FigNum = figure number
        time_Label = text for time axis label
        X_Label = text for X axis
        FigTitle, title for figure
        Imshow, if True, plot imshow, if false plot pcolormesh
    '''    
    Time_Axis = np.arange(0, Bscan.shape[1])*Time_Scale - Time_OffSet
    Xaxis = np.arange(0, Bscan.shape[0])*Xaxis_Scale
    fig = plt.figure(num=FigNum, clear=True)    
    fig.suptitle(FigTitle)            
    ax1 = plt.subplot(2,1,1)
#    norm = cm.colors.Normalize(vmax=abs(Bscan).max()/2, vmin=-abs(Bscan).max())
    if Imshow:
        ax1.imshow(Bscan, aspect='auto', cmap='RdBu',interpolation = 'bilinear')
    else:
#        ax1.pcolormesh(Time_Axis, Xaxis,Bscan, norm=norm,cmap=ColorMap,shading = 'gouraud') 
        ax1.pcolormesh(Time_Axis, Xaxis,Bscan, cmap=ColorMap,shading = 'gouraud') 
    ax1.set_ylabel(X_Label)
    ax1.set_xlabel(time_Label)
    ax2 = plt.subplot(2,1,2)
    ax2.plot(Time_Axis, Bscan[Xtoplot,:])
    plt.xlim(Time_Axis[0],Time_Axis[-1])
    ax2.set_ylabel('Ascan')
    ax2.set_xlabel(time_Label)
    
def NSNR_Ascan(Ascan,PulseLen,FlawLoc):
    '''
    Used to calculate Normalized Signal to Noise Ratio
    Inputs:
        Ascan: Ascan to be analyzed
        Pulse_Len : length of the transmitted pulse, in samples
        FlawLoc : Location of the defect (center), in samples
    Outputs:
        ratio between power at pulse location and power in other place
    '''
    N1 = FlawLoc-int(PulseLen/2)
    N2 = FlawLoc+int(PulseLen/2)
    Rem = np.concatenate((np.arange(N1),N2+np.arange(len(Ascan)-N2)))
    FlawPower = (np.sum(Ascan[N1:N2]**2)) / PulseLen
    NoisePower = (np.sum(Ascan[Rem]**2)) / len(Rem)
    if FlawPower==0:
        return 0
    elif NoisePower ==0:
        return 1000
    else:
        return FlawPower/NoisePower

def FCR_Ascan(Ascan,PulseLen,FlawLoc):
    '''
    Used to calculate Flaw to Clutter Ratio
    Inputs:
        Ascan: Ascan to be analyzed
        Pulse_Len : length of the transmitted pulse, in samples
        FlawLoc : Location of the defect (center), in samples  
    Outputs:
        ratio between max at pulse location and max in other place
    '''     
    N1 = FlawLoc-PulseLen
    N2 = FlawLoc+PulseLen 
    Rem = np.concatenate((np.arange(N1),N2+np.arange(len(Ascan)-N2)))
    S = np.max(Ascan[N1:N2])
    N = np.max(Ascan[Rem])
    if S==0:
        return 0
    elif N==0:
        return 1000
    else:
        return S/N


def PDPFA_Bscan(Bscan,PulseLen,FlawLoc,Thr):
    '''
    Used to calculate PD and PFA
    Inputs:
        Bscan: Bscan to be analyzed
        Pulse_Len : length of the transmitted pulse, in samples
        FlawLoc : Location of the defect (center), in samples 
        Thr : array of thresholds
    '''
    N1 = FlawLoc-PulseLen
    N2 = FlawLoc+PulseLen 
    Rem = np.concatenate((np.arange(N1),N2+np.arange(Bscan.shape[1]-N2)))
    j = -1
    PFA = np.zeros(len(Thr))
    PD = np.zeros_like(PFA)
    for i in Thr:
        j+=1
        D = 0.
        PFA[j] = np.count_nonzero(Bscan[:,Rem]>=i)*1./np.size(Bscan[:,Rem])        
        for k in np.arange(Bscan.shape[0]):
            if np.count_nonzero(Bscan[k,N1:N2]>=i):
                D+=1
        PD[j] = D/Bscan.shape[0]       
            
    return PD,PFA