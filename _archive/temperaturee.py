# -*- coding: utf-8 -*-
"""
temperaturee.py
Clase Arduino para leer temperaturas de dos sensores promediando N_avg lecturas.
Usa un límite de tiempo (max_time_s) en lugar de un número de intentos.
"""

import serial
import numpy as np
import time


class Arduino:
    def __init__(self, baudrate=115200, port='COM3', N_avg=1, timeout=0.2):
        """
        Inicializa la conexión con Arduino.
        - baudrate: AJÚSTALO al del sketch (p. ej., 115200 o 9600)
        - timeout: tiempo de espera por línea
        """
        self.N_avg = max(1, int(N_avg))
        self.port = port
        self.baudrate = baudrate
        try:
            self.ser = serial.Serial(port, baudrate, timeout=timeout)
            time.sleep(2)  # esperar reinicio del Arduino (DTR)
            # Limpiar buffers SOLO una vez, al inicio
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except serial.SerialException as e:
            print(f"[ERROR] No se pudo abrir el puerto {port}: {e}")
            self.ser = None

    def _parse_line(self, line_bytes):
        """Devuelve (temp1, temp2) o None si la línea no es válida."""
        if not line_bytes:
            return None
        try:
            line = line_bytes.decode('ascii', errors='ignore').strip()
            if not line:
                return None
            parts = line.split()
            if len(parts) != 2:
                return None
            t1 = float(parts[0])
            t2 = float(parts[1])
            return (t1, t2)
        except Exception:
            return None

    def getTemperatures(self, max_time_s=1.0):
        """
        Acumula N_avg lecturas válidas sin resetear buffers en cada intento.
        Si no se logra en max_time_s, lanza TimeoutError.
        """
        if self.ser is None or not self.ser.is_open:
            raise ConnectionError(f"Puerto {self.port} no está abierto.")

        t_start = time.time()
        vals_t1 = []
        vals_t2 = []

        while len(vals_t1) < self.N_avg:
            if (time.time() - t_start) > max_time_s:
                raise TimeoutError(
                    f"No se obtuvieron {self.N_avg} lecturas válidas en {max_time_s:.2f}s"
                )

            line = self.ser.readline()  # condicionado por timeout
            parsed = self._parse_line(line)
            if parsed is not None:
                t1, t2 = parsed
                vals_t1.append(t1)
                vals_t2.append(t2)

        mean_temp1 = float(np.mean(vals_t1)) if self.N_avg > 1 else vals_t1[0]
        mean_temp2 = float(np.mean(vals_t2)) if self.N_avg > 1 else vals_t2[0]
        return mean_temp1, mean_temp2

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"[INFO] Puerto {self.port} cerrado.")

    def __del__(self):
        try:
            self.close()
        except:
            pass


# ===============================
# Ejemplo de uso
# ===============================
if __name__ == "__main__":
    try:
        # AJUSTA baudrate al de tu sketch (115200 o 9600)
        arduino = Arduino(baudrate=115200, port='COM3', N_avg=3, timeout=0.2)

        temp1, temp2 = arduino.getTemperatures(max_time_s=0.5)
        print(f"Sensor 1: {temp1:.2f} °C")
        print(f"Sensor 2: {temp2:.2f} °C")

    except Exception as e:
        print(f"[ERROR] No se pudo leer temperatura: {e}")
        temp1, temp2 = None, None
    finally:
        if 'arduino' in locals():
            arduino.close()