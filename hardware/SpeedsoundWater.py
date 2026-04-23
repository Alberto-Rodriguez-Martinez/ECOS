# SpeedsoundWater.py
import numpy as np
from temperature_Alberto_temporal import Arduino

def water_temp2sos(T):
    """
    Calcula la velocidad del sonido en agua según la temperatura T (°C).
    """
    c = 1.569678141e3 * np.exp(-((T - 5.907868678e1) / (-3.443078912e2))**2) - \
        2.574064370e4 * np.exp(-((T + 3.705052160e2) / (-1.601257116e2))**2)
    return c

def get_Cw_from_arduino(N_avg=3, max_attempts=5, closePort=False, port='COM4', baudrate=115200):
    """
    Lee las temperaturas del Arduino y calcula la velocidad del sonido en agua.

    Parámetros:
    - N_avg: número de lecturas promedio
    - max_attempts: máximo de intentos si falla la lectura
    - closePort: cerrar el puerto serie al terminar
    - port: puerto COM del Arduino (por defecto 'COM4')
    - baudrate: velocidad del puerto serie (por defecto 115200)

    Retorna:
    - temp1, temp2: temperaturas de los sensores (°C)
    - Cw1, Cw2: velocidades del sonido calculadas (m/s)
    """
    arduino = Arduino(baudrate=baudrate, port=port, N_avg=N_avg)
    
    # Intentos de lectura segura
    for attempt in range(max_attempts):
        try:
            temp1, temp2 = arduino.getTemperatures(
                error_msg=f"Intento {attempt+1}: Error leyendo sensor",
                exception_msg=f"Intento {attempt+1}: Excepción al leer sensor"
            )
            break  # lectura exitosa
        except Exception as e:
            print(f"[ERROR] {e}")
            temp1, temp2 = None, None
    else:
        print("[ERROR] No se pudo leer temperatura del Arduino después de varios intentos.")
    if closePort is True:
        arduino.close()
    
    if temp1 is None or temp2 is None:
        return None, None, None, None

    # Calcula velocidades del sonido
    Cw1 = water_temp2sos(temp1)
    Cw2 = water_temp2sos(temp2)

    return temp1, temp2, Cw1, Cw2

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Lee temperatura del Arduino y calcula Cw en agua.")
    parser.add_argument('--port',     default='COM4',   help='Puerto COM del Arduino (default: COM4)')
    parser.add_argument('--baudrate', default=115200,   type=int, help='Baudrate (default: 115200)')
    parser.add_argument('--navg',     default=3,        type=int, help='Número de lecturas promedio (default: 3)')
    args = parser.parse_args()

    temp1, temp2, Cw1, Cw2 = get_Cw_from_arduino(N_avg=args.navg, port=args.port, baudrate=args.baudrate)
    if temp1 is not None:
        print(f"Sensor 1: T={temp1:.2f} °C, Cw={Cw1:.2f} m/s")
        print(f"Sensor 2: T={temp2:.2f} °C, Cw={Cw2:.2f} m/s")
