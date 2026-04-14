# -*- coding: utf-8 -*-
"""
Created on Tue Jan 27 10:27:20 2026

@author: Alberto
"""

# -*- coding: utf-8 -*-
import serial
import numpy as np
import time

class Arduino:
    def __init__(self, port='COM4', baudrate=115200, N_avg=1):
        self.N_avg = N_avg
        self.ser = serial.Serial(port, baudrate, timeout=0.2)
        time.sleep(2)  # esperar a que Arduino reinicie
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def getTemperatures(self, error_msg=None, exception_msg=None):
        temps_list = []

        for _ in range(self.N_avg):
            try:
                line = self.ser.readline().decode(errors='ignore').strip()
                if not line:
                    continue  # timeout, línea vacía
                parts = line.split()
                if len(parts) == 2:
                    temps_list.append([float(parts[0]), float(parts[1])])
                else:
                    if error_msg:
                        print(error_msg)
            except Exception:
                if exception_msg:
                    print(exception_msg)

        if temps_list:
            return np.mean(temps_list, axis=0)
        else:
            return None, None

    def close(self):
        if self.ser.is_open:
            self.ser.close()


if __name__ == "__main__":
    arduino = Arduino(port='COM4', baudrate=115200, N_avg=2)
    T1, T2 = arduino.getTemperatures()
    print(f"Sensor1 = {T1:.2f} °C, Sensor2 = {T2:.2f} °C")
    arduino.close()
