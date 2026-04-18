from ctypes import (c_uint8, c_uint16, c_double, c_byte, c_ulong, c_short,
                    c_long, c_uint, c_char_p, POINTER, byref, cdll, WinDLL)
import numpy as np
from pathlib import Path
import os

def Gencode_from_file(f_n):
    f = open(f_n, 'r')
    lines = []
    for line in f:
        line = line.strip('\r\n')
        lines.append(line)
    f.close()
    return lines
  
def ClosestPowerOf2(gencode_len):
    # Cambiado ligeramente del original, que esta comentado
#    N = 0
#    while 2**N < gencode_len:
#        N = N + 1
#    
#    return N
    return int(np.ceil(np.log2(np.abs(gencode_len))))


class SeDaqDLL:
    def __init__(self, dllPath=None):
        usb_path = Path(__file__).parent / "USB2.dll"
        self.usb = WinDLL(str(usb_path))

        if dllPath is None:
            dll_path = Path(__file__).parent / "SeDaqDLL.dll"
            cmd = cdll.LoadLibrary(str(dll_path))
        else:
            cmd = cdll.LoadLibrary(dllPath)
        self.SeDaqDLL_SetExcVoltage = cmd.SeDaqDLL_SetExcVoltage
        self.SeDaqDLL_SetSoftTrig = cmd.SeDaqDLL_SetSoftTrig
        self.SeDaqDLL_SetExcWave = cmd.SeDaqDLL_SetExcWave
        self.SeDaqDLL_SetGain = cmd.SeDaqDLL_SetGain
        self.SeDaqDLL_GetAScan = cmd.SeDaqDLL_GetAScan
        self.SeDaqDLL_SetRecLen = cmd.SeDaqDLL_SetRecLen
        self.SeDaqDLL_SetBankDelay= cmd.SeDaqDLL_SetBankDelay
        self.SeDaqDLL_Init = cmd.SeDaqDLL_Init
        self.SeDaqDLL_EnableExc = cmd.SeDaqDLL_EnableExc
        self.SeDaqDLL_UartSend = cmd.SeDaqDLL_UartSend
        self.SeDaqDLL_UartGet = cmd.SeDaqDLL_UartGet
        self.SeDaqDLL_SetRelay = cmd.SeDaqDLL_SetRelay
        self.SeDaqDLL_UartRead = cmd.SeDaqDLL_UartRead
        self.ApintUsb = cmd.ApintUsb

        # self.SeDaqDLL_Init()

        self.ProductNumber = c_ulong(1)
        self.ChannelNumber = c_ulong(1)
        self.In2 = c_double(0); self.In3 = c_double(0)
        self.In4 = c_double(0); self.In5 = c_double(0); self.In6 = c_double(0)
        self.Out1 = c_short(0); self.Out2 = c_short(0); self.Out3 = c_short(0)
        self.Out4 = c_short(0); self.Out5 = c_short(0); self.Out6 = c_short(0)
        self.Arr = c_uint * 1
        self.leng = c_long(1)
        self.Array = self.Arr()

        ADC1 = c_uint16 * (1024*32)
        ADC2 = c_uint16 * (1024*32)
        
        self.DataADC1 = ADC1()
        self.DataADC2 = ADC2()
        
        self.GenCodes = []
        self.RecLen = 1024*32
    
    def SetRecLen(self, RecLen):
        self.SeDaqDLL_SetRecLen(RecLen, 1)
        self.SeDaqDLL_SetRecLen(RecLen, 2)
        self.RecLen = RecLen
    
    def GetAScan(self):
        self.SeDaqDLL_SetSoftTrig(1)
        self.SeDaqDLL_GetAScan(byref(self.DataADC1),1)
        self.SeDaqDLL_GetAScan(byref(self.DataADC2),2)
    
    def GetAScan1(self):
        # thread.start_new_thread(self.SeDaqDLL_SetSoftTrig, (1, ))
        # thread.start_new_thread(self.SeDaqDLL_GetAScan, (byref(self.DataADC1),1, ))
        self.SeDaqDLL_SetSoftTrig(1)
        self.SeDaqDLL_GetAScan(byref(self.DataADC1),1)
        
    def GetCycleAScan1(self, CycleNo):
        # thread.start_new_thread(self.SeDaqDLL_SetSoftTrig, (1, ))
        # thread.start_new_thread(self.SeDaqDLL_GetAScan, (byref(self.DataADC1),1, ))
        CycleAScan1 = []
        for i in xrange(CycleNo):
            self.GetAScan1()
            CycleAScan1.append(self.DataADC1[:self.RecLen])
        return np.array(CycleAScan1)
        
    def GetAScan2(self):
        self.SeDaqDLL_SetSoftTrig(1)
        self.SeDaqDLL_GetAScan(byref(self.DataADC2),2)
           
    def SetGenCode(self, GenCodeNo):
        GenArrayTo = self.GenCodes[GenCodeNo-1] # 
        BytesTot = len(GenArrayTo)
        self.SeDaqDLL_SetExcWave(byref(GenArrayTo),BytesTot,0)
        
    def UpdateGenCode(self, gencode):
        gencode_len = len(gencode)
        N = ClosestPowerOf2(gencode_len)
        BytesTot = 2**N
        GenArrayTo = (c_uint8 * BytesTot)()
        for i in range(BytesTot):
            if i<gencode_len:
                GenArrayTo[i] = c_uint8(int(gencode[i]))
            else:
                GenArrayTo[i] = c_uint8(0)
        BytesTot = len(GenArrayTo)
        self.SeDaqDLL_SetExcWave(byref(GenArrayTo),BytesTot,0)
        
        
    def AddGenCode(self, file_name):
        gencode = Gencode_from_file(file_name)

        gencode_len = len(gencode)
        N = ClosestPowerOf2(gencode_len)
        BytesTot = 2**N

        GenArrayTo = (c_uint8 * BytesTot)()
        for i in range(BytesTot):
            if i<gencode_len:
                GenArrayTo[i] = c_uint8(int(gencode[i]))
            else:
                GenArrayTo[i] = c_uint8(0)
        self.GenCodes.append(GenArrayTo)
        
        
    def SetBankDelay(self, BankDelay):
        self.SetBankDelay(c_double(BankDelay),1)
        self.SetBankDelay(c_double(BankDelay),2)

    def SetGain1(self, gain):
#        thread.start_new_thread( self.SeDaqDLL_SetGain, (c_double(gain),1, ))
        self.SeDaqDLL_SetGain(c_double(gain),1)

    def SetGain2(self, gain):
#        thread.start_new_thread( self.SeDaqDLL_SetGain, (c_double(gain),2, ))
        self.SeDaqDLL_SetGain(c_double(gain),2)

    def SetExtVoltage(self, voltage, timeout=2.0):
        import time
        t0 = time.time()
        while self.Out1.value != 0:
            if time.time() - t0 > timeout:
                break
            time.sleep(0.005)
        self.ApintUsb(self.ProductNumber, self.ChannelNumber,
                      c_char_p(b'voltage'), c_double(voltage),
                      self.In2, self.In3, self.In4, self.In5, self.In6,
                      byref(self.Out1), byref(self.Out2), byref(self.Out3),
                      byref(self.Out4), byref(self.Out5), byref(self.Out6),
                      self.Array, byref(self.leng))

    def SetRelay(self, mode):
        self.SeDaqDLL_SetRelay(mode)

    def Close(self):
        self.usb.UsbClose(c_byte(0))


        