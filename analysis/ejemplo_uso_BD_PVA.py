# -*- coding: utf-8 -*-
"""
Created on Mon Oct 6 12:01:46 2025
@author: Alberto
"""

# En la máquina de adquisición (32-bit)
import numpy as np
from BD_Experimentos_PVA import (
    save_experiment_raw_32, load_raw32, plot_signals,
    append_experiment_to_xlsx, quick_stats,
    plot_signals_stacked, export_results_catalog_csv
)
      
#%%
# Estructuras de experimento
#==============================

specimen = {
    "fecha_fabricacion": "2025-10-01",
    "base": "agua",
    "porcentaje_pva": "10%",
    "aditivo1": "Propenglicol",
    "porcentaje_aditivo1": "20%",
    "ciclos": 2,
    "pieza": "I",
    "otros": ""
}

equipment1 = {
    "nombre": "SEDAQ",
    "transductor_pe": "Enfocado 5MHz XXX",
    "transductor_tt": "No enfocado 5 MHz XXX",
    "params": {
        "Gain_Ch1": 35, "Gain_Ch2": 40, "Voltaje": 50,
        "F_muestreo": 100e6, "Fc_pulso": 5e6, "Tipo_excitacion": "Pulso",
        "QuantizationLevels": 1024, "AverageSamples": 25,
        "RecLen": 32000, "Smin": 1000, "Smax": 4000, "Slen": 3000,
        "WindowLen": 200
    }
}

equipment2 = {
    "nombre": "Arduino",
    "transductor_temp_1": "XYZ",
    "transductor_temp_2": "",
    "otros": ""
}

protocol = {"description": "Ensayo ultrasónico", "notes": ""}


# Señales (simuladas)
#==============================

Fs = float(equipment1["params"]["F_muestreo"])
Smin, Smax = 1000, 4000
n = np.arange(Smin, Smax)
t = n / Fs

Signal_PE  = np.sin(2 * np.pi * 5e6 * t) + 0.01 * np.random.randn(t.size)
Signal_TT  = 0.7 * np.sin(2 * np.pi * 4.2e6 * t + 0.3) + 0.01 * np.random.randn(t.size)
Signal_Ref = 0.5 * np.sin(2 * np.pi * 5e6 * t - 0.5) + 0.01 * np.random.randn(t.size)

#%% ==============================
# Resultados del experimento
#==============================

results = {
    "T1": 23.456,
    "T2": 24.564,
    "C1": 1500.452,
    "C2": 1499.456,
    "Cw": 1546.34,
    "Cl": 1565.667,
    "L": 3.456
}

#%% ==============================
# Guardar experimento
#==============================

exp_dir_32 = save_experiment_raw_32(
    specimen=specimen,
    equipment1=equipment1,
    equipment2=equipment2,
    protocol=protocol,
    results=results,
    Signal_PE=Signal_PE,
    Signal_TT=Signal_TT,
    Signal_Ref=Signal_Ref,
    base_dir="data_32"
)

print("Guardado 32-bit en:", exp_dir_32)

#%% ==============================
# Cargar experimento (ejemplo)
#==============================

# Sustituye por la carpeta generada en tu ejecución si es distinta
exp_dir = r"data_32\20260220_105943_EXPID-4F799CC8"

meta, results, signals, times = load_raw32(exp_dir)

print("ID:", meta["experiment"]["id"])
print("Operador:", meta["experiment"].get("operator"))
print("Resultados:", results)

#%% ==============================
# Estadísticos por señal
#==============================

Fs = float(meta["equipment"]["device_1_ultrasound"]["params"].get("F_muestreo", 0.0) or 0.0)
for name, y in signals.items():
    print(name, quick_stats(y, Fs=Fs))

#%% ==============================
# Graficar señales (si matplotlib está instalado)
#==============================

plot_signals_stacked(signals, times, title=f"Experimento {meta['experiment']['id']}")

#%% ==============================
# Generar CSV con todos los resultados
#==============================

csv_path, n_rows, n_cols = export_results_catalog_csv(
    base_dir="data_32",
    out_csv="data_32/catalogo_resultados.csv",
    delimiter=";",         # bien
    decimal_comma=False    # <-- usa punto decimal para Excel en inglés
)


#%% ==============================
# Añadir nuevo experimento al Excel
#==============================

exp_dir = r"data_32\20260220_135655_EXPID-0E1DBE3C"  # carpeta del experimento (meta.json + results.json)
xlsx, nrow, ncol = append_experiment_to_xlsx(
    exp_dir,
    xlsx_path="salidas/catalogo_resultados.xlsx",
    sheet_name="Catalog"
)


print(f"Añadido a {xlsx} (fila {nrow}, columnas {ncol})")


#%%

#%%

from pathlib import Path   # <-- NECESARIO

# 1) Tu carpeta de experimento
exp_dir = r"data_32\20251114_112957_EXPID-FDEDF1FB"

# 2) Crea la carpeta 'salidas' si no existe
Path("salidas").mkdir(parents=True, exist_ok=True)

# 3) Validaciones rápidas y rutas absolutas
p_exp = Path(exp_dir).expanduser().resolve()
p_xlsx = Path("salidas/catalogo_resultados.xlsx").expanduser().resolve()

print("EXP DIR ABS:", p_exp, "  Existe?:", p_exp.exists())
print("XLSX ABS   :", p_xlsx)

# 4) Comprueba JSONs
print(" - metadata.json:", (p_exp / "metadata.json").exists())
print(" - meta.json    :", (p_exp / "meta.json").exists())
print(" - results.json :", (p_exp / "results.json").exists())
