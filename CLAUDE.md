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
- `acquisition/` — Adquisición: `ecos_gui.py` (GUI principal), densidad, pulser y la pestaña
  del escáner (`scanner_panel.py`, `scan_sequencer.py`, `focus_tool.py`, `echo_tracking.py`,
  SeDaq sintético `sim_sedaq.py`)
- `tools/` — Toolboxes del laboratorio (ACQ, US, SSP, Plotters, Loaders...)
- `database/` — Gestor de base de datos de experimentos PVA
- `hardware/` — Temperatura, velocidad del sonido en agua, Arduino; `hardware/scanner/`,
  driver del escáner XYZR y su simulador serie
- `analysis/` — Scripts de análisis y ejemplos de uso
- `data/` — Datos de medida (local only, no sincronizado con GitHub)
- `_archive/` — Código obsoleto (local only; no existe en todas las máquinas)

## Escáner
El modelo verificado del firmware del escáner y el estado de las fases están en
`scanner_tab_spec.md`; no se duplican aquí.

## Convenciones clave
- Señales: s_W (water path), s_T (through-transmission), s_R (pulse-echo)
- TOF extraído por cross-correlación
- Frecuencia de muestreo adquisición: 100 MHz
- Diseño de medidas: repeated-measures sobre ciclos freeze-thaw

## Entornos por máquina
Son distintos en cada máquina.

**Despacho** (`D:\proyectoscode\ecos`)
- Adquisición: `~\anaconda3_32`, Python 3.9.7 de 32 bits, con scipy 1.6.2 y pyqtgraph 0.11.0.
  Se activa con `conda activate ~\anaconda3_32` o se usa `conda run -p ~\anaconda3_32 ...`.
  Llamar al `python.exe` directamente falla: `Library\bin` no queda en el PATH y numpy no
  carga sus DLL.
- Análisis: conda base de 64 bits, Python 3.13.5.

**Portátil** (`C:\Users\Alberto Rodriguez\ProyectosCode\ecos`)
- Adquisición: `.venv32`, Python 3.9.13 de 32 bits creado desde python.org, sin Anaconda.
  Reproducible con `requirements-acq32.txt`.
- Análisis: `.venv` de 64 bits.
- Aquí no hay conda para el proyecto.

**Restricción común:** el código de adquisición y de la pestaña del escáner debe funcionar
en Python 3.9 y con pyqtgraph 0.11. Nada de sintaxis posterior a 3.9 ni de API posterior a 0.11.

**numpy < 1.24 en adquisición (en todas las máquinas).** pyqtgraph 0.11 usa `np.float` y
`np.int`, que numpy 1.24 eliminó, y falla **en silencio**: la excepción salta dentro de un
evento de Qt, que se la traga. Medido el 06/10 con numpy 1.24.4: ningún `ImageItem` se pinta
(`functions.makeARGB`; el mapa 2D del barrido quedaba en blanco) y arrastrar con el ratón para
desplazar o ampliar no hace nada en ninguna gráfica (`ViewBox.mouseDragEvent`). `scan_tool`
tiene su propio `RGBAImageItem`, pero el arreglo es no salir de numpy < 1.24.
- Portátil: `numpy==1.23.5`, fijado en `requirements-acq32.txt` (compatible con scipy 1.9.1
  y contourpy 1.3.0).
- Despacho: comprobar con `conda run -p ~\anaconda3_32 python -c "import numpy; print(numpy.__version__)"`
  y anotarla aquí. Lo exigido es < 1.24; el objetivo es la misma versión exacta que el
  portátil (1.23.5), comprobando antes con `conda install --dry-run` que es compatible con su
  scipy 1.6.2.

**pandas en análisis:** `analysis/ecos_loader.py` lo importa; está en `requirements-analysis.txt`.

## Tests
`python -m unittest` desde la raíz no descubre ninguno: `acquisition/` no es un
paquete (no tiene `__init__.py`). Hay que lanzar cada carpeta por separado, desde la raíz:
- `python -m unittest discover -s acquisition`
- `python -m unittest discover -s hardware/scanner`

Siempre con el intérprete de 32 bits de la máquina correspondiente:
- Despacho: `conda run -p ~\anaconda3_32 python -m unittest discover -s acquisition`
- Portátil: `.venv32\Scripts\python.exe -m unittest discover -s acquisition`

`hardware/scanner/test_connection.py` es un script manual para el hardware real: el
discover lo importa pero no ejecuta nada.

## Tarea actual
Antes de desarrollar código nuevo, auditar la carpeta `tools/` para identificar:
- Funciones duplicadas o solapadas
- Funciones que hacen lo mismo con nombres distintos
- Qué está en uso vs. código muerto

Después: desarrollar `acquisition/density_archimedes.py` para medida de densidad  
por método de Arquímedes con columna de agua y transductor de 10 MHz no enfocado.  
Fórmula: ρ = m / (π·r²·c_w(T)·ΔToF/2)