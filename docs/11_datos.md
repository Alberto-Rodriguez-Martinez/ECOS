# 11. Los datos

> **Estado: borrador.** Escrito a partir del informe de lectura del código del 09/10/2026. Lo marcado como *[pendiente]* depende de decisiones sin tomar o de comprobaciones que aún no se han hecho. Este capítulo se actualiza cada vez que cambie el formato de los datos o el software de análisis.

Este capítulo explica qué guarda ECOS en disco, cómo se leen esos datos desde Python y cómo se construye el catálogo sobre el que trabajan los cuadernos de análisis.

## 11.1. Qué se guarda y dónde

ECOS genera tres tipos de medida. Cada una se guarda en su propia carpeta.

| Tipo | Se genera con | Etiqueta en el nombre | Contenido |
|---|---|---|---|
| Ultrasonidos de punto | Pestaña **Acquisition** | `US` | Velocidad, espesor, temperatura y señales de una medida |
| Densidad | Aplicación de densidad (Arquímedes) | `DENS` | Densidad y datos de la columna de agua |
| Barrido | Pestaña del escáner | `SCAN` | Señales de todos los puntos de una línea o superficie |

> **Las medidas reales se guardan siempre en `database/`.** Es la carpeta que lee el catálogo. Los barridos se guardan ahí automáticamente. `debug/` queda para las medidas de depuración, que no deben entrar nunca en el análisis.

La carpeta raíz de los datos se puede cambiar (por ejemplo, si están en otro ordenador o en una unidad de red). Es un único ajuste, que usan la adquisición, el cargador y los cuadernos, y que la interfaz recuerda.

> Hoy los diálogos de guardado de las medidas de punto y de densidad proponen `data/`, y la carpeta que lee el catálogo está fija en `database/`. Hasta que se cambie, hay que elegir `database/` a mano al guardar. *[pendiente: proponer `database/` por defecto, renombrar la carpeta de depuración de `data/` a `debug/` y hacer la carpeta raíz configurable.]*

## 11.2. Nombres de carpeta

El nombre de cada carpeta identifica la muestra y el momento de la medida:

```
PVA_{XX}_PG_{YY}_{L}_C{NNN}_{TIPO}_{AAAAMMDD_HHMMSS}
```

| Campo | Significado | Ejemplo |
|---|---|---|
| `XX` | Porcentaje de PVA (en décimas si lleva decimales) | `10`, `125` (= 12,5 %), `15` |
| `YY` | Porcentaje de aditivo (PG) | `0`, `5`, `10`, `15` |
| `L` | Letra de la pieza (puede cambiar al añadir piezas nuevas) | `A` a `E`, u otras |
| `NNN` | Ciclo de congelación-descongelación, con tres cifras | `001`, `005` |
| `TIPO` | `US`, `DENS` o `SCAN` | `US` |
| marca | Fecha y hora de la medida | `20261007_093015` |

> El catálogo compara estos campos **como texto**: `5` y `05` se tratan como muestras distintas. Hay que escribirlos siempre igual.

### Qué identifica una pieza

Las letras pueden cambiar o reutilizarse (por ejemplo, para añadir un componente nuevo), y se pueden fabricar piezas distintas con los mismos componentes. Por eso la composición y la letra **no bastan** para identificar una pieza física. Una pieza se identifica por (PVA, PG, letra, **fecha de fabricación**), y el ciclo es un dato aparte de esa pieza.

### Fechas que se registran

| Fecha | Cómo se obtiene | Para qué sirve |
|---|---|---|
| Medida | Está en el nombre de la carpeta | Columna del catálogo |
| Fabricación de la pieza | Se introduce una vez por pieza, en el registro de piezas | Junto con la fecha de medida da la **antigüedad** de la pieza |
| Cada ciclo | Se apunta a mano en el registro de piezas al terminar cada ciclo | Distingue las veces que se ha ciclado del tiempo de reposo |

> Si falta la fecha de un ciclo, el catálogo la deja vacía. No se sustituye por la fecha de la primera medida de ese ciclo.

El registro de piezas es una hoja de cálculo con una fila por pieza: composición, letra, fecha de fabricación, masa en seco, espesor con calibre, densidad de referencia y las fechas de cada ciclo. La adquisición lee de ahí los datos de la pieza al elegirla, así que no hay que escribirlos en cada medida. *[pendiente: crear el registro y que la adquisición lo lea.]*

## 11.3. Entornos de trabajo

ECOS usa dos entornos de Python que no se mezclan.

| Entorno | Para qué | Qué incluye |
|---|---|---|
| 32 bits | Adquisición (SeDaq) | Python 3.9, numpy, scipy, PyQt5, pyqtgraph y pyserial |
| 64 bits | Análisis y cuadernos | Python 3.12, numpy, pandas, scipy, matplotlib, jupyter y openpyxl |

Para el análisis, `statsmodels` y `pingouin` son opcionales: sin ellos los cuadernos usan una alternativa (por ejemplo, Kruskal-Wallis en lugar del ANOVA de dos factores).

> Hoy el fichero `requirements-analysis.txt` está incompleto: le falta `openpyxl`, fija una versión de matplotlib con la que fallan los cuadernos (véase 11.10) y está guardado en UTF-16. *[pendiente: regenerarlo.]*

## 11.4. Contenido de cada medida

### Medida de punto (`US`)

| Fichero | Qué contiene |
|---|---|
| `meta.json` | Muestra, equipo, protocolo, operador y fechas (esquema `raw-32-1.0`) |
| `results.json` | `T1`, `T2` (°C), `Cw1`, `Cw2`, `Cw_mean` (m/s), `Cl` (m/s), `d` (m) |
| `signals/signals.npz` | `Signal_PE`, `Signal_TT`, `Signal_Ref` |

Las tres señales se guardan en decimal de 64 bits, con la ventana Smin–Smax **sin enventanar**, en unidades de fondo de escala (±0,5), con la media de cada captura restada y **sin corregir por ganancia**.

> Las medidas hechas con el script original (`ECOS_acquisition.py`) se guardan en `data_32/` con nombres `<fecha>_EXPID-…` y otras claves (`C1`, `C2`, `Cw`, `Cl`, `L`). **No entran en el catálogo.**

### Densidad (`DENS`)

| Fichero | Qué contiene |
|---|---|
| `density.json` | `T_C` (°C), `cw_ms` (m/s), `r_vessel_cm` y `mass_g` (se guardan como texto), `delta_tof_s` (s), `delta_h_cm`, `V_disp_cm3`, `density_gcm3` (vacío si no se introdujo masa), `reclen`, `avg_n` |
| `sW1.npy`, `sW2.npy` | Promedio de Ch2 en la columna de agua, sin y con muestra |

> La densidad no guarda Smin, Smax ni la resolución del ADC, así que no se puede reconstruir el eje de tiempos de `sW1` y `sW2`. *[pendiente: guardar estos datos.]*

### Barrido (`SCAN`)

Cada barrido tiene un `meta.json` y un `scan.npz`.

| Contenido de `scan.npz` | Forma | Notas |
|---|---|---|
| `signals_ch1`, `signals_ch2` | (líneas, puntos, muestras) | Sumas enteras de las capturas, en `int16` (o `int32` si no caben). Solo la ventana Smin–Smax |
| `offsets_ch1`, `offsets_ch2` | (líneas, puntos) | Media del registro completo de cada punto |
| `point_time`, `acq_index`, `coords`, `positions_requested` | (líneas, puntos) | Instante (reloj de pared), orden de adquisición, posición leída y posición pedida |
| `ref_initial_*`, `ref_final_*` | — | Referencias de agua (WP) al principio y al final, si se tomaron |
| `temp_series_*` | — | Serie continua de las dos sondas PT100 (desde el esquema 3.3) |

*[pendiente: describir `point_valid` y las marcas de seguimiento perdido y de ventana estrecha. No constan en el informe de lectura del código y hay que leerlas de `scan_tool.py` y de `scan.npz`.]*

Ch1 es el canal de transmisión (TT; en las referencias, WP) y Ch2 es el de pulso-eco. Las referencias se toman con otros promedios, otras ganancias y otra posición que los puntos; los valores concretos de cada barrido están en su `meta.json`.

El `meta.json` de un barrido agrupa la información en bloques: experimento, muestra, protocolo, equipo, sesión del escáner, barrido (con la velocidad del agua usada, su origen y el modelo), conversión y comentario.

> La casilla de referencias de agua viene marcada por defecto. Sin referencias no se puede aplicar la corrección térmica del tiempo de transmisión.

## 11.5. Nombres de señales y canales

En el programa, los ficheros y los documentos conviven varios nombres para lo mismo.

| Señal | Nombres que se usan |
|---|---|
| Pulso-eco | `s_PE`, `PE_Ascan`, `Signal_PE` (en documentos antiguos, `s_R`) |
| Transmisión con muestra | `s_TT`, `TT_Ascan`, `Signal_TT` (en documentos antiguos, `s_T`) |
| Camino de agua | `s_WP`, `WP_Ascan`, `Signal_Ref` (en documentos antiguos, `s_W`) |
| Barridos | `ch1` (transmisión) y `ch2` (pulso-eco) |
| Densidad | `sW1`, `sW2` |

> `sW1` y `sW2` **no son** el camino de agua `s_W` de ultrasonidos: son la columna de agua de la medida de densidad.

*[pendiente: unificar la nomenclatura en el código y en los documentos.]*

## 11.6. Cargar datos desde Python

Se hace en el entorno de 64 bits, desde la carpeta `analysis/`.

| Quiero cargar | Función | Qué devuelve |
|---|---|---|
| Una medida de punto (resultados) | `ecos_loader.load_us(carpeta)` | Un diccionario con la muestra, temperaturas, velocidades y espesor |
| Una densidad (resultados) | `ecos_loader.load_density(carpeta)` | Un diccionario; la masa y el radio salen como número (o `None` si no se pueden leer) |
| Las señales de una medida de punto | `ecos_loader.load_signals(carpeta)` | `Signal_PE`, `Signal_TT`, `Signal_Ref`, `Fs` y `Smin` |
| Las señales de una densidad | `ecos_loader.load_density_signals(carpeta)` | `sW1` y `sW2` |
| Un barrido (solo metadatos) | `ecos_loader.load_scan(carpeta)` | Un diccionario con la muestra y los campos del barrido |
| Un barrido (señales) | `load_scan_raw_32(carpeta)` en `database/BD_Experimentos_PVA.py` | `(meta, datos)`, con las señales convertidas a decimal |

Ejemplo para un barrido:

```python
from pathlib import Path
import sys
sys.path.insert(0, "../database")
from BD_Experimentos_PVA import load_scan_raw_32

meta, datos = load_scan_raw_32(Path("../database/PVA_..._SCAN_..."))
ch2 = datos["signals_ch2"]       # (líneas, puntos, muestras), en unidades de fondo de escala
```

La conversión de cuentas a decimal es `x = suma / (fondo_de_escala · n_promedios) − offset`, y la hace el propio cargador.

> Los ficheros que faltan o están incompletos se tratan de forma distinta según la función: unas lanzan un error y otras avisan y usan valores por defecto (por ejemplo, 100 MHz de frecuencia de muestreo si falta `meta.json`). Si un resultado sale con un valor vacío, conviene comprobar que existen `meta.json` y `results.json`.

## 11.7. El catálogo

El catálogo es una tabla (un `DataFrame` de pandas) con una fila por combinación de muestra y ciclo, que une las medidas de ultrasonidos y de densidad y calcula la impedancia (`Z`) y el módulo longitudinal (`M_GPa`).

> **Hoy el catálogo no guarda fechas y descarta medidas repetidas.** La clave de cruce es (PVA, PG, letra, ciclo), y si hay varias medidas del mismo tipo para esa clave se queda con la más reciente y avisa por pantalla. Con piezas distintas de la misma composición, eso puede mezclarlas o descartar una medida válida.
>
> El catálogo debe tener una fila por medida, con la fecha de medida, la fecha de fabricación, la antigüedad y la fecha del ciclo, sin descartar ninguna en silencio. Si una densidad puede corresponder a varias medidas de ultrasonidos, el cruce debe marcar la ambigüedad en lugar de elegir una. *[pendiente: implementarlo.]*

- **Se reconstruye cada vez** que se ejecuta un cuaderno, con `build_catalog(Path('../database'))`.
- **Para guardarlo en disco**, se ejecuta `python ecos_loader.py` desde `analysis/`. Genera `catalog.csv` (separador `;` y coma decimal) y `catalog.xlsx` (este necesita `openpyxl`). Ningún cuaderno lee esos ficheros, y no se versionan.
- **Barridos:** `build_scan_catalog` da una fila por barrido, solo con metadatos.
- **Comprobar la coherencia** entre el nombre de cada carpeta y su contenido: `check_consistency(base_dir)`.

> Las carpetas con el nombre mal escrito, o con porcentajes o ciclos distintos de los del JSON, aparecen como discrepancias en `check_consistency`.

## 11.8. Los cuadernos de análisis

Se ejecutan con Jupyter, con `analysis/` como directorio de trabajo, y guardan sus figuras en `analysis/figures/`.

| Cuaderno | Qué responde |
|---|---|
| `ECOS_block1` | Estadística por ciclo: medias, dispersión, cajas, superficies 3D, mapas de calor y ANOVA de dos factores |
| `ECOS_block2` | Evolución con los ciclos de velocidad, densidad y espesor; diferencias pareadas y trayectorias por pieza |
| `ECOS_block3` | Control: temperatura, acuerdo entre las dos sondas, velocidad frente a temperatura, sensibilidad al radio del vaso y valores atípicos |
| `ECOS_block4` | Comparación con tejidos, usando rangos de la bibliografía incluidos en el cuaderno |
| `analyze_catalog` | Versión temprana del bloque 1 (se solapa con él) |

> **Los cuadernos no recalculan espesor ni velocidad.** Usan los valores guardados en `results.json` y `density.json`. Si cambia el método de cálculo, los datos ya tomados solo se actualizan reprocesando las señales de `signals.npz`.

### Parámetros que se pueden tocar

| Parámetro | Dónde | Valor por defecto | Efecto |
|---|---|---|---|
| `CYCLE` | Bloque 1 | 5 | Ciclo que se analiza |
| `DENSITY_MODE` | Bloques 2 y 3 | `"calibrated"` | `"measured"` usa la densidad guardada; `"calibrated"` la **recalcula** con un radio de vaso ajustado |
| `R_MODE` | Bloques 2 y 3 | `"auto"` | `"auto"` elige el radio para que el 95 % de las densidades supere 1,0 g/cm³; `"manual"` usa `R_MANUAL_CM` |
| `R_MANUAL_CM` | Bloques 2 y 3 | 8,95 | Radio manual, en cm |
| `T_US_TARGET` | Bloque 3 | 36,0 | Temperatura objetivo, en °C |

> Con `DENSITY_MODE="calibrated"` y `R_MODE="auto"`, la densidad **no es una medida**: es una recalibración del radio del vaso. Hay que indicarlo cuando se presenten esos resultados. *[pendiente: decidir si el radio se calibra con un cuerpo de densidad conocida.]*

## 11.9. Versiones del formato

| Esquema | Qué cambia | Lo leen |
|---|---|---|
| `raw-32-1.0` (punto) | Única versión | `load_raw32` y `ecos_loader.load_us` (no comprueban la versión) |
| `scan-32-2.0` | Señales en enteros | `load_scan_raw_32` |
| `scan-32-3.0` | Superficie, líneas parciales, punto testigo, temperatura por línea | `load_scan_raw_32` |
| `scan-32-3.1` | Saturación desde las cuentas crudas | `load_scan_raw_32` |
| `scan-32-3.2` | Saturación por canal | `load_scan_raw_32` |
| `scan-32-3.3` | Serie continua de temperatura y antigüedad de cada lectura | `load_scan_raw_32` |

`load_scan_raw_32` rechaza las versiones que no conoce con un error explícito. `ecos_loader.load_scan` no comprueba la versión.

## 11.10. Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| La medida no aparece en el catálogo | La carpeta no está en `database/`, o el nombre no sigue el patrón de 11.2. Las medidas del script original (`EXPID`) no entran en el catálogo |
| Dos muestras iguales aparecen separadas | Algún campo se escribió de forma distinta (`5` y `05`) |
| Densidad por encima de 1 en todas las muestras | Con `DENSITY_MODE="calibrated"` y `R_MODE="auto"` el radio se ajusta para que así sea. Véase 11.8 |
| Densidad por debajo de 1 g/cm³ con `"measured"` | Suele indicar un radio de vaso incorrecto |
| `TypeError: Axes.boxplot() got an unexpected keyword argument 'labels'` | Matplotlib 3.11 ya no acepta `labels`. Hay nueve llamadas así en los cuadernos. *[pendiente: sustituir por `tick_labels`.]* Mientras tanto, usar una versión anterior |
| `export_catalog` falla al escribir el `.xlsx` | Falta `openpyxl` |
| Los cuadernos no encuentran los datos | Se ejecutaron desde otra carpeta: hay que abrirlos con `analysis/` como directorio de trabajo |
| `pva_pct` vale 125 | Es 12,5 %. El cuaderno lo divide entre 10 cuando el valor supera 100 |

## 11.11. Pendiente

- **Análisis de barridos.** No existe: los barridos se pueden cargar, pero ningún programa calcula todavía el espesor y la velocidad de cada punto. *[pendiente: método de tres señales con corrección térmica del tiempo de transmisión, y un mapa final.]*
- **Reprocesado de las medidas de punto** desde `signals.npz`, si cambia el método de cálculo.
- **Una función única** para la selección de modo de densidad y la corrección de porcentajes, hoy copiadas en cada cuaderno.
- **Contenido real de las medidas de punto y de densidad.** Este capítulo describe esos dos formatos a partir del código; falta comprobarlos con datos reales.
- **Formato único de señales en enteros** para punto, densidad y barrido: suma de capturas, `n_avg`, bits del ADC, fondo de escala, ganancia, Smin, Smax y offset por señal. Los cargadores distinguirán por la versión del esquema entre los datos nuevos (enteros) y los antiguos (decimales), y devolverán siempre decimales.
- **Registro de piezas** (hoja de cálculo) y su lectura desde la adquisición.
- **Catálogo con fechas**, sin descartar medidas repetidas y con identificación de la pieza por fecha de fabricación.
- **Carpeta raíz de datos configurable**, con `database/` por defecto y `debug/` para depuración.
- **Figuras y referencias cruzadas** a los capítulos 2, 5 y 8.
