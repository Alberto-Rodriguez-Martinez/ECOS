# Análisis: integración del escáner en `ecos_gui.py` (Fase 2)

Informe de solo lectura, respuesta a `task_scanner_phase2_analysis.md`. No se ha modificado
ningún archivo del repositorio. Referencias como `archivo:línea` apuntan al estado del
código en el momento de este análisis (2026-09-24).

## 0. Resumen ejecutivo

- `ecos_gui.py` **no usa `QTabWidget` en ningún sitio hoy**. Para llegar a la distribución de
  `scanner_tab_spec.md` sección 4 hacen falta dos pestañas nuevas (gráfica grande y columna de
  controles), pero el cambio queda contenido en `_build_left_panel` y `_build_right_panel`; el
  resto de la lógica (curvas, blocks de control) no necesita tocarse.
- El acceso al SeDaq **no tiene ningún mecanismo de exclusión formal** (ni lock, ni bandera).
  El único patrón existente — parar el `QTimer` antes de una adquisición bloqueante y
  arrancarlo después — es exactamente el mismo truco que necesita el secuenciador del escáner,
  y es reutilizable tal cual.
- **Hallazgo importante no anticipado por la spec**: `ECOS_US_ToolBox.py` y `GenCode_ToolBox.py`
  hacen `from scipy import signal` en la cabecera del módulo (import a nivel de módulo, no
  dentro de una función). Esto significa que **ni siquiera se puede importar `Envelope` o
  `LongVelocity_Thickness`** en un intérprete sin scipy — no es solo que algunas llamadas fallen.
  Ver sección 5 y "Dudas".
- Leer la temperatura por Arduino tal como está implementado (`Arduino(port=..., ...)`,
  `hardware/temperature_Alberto_temporal.py:16-17`) abre el puerto serie y **espera 2 segundos
  fijos** en cada instancia. Invocarlo una vez por punto de un barrido de, por ejemplo, 100
  puntos añadiría más de 3 minutos solo en esperas de reinicio de Arduino. Ver sección 3.
- No existe ninguna función para leer la ganancia actual del SeDaq (no hay `GetGain`). El
  "restaurar ganancia" de las referencias en agua (spec 5.6) tendrá que apoyarse en el estado
  software ya espejado en `AcqState.Gain_Ch1/Gain_Ch2`, confiando en que sea siempre correcto.
- El guardado (`BD_Experimentos_PVA.py`) usa una carpeta con 3 archivos
  (`meta.json` + `results.json` + `signals/signals.npz`) pensada para exactamente 3 señales 1D
  de igual longitud. No sirve para un cubo de barrido sin modificarla; hace falta una función
  nueva, aunque puede seguir el mismo esquema de metadatos.

---

## 1. Estructura de `ecos_gui.py`

### Clase principal y construcción de la ventana
- Una única clase, `EcosGUI(QMainWindow)` (`acquisition/ecos_gui.py:202`). `AcqState` (línea 171)
  es una clase-contenedor de estado mutable compartido (señales capturadas, temperaturas,
  ganancias espejadas), sin comportamiento propio.
- `__init__` (línea 204): crea el SeDaq (línea 218-248), construye la UI (`central`,
  `main_layout`, `splitter`, líneas 251-261), monta el menú (línea 263), restaura sesión desde
  `ecos_gui_session.json` (línea 268-274) y arranca el `QTimer` de refresco en vivo (línea
  276-279).
- La ventana es un `QSplitter(Qt.Horizontal)` con dos widgets: `_build_left_panel()` (gráficas,
  línea 355) y `_build_right_panel()` (controles, línea 453), tamaños iniciales `[980, 420]`
  (línea 260).

### `QTabWidget`: no se usa en ningún sitio
Búsqueda completa del archivo: cero apariciones de `QTabWidget`. La spec (sección 4) pide dos
pestañas — una para la gráfica grande ("A-scan" / "Escáner") y otra para la columna derecha
("Adquisición" / "Escáner") — que hoy simplemente no existen como concepto en el código.

**Dónde encajaría con el menor cambio posible:**
- `_build_left_panel` (línea 355-448) hoy apila verticalmente `self._plot_zoom` (zoom, stretch
  3, líneas 390-422) y `self._plot_ov` (overview, stretch 1, líneas 425-447). El overview **ya
  es** la "gráfica pequeña, siempre visible" que pide la spec — no necesita cambiar. Solo hay
  que envolver `self._plot_zoom` como una página ("A-scan") de un `QTabWidget` nuevo, y añadir
  como segunda página ("Escáner") lo que sea que la fase de foco/planitud/barrido necesite
  mostrar. El resto del método (curvas, región, cursor) no cambia.
- `_build_right_panel` (línea 453-470) es un `QScrollArea` con un `QVBoxLayout` que apila los 7
  bloques de control (`_build_block_pulser` ... `_build_block_save`). Aquí el cambio es
  envolver ese `QScrollArea` completo como página "Adquisición" de un `QTabWidget`, y añadir
  `ScannerPanel` (o su contenido) como página "Escáner".
- Ninguno de los métodos `_build_block_*` necesita cambiar. El cambio queda confinado a estos
  dos métodos constructores y a las llamadas en `_build_ui`/`__init__` que los invocan.

### Gráficas: viabilidad de alternar el contenido de la grande
- `self._plot_zoom` es un `pg.PlotWidget` con curvas (`_curve_zoom_ch1/ch2`,
  `_curve_insp_*`), una línea de cursor y conexiones de señales (`sigMouseMoved`,
  `sigXRangeChanged`) fijadas en `_build_left_panel`. Ninguna de esas conexiones ni la lógica
  de `_update_plots` (línea 782), `_on_region_changed` (832) o `_on_mouse_moved` (875) hace
  referencia a si el widget está "visible" o no — pyqtgraph sigue aceptando `setData()` en un
  widget aunque esté en una pestaña oculta de un `QTabWidget`. **Es viable envolverlo sin
  reescribir su lógica.**
- Efecto secundario a tener en cuenta: `_update_plots` sigue llamando a
  `self._sedaq.GetAScan()` cada 34 ms **aunque la pestaña "Escáner" esté activa** (no hay ningún
  chequeo de pestaña visible). Esto es exactamente el punto de conflicto de la sección 2: el
  refresco en vivo no se detiene por sí solo al cambiar de pestaña, hay que pararlo
  explícitamente.
- "Al lanzar una herramienta, la gráfica grande pasa automáticamente a la pestaña Escáner"
  (spec sección 4) es una línea de código trivial una vez exista el `QTabWidget`
  (`self._left_tabs.setCurrentIndex(...)`); no hay dificultad estructural aquí.

---

## 2. Acceso al SeDaq — lo más importante

### Objeto SeDaq: creación y alcance
- `self._sedaq` se crea una sola vez en `EcosGUI.__init__` (`ecos_gui.py:221`, clase
  `SeDaqDLL` de `tools/SeDaq.py:26`) o, si falla o no hay hardware, `_DemoSeDaq()` (línea 123,
  también en `ecos_gui.py`). Es un atributo de instancia de `EcosGUI`, compartido por **todo**
  el resto de métodos de la clase (no hay wrapper, no hay lock, no hay cola).
- `SeDaqDLL` (`tools/SeDaq.py:26-168`) es un wrapper `ctypes` directo sobre `SeDaqDLL.dll` /
  `USB2.dll`. No tiene ningún mecanismo de sincronización propio (nada de `threading.Lock`,
  nada de comprobación de reentrancia). Si dos hilos llamaran a sus métodos a la vez, la
  seguridad dependería enteramente de la DLL nativa, que no se puede inspeccionar desde aquí.

### Función de adquisición
- `GetAScan()` (`tools/SeDaq.py:77-80`): sin parámetros. Llama a `SeDaqDLL_SetSoftTrig(1)` y
  luego `SeDaqDLL_GetAScan(...)` para los canales 1 y 2. No devuelve nada; escribe el resultado
  en los buffers `self.DataADC1` / `self.DataADC2` (arrays `ctypes` preasignados a 32×1024
  muestras, línea 63-67). El llamador debe leer esos atributos después.
  - Ventana de muestras: fijada antes con `SetRecLen(RecLen)` (línea 72-75), que llama a
    `SeDaqDLL_SetRecLen` dos veces (una por canal). No es un parámetro de `GetAScan`; es estado
    global del objeto.
  - Canal: `GetAScan` siempre adquiere **ambos** canales. Existen `GetAScan1`/`GetAScan2`
    (línea 82-99) para uno solo, pero `ecos_gui.py` no los usa nunca.
  - Promedios: no existen a este nivel. El promediado lo hace `EcosGUI._acquire_ch_avg`
    (`ecos_gui.py:1111-1126`) con un bucle Python que llama a `GetAScan()` repetidamente.
- Conversión a flotante: `EcosGUI._raw_to_float` (línea 822-827), estático, resta el punto medio
  del cuantizador (1024 cuentas fijas en el código, línea 786/1114 — no se lee de `BITS_OPTIONS`,
  que están declaradas en línea 105-109 pero **no until se usan en ningún otro sitio del
  archivo**; posible cabo suelto).

### Refresco en vivo
- `QTimer` (`ecos_gui.py:277-279`), intervalo `REALTIME_INTERVAL = 34` ms (línea 102, ~30 fps),
  conectado a `self._update_plots` (línea 782-820). **Corre en el hilo de la GUI**, no hay
  ningún `QThread` ni hilo Python implicado en el refresco en vivo — es una llamada de callback
  directa del bucle de eventos de Qt.
- `_update_plots` llama a `self._sedaq.GetAScan()` sin promediar (un solo disparo por tick) y
  actualiza las curvas del zoom y del overview.

### Mecanismo de exclusión ya existente
**Sí existe uno, aunque no está documentado como tal**: antes de cualquier adquisición
bloqueante con promediado, el código para el timer y lo vuelve a arrancar en un `finally`:
- `_on_acquire_pett` (línea 1131-1145): `self._timer.stop()` → adquiere → `self._timer.start(...)`
  en `finally`.
- `_on_acquire_wp` (línea 1147-1160): idéntico patrón.
- `_on_preview_window` (línea 1188-1226): también para el timer antes de mostrar la ventana
  modal de matplotlib (bloqueante) y lo reinicia después.

Es decir: la exclusión actual es "parar el generador de la contienda" (el `QTimer`), no un
lock sobre el recurso. Funciona porque **todo ocurre en el mismo hilo** (GUI): mientras el
código de `_on_acquire_pett` se ejecuta de forma síncrona, Qt no puede disparar el `timeout`
del timer (el bucle de eventos está bloqueado esperando a que termine el callback). No hay
ninguna trampa aquí; es correcto y es exactamente el patrón que el secuenciador del escáner
necesita imitar.

### ¿Es bloqueante? ¿Cuánto tarda?
- `GetAScan()` en sí: es una llamada `ctypes` síncrona a una DLL nativa. **No se puede deducir
  su duración exacta leyendo el código Python** — depende de la velocidad de transferencia USB
  y de `RecLen`. Señalado como duda explícita más abajo.
- `_acquire_ch_avg` (línea 1111-1126): bucle `while n < avg_n: GetAScan(); ...` con
  `AVG_N = 25` por defecto (línea 101). Si una señal capturada es exactamente todo ceros, la
  iteración **no cuenta** esa muestra y sigue intentando — con hardware real desconectado o en
  fallo, este bucle puede no terminar nunca (no hay timeout). Es un riesgo preexistente, no
  introducido por el escáner, pero se agravaría si el secuenciador reutiliza esta función tal
  cual dentro de un barrido largo sin vigilancia.
- Con el timer parado durante `_acquire_ch_avg`, el hilo de la GUI queda bloqueado (sin repintar,
  sin procesar clics) durante toda la adquisición promediada. Esto ya ocurre hoy con cada pulsación
  de "Acquire s_PE + s_TT"; el secuenciador multiplicaría esa pausa por cada punto del barrido.

---

## 3. Temperatura (PT100)

- Lectura vía `hardware/temperature_Alberto_temporal.py`, clase `Arduino`. `ecos_gui.py`
  la usa solo dentro de `_read_temperature` (línea 1028-1056): crea una instancia nueva de
  `Arduino(port=port, baudrate=115200, N_avg=3)` **en cada llamada** (línea 1040), lee
  `getTemperatures()` (línea 1041) y cierra el puerto inmediatamente (línea 1042,
  `arduino.close()`).
- Puerto: campo de texto `self._txt_arduino_port`, valor por defecto `DEFAULT_COM = "COM3"`
  (línea 103, 581). Se lee en el momento de la llamada (línea 1038), no está fijado en el
  código como constante inamovible — coincide con lo que `scanner_panel.py` espera al leer
  `ecos_gui_session.json`'s `arduino_port` (ese campo se escribe en `_collect_session`, línea
  1437, confirmando que el enlace entre ambos paneles ya es real, no solo una suposición del
  panel del escáner).
- Frecuencia: **solo bajo demanda**, no hay temporizador de temperatura. Se invoca desde
  `_on_acquire_pett` y `_on_acquire_wp` (líneas 1134, 1150) antes de cada adquisición, nunca en
  el refresco en vivo.
- **Coste real de cada lectura**: `Arduino.__init__` (`temperature_Alberto_temporal.py:16-17`)
  abre el puerto serie y hace `time.sleep(2)` fijo para esperar el reinicio del Arduino al abrir
  el puerto, **cada vez que se instancia**. `getTemperatures` en sí (línea 21-42) es rápido una
  vez abierto (lee `N_avg` líneas ya en curso).
- **Respuesta a la pregunta de la tarea — sí, se puede invocar puntualmente** desde cualquier
  otro punto del código: no depende de la GUI, es una clase de Python normal con
  `getTemperatures()` reentrante mientras el puerto siga abierto. Pero el patrón actual
  (instanciar y cerrar en cada lectura) **no es apto para "una lectura por punto de barrido"
  tal cual**: repetir ese patrón N veces multiplicaría por N los 2 segundos de espera de
  reinicio. Para un barrido habría que abrir un único `Arduino(...)` al principio de la
  secuencia y llamar a `getTemperatures()` repetidamente sobre esa misma instancia,
  cerrándola al final — un cambio de uso sencillo, pero que no existe ya escrito en ningún
  sitio del repo (ni siquiera `hardware/SpeedsoundWater.py:get_Cw_from_arduino`, que también
  crea un `Arduino` nuevo en cada llamada, línea 28, con el mismo coste).
- Sin Arduino disponible: `_read_temperature` cae a `_ask_manual_temperature` (línea
  1058-1082), un diálogo modal bloqueante que pide temperatura a mano. Un barrido automático no
  puede depender de un diálogo modal por punto; la spec ya lo prevé (5.6: "si faltan los PT100,
  se avisa: la temperatura se guardará como no disponible"), pero el código actual no tiene un
  modo "no preguntar, marcar NaN y seguir" — hay que añadirlo, no reutilizarlo.

---

## 4. Pulser y ganancias

- `SetGain1`/`SetGain2` son llamadas `ctypes` independientes (`tools/SeDaq.py:140-146`), cada
  una una sola línea (`SeDaqDLL_SetGain(c_double(gain), canal)`). El wrapper Python no contiene
  ninguna lógica sobre el fallo; el comentario "`FIRMWARE BUG: Ch1 must always be set before
  Ch2`" aparece en `ecos_gui.py`, no en `SeDaq.py` — es decir, el propio wrapper no protege de
  nada, es disciplina impuesta por quien llama.
- El manejo del fallo está en dos sitios de `ecos_gui.py`, ambos con el mismo patrón manual
  (llamar `SetGain1` y luego siempre `SetGain2`, nunca al revés):
  - Inicialización: línea 232-234.
  - `_on_gain_changed` (línea 937-947): se dispara con `editingFinished` de **ambos** campos de
    ganancia (línea 484-485) — es decir, aunque el usuario solo edite `Gain_Ch2`, el callback
    reenvía `SetGain1` igualmente antes que `SetGain2`. Es un "siempre mandar los dos, en
    orden", no una detección de cuál cambió.
- **No existe ninguna función para leer la ganancia actual del hardware.** Búsqueda completa en
  `tools/SeDaq.py`: no hay `GetGain`, `ReadGain` ni equivalente. Lo único disponible es el
  estado espejado en `AcqState.Gain_Ch1` / `AcqState.Gain_Ch2` (`ecos_gui.py:187-188`,
  actualizado únicamente en `_on_gain_changed`, línea 944-945) o el texto de los propios
  `QLineEdit` (`self._txt_gain_ch1/2`). Guardar/restaurar la ganancia para las referencias en
  agua (spec 5.6) tendrá que apoyarse en ese estado software, **no** en una lectura real del
  equipo — y solo será fiable si cualquier código nuevo que cambie la ganancia (p. ej. al fijar
  la ganancia de referencia) pasa siempre por el mismo camino que actualiza `AcqState` y respeta
  el orden Ch1→Ch2.

---

## 5. Estimadores de señal

### Funciones existentes y de dónde vienen
- `Envelope(MySignal)` — `tools/ECOS_US_ToolBox.py:377-382`. `np.abs(signal.hilbert(MySignal))`.
  La usa `ecos_gui.py._make_window` (línea 1174) para centrar la ventana de Tukey en el pico de
  la envolvente.
- `MakeWindow(SortofWin, WinLen, param1, param2, Span, Delay)` —
  `tools/ECOS_US_ToolBox.py:330-365`. Envoltorio genérico sobre `scipy.signal.get_window` que
  admite muchos tipos de ventana (boxcar, tukey, gaussian, chebwin, ...). `ecos_gui.py` **solo
  la llama con `'Tukey'`** (línea 1177).
- `LongVelocity_Thickness(PE_Ascan, TT_Ascan, WP_Ascan, Ref_PE, Fs, Cw, UseHilbEnv)` —
  `tools/ECOS_US_ToolBox.py:522-558`. Es el estimador de velocidad longitudinal y espesor;
  `ecos_gui.py._compute_results` (línea 1268-1276) la llama con `UseHilbEnv=True`. Internamente
  usa `CalcToFAscanCosine_XCRFFT` (línea 452-474, correlación cruzada vía FFT + interpolación
  coseno, todo numpy) para el ToF, y `ShiftSubsampleByfft` (línea 159-163, numpy puro) para
  realinear señales.
- Dependencias: `ECOS_US_ToolBox.py` importa `numpy`, `scipy.signal` y `matplotlib.pyplot` a
  nivel de módulo (líneas 10-12). `GenCode_ToolBox.py` (usado para generar la excitación, no
  para estimadores) también importa `scipy.signal` a nivel de módulo (línea 9), para
  `GC_MakeChirp` (línea 46-61, `signal.chirp`); `GC_MakePulse`, que es el modo realmente usado
  por el proyecto (pulsos rectangulares, ver `CLAUDE.md`), no llama a scipy internamente.

### Qué usa scipy exactamente, y con qué dificultad portarlo
| Función | Usa scipy | Difficultad de portar a numpy |
|---|---|---|
| `Envelope` | `scipy.signal.hilbert` | **Baja.** Transformada de Hilbert vía FFT es el propio método que ya cita la spec (sección 3): FFT, poner a cero las frecuencias negativas (duplicando las positivas), IFFT. Es un algoritmo estándar de ~10 líneas. |
| `CosineInterpMax(..., UseHilbEnv=True)` (usada dentro de `CalcToFAscanCosine_XCRFFT`, y por tanto dentro de `LongVelocity_Thickness`) | `scipy.signal.hilbert` (línea 181) | **Baja**, mismo fix que `Envelope` — es la misma llamada, no un algoritmo distinto. Nótese que `LongVelocity_Thickness` llama a esta ruta con `UseHilbEnv=True` **siempre** para la parte de PE (líneas 543, 547, hardcodeado, no parametrizable desde fuera) y también para TT/WP si `ecos_gui.py` pide `UseHilbEnv=True` (que es lo que hace). Es decir: **`LongVelocity_Thickness`, tal como la usa `ecos_gui.py`, siempre necesita Hilbert.** |
| `MakeWindow('Tukey', ...)` | `scipy.signal.get_window` | **Baja para el caso realmente usado.** Una ventana de Tukey tiene fórmula cerrada sencilla (meseta plana con bordes en coseno) y no depende de scipy para implementarse. Portar **todos** los tipos de ventana que `MakeWindow` admite (chebwin, dpss, slepian, ...) sería trabajo considerable, pero `ecos_gui.py` nunca pide otro tipo que `'Tukey'`. |
| `GC_MakeChirp` | `scipy.signal.chirp` | No relevante para la ruta usada hoy (excitación tipo "Pulse"), pero el import a nivel de módulo de `GenCode_ToolBox.py` bloquea igualmente la carga si scipy no está, aunque nunca se llame a `GC_MakeChirp`. |

### El problema de fondo: el import, no solo la llamada
`ECOS_US_ToolBox.py` y `GenCode_ToolBox.py` hacen `from scipy import signal` **en la cabecera
del módulo**, no dentro de las funciones que lo necesitan. En Python esto se ejecuta en cuanto
se importa el módulo, sin condición. Consecuencia práctica: en un intérprete sin scipy, ni
siquiera se puede hacer `from ECOS_US_ToolBox import Envelope` — el `import` completo del
módulo falla con `ModuleNotFoundError`, aunque la función que se quiera usar no toque scipy
para nada (como pasaría, por ejemplo, si `scanner_panel.py` quisiera reutilizar solo
`Envelope`, o si la fase de foco del escáner quisiera reutilizar solo `MakeWindow('Tukey', ...)`).

Portar de verdad estas dos funciones (`Envelope`, y la parte de `MakeWindow` que cubre
`'Tukey'`) a numpy puro, en un módulo que no importe scipy en absoluto, resuelve el problema de
raíz. Un simple `import scipy` dentro de la función (import perezoso) evitaría el fallo en
carga pero seguiría fallando en cuanto se llamase esa función concreta — no es una solución
real dado que la spec exige que el escáner funcione sin scipy instalado, no solo que cargue.

---

## 6. Guardado

### Cómo se construyen hoy nombre de archivo y metadatos
- Nombre de experimento: `EcosGUI._update_exp_name` (`ecos_gui.py:1305-1315`), disparado por
  `textChanged` de varios campos del descriptor de muestra (línea 716-718). Construye
  literalmente `f"PVA_{pva}_PG_{add}_{letra}_C{cyc}_US_{ts}"` — **no es una función reutilizable
  parametrizada por "tipo"**, es un f-string fijo con `"PVA"` y `"US"` incrustados a mano. No
  hay ninguna utilidad de nombrado genérica en el repo que ya soporte añadir `"SCAN"` como tipo
  (spec 5.6); habría que generalizar este método o escribir un constructor de nombre nuevo para
  barridos.
- Metadatos y guardado: `database/BD_Experimentos_PVA.py:save_experiment_raw_32` (línea 23-70),
  llamada desde `EcosGUI._on_compute_save` (línea 1320-1409). Crea una **carpeta** por
  experimento (`base_dir/exp_name` o `base_dir/{timestamp}_{EXPID}` si no hay nombre, línea
  45-48) con tres archivos:
  - `meta.json` — `experiment` (id, timestamps, `"operator": "Sebas"` **hardcodeado**, línea
    52, no viene de ningún campo de la UI), `specimen`, `protocol`, `equipment` (dos sub-dicts,
    `device_1_ultrasound` con un `params` interno y `device_2_aux`).
  - `results.json` — dict plano de escalares (T1, T2, Cw, Cl, d, ...).
  - `signals/signals.npz` — exactamente tres arrays 1D de igual longitud (`Signal_PE`,
    `Signal_TT`, `Signal_Ref`), con validación explícita de que todas midan `Slen` (línea
    41-43).
  - `schema_version: "raw-32-1.0"` (línea 51) — hay precedente de versionar el esquema, se
    podría seguir la misma convención para barridos (p. ej. `"scan-32-1.0"`).
- Carpeta destino: `_on_compute_save` **siempre** pregunta con un diálogo
  `QFileDialog.getExistingDirectory` (línea 1382-1387) — no hay una ruta automática a
  `../database` hoy; el usuario elige la carpeta cada vez. La spec 5.6 propone guardar barridos
  automáticamente en `../database`; eso sería un comportamiento nuevo, distinto del actual (no
  necesariamente incompatible, pero sí una decisión de diseño a tomar explícitamente).

### ¿Sirve para el formato de barrido propuesto (spec 5.6)?
No tal cual. `save_experiment_raw_32` está diseñada para exactamente tres señales 1D de igual
longitud (comprobado con una validación explícita, línea 41-43); un barrido necesita un cubo
N_z × N_lat × N_muestras, coordenadas reales por punto, temperatura por punto y,
opcionalmente, referencias en agua — no encaja en esa firma sin cambiarla.

La propuesta de la spec (un único `.npz` con el cubo + coordenadas + temperatura + referencias,
más metadatos en JSON) es coherente con las convenciones ya existentes en el propio archivo
(JSON para metadatos + `.npz` comprimido para las señales, sin pandas, ver el comentario del
propio módulo "`Requisitos: numpy (evita pandas/pyarrow)`", línea 8) — es una variación natural
del mismo patrón, no algo ajeno. Mi valoración es que el formato propuesto encaja bien con el
estilo del resto de ECOS; lo que hace falta es **una función nueva** (p. ej.
`save_scan_raw_32`), no forzar la reutilización de `save_experiment_raw_32`. Los bloques
`specimen`/`protocol`/`equipment` de `meta.json` se pueden reutilizar prácticamente igual,
añadiendo un bloque `scanner_session` con el diccionario que ya produce
`ScannerPanel._write_session_file` (eje del haz, lado PE, límites, jog, velocidades — ya es un
dict serializable a JSON).

---

## Riesgos y puntos de conflicto

1. **Acceso concurrente al SeDaq (el más importante).** Hoy solo hay un consumidor del SeDaq —
   la GUI, siempre en su propio hilo — y la exclusión se resuelve parando el `QTimer`. En cuanto
   el secuenciador del escáner necesite adquirir en cada punto de un barrido, hay que decidir en
   qué hilo corre ese secuenciador:
   - Si corre en el hilo de la GUI (como hoy las adquisiciones puntuales), un barrido largo
     bloquea toda la ventana — no se puede pintar el mapa en vivo, ni procesar clics de
     Pausa/Parar, salvo que se intercalen llamadas explícitas a
     `QApplication.processEvents()` (frágil, y no se usa hoy en ningún sitio del archivo).
   - Si corre en un hilo aparte (p. ej. extendiendo `ScannerWorker` o con un segundo `QThread`),
     hay que asegurar que **nunca** coincide con `_update_plots` disparándose desde el timer del
     hilo de la GUI, y que `ScannerWorker` (que ya vive en su propio hilo, según
     `scanner_tab_spec.md` sección 3) no acaba llamando al SeDaq desde un tercer hilo distinto
     del que posee el puerto serie del escáner. No hay ningún lock hoy que lo impida.
2. **Choque de nombres `Scanner`.** Existe `tools/Scanner.py` (una clase `Scanner` antigua y
   completamente distinta, API `Scanner(COM, baudrate)`, sin relación con
   `hardware/scanner/Scanner.py`) y `ecos_gui.py` inserta `tools/` en `sys.path` (línea 58,
   `sys.path.insert(0, _TOOLS_DIR)`), mientras que `scanner_panel.py` inserta
   `hardware/scanner/` también al principio de `sys.path` para poder hacer `from Scanner import
   Scanner`. Al embeber `scanner_panel.py` dentro de `ecos_gui.py`, el orden en que se hacen
   esos `sys.path.insert(0, ...)` decide cuál de los dos `Scanner.py` gana — un error de
   importación silencioso y difícil de diagnosticar si se invierte el orden alguna vez. Esto es
   además el tipo de "función duplicada con nombre distinto" que menciona `CLAUDE.md` como
   tarea de auditoría pendiente de `tools/`.
3. **Import de scipy a nivel de módulo** (sección 5): si el widget del escáner importa
   `ECOS_US_ToolBox` para reutilizar `Envelope`/`LongVelocity_Thickness` tal cual, hereda la
   dependencia de scipy de todo el módulo, no solo de esas dos funciones. En 32 bits sin scipy,
   el `import` falla antes de llegar a usarse nada.
4. **Bucle sin salida en `_acquire_ch_avg`** (`ecos_gui.py:1117-1125`): si `GetAScan()` devuelve
   ceros de forma persistente (hardware desconectado, fallo), el bucle de promediado no
   termina nunca. Si el secuenciador del escáner reutiliza esta función o una variante suya
   para cada punto, un fallo de hardware a mitad de un barrido largo colgaría la sesión sin
   ningún aviso.
5. **Sin lectura de ganancia real** (sección 4): el mecanismo de "guardar ganancia de barrido,
   aplicar ganancia de referencia, restaurar" tiene que confiar en el estado software
   (`AcqState.Gain_Ch1/Gain_Ch2`); cualquier ruta de código nueva que cambie la ganancia sin
   pasar por el mismo punto (y sin respetar el orden Ch1→Ch2) rompe esa suposición de forma
   silenciosa.
6. **Coste de lectura de temperatura por punto** (sección 3): si el secuenciador reutiliza el
   patrón actual de `_read_temperature` (crear/cerrar `Arduino` en cada lectura), un barrido de
   N puntos añade N × ~2 s solo en esperas de reinicio del Arduino. Hace falta una instancia de
   `Arduino` persistente durante todo el barrido — que no existe ya implementada en ningún lado
   del repo.
7. **`RecLen` es estado global del SeDaq**, no un parámetro por llamada (`SetRecLen` fija el
   valor para todas las adquisiciones posteriores, `tools/SeDaq.py:72-75`). Si el secuenciador
   del barrido quisiera un `RecLen` distinto (por ejemplo, más corto para ir más rápido) tendría
   que cambiarlo y devolverlo a su valor original al terminar, o el refresco en vivo y las
   siguientes adquisiciones manuales quedarían con una ventana de muestras equivocada.
8. **Congelación de la GUI ya existe hoy**, sin escáner de por medio: cada pulsación de
   "Acquire s_PE + s_TT" o "Acquire s_W" ya bloquea la ventana durante el promediado (con
   `AVG_N=25` por defecto) más la espera de 2 s del Arduino. La integración no introduce este
   problema, pero sí lo multiplica si el patrón se repite sin cambios en cada punto de un
   barrido de decenas o cientos de puntos.

---

## Opciones de integración

### Opción A — Pausar el refresco en vivo durante toda la secuencia (extensión directa del patrón actual)
Igual que hoy hacen `_on_acquire_pett`/`_on_acquire_wp`/`_on_preview_window`: al arrancar una
secuencia (foco, planitud o barrido), `self._timer.stop()`; el secuenciador adquiere con
`self._sedaq.GetAScan()` / `_acquire_ch_avg` normalmente; al terminar (o al pausar/parar),
`self._timer.start(...)`.
- **Ventajas**: cero código nuevo de sincronización; es literalmente el mismo patrón ya
  probado en producción. Si el secuenciador corre en el hilo de la GUI, la exclusión es
  automática (un único hilo, nunca hay solape).
- **Inconvenientes**: si el secuenciador corre en el hilo de la GUI (la forma más simple de
  aplicar este patrón), la ventana se congela durante todo el barrido salvo que se intercalen
  `processEvents()`. Si en cambio el secuenciador corre en un hilo aparte, parar/arrancar un
  `QTimer` que vive en el hilo de la GUI desde otro hilo no es seguro en Qt sin pasar por
  señales/slots — añade la necesidad de comunicar "empieza secuencia" / "termina secuencia"
  mediante señales igualmente.

### Opción B — El refresco en vivo se sirve desde las propias adquisiciones de la secuencia
El secuenciador, mientras corre, es la única fuente de A-scans: cada vez que adquiere un punto,
emite también la señal que hoy dispara `_update_plots` (o llama directamente a las mismas
funciones de actualización de curvas) para que el usuario siga viendo algo en vivo, sin que el
`QTimer` dispare su propio `GetAScan()` en paralelo. El `QTimer` se desactiva mientras dura la
secuencia (igual que en A) pero la sensación de "en vivo" no se pierde porque cada movimiento
del barrido sí repinta.
- **Ventajas**: no hay huecos de refresco perceptibles durante secuencias largas; el usuario ve
  progreso real punto a punto en vez de una gráfica congelada.
- **Inconvenientes**: acopla el secuenciador a la lógica de refresco de plots (tiene que saber
  actualizar las mismas curvas / unidades que `_update_plots`), lo que es más código y más
  puntos de contacto entre `scanner_panel.py` (o el secuenciador) y `ecos_gui.py`. Si el
  secuenciador vive en otro hilo, esa actualización de UI debe hacerse vía señal Qt, no
  directamente (las llamadas a widgets Qt desde un hilo que no es el de la GUI no son seguras).

### Opción C — Un mediador de acceso único al SeDaq (lock explícito + cola de peticiones)
Introducir un objeto pequeño (p. ej. `SeDaqAccess`) que envuelva `self._sedaq` con un
`threading.Lock`, de forma que tanto `_update_plots` (timer, hilo GUI) como el secuenciador
(en su propio hilo, si lo tiene) pidan el acceso a través de él en vez de llamar a `GetAScan()`
directamente. El timer, si no consigue el lock (`acquire(blocking=False)`), simplemente se
salta ese tick en vez de bloquear el hilo de la GUI.
- **Ventajas**: es la solución más robusta frente a futuros consumidores del SeDaq (por
  ejemplo, si algún día `ECOS_acquisition.py` u otra herramienta comparten proceso); no depende
  de acordarse de parar/arrancar un timer en cada sitio nuevo que se añada.
- **Inconvenientes**: es la opción con más código nuevo y más alejada de cómo está escrito
  `ecos_gui.py` hoy (que no usa ningún primitivo de concurrencia); mayor superficie para
  introducir un bug de sincronización nuevo (p. ej. un lock que se queda tomado si una
  excepción interrumpe la adquisición sin pasar por el `finally`).

---

## Recomendación

**Opción A como base, con la variante de la Opción B solo para el mapa/curva en vivo del
barrido**, y sin necesidad de la Opción C mientras el único consumidor adicional del SeDaq siga
siendo el propio proceso de `ecos_gui.py` (no hay indicios en el código de que vaya a haber un
segundo proceso o una segunda ventana accediendo al mismo SeDaq).

Razones:
- El patrón parar/arrancar el `QTimer` ya existe, ya está probado con hardware real (fase 1 de
  ECOS lleva usándolo desde antes de esta tarea) y es exactamente lo que pide
  `scanner_tab_spec.md` sección 3 ("el refresco en vivo se pausa... para que nunca haya dos
  accesos simultáneos"). No hace falta reinventar un lock para un problema que ya se resuelve
  con un único hilo.
- El secuenciador genérico (spec sección 3) puede vivir en el propio `ScannerWorker` (que ya es
  un `QThread` dedicado a mover el escáner) **o** en el hilo de la GUI, según cuánto tiempo real
  tome cada punto. Esto es algo que **no se puede decidir solo leyendo el código actual** — ver
  "Dudas" — y condiciona si hace falta la variante de la Opción B (actualización vía señal) o
  basta con llamadas directas.
- Reutilizar `_acquire_ch_avg` (o una versión ligeramente adaptada) para el promediado por
  punto evita reescribir la lógica de conversión/promediado, pero **antes de reutilizarla** hay
  que arreglar el bucle sin salida en caso de señal nula (riesgo 4) — de lo contrario un barrido
  largo puede colgarse por un fallo de hardware transitorio en cualquier punto intermedio, sin
  ningún mensaje.

**Qué partes de `ecos_gui.py` habría que tocar, y cuánto:**
- `_build_left_panel` y `_build_right_panel` (líneas 355, 453): cambio estructural moderado —
  envolver los widgets existentes en dos `QTabWidget` nuevos. No toca la lógica de los blocks
  ni de las curvas.
- `__init__` (línea 202-279): añadir la construcción de `ScannerWorker`/`ScannerPanel` y su
  cableado de señales (siguiendo el mismo patrón que ya usa `scanner_panel.py` en solitario).
- `_update_plots` (línea 782): mínimo cambio, o ninguno, si la exclusión se resuelve
  parando/arrancando el timer desde fuera (igual que ya hacen las funciones de adquisición
  puntual).
- Un lugar nuevo para el secuenciador genérico: no existe hoy en `ecos_gui.py` ni en
  `scanner_panel.py`; es código nuevo, no una modificación de algo existente.
- `_acquire_ch_avg` (línea 1111): pequeño cambio necesario (cortar el bucle infinito con un
  máximo de intentos) antes de reutilizarla desde el secuenciador.
- Nueva función de guardado en `database/BD_Experimentos_PVA.py` (o un módulo hermano): código
  nuevo, no modificación de `save_experiment_raw_32`.
- `Envelope` y la parte de `MakeWindow` que cubre `'Tukey'`: hay que portarlas a un módulo
  numpy-puro (nuevo o dentro de `ECOS_US_ToolBox.py` protegido con un import perezoso solo para
  los tipos de ventana que sí siguen necesitando scipy) antes de que el código de la pestaña
  del escáner pueda importarlas con seguridad en 32 bits.

---

## Dudas explícitas (no determinables leyendo el código)

- **Duración real de `GetAScan()`** (con y sin promediado, para el `RecLen` que se vaya a usar
  en el escáner): es una llamada a una DLL nativa; no hay temporización en el código Python
  que la envuelve. Habría que medirla empíricamente en el hardware real antes de fijar el
  tiempo de asentamiento y el número de promedios del secuenciador.
- **Si scipy está realmente ausente en el intérprete de 32 bits que se usa en producción hoy**:
  `CLAUDE.md` y `scanner_tab_spec.md` sección 3 afirman que "scipy no se instala en Python 3.12
  de 32 bits", pero `ecos_gui.py` **ya** depende de scipy en tiempo de import a través de
  `ECOS_US_ToolBox.py`/`GenCode_ToolBox.py` (sección 5). No puedo determinar desde el código si
  esto significa que (a) la función de ventana/resultados de `ecos_gui.py` está de hecho rota
  o sin usar en el entorno de producción real, (b) existe alguna rueda de scipy para esa versión
  concreta de Python de 32 bits que sí funciona pese a la limitación general, o (c) `ecos_gui.py`
  se ejecuta hoy en un Python distinto (64 bits) al que se usará para el escáner. Esto cambia
  bastante el riesgo real de la sección 5 y no se puede resolver sin preguntar o probar en la
  máquina de laboratorio.
- **En qué hilo debe vivir el secuenciador genérico** (spec sección 3): la spec deja abierta la
  cuestión de si el secuenciador reutiliza el hilo de `ScannerWorker`, usa uno propio, o corre
  en el hilo de la GUI con `processEvents()`. No hay precedente de ningún hilo de trabajo para
  adquisición en `ecos_gui.py` hoy (todo el SeDaq se toca desde el hilo de la GUI); decidirlo
  condiciona directamente cuál de las opciones de integración (A o B) aplica y si hace falta
  comunicación por señales Qt para actualizar la UI seguramente entre hilos.
- **Tiempo de asentamiento tras un movimiento** (spec 3: "esperar el tiempo de asentamiento")
  no tiene ningún valor de referencia en el código actual ni en `scanner_tab_spec.md`; no hay
  manera de deducirlo del código, hace falta caracterizarlo en el hardware real (vibración
  residual del soporte tras parar el motor).
- **Si `BITS_OPTIONS`** (`ecos_gui.py:105-109`, `{"8 bit": 256, "10 bit": 1024, "12 bit": 4096}`)
  es código muerto o si en algún flujo no cubierto por este análisis se usa para seleccionar el
  cuantizador en vez del `1024` fijo que aparece hardcodeado en `_update_plots` (línea 786) y
  `_acquire_ch_avg` (línea 1114): no se encuentra ninguna referencia a `BITS_OPTIONS` fuera de
  su propia declaración. Si el escáner necesita saber la resolución real del ADC (por ejemplo,
  para dimensionar el ruido esperado en la envolvente de foco), esto habría que aclararlo antes.
- **Compatibilidad de puertos serie simultáneos** (Arduino + escáner + posible reasignación de
  COM): `scanner_tab_spec.md` sección 1 ya avisa de que "el Arduino PT100 también usa un puerto
  serie: pueden intercambiarse los números según el equipo". No he encontrado en el código
  ningún mecanismo que impida abrir el mismo puerto COM dos veces desde dos partes distintas de
  una `ecos_gui.py` integrada (Arduino de temperatura vs. Arduino... no aplica aquí, pero sí
  escáner vs. Arduino si por error apuntan al mismo COM); es una posibilidad real que no se
  puede descartar leyendo el código, solo probando con el hardware conectado.
