# -*- coding: utf-8 -*-
"""
Created on Wed Oct  1 11:47:29 2025

@author: Alberto
"""

import serial
import numpy as np

class Arduino:
    def __init__(self, baudrate=9600, port='COM4', N_avg=1):
        self.N_avg = N_avg  # número de lecturas a promediar
        self.ser = serial.Serial(port, baudrate, timeout=None)  # abre comunicación

    def getTemperatures(self, error_msg: str = None, exception_msg: str = None):
        """
        Lee N_avg líneas de datos del Arduino y devuelve
        el promedio de T1 y T2 como una tupla (T1, T2).
        """
        lines = [None] * self.N_avg
        temps = np.zeros((self.N_avg, 2))  # matriz N_avg x 2
        GoodMeasurement = False

        while not GoodMeasurement:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

            # sincroniza con salto de línea
            while self.ser.read() != b'\n':
                pass

            for i in range(self.N_avg):
                lines[i] = self.ser.readline()

            GoodMeasurement = True

            for i in range(self.N_avg):
                try:
                    if lines[i] != b'':
                        parts = lines[i].decode().strip().split()
                        if len(parts) == 2:  # esperamos T1 y T2
                            temps[i, 0] = float(parts[0])
                            temps[i, 1] = float(parts[1])
                        else:
                            if error_msg is not None:
                                print(error_msg)
                            GoodMeasurement = False
                    else:
                        if error_msg is not None:
                            print(error_msg)
                        GoodMeasurement = False
                except Exception:
                    if exception_msg is not None:
                        print(exception_msg)
                    GoodMeasurement = False

        return np.mean(temps, axis=0)  # devuelve [T1_avg, T2_avg]
    def close(self):
        if self.ser.is_open:
            self.ser.close()
    
#%%
arduino = Arduino(port='COM4', baudrate=9600, N_avg=5)
T1, T2 = arduino.getTemperatures()
print(f"Sensor1 = {T1:.2f} °C, Sensor2 = {T2:.2f} °C")
arduino.close()    