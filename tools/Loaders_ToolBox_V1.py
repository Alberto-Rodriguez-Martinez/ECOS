# -*- coding: utf-8 -*-
"""
Created on Mon Mar 07 19:11:44 2016
This tollBox is used to create loader for all sort of data
@author: Alberto
"""
import sys
import numpy as np


# this creates variables with all the variables of acquisition in standard.var
class StdVar:
    def __init__(self, FileName):
        
        with open(FileName, 'r') as f:
            for line in f: # search in all lines
#                print line
                [A,B] = line.split(' - ')
                [C,D] = B.split('\n')
                try: # check if they are numeric
                    setattr(self,C,int(A)) # create new attribute as integer
                except ValueError:
                    try:
                        setattr(self,C,float(A)) # create new attribute as float
                    except ValueError:
                        setattr(self,C,A) # create new attribute as string
        f.close()
        

# Load data from bin file and reshape into matrix. USed for Cscans
def LoadBinCscan(filename, Xsteps, Ysteps, Avg, ScanLen, N1=0, N2=0):
    """
    Load Cscan from Bin file, lithuanian ACQ format
    Inputs:
        filename = file to load, *.bin
        Xsteps number of scanning points along X axis for Cscan
        Ysteps number of scanning points along Y axis for Cscan
        Avg = number of Ascans acq. at each location, to be averaged
        ScanLen = total scanlength
        N1 = starting sample for the output
        N2 = last sample for the output, if 0 then to ScanLength
    Outputs:
        MyData = 3D matrix with Cscan [Xsteps,ScanLen,Ysteps]
        
    """
    fd = open(filename, 'rb')
    if N2==0:        
        N2=ScanLen
    MyData = np.zeros((Xsteps,N2-N1,Ysteps))
    if Avg==1:
        for i in range(Ysteps):            
            for j in range(Xsteps):
                Ascan = np.fromfile(fd, dtype=np.uint16, count=ScanLen)/1024.
                MyData[j,:,i] = (Ascan - np.mean(Ascan))[N1:N2]
                
    else:
        for i in range(Ysteps):
            for j in range(Xsteps):
                Ascan = np.zeros(ScanLen)
                for k in range(Avg):
                    Ascan = np.fromfile(fd, dtype=np.uint16,count=ScanLen) + Ascan
                Ascan = (Ascan/1024.) / Avg                
                MyData[j,:,i] = (Ascan - np.mean(Ascan))[N1:N2]
    fd.close()
    return MyData

# Load data from bin file and reshape into matrix. USed for Cscans
def LoadBinCscanFFT(filename, Xsteps, Ysteps, Avg, ScanLen, N1=0, N2=0, Fs=100e6, nfft=1024,Flim=10):
    """
    Load Cscan from Bin file, lithuanian ACQ format
    Inputs:
        filename = file to load, *.bin
        Xsteps number of scanning points along X axis for Cscan
        Ysteps number of scanning points along Y axis for Cscan
        Avg = number of Ascans acq. at each location, to be averaged
        ScanLen = total scanlength
        N1 = starting sample for the output
        N2 = last sample for the output, if 0 then to ScanLength
    Outputs:
        MyData = 3D matrix with Cscan [Xsteps,ScanLen,Ysteps]
        
    """

    N = int(Flim/Fs*nfft)
    fd = open(filename, 'rb')
    if N2==0:        
        N2=ScanLen
    MyData = np.zeros((Xsteps,N,Ysteps))
    if Avg==1:
        for i in range(Ysteps):            
            for j in range(Xsteps):
                Ascan = np.fromfile(fd, dtype=np.uint16, count=ScanLen)/1024.
                Bscan = (Ascan - np.mean(Ascan))[N1:N2]
                MyData[j,:,i] = np.abs(np.fft.fft(Bscan,nfft))[:N]
                
    else:
        for i in range(Ysteps):
            for j in range(Xsteps):
                Ascan = np.zeros(ScanLen)
                for k in range(Avg):
                    Ascan = np.fromfile(fd, dtype=np.uint16,count=ScanLen) + Ascan
                Ascan = (Ascan/1024.) / Avg
                Bscan = (Ascan - np.mean(Ascan))[N1:N2]
                MyData[j,:,i] = np.abs(np.fft.fft(Bscan,nfft))[:N]                

    fd.close()
    return MyData

# Load data from bin file and reshape into matrix. USed for bscans
def LoadBinBscan(filename, Xsteps, Avg, ScanLen, N1=0, N2=0):
    """
    Load Bscan from Bin file, lithuanian ACQ format
    Inputs:
        filename = file to load, *.bin
        Xsteps number of scanning points for Bscan
        Avg = number of Ascans acq. at each location, to be averaged
        ScanLen = total scanlength
        N1 = starting sample for the output
        N2 = last sample for the output, if 0 then to ScanLength
    Outputs:
        MyData = 2D matrix with Cscan [Xsteps,ScanLen]        
    """
    fd = open(filename, 'rb')
    if N2==0:        
        N2=ScanLen
    MyData = np.zeros((Xsteps,N2-N1))
    if Avg==1:
        for j in range(Xsteps):            
            Ascan = np.fromfile(fd, dtype=np.uint16, count=ScanLen)/1024.
            MyData[j,:] = (Ascan - np.mean(Ascan))[N1:N2]                
    else:
        for j in range(Xsteps):
            Ascan = np.zeros(ScanLen)
            for k in range(Avg):
                Ascan = np.fromfile(fd, dtype=np.uint16, count=ScanLen) + Ascan
            Ascan = (Ascan/1024.) / Avg                
            MyData[j,:] = (Ascan - np.mean(Ascan))[N1:N2]
    fd.close()
    return MyData

# Load data from bin file and reshape into matrix. USed for Ascans
def LoadBinAscan(filename, Avg, ScanLen, N1=0, N2=0):
    """
    Load Ascan from Bin file, lithuanian ACQ format
    Inputs:
        filename = file to load, *.bin
        Avg = number of Ascans acq. at each location, to be averaged
        ScanLen = total scanlength
        N1 = starting sample for the output
        N2 = last sample for the output, if 0 then to ScanLength
    Outputs:
        MyData = 2D matrix with Cscan [Xsteps,ScanLen]        
    """
    fd = open(filename, 'rb')
    if N2==0:        
        N2=ScanLen
    MyData = np.zeros(N2-N1)
    if Avg==1:        
        Ascan = np.fromfile(fd, dtype=np.uint16, count=ScanLen)/1024.
        MyData = (Ascan - np.mean(Ascan))[N1:N2]                
    else:
        Ascan = np.zeros(ScanLen)
        MyAvg = Avg
        for k in range(Avg):
            Ascan1 = np.fromfile(fd, dtype=np.uint16, count=ScanLen) 
            if not(np.all(Ascan1==0.0)):                
                Ascan = Ascan1 + Ascan
            else:
                MyAvg = MyAvg-1
        print('%d Ascans rejected '%(Avg-MyAvg))
        Ascan = (Ascan/1024.) / MyAvg                
        MyData = (Ascan - np.mean(Ascan))[N1:N2]
    fd.close()
    return MyData


# create Data_Matrix loading binary files from acquisition
# very old version, maybe not used anymore
class SingleCycleData:
    def __init__(self, FileName, MyStdVar, LoadType = 'SingleCycle',
                 Average = 'True', ChNr = 1, SigNr = 1, LoadRange = np.array([0])):
        # Check simensions
        x = MyStdVar.GenCode # number of excitations
        y = MyStdVar.TestCycNr #number of experiment repetitions
        z = MyStdVar.AvgSamplesNumber # numer of Ascan per step
        s = MyStdVar.Smax-MyStdVar.Smin # number of samples per Ascan
        Data = Load_data_bin(FileName,x,y,z,s)/1024.0 # Load Data
        if LoadRange.size>1:
            Data = Data[:,:,:,LoadRange]
            s = LoadRange.size
        for i in range(x):
            for j in range(y):
                for k in range(z):
                    Data[i,j,k,:] = Data[i,j,k,:]-np.mean(Data[i,j,k,:])
                    
        if Average:
            Data = np.mean(Data,axis=2)
            Data.resize((x,y,s))
        else:
            if z == 1:
                Data.resize((x,y,s))
        shape = Data.shape
        if shape[0] == 1:
            Data.resize(shape[1:])
            shape = Data.shape
            if shape[0] == 1:
                if len(shape)>2:
                    Data.resize(shape[1:])
        else:
            if shape[1] == 1:
                if len(shape)>3:
                    Data.resize(x,z,s)
                else:
                    Data.resize(x,s)
        self.Data = Data            

          
# Load data from bin file and reshape into matrix. USed in SingleCycleData:
# very old version, maybe not used anymore
def Load_data_bin(filename,x,y,z,s):
# x - number of rows, y - number of columns, z - Ascans per step, s - Ascan length
    shape = (x,y,z,s)
    fd = open(filename, 'rb')
    data = np.fromfile(file=fd, dtype=(np.uint16)).reshape(shape)
    fd.close()
    return data


# Load 2 channel data data from text file. Also loads standar.var
def Load_Ascans_PE_TT(DataPath):
    #----------------------------------------------
    # Load 2 channels Ascan TT and PE, from text file
    # Ascans already averaged and Gain corrected
    # 
    # Inputs:
    #   DataPath = name of the path where the data is saved
    #
    # Outputs
    #   TT_Ascan = Ascan from channel 1 TT
    #   PE_Ascan = Ascan from channel 2 PE
    #   MyVars = standard vars from experiment
    #
    # Alberto, 24/05/2017
    #----------------------------------------------

    #----------------------------------------------
    # load standvar
    #----------------------------------------------
    FileStdVar = DataPath +"\standard.var" #standard.var file  
    MyVars = StdVar(FileName = FileStdVar)
#    variables = MyVars.__dict__.keys() # all the variables  
    
    #----------------------------------------------
    # Load Ascans
    #----------------------------------------------    
    
    File2Load_1 = DataPath + '\Ch1_Ascan.txt' #Ascan from Ch1
    File2Load_2 = DataPath + '\Ch2_Ascan.txt' #Ascan from Ch2
        
    TT_Ascan = np.fromfile(File2Load_1, dtype=float, count=-1, sep='\n') #load channel 1 Ascan
    PE_Ascan = np.fromfile(File2Load_2, dtype=float, count=-1, sep='\n') #load channel 2 Ascan    
    
    TT_Ascan = TT_Ascan / np.power(10,(MyVars.Gain1/20)) # Correct gain
    PE_Ascan = PE_Ascan / np.power(10,(MyVars.Gain2/20)) # correct gain
           
    return TT_Ascan, PE_Ascan, MyVars

# loads Ascan from file
def Load_Ascan(File2Load):
    #----------------------------------------------
    # Load Ascan from text file
    # Ascans already averaged and Gain corrected
    # Inputs:
    #   File2Load = name of the file where the data is saved, including path
    #
    # Outputs
    #   Ascan = Ascan from file
    #
    # Alberto, 24/05/2017
    #----------------------------------------------
    
    #----------------------------------------------
    # Load Ascans
    #----------------------------------------------    

    Ascan = np.fromfile(File2Load, dtype=float, count=-1, sep='\n') #load channel 2 Ascan    
    
#    TT_Ascan = TT_Ascan / np.power(10,(MyVars.Gain1/20)) # Correct gain
#    PE_Ascan = PE_Ascan / np.power(10,(MyVars.Gain2/20)) # correct gain
           
    return Ascan

    
