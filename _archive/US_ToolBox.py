# -*- coding: utf-8 -*-
"""
Created on Fri Jan 09 10:18:29 2015

@author: Alberto
"""

import numpy as np
from scipy import signal
import matplotlib.pyplot as plt
import signal_toolbox as st

class CreateTransducer:
    def __init__(self, SamplingFrequency = 100e6, ScanLength = 1024, # Experiment parameters
                     CentralFrequencyNominal = 5e6, BandWidthNominal = 2.5e6, PulseDurationNominal = [],
                    
                     TransducerDiameter = 0.008, # Transducer parameters                                          
                     ):
        
        self.CentralFrequency = CentralFrequencyNominal# Nominal central frequency of the pulse in hertz   
        self.BandWidth = BandWidthNominal # nominal Bandwidth in Hertz
        self.BandWidthRatio = self.BandWidth / self.CentralFrequency #Bandwidth ratio (0,1)
        self.TransducerDiameter = TransducerDiameter # Transducer diameter in meters
        self.PulseWidthTheo = 2 / self.BandWidth * self.SamplingFrequency
        self.BeamFormed = False # If beamformed
        self.Normalized = False # If Normalized
        self.PulseCreated = False # To check error
        self.ZeroPhase = False # Inititate zero phase to non
        
        self.Pulsemodel = 'None' # Sort of excitation initiated to none
        self.PulseRaw = np.zeros(self.ScanLength) # Initiate pulse raw and pulse
        self.Pulse = self.PulseRaw
    
    def pulsewidth(self, Ratio = 0.1):        
        A = self.Pulse / np.max(np.absolute(self.Pulse))
        B = np.nonzero(np.absolute(A) > Ratio)
        self.PulseWidthEstimated = B[0].size
        self.PulseNonZero = B[0]
        
    
    def make_Gaussian_pulse(self, PulseCutPower, PulseDecayTime):
        self.Pulsemodel = 'Gaussian' # Sort of excitation
        self.PulseCutPower = PulseCutPower # Cut power for the gasussian pulse
        self.PulseDecayTime = PulseDecayTime # Decay time Gaussian Pulse        
        self.PulseRaw, self.t = GaussPulseFilter(self.ScanLength, self.SamplingFrequency, self.CentralFrequency, self.BandWidthRatio , self.PulseCutPower, self.PulseDecayTime)
        self.Pulse = self.PulseRaw
        self.OriginalPulseLoc = np.argmax(self.Pulse)
        self.PulseCreated = True
        self.BeamFormed = False # If beamformed
        self.Normalized = False # If Normalized
        
    def make_Exponential_pulse(self, PulseAttenuation, PulseExponential):
        self.Pulsemodel = 'Exponential' # Sort of excitation
        self.PulseAttenuation = PulseAttenuation
        self.PulseExponential = PulseExponential
        self.PulseRaw, self.t = RaiseExpPulse(self.ScanLength, self.SamplingFrequency, self.CentralFrequency, self.PulseAttenuation, self.PulseExponential)
        self.Pulse = self.PulseRaw
        self.OriginalPulseLoc = np.argmax(self.Pulse)
        self.PulseCreated = True
        self.BeamFormed = False # If beamformed
        self.Normalized = False # If Normalized
     
    def beamforms_pulse(self, TransducerTriggerTimer, TransducerTriggerFactor):
        if not self.BeamFormed:
            self.TransducerTriggerTimer = TransducerTriggerTimer # Transducer trigger time for beamforming
            self.TransducerTriggerFactor = TransducerTriggerFactor # Transducer trigger factor for beamforming
            self.Pulse = Beamforming(self.PulseRaw, self.SamplingFrequency, self.TransducerTriggerTimer, self.TransducerTriggerFactor)
            self.OriginalPulseLoc = np.argmax(self.Pulse)
            self.BeamFormed = True # If beamformed
            if self.Normalized:
                self.Pulse = self.Pulse / np.max(np.absolute(self.Pulse))     
                   
    def normalize_pulse(self):
        if not self.Normalized:
            self.Pulse = self.Pulse / np.max(np.absolute(self.Pulse))                
            self.Normalized = True
    
    def set_original_pulse(self):
        self.Pulse = self.PulseRaw
    
    def zero_phase_pulse(self):
        if not self.ZeroPhase:
            self.ZeroPhasedPulse, _ = ZeroPhasing(self.Pulse)
            self.ZeroPhase = True
            
    
    def make_ft_pulse(self, ZeroPhase = False, Expand = True):        
        self.Expanded = Expand
        Pulso = self.Pulse        
        if Expand:
            Pulso = np.concatenate((Pulso, np.zeros_like(Pulso)))
        if ZeroPhase:
            Pulso, _ = ZeroPhasing(Pulso)
        self.FTPulse = np.fft.fft(Pulso)        

class CreateAscan:
    def __init__(self, Pulse, PulseWidth, CentralFrequency = 5e6, TransducerDiameter = 0.01, # transducer parameters
                 ScanLength = 1024, SamplingFrequency = 100e6, WGN = 0.1,# Experiment parameters
                 NoiseModel = 'Stationary', SoundVelocity = 3000, #Material general parameters
                 NoisePower = 0.1, #Stationary noise parameter
                 NumReflectors = 5000, MaterialAtt = 4.86e-28, MaterialConst = 5e-12, # Non stationary model parameters
                 FlawLoc = 256, FlawCoef = 1e6, # Flaw parameters
                 ZerosSurr = 32, ZerosSurrFactor = 1, SortofWin = 'Hamming', WinParam = 1, Windowed = True, # zero windowing parameters
                 ZeroPhase = True):
        self.PulseWidth = PulseWidth             
        self.SoundVelocity = SoundVelocity
        self.SamplingFrequency = SamplingFrequency
        self.ScanLength = ScanLength
        self.CentralFrequency = CentralFrequency
        self.TransducerDiameter = TransducerDiameter
        self.WGN = WGN
        self.FlawCoef = FlawCoef
        self.FlawLoc = FlawLoc
        self.ZerosSurrFactor = ZerosSurrFactor
        self.ZerosSurrounding = ZerosSurr*ZerosSurrFactor
        self.WinParam = WinParam
        self.SortofWin = SortofWin
        self.NoiseModel = NoiseModel
        self.Windowed = Windowed
        self.ZeroPhase = ZeroPhase
        
        Pulse = np.concatenate((Pulse, np.zeros_like(Pulse)))
        
        if self.NoiseModel.lower == 'NonStationary'.lower:
            self.NumReflectors = NumReflectors
            self.MaterialAtt = MaterialAtt
            self.MaterialConst = MaterialConst
            self.WaveLength = self.SoundVelocity / self.CentralFrequency
            self.DminSamples =  np.round( (np.square(self.TransducerDiameter) / (4 * self.WaveLength)) / self.SoundVelocity * self.SamplingFrequency)
            self.Dmin = self.SoundVelocity / self.SamplingFrequency * self.DminSamples
            self.Dmax = self.Dmin + 0.5 * self.SoundVelocity * self.ScanLength / self.SamplingFrequency * 2                    
            self.W = np.linspace(0, np.pi * self.SamplingFrequency, self.ScanLength + 1, endpoint = True)             
            self.HMaterial = np.zeros_like(self.W, dtype=np.complex128)
            self.HReflector = np.zeros_like(self.W, dtype=np.complex128)            
            if self.ZeroPhase:
                self.Pulse, _ = ZeroPhasing(Pulse)
                self.delay = np.int( self.Dmin / self.SoundVelocity * self.SamplingFrequency * 2) 
            else:
                self.Pulse = Pulse 
                self.delay = self.ScanLength + np.int( self.Dmin / self.SoundVelocity * self.SamplingFrequency * 2)                                 
        elif self.NoiseModel.lower == 'Stationary'.lower:
            self.NoisePower = NoisePower            
            self.MyRef = np.zeros(self.ScanLength * 2)
            if self.ZeroPhase:
                self.Pulse, _ = ZeroPhasing(Pulse)
                self.delay = 0
            else:
                self.Pulse = Pulse 
                self.delay = self.ScanLength/2 + np.argmax(Pulse)
        else:
            error = 'Noise model unknown'
            return error

        self.FTPulse = np.fft.fft(self.Pulse) * np.fft.fft(self.Pulse)                                    

        if self.Windowed:
            if self.SortofWin.lower == 'Hamming'.lower:
                Ventana = (np.hamming(self.ZerosSurrounding * 2 + 1) - 0.08) / 0.92
            elif self.SortofWin.lower == 'Hanning'.lower:
                Ventana = (np.hanning(self.ZerosSurrounding * 2 + 1))
            elif self.SortofWin.lower == 'Bartlett'.lower:
                Ventana = (np.bartlett(self.ZerosSurrounding * 2 + 1))
            elif self.SortofWin.lower == 'Blackman'.lower:
                Ventana = (np.blackman(self.ZerosSurrounding * 2 + 1))
            elif self.SortofWin.lower == 'Kaiser'.lower:
                Ventana = (np.kaiser(self.ZerosSurrounding * 2 + 1, self.WinParam))
            elif self.SortofWin.lower == 'Gaussian'.lower:
                Ventana = signal.gaussian(self.ZerosSurrounding * 2 + 1, self.WinParam)            
            Ventana = np.concatenate((Ventana, np.zeros(self.ScanLength * 2 - Ventana.size )))
            Ventana = 1 - np.roll(Ventana,FlawLoc-self.ZerosSurrounding)           
        else:
            Ventana = 1
        self.Ventana = Ventana

    def newAscan(self, FlawLoc, FlawCoef, SNR = 0.5, WGN = 0.01, Normalized = True):
        # Make new Ascan
        self.FlawLoc = FlawLoc
        self.FlawCoef = FlawCoef
        self.SNR = SNR
        self.WGN = WGN
        self.Normalized = Normalized
        
        self.makeflaw()
        self.makenoise()
        self.makeAscan()
        
        self.NSNRIn = CalcNormSNR(self.Ascan, self.FlawLoc, self.PulseWidth)
        self.FCRIn =CalcFCR(self.Ascan, self.FlawLoc, self.PulseWidth)
        self.DetectabilityIn =CalcDetectability(self.Ascan, self.FlawLoc, self.PulseWidth)
        
    def makeflaw(self):
        # Make flaw record to be convolved with pulse        
        if self.NoiseModel.lower == 'NonStationary'.lower:
            self.DFlaw = self.Dmin + 0.5 * self.SoundVelocity * self.FlawLoc / self.SamplingFrequency            
            self.HReflector = self.FlawCoef * np.exp(-self.MaterialAtt * 2 * self.DFlaw * np.power(self.W, 4)) * np.exp(-2 * 1j * self.W * self.DFlaw / self.SoundVelocity)        
            SPCRef = self.HReflector[1:-1]
            ARef = SPCRef[::-1]            
            self.FTMyRef = np.concatenate((self.HReflector, np.conj(ARef)))
            self.MyRef = np.fft.ifft(self.FTMyRef)
        else:
            self.MyRef[self.FlawLoc] = self.FlawCoef        
            self.FTMyRef = np.fft.fft(self.MyRef)

    def makenoise(self):
        # Make new noise record to be convolved with pulse            
        if self.NoiseModel.lower == 'NonStationary'.lower:
            Ks = np.random.uniform(self.Dmin, self.Dmax, self.NumReflectors)
            for i in np.arange(self.W.size):
                HM = ( self.MaterialConst * np.power(self.W[i], 2) / Ks ) * np.exp(-self.MaterialAtt * 2 * Ks * np.power(self.W[i], 4)) * np.exp(-2 * 1j * self.W[i] * Ks / self.SoundVelocity)
                self.HMaterial[i] = np.sum( HM )                               
            SPCMat = self.HMaterial[1:-1]
            AMat = SPCMat[::-1]         
            self.FTMyNoise = np.concatenate((self.HMaterial, np.conj(AMat)))
            self.MyNoise = np.fft.ifft(self.FTMyNoise)
        else:
            self.MyNoise = np.sqrt(self.NoisePower)*np.random.randn(self.ScanLength * 2)
            self.FTMyNoise = np.fft.fft(self.MyNoise)
    
    def makeAscan(self):
        # generates new Ascan
        
        Noise = np.fft.ifft(self.FTPulse * self.FTMyNoise) * self.Ventana
        Noise = Noise.real
        Signal = np.fft.ifft(self.FTPulse * self.FTMyRef)
        Signal = Signal.real             
        if self.SNR == 0:
            Provisional = np.roll(Noise,-self.delay)
        elif self.SNR == 1:
            Provisional = np.roll(Signal,-self.delay)
        else:            
            NP = np.sum(np.square(Noise))
            if NP==0:
                PowerFactor = 1
            else:
                SP = np.sum(np.square(Signal))
                PowerFactor = self.SNR * NP / (SP * (1 - self.SNR))  
                Provisional = np.roll(Noise + Signal * PowerFactor,-self.delay)        
        self.Ascan = Provisional[0:self.ScanLength] +  np.sqrt(PowerFactor*SP/2048) * np.sqrt(self.WGN) * np.random.randn(self.ScanLength)            
        if self.Normalized:
            self.normalize_Ascan()
    
    def normalize_Ascan(self):
    # Normalize Ascan
        self.Ascan = self.Ascan / np.amax(np.absolute(self.Ascan))
        
    def makeFFTAscan(self, Nfft):
        self.FTAscan = np.fft.fft(self.Ascan, Nfft)
        
    def ss_ZeroPhase_filter_Ascan(self,FilterBank):
        Nfft = FilterBank.FTBank.shape[0]
        self.FTAscan = np.fft.fft(self.Ascan, Nfft)
        self.SSFilteredAscan = SS_filter_ZeroPhase(self.FTAscan, FilterBank.FTBank, self.ScanLength)
        self.SSFiltered = True

        self.MehotdsApplied = 0 # Number of methods applied
        self.SSMethods = [] # initializes list of recombination methods applied 
        self.SSMethodsTitle = [] # initializes method description
        self.NSNROut = [] # initializes list of recombination methods applied 
        self.NSNRGain = [] # initializes list of recombination methods applied 
        self.FCROut = [] # initializes list of recombination methods applied 
        self.FCRGain = [] # initializes list of recombination methods applied 
        self.DetectabilityOut = [] # initializes list of recombination methods applied 
        self.DetectabilityGain = [] # initializes list of recombination methods applied        
              


    def frequency_multiplication_raw(self, Absolute = True):
        # Applies raw frequency multiplication recombinator to Matrix
        # Output is normalized if Normalized is True
        # Output is unsigned if Absolute is True
        # Name of this methos is = 'fm00'
                
        self.SSMethods.append('fm_raw')
        self.SSMethodsTitle.append('Frequency Multiplication Raw')
        if self.MehotdsApplied == 0:
            self.SSPResults = np.ones((self.SSFilteredAscan.shape[0],1))
        else:
            self.SSPResults = np.insert(self.SSPResults, self.MehotdsApplied, np.ones(self.SSFilteredAscan.shape[0]), axis=1)
        for i in range(self.SSFilteredAscan.shape[1]):
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * self.SSFilteredAscan[:,i]
        if Absolute:
            self.SSPResults = np.absolute(self.SSPResults)
            
        if self.Normalized:
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] / np.max(np.absolute(self.SSPResults[:,self.MehotdsApplied]))
            
        self.NSNROut.append(CalcNormSNR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.NSNRGain.append(self.NSNROut[self.MehotdsApplied] / self.NSNRIn)
        
        self.FCROut.append(CalcFCR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.FCRGain.append(self.FCROut[self.MehotdsApplied] / self.FCRIn)
        
        self.DetectabilityOut.append(CalcDetectability(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.DetectabilityGain.append(self.DetectabilityOut[self.MehotdsApplied] / self.DetectabilityIn)
            
        self.MehotdsApplied = self.MehotdsApplied + 1 
    
    
    def geometric_mean_raw(self, Absolute = True):
        # Applies raw frequency multiplication recombinator to Matrix
        # Output is normalized if Normalized is True
        # Output is unsigned if Absolute is True
        # Name of this methos is = 'fm00'
                
        self.SSMethods.append('gm_raw')
        self.SSMethodsTitle.append('Geometric Mean Raw')
        if self.MehotdsApplied == 0:
            self.SSPResults = np.ones((self.SSFilteredAscan.shape[0],1))
        else:
            self.SSPResults = np.insert(self.SSPResults, self.MehotdsApplied, np.ones(self.SSFilteredAscan.shape[0]), axis=1)
            
        for i in range(self.SSFilteredAscan.shape[1]):
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * self.SSFilteredAscan[:,i]
        
        if not Absolute:
            B = np.sign(self.SSPResults[:,self.MehotdsApplied])
        else:
            B = 1
        self.SSPResults[:,self.MehotdsApplied] = B * np.power(np.absolute(self.SSPResults[:,self.MehotdsApplied]), 1. / self.SSFilteredAscan.shape[1])
        
        
        if self.Normalized:
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] / np.max(np.absolute(self.SSPResults[:,self.MehotdsApplied]))
            
        self.NSNROut.append(CalcNormSNR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.NSNRGain.append(self.NSNROut[self.MehotdsApplied] / self.NSNRIn)
        
        self.FCROut.append(CalcFCR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.FCRGain.append(self.FCROut[self.MehotdsApplied] / self.FCRIn)
        
        self.DetectabilityOut.append(CalcDetectability(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.DetectabilityGain.append(self.DetectabilityOut[self.MehotdsApplied] / self.DetectabilityIn)            
        self.MehotdsApplied = self.MehotdsApplied + 1 
        
    def minimization_raw(self, Absolute = True):
        # Applies raw minimization recombinator to Matrix
        # Output is normalized if Normalized is True
        # Output is unsigned if Absolute is True
        # Name of this methos is = 'fm00'
        
        self.SSMethods.append('min_raw')
        self.SSMethodsTitle.append('Minimization Raw')
        if self.MehotdsApplied == 0:
            self.SSPResults = np.ones((self.SSFilteredAscan.shape[0],1))
        else:
            self.SSPResults = np.insert(self.SSPResults, self.MehotdsApplied, np.ones(self.SSFilteredAscan.shape[0]), axis=1)            
            
        self.SSPResults[:,self.MehotdsApplied] = np.nanmin(np.absolute(self.SSFilteredAscan), axis=1)
        if not Absolute:            
            A = np.argmin(np.absolute(self.SSFilteredAscan), axis=1)
            B = np.zeros_like(A)
            for i in range(A.size):
                B[i] = np.sign(self.SSFilteredAscan[i,A[i]])
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * B
                
        if self.Normalized:
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] / np.max(np.absolute(self.SSPResults[:,self.MehotdsApplied]))
            
        self.NSNROut.append(CalcNormSNR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.NSNRGain.append(self.NSNROut[self.MehotdsApplied] / self.NSNRIn)
        
        self.FCROut.append(CalcFCR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.FCRGain.append(self.FCROut[self.MehotdsApplied] / self.FCRIn)
        
        self.DetectabilityOut.append(CalcDetectability(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.DetectabilityGain.append(self.DetectabilityOut[self.MehotdsApplied] / self.DetectabilityIn)
            
        self.MehotdsApplied = self.MehotdsApplied + 1 
        
    
    def polarity_thresholding_raw(self, Mask = True, Threshold = 1, Absolute = True):
        # Applies raw polarity thresholding recombinator to Matrix
        # compares normalized sum(sign(bands))  with threshold
        # If True it returns the signal multiplied by mask, otherwise returns mask
        # Output is normalized if Normalized is True
        # Output is unsigned if Absolute is True
        # Name of this methos is = 'fm_raw'
    
        self.SSPolarityThreshold = Threshold       
        self.SSMethods.append('pth_raw')
        self.SSMethodsTitle.append('Polarity Thresholding Raw')
        if self.MehotdsApplied == 0:
            self.SSPResults = np.ones((self.SSFilteredAscan.shape[0],1))
        else:
            self.SSPResults = np.insert(self.SSPResults, self.MehotdsApplied, np.ones(self.SSFilteredAscan.shape[0]), axis=1)            
                
        self.SSPResults[:,self.MehotdsApplied] = (np.absolute((np.sum(np.sign(self.SSFilteredAscan), axis=1) / self.SSFilteredAscan.shape[1]) * 1.) >= Threshold)
        
        if Mask:
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * self.Ascan
            if Absolute:
                self.SSPResults[:,self.MehotdsApplied] = np.absolute(self.SSPResults[:,self.MehotdsApplied])
            if self.Normalized:
                self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] / np.max(np.absolute(self.SSPResults[:,self.MehotdsApplied]))
        
        
            
        self.NSNROut.append(CalcNormSNR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.NSNRGain.append(self.NSNROut[self.MehotdsApplied] / self.NSNRIn)
        
        self.FCROut.append(CalcFCR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.FCRGain.append(self.FCROut[self.MehotdsApplied] / self.FCRIn)
        
        self.DetectabilityOut.append(CalcDetectability(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.DetectabilityGain.append(self.DetectabilityOut[self.MehotdsApplied] / self.DetectabilityIn)
            
        self.MehotdsApplied = self.MehotdsApplied + 1 
    
    def polarity_thresholding_min(self, Mask = True, Threshold = 1, Absolute = True):
        # Applies raw polarity thresholding recombinator to Matrix
        # compares normalized sum(sign(bands))  with threshold
        # If True it returns the signal multiplied by mask, otherwise returns mask
        # Output is normalized if Normalized is True
        # Output is unsigned if Absolute is True
        # Name of this methos is = 'fm_raw'
    
        self.SSPolarityThreshold = Threshold       
        self.SSMethods.append('pth_min')
        self.SSMethodsTitle.append('Polarity Thresholding with Minimization')
        if self.MehotdsApplied == 0:
            self.SSPResults = np.ones((self.SSFilteredAscan.shape[0],1))
        else:
            self.SSPResults = np.insert(self.SSPResults, self.MehotdsApplied, np.ones(self.SSFilteredAscan.shape[0]), axis=1)            
                
        self.SSPResults[:,self.MehotdsApplied] = (np.absolute((np.sum(np.sign(self.SSFilteredAscan), axis=1) / self.SSFilteredAscan.shape[1]) * 1.) >= Threshold)
        
        if Mask:
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * np.nanmin(np.absolute(self.SSFilteredAscan), axis=1)
            if not Absolute:            
                A = np.argmin(np.absolute(self.SSFilteredAscan), axis=1)
                B = np.zeros_like(A)
                for i in range(A.size):
                    B[i] = np.sign(self.SSFilteredAscan[i,A[i]])
                self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * B
            if self.Normalized:
                self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] / np.max(np.absolute(self.SSPResults[:,self.MehotdsApplied]))
        
        
            
        self.NSNROut.append(CalcNormSNR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.NSNRGain.append(self.NSNROut[self.MehotdsApplied] / self.NSNRIn)
        
        self.FCROut.append(CalcFCR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.FCRGain.append(self.FCROut[self.MehotdsApplied] / self.FCRIn)
        
        self.DetectabilityOut.append(CalcDetectability(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.DetectabilityGain.append(self.DetectabilityOut[self.MehotdsApplied] / self.DetectabilityIn)
            
        self.MehotdsApplied = self.MehotdsApplied + 1 
    
    def polarity_scaled_raw(self, Mask = True, Absolute = True):
        # Applies raw polarity escaled recombinator to Matrix
        # calculates the sum(sign(bands)) as mask
        # If Mask is true returns the signal multiplied by mask, otherwise returns mask
        # Output is normalized if Normalized is True
        # Output is unsigned if Absolute is True
        # Name of this methos is = 'fm_raw'
       
        self.SSMethods.append('psc_raw')
        self.SSMethodsTitle.append('Polarity Scaled Raw')
        if self.MehotdsApplied == 0:
            self.SSPResults = np.ones((self.SSFilteredAscan.shape[0],1))
        else:
            self.SSPResults = np.insert(self.SSPResults, self.MehotdsApplied, np.ones(self.SSFilteredAscan.shape[0]), axis=1)            
                
        self.SSPResults[:,self.MehotdsApplied] = np.absolute((np.sum(np.sign(self.SSFilteredAscan), axis=1) / self.SSFilteredAscan.shape[1]) * 1.)
        
        if Mask:
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * self.Ascan
            if Absolute:
                self.SSPResults[:,self.MehotdsApplied] = np.absolute(self.SSPResults[:,self.MehotdsApplied])
            if self.Normalized:
                self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] / np.max(np.absolute(self.SSPResults[:,self.MehotdsApplied]))
        
        
            
        self.NSNROut.append(CalcNormSNR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.NSNRGain.append(self.NSNROut[self.MehotdsApplied] / self.NSNRIn)
        
        self.FCROut.append(CalcFCR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.FCRGain.append(self.FCROut[self.MehotdsApplied] / self.FCRIn)
        
        self.DetectabilityOut.append(CalcDetectability(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.DetectabilityGain.append(self.DetectabilityOut[self.MehotdsApplied] / self.DetectabilityIn)
            
        self.MehotdsApplied = self.MehotdsApplied + 1 
    
    def polarity_scaled_min(self, Mask = True, Absolute = True):
        # Applies raw polarity escaled recombinator to Matrix
        # calculates the sum(sign(bands)) as mask
        # If Mask is true returns the output of minimum recombination by mask, otherwise returns mask
        # Output is normalized if Normalized is True
        # Output is unsigned if Absolute is True
        # Name of this methos is = 'fm_raw'
       
        self.SSMethods.append('psc_min')
        self.SSMethodsTitle.append('Polarity Scaled with Minimization')
        if self.MehotdsApplied == 0:
            self.SSPResults = np.ones((self.SSFilteredAscan.shape[0],1))
        else:
            self.SSPResults = np.insert(self.SSPResults, self.MehotdsApplied, np.ones(self.SSFilteredAscan.shape[0]), axis=1)            
                
        self.SSPResults[:,self.MehotdsApplied] = np.absolute((np.sum(np.sign(self.SSFilteredAscan), axis=1) / self.SSFilteredAscan.shape[1]) * 1.)
        
        if Mask:
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * np.nanmin(np.absolute(self.SSFilteredAscan), axis=1)
            if not Absolute:            
                A = np.argmin(np.absolute(self.SSFilteredAscan), axis=1)
                B = np.zeros_like(A)
                for i in range(A.size):
                    B[i] = np.sign(self.SSFilteredAscan[i,A[i]])
                self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * B
                    
            if self.Normalized:
                self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] / np.max(np.absolute(self.SSPResults[:,self.MehotdsApplied]))
        
        
            
        self.NSNROut.append(CalcNormSNR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.NSNRGain.append(self.NSNROut[self.MehotdsApplied] / self.NSNRIn)
        
        self.FCROut.append(CalcFCR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.FCRGain.append(self.FCROut[self.MehotdsApplied] / self.FCRIn)
        
        self.DetectabilityOut.append(CalcDetectability(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.DetectabilityGain.append(self.DetectabilityOut[self.MehotdsApplied] / self.DetectabilityIn)
            
        self.MehotdsApplied = self.MehotdsApplied + 1 
    
    def polarity_diversity_raw(self, Mask = True, Absolute = True):
        # Applies raw polarity diversity according to Rubbers recombinator to Matrix
        # calculates the phase diversity of the matrix
        # If Mask is true returns the signal multiplied by mask, otherwise returns mask
        # Output is normalized if Normalized is True
        # Output is unsigned if Absolute is True
        # Name of this methos is = 'pd_raw'
       
        self.SSMethods.append('pdv_raw')
        self.SSMethodsTitle.append('Polarity Diversity Raw')
        if self.MehotdsApplied == 0:
            self.SSPResults = np.ones((self.SSFilteredAscan.shape[0],1))
        else:
            self.SSPResults = np.insert(self.SSPResults, self.MehotdsApplied, np.ones(self.SSFilteredAscan.shape[0]), axis=1)            
                
        self.SSPResults[:,self.MehotdsApplied] = np.absolute((np.sum(np.sign(self.SSFilteredAscan), axis=1) / self.SSFilteredAscan.shape[1]) * 1.)
        
        if Mask:
            self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * np.nanmin(np.absolute(self.SSFilteredAscan), axis=1)
            if not Absolute:            
                A = np.argmin(np.absolute(self.SSFilteredAscan), axis=1)
                B = np.zeros_like(A)
                for i in range(A.size):
                    B[i] = np.sign(self.SSFilteredAscan[i,A[i]])
                self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] * B
                    
            if self.Normalized:
                self.SSPResults[:,self.MehotdsApplied] = self.SSPResults[:,self.MehotdsApplied] / np.max(np.absolute(self.SSPResults[:,self.MehotdsApplied]))
           
        self.NSNROut.append(CalcNormSNR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.NSNRGain.append(self.NSNROut[self.MehotdsApplied] / self.NSNRIn)
        
        self.FCROut.append(CalcFCR(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.FCRGain.append(self.FCROut[self.MehotdsApplied] / self.FCRIn)
        
        self.DetectabilityOut.append(CalcDetectability(self.SSPResults[:,self.MehotdsApplied], self.FlawLoc, self.PulseWidth))
        self.DetectabilityGain.append(self.DetectabilityOut[self.MehotdsApplied] / self.DetectabilityIn)
            
        self.MehotdsApplied = self.MehotdsApplied + 1 
    
    def plot_ss_output(self, tscale=1, xlabel1='time (samples)', GridOn = False, FigNumber = 1):
        NumFigs = self.SSFilteredAscan.shape[1]
        taxis = np.arange(0,self.SSFilteredAscan.shape[0],1) * tscale
        plt.figure(FigNumber)
        plt.clf()
        f, ax = plt.subplots(NumFigs + 1, 1, sharex = True, num = FigNumber)
        ax[0].plot(taxis, self.Ascan)            
        ax[0].set_ylabel('Ascan')
        ax[0].set_xlim((np.min(taxis), np.max(taxis)))
        start, end = ax[0].get_ylim()
        ax[0].yaxis.set_ticks(np.linspace(start, end, 5))
        if GridOn:
            ax[0].grid()
        for i in range(NumFigs):            
            ax[i+1].plot(taxis, self.SSFilteredAscan[:,i])            
            ax[i+1].set_ylabel('Band ' + str(i + 1))            
            ax[i+1].set_xlim((np.min(taxis), np.max(taxis)))
            start, end = ax[i+1].get_ylim()
#            ax[i+1].yaxis.set_ticks(np.arange(start, end, (end-start) / 4))
            ax[i+1].yaxis.set_ticks(np.linspace(start, end, 5))
            if GridOn:
                ax[i+1].grid()
                
        ax[NumFigs].set_xlabel(xlabel1)
        f.subplots_adjust(bottom=0.075, left=.1, right=.975, top=.95, hspace=0.2)
#        f.tight_layout()        
        plt.show()

    def plot_result_ss(self, Method2Plot = 0, tscale=1, xlabel1='time (samples)', GridOn = False, FigNumber = 1):
        NumFigs = self.SSFilteredAscan.shape[1] + 1
        taxis = np.arange(0,self.Ascan.size,1) * tscale
        plt.figure(FigNumber)
        plt.clf()
        f, ax = plt.subplots(NumFigs + 1, 1, sharex = True, num = FigNumber)
        ax[0].plot(taxis, self.Ascan)            
        ax[0].set_ylabel('Ascan')
        ax[0].set_title('Results for Split ' + self.SSMethodsTitle[Method2Plot])
        ax[0].set_xlim((np.min(taxis), np.max(taxis)))
        start, end = ax[0].get_ylim()
        ax[0].yaxis.set_ticks(np.linspace(start, end, 5))        
        if GridOn:
            ax[0].grid()
            
        ax[1].plot(taxis, self.SSPResults[:,Method2Plot])            
        ax[1].set_ylabel(self.SSMethods[Method2Plot])
        ax[1].set_xlim((np.min(taxis), np.max(taxis)))
        start, end = ax[0].get_ylim()
        ax[1].yaxis.set_ticks(np.linspace(start, end, 5))        
        if GridOn:
            ax[1].grid()
            
        for i in range(NumFigs - 1):            
            ax[i+2].plot(taxis, self.SSFilteredAscan[:,i])            
            ax[i+2].set_ylabel('Band ' + str(i + 1))
            ax[i+2].set_xlim((np.min(taxis), np.max(taxis)))
            start, end = ax[i+2].get_ylim()
#            ax[i+1].yaxis.set_ticks(np.arange(start, end, (end-start) / 4))
            ax[i+2].yaxis.set_ticks(np.linspace(start, end, 5))
            if GridOn:
                ax[i+2].grid()
                
        ax[NumFigs].set_xlabel(xlabel1)
#        f.subplots_adjust(left=0.1, bottom=0.1, right=0.1, top=0.1,
#                wspace=0.1, hspace=0.1)
        f.subplots_adjust(bottom=0.1, left=.1, right=.975, top=.95, hspace=0.2)
#        f.tight_layout()        
        plt.show()
        
    def plot_allresult_ss(self, tscale=1, xlabel1='time (samples)', GridOn = False, FigNumber = 1, Envelope = True):
        #EL mejor es spline interp of the envelope peaks with absolute values
        NumFigs = self.MehotdsApplied
        taxis = np.arange(0,self.Ascan.size,1) * tscale
        plt.figure(FigNumber)
        plt.clf()
        f, ax = plt.subplots(NumFigs + 1, 1, sharex = True, num = FigNumber)
        ax[0].plot(taxis, self.Ascan)  
        if Envelope:
            ax[0].plot(taxis, CalcEnvelope(self.Ascan))           
        ax[0].set_ylabel('Ascan')
        ax[0].set_title('Results for Split Spectrum Processing')
        ax[0].set_xlim((np.min(taxis), np.max(taxis)))
        start, end = ax[0].get_ylim()
#        ax[0].set_xlabel(xlabel1)
        ax[0].yaxis.set_ticks(np.linspace(start, end, 5))        
        if GridOn:
            ax[0].grid()

        for i in range(NumFigs):            
            ax[i+1].plot(taxis, self.SSPResults[:,i])
            if Envelope:
                ax[i+1].plot(taxis, CalcEnvelope(self.SSPResults[:,i])) # envelope
                MyPeaks, xnew, ynew = st.PeakEnvelopeDetector(CalcEnvelope(self.SSPResults[:,i])) # spline interp envelope peaks
                MyPeaks, xnew, ynew2 = st.PeakEnvelopeDetector(self.SSPResults[:,i]) # spline interp Raw peaks
#                ax[i+1].plot(taxis, MyPeaks) 
                ax[i+1].plot(taxis, ynew) 
                ax[i+1].plot(taxis, ynew2)
                ax[i+1].legend(['Raw', 'Envelope', 'Spline Envelope', 'Spline'])
            ax[i+1].set_ylabel(self.SSMethods[i])
            ax[i+1].set_xlim((np.min(taxis), np.max(taxis)))
#            ax[i+1].set_xlabel(xlabel1)
            start, end = ax[i+1].get_ylim()
#            ax[i+1].yaxis.set_ticks(np.arange(start, end, (end-start) / 4))
            ax[i+1].yaxis.set_ticks(np.linspace(start, end, 5))
            if GridOn:
                ax[i+1].grid()
        
        ax[NumFigs].set_xlabel(xlabel1)
#        f.subplots_adjust(left=0.1, bottom=0.1, right=0.1, top=0.1,
#                wspace=0.1, hspace=0.1)
        f.subplots_adjust(bottom=0.1, left=.1, right=.975, top=.95, hspace=0.2)
#        f.tight_layout()        
        plt.show()
        
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
    def zero_phase_bank(self):
        if not self.ZeroPhase:
            self.ZeroPhasedBank = np.zeros_like(self.MyGausPulseRaw)
            for i in range(self.NumberOfFilters):
                self.ZeroPhasedBank[:,i], _ = ZeroPhasing(self.MyGausPulseRaw[:,i])
            self.ZeroPhase = True
            
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

def SS_filter_ZeroPhase(FTSignal, FTBank, ScanLength):
    FilteredSignal = np.zeros((ScanLength, FTBank.shape[1]))
    for i in range(FTBank.shape[1]):        
        Aux = np.fft.ifft(FTSignal * FTBank[:,i])
        FilteredSignal[:,i] = Aux[0:ScanLength].real
    return FilteredSignal



# This function calculates the maxima location in subsample basis using cosine interpolation
def CosineInterpMax(MySignal):
    # Signal is the input signal

    
#    MySignal = np.absolute( signal.hilbert(MySignal) )
    

    MaxLoc = np.argmax(MySignal) # find index of maximum
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


def ZeroPhasing(MySignal):
    MyDelay = CosineInterpMax( np.absolute(MySignal) )
    MySignal = ShiftSubsampleByfft(MySignal, MyDelay)
    return MySignal, MyDelay


def RaiseExpPulse( SigLength=1024, Fs = 100e6, Fc = 6e6, pulseAttenuation = 7, pulseExponential = 16e6): 
#Calculate a Gaussian filter acording to specifications
# The filter is given centered unless zerophase set to true
#
#Inputs
#  Fs Sampling Frequency in Hz
#  Fc Central frequency of the filter (Hz)
#  pulseAttenuation attenuation factor
#  pulseExponential Exponential factor 

#Outputs
#  MyGaussPulse -> Gaussian Filter

#
#Alberto, 13/01/2015
#
#Example
# N=1024
#Fc=6e6; % Central frequency of the filter (Hz)
#Fs = 100e6 % sampling frequency 100MHz
#pulseAttenuation = 7
#pulseExponential = 16e6

#Filtro,t,_=RaiseExpPulse(N, Fs, Fc, pulseAttenuation, pulseExponential)

    Tpulse = SigLength/Fs
    t = np.linspace(0, Tpulse-1/Fs, SigLength, endpoint=False) #Creates time basis (N)
    MyPulse = np.power(t,pulseAttenuation) * np.exp(-pulseExponential*t) * np.sin(2*np.pi*Fc*t) #Creates pulse
           
    return MyPulse, t



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

def Beamforming(Pulse, SamplingFrequency = 100e6, TransducerTriggerTimer = 110e-9, TransducerTriggerFactor = 0.8):
    # Beamforms pulses
    t = np.linspace(0, Pulse.size/SamplingFrequency-1/SamplingFrequency, Pulse.size, endpoint=False) #Creates time basis (N)
    Tprima = TransducerTriggerTimer / TransducerTriggerFactor # time constant fo the trigger window
    v = np.zeros_like(Pulse) # trigger window creation
    a = np.nonzero( (Tprima-TransducerTriggerTimer)/2 <= t )[0][0]
    b = np.nonzero( t>= (Tprima+TransducerTriggerTimer)/2 )[0][0]
    v[a:b]=1
    LastPulse = np.convolve(Pulse, v, mode='full')

    return LastPulse[0:Pulse.size]

def CalcMeanPower(MySignal):
    # Calculates mean power of a sequence (energy as limited)
    MyPower = np.sum( np.square(MySignal) ) / MySignal.size
    return MyPower     

def CalcNormSNR(MySignal, FlawLoc, PulseWidth):
    # Calculates normalized signal to noise ratio as the ratio between the
    # energy at flaw location with width equal to pulsewidth and the total
    # energy. It gives 1 if there is no noise and 0 if there is no pulse
    PS = np.sum(np.square(MySignal[FlawLoc - np.round(PulseWidth / 2):FlawLoc + np.round(PulseWidth / 2)]))
    PN = np.sum(np.square(MySignal))
    return PS / PN
    
def CalcFCR(MySignal, FlawLoc, PulseWidth):
    # Calculates the flaw to clutter ratio as the ratio between the
    # maximum value around flaw location (with pulse width) and the maximum
    # of the noise (outside the flaw location)
    MaxSig = np.max(np.absolute(MySignal[FlawLoc - np.round(PulseWidth / 2):FlawLoc + np.round(PulseWidth / 2)]))
    MaxNoise = np.max(np.absolute([np.max(MySignal[0:FlawLoc - np.round(PulseWidth / 2)-1]), np.max(MySignal[FlawLoc + np.round(PulseWidth / 2)+1:])]))
    return MaxSig / MaxNoise
    
def CalcDetectability(MySignal, FlawLoc, PulseWidth):
    # Calculates the detectability of the flaw, measured as the ratio between 
    # the maximum of the flaw and the maximum of the signal. If detectability
    # is one, the maximum will be at defect location, otherwise will
    # provide a measure of how far is the flaw from the maximum
    MaxSig = np.max(np.absolute(MySignal[FlawLoc - np.round(PulseWidth / 2):FlawLoc + np.round(PulseWidth / 2)]))    
    return MaxSig / np.max(np.absolute(MySignal))
    

def CalcEnvelope(MySignal):
    return np.abs(signal.hilbert(MySignal))
    
