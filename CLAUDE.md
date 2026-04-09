# ECOS — Elastic Characterization Of Soft-tissue phantoms
**Universidad Miguel Hernández (UMH)** · Dpto. Ingeniería de Comunicaciones  
**Investigador principal:** A. Rodríguez-Martínez

## Contexto del proyecto
Caracterización ultrasónica de phantoms de tejido blando (hidrogeles de PVA) para 
robótica quirúrgica. Construido sobre experiencia previa en caracterización de 
composites dopados con nanopartículas.

## Stack tecnológico
- **Python 32 bits** — obligatorio por compatibilidad con hardware (SeDaqDLL.dll)
- NumPy, SciPy, Matplotlib
- Adquisición hardware vía SeDaq.py / SeDaqDLL.dll (digitizador)
- Control de temperatura vía Arduino (MAX31865)
- Entorno: VSCode + GitHub

## Excitación
Pulsos rectangulares a 5 o 10 MHz según el transductor utilizado.  
APWP (Adaptive Pulse Waveform Programming) está previsto para fases futuras — no usar en el desarrollo actual.

## Estructura del repositorio
- `acquisition/` — Script principal de adquisición
- `tools/` — Toolboxes del laboratorio (ACQ, US, SSP, Plotters, Loaders...)
- `database/` — Gestor de base de datos de experimentos PVA
- `hardware/` — Temperatura, velocidad del sonido en agua, Arduino
- `analysis/` — Scripts de análisis y ejemplos de uso
- `data/` — Datos de medida (local only, no sincronizado con GitHub)
- `_archive/` — Código obsoleto (local only)

## Convenciones clave
- Señales: s_W (water path), s_T (through-transmission), s_R (pulse-echo)
- TOF extraído por cross-correlación
- Frecuencia de muestreo adquisición: 100 MHz
- Diseño de medidas: repeated-measures sobre ciclos freeze-thaw

## Tarea actual
Antes de desarrollar código nuevo, auditar la carpeta `tools/` para identificar:
- Funciones duplicadas o solapadas
- Funciones que hacen lo mismo con nombres distintos
- Qué está en uso vs. código muerto

Después: desarrollar `acquisition/density_archimedes.py` para medida de densidad  
por método de Arquímedes con columna de agua y transductor de 10 MHz no enfocado.  
Fórmula: ρ = m / (π·r²·c_w(T)·ΔToF/2)