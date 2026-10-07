# Especificación: pestaña Escáner en ECOS

Estado: aprobada. Fase 1 implementada y probada en hardware (21–24/09). Fase 3 (foco) cerrada tras las pruebas en hardware (30/09). Fases 4 (planitud) y 5 (barrido en línea, referencias en agua y guardado) implementadas y probadas con el SeDaq sintético, pendientes de prueba en hardware. Fase 6 (barrido en superficie, espesor por punto, punto testigo) implementada y probada con el SeDaq sintético y en la GUI con el escáner simulado; el espesor, comprobado además sobre los barridos reales del 05/10; pendiente de prueba en hardware. Formato de barrido `scan-32-3.2` (06/10: saturación por canal desde las cuentas crudas, sección 5.7; se siguen leyendo 2.0, 3.0 y 3.1). Última revisión: 2026-10-05.

## 1. Contexto

Escáner XYZR (controlador SE SC-03-00) para posicionar muestras de PVA dentro de la vasija de ultrasonidos. Driver: `hardware/scanner/Scanner.py` (Arnau Busqué, corregido 2026-09).

### Montaje
- Dos transductores fijos en el fondo de la vasija, horizontales y enfrentados en Y (o en X, según el montaje).
- Cadena mecánica: Y → X (sobre Y) → Z (sobre X) → R (motor en la punta de Z, giro alrededor del eje vertical) → tilt manual → soporte de muestra.
- Transductor de pulso-eco (PE): lo habitual es que esté en el extremo cercano al origen del eje del haz (p. ej. cerca de Y = 0), apuntando hacia el sentido positivo; el otro transductor, en el extremo opuesto, apunta hacia el negativo. Configurable, porque el montaje puede cambiar.

### Comportamiento verificado en hardware
- Puerto serie a elegir (COM3 en el portátil de pruebas del 21/09), 19200 baud. Respuestas de 10 bytes: `OK` + eje + 6 dígitos + `\r`. El Arduino PT100 también usa un puerto serie: pueden intercambiarse los números según el equipo.
- Resolución: X e Y 0,01 mm/paso, Z 0,005 mm/paso, R 1,8°/paso.
- Los movimientos **bloquean hasta terminar**: el `OK` llega al final. Con speed=100, X ≈ 6,7 mm/s.
- El firmware **rechaza** destinos < 0 o > límite (`SL`) con `b'ER' + eje + 6 caracteres + b'\r'`. No hay finales de carrera físicos.
- **Órdenes de movimiento** (verificado el 23/09): `SM` absoluto, limitado. `SD` (`diffMove*`) relativo **con signo** y limitado en ambos extremos. `SN` (`unlimitedDiffMove*`) relativo con signo y **sin límites**. `SW` (dirección) invierte solo los **absolutos**, no afecta a los relativos, y **no se usa nunca** en el panel: es un estado oculto que se pierde al cortar la tensión.
- Posiciones negativas: el signo ocupa el lugar de un dígito, la respuesta sigue teniendo 10 bytes (`b'OKX-00010\r'` = −0,1 mm).
- **Z positivo = hacia abajo** (dirección `'-'` que fija el constructor).
- **Sentido del eje del haz**: el contador creciente puede llevar la muestra **hacia** el transductor PE (es el caso del montaje del 23/09). No se corrige invirtiendo el eje ni moviendo el origen: se declara con **PE side = máximo** y el software aplica el signo correcto al tiempo de vuelo.
- `Ctrl+C` / `SSF` detiene el movimiento en seco; el contador queda en la posición real.
- Cortar la tensión del controlador: la **posición se conserva**, los **límites vuelven a 10000 pasos** (100/100/50 mm, 18000°). Reabrir el puerto serie no afecta.
- El constructor de `Scanner` tarda ~4 s (≈20 órdenes). Solo una vez por sesión.
- **Eje R** (verificado el 23/09): `uStepR = 1.8` es correcto (200 pasos = una vuelta) y el contador es **circular** (al completar la vuelta vuelve a 0). `SPR` **no tiene efecto** sobre R. Con el soporte de muestras montado, un giro continuo **pierde pasos**; paso a paso (órdenes de 1,8° sueltas) gira bien. Por eso todo movimiento de R se trocea en pasos con una pausa configurable. **R no se usa para corregir la planitud**: 1,8° por paso es insuficiente. Queda para orientar la pieza de forma gruesa (fase 4).

## 2. Conceptos

- **Eje del haz**: Y o X, a elegir en la configuración de sesión.
- **Eje lateral**: el otro eje horizontal.
- **Z**: eje vertical.
- **Lado PE**: extremo del eje del haz donde está el transductor PE (origen o máximo). Determina el signo: con el PE en el origen, mover la muestra hacia + la aleja del PE y el tiempo de vuelo del eco frontal crece; con el PE en el máximo, ocurre lo contrario. Se declara según cómo se mueva físicamente el eje, sin invertir nada.
- Toda la GUI habla de haz, lateral y Z. La traducción a X/Y ocurre en una sola función.
- Coordenadas de sesión: rango [0, límite] por eje. El cero se fija en una esquina del volumen de trabajo; Z = 0 es la altura segura, arriba.

## 3. Arquitectura

- **Driver**: `hardware/scanner/Scanner.py`, sin cambios de API.
- **Worker**: `ScannerWorker` (QThread), único dueño del puerto serie. Recibe órdenes por cola y emite señales: `moved(coords)`, `error(str)`, `busy(bool)`, `progress(i, n)`. Ninguna llamada al puerto desde el hilo de la GUI.
- **Secuenciador genérico**: uno solo para foco, planitud y barridos.
  - Entrada: lista de posiciones, tiempo de espera tras cada movimiento, número de promedios y una función de medida por punto.
  - Por cada punto: mover → esperar el `OK` → esperar el tiempo de asentamiento → adquirir N veces y promediar → calcular la medida → emitir el resultado.
  - Admite pausa, continuar y parada.
- **El secuenciador es dirigido por eventos, no un bucle** (decidido el 25/09, tras el análisis de `ecos_gui.py`). Vive en el hilo de la GUI y avanza así:
  1. Pide el movimiento al `ScannerWorker`, que está en su hilo, y devuelve el control enseguida.
  2. Al recibir `moved`, programa un `QTimer.singleShot` con el tiempo de asentamiento.
  3. Al vencer, adquiere **en el hilo de la GUI**, calcula la medida, actualiza la gráfica y pide el punto siguiente.
  - Motivo: el SeDaq se sigue tocando siempre desde el mismo hilo que hoy, así que no hace falta ningún lock ni suponer nada sobre la seguridad de la DLL. La ventana no se congela, porque lo largo (el movimiento) ocurre en el worker. Pausa y parada funcionan entre puntos, sin `processEvents()`.
- **Acceso al SeDaq**: el secuenciador adquiere con la misma función de `ecos_gui.py`. Al empezar una secuencia se para el `QTimer` de refresco en vivo y se reanuda al terminar, que es el patrón que ya usan `_on_acquire_pett`, `_on_acquire_wp` y `_on_preview_window`. Durante la secuencia, cada punto repinta la gráfica, así que no se pierde la sensación de tiempo real.
- **Ubicación del código**: la GUI va en `acquisition/scanner_panel.py`, y en `hardware/` solo el driver. El panel es un QWidget que se puede ejecutar solo para pruebas (`python scanner_panel.py`) o insertar como pestaña en `ecos_gui.py`.
- **Estimadores**: reutilizar los de ECOS para el tiempo de vuelo y la envolvente (Hilbert), sin duplicar el procesado.
- **Entornos** (corregido el 25/09): `ecos_gui.py` importa scipy al cargar y funciona en la máquina de adquisición, luego allí hay scipy. **No hay que portar nada a numpy.** El `.venv32` del portátil de desarrollo no tiene scipy, así que la GUI integrada se desarrolla y se prueba en el `.venv` de 64 bits (con `_DemoSeDaq` y el simulador del escáner); el `.venv32` queda para `scanner_panel.py --sim`, que solo necesita pyserial, PyQt5 y numpy. La prueba en 32 bits se hace en la máquina con el hardware.

## 4. Distribución en pantalla

```
┌─────────────────────────────────┬──────────────────────────┐
│ [A-scan] [Escáner]  ← pestañas  │ [Adquisición] [Escáner]  │
│ Gráfica grande: A-scan, o bien  │ Controles (sección 5)    │
│ curva de foco / ToF de          │                          │
│ planitud / mapa del barrido     │                          │
├─────────────────────────────────┤                          │
│ Gráfica pequeña: A-scan en vivo │                          │
│ (siempre visible)               │                          │
└─────────────────────────────────┴──────────────────────────┘
```

Al lanzar una herramienta, la gráfica grande pasa automáticamente a la pestaña Escáner.

### Pestaña Escáner de la columna derecha (reorganizada el 2026-10-05)
Tres subpestañas bajo una cabecera fija. Primero eran dos, «Movimiento y calibración» y «Barridos», pero la primera tenía demasiados campos a la vez:

```
┌──────────────────────────────────────────────┐
│ Cabecera fija (siempre visible, encima de    │
│ las tres subpestañas):                       │
│   posición haz / lateral / Z / R             │
│   [ STOP ]  estado (Libre, Moviendo,         │
│             Secuencia i/n)                   │
├──────────────────────────────────────────────┤
│ [Movimiento] [Calibración] [Barridos]        │
│                                              │
│ Movimiento (la inicial):                     │
│   Conexión (puerto, conectar, resultado)     │
│   Sesión (eje del haz, lado PE, límites,     │
│     pasos, velocidades, ceros)               │
│   Movimiento manual                          │
│   [simulador: modelo del SeDaq sintético y   │
│    secuencia de prueba]                      │
│                                              │
│ Calibración:                                 │
│   Foco (5.4), con todos sus parámetros       │
│   Planitud (5.5), con todos sus parámetros   │
│   Test de estabilidad (5.5 bis)              │
│                                              │
│ Barridos (5.6):                              │
│   Eje de la línea, rango, paso               │
│   [ ] Superficie → segundo eje (el otro de   │
│       lateral/Z), su rango y paso, recorrido │
│       en zigzag o en un solo sentido         │
│   Asentamiento, asentamiento del cambio de   │
│   línea, promedios                           │
│   Mapa: magnitud, escala, ToF corregido,     │
│   amplitud al lado                           │
│   Espesor (c nominal, correlación mínima)    │
│   Punto testigo (posición, cada N líneas,    │
│   umbral de salto)                           │
│   Referencias en agua (ganancias, promedios) │
│   Operador, comentario, límites de deriva    │
│   Tiempo estimado; Inicio / Pausa / Parar;   │
│   pasos de referencia; guardar               │
└──────────────────────────────────────────────┘
```

- En la interfaz (en inglés, como el resto de ECOS) las subpestañas se llaman *Motion*, *Calibration* y *Scans*.
- **«Movimiento» es la inicial**: es con lo que se empieza una sesión.
- **La cabecera fija queda por encima de las tres** y no pertenece a ninguna. El foco y la planitud mueven el escáner y vuelven al centro al terminar, así que la posición tiene que verse desde «Calibración» sin cambiar de pestaña, y el STOP tiene que estar alcanzable desde cualquiera de las tres.
- Al lanzar el foco o la planitud, la gráfica grande pasa a la vista del escáner, como antes. El test de estabilidad tiene su propia pestaña en la gráfica grande, «Stability», con cuatro paneles frente al tiempo.
- **Barridos: una sola sección para línea y superficie.** Una línea es el caso de una sola línea, igual que en el formato de datos (N_línea = 1). La casilla «Superficie» activa los campos del segundo eje (inicio, fin y paso; el modo relativo o absoluto es el del primero) y el recorrido: **zigzag**, que alterna el sentido del primer eje, o **un solo sentido**, en el que todas las líneas se recorren igual para que la holgura no desplace las líneas alternas.
- Fase 6: con «Superficie» marcada, Inicio adquiere la superficie (ya no se rechaza). El recorrido por defecto es el zigzag. El mapa de una superficie se dibuja en su propia pestaña de la gráfica grande, «Scan map»; el de una línea sigue en «Scanner».
- `ScannerPanel.add_tool_widget(widget, tab='motion' | 'calibration' | 'scans')` coloca cada herramienta en su subpestaña. Las subpestañas se muestran siempre en ese orden, sea cual sea el orden en que se añadan. «Calibración» y «Barridos» se crean al añadir su primer widget, así que el panel independiente (sin ECOS) solo muestra «Movimiento».

## 5. Pestaña Escáner (columna derecha)

### 5.1 Estado: cabecera fija y conexión
Posición, STOP y estado van en la **cabecera fija**, encima de las tres subpestañas y fuera de todas (sección 4): se ven y se alcanzan desde «Movimiento», «Calibración» y «Barridos». Puerto, conexión y resultado van en el grupo Conexión de «Movimiento».
- Selección de puerto: desplegable con los puertos serie detectados (`serial.tools.list_ports`, mostrando descripción) y botón de refresco. Se preselecciona el último usado (guardado en la sesión). El puerto asignado al Arduino PT100 en ECOS se marca y no se preselecciona. Nada de puertos fijos en el código.
- Botones Conectar y Desconectar. **Verificación de identidad antes de instanciar `Scanner`**: abrir el puerto con pyserial, enviar `SCX` y exigir una respuesta con el formato `OKX` + 6 dígitos + `\r`. Si no coincide o no hay respuesta, se muestra «El dispositivo en COMx no es el escáner» y se cierra el puerto. Solo si la verificación es correcta se crea `Scanner(port=...)` (su constructor habilita motores y envía velocidades). Resultado siempre visible: «Conectado: escáner en COMx» o el error concreto.
- Posición actual X / Y / Z / R, con la etiqueta de cada eje según su papel (haz, lateral, Z). Se actualiza al terminar cada movimiento.
- **Botón STOP** grande, siempre visible y activo, también durante las secuencias. Envía `SSF` desde fuera del bucle de espera. **Verificar que funciona con el worker bloqueado en `write()`.**
- Estado: «Libre», «Moviendo» o «Secuencia i/n».

### 5.2 Sesión
- Eje del haz (Y o X) y lado PE (origen o máximo).
- Límites por eje: aplicar y leer de vuelta del firmware.
- Paso manual por eje (mm, o ° en R) y velocidad por eje (parámetro del firmware, 1–65536).
- Botones Fijar cero (por eje y todos), y «Esta posición vale N» por eje (cambiar el origen sin usar `SN`). Antes de ejecutar, comprobar que N no supera el límite.
- Guardar y cargar la sesión en `hardware/scanner/scanner_session.json` (en `.gitignore`), con: eje del haz, lado PE, límites, pasos y velocidades.
- **Al conectar**:
  1. Leer los límites. Si los cuatro valen 10000 pasos, avisar de que el controlador se ha reiniciado y ofrecer reenviar los de la sesión guardada.
  2. Mostrar el aviso: «¿Se ha movido algún eje a mano desde la última sesión? Si es así, fija el cero de nuevo.»
  3. Hasta completar estos pasos, bloquear las herramientas y los barridos (el movimiento manual sigue permitido).

### 5.3 Movimiento manual
- Botones +/− por eje, con el paso configurado.
- Ir a una posición absoluta (por eje o todos).
- Controles deshabilitados mientras hay un movimiento en curso.
- R lo controla el usuario, sin restricciones adicionales en la GUI.

### 5.4 Foco
- Parámetros: rango ±N mm en el eje del haz, alrededor de la posición actual; paso grueso; barrido fino opcional (casilla, rango ± y paso); promedios (100 por defecto) y asentamiento (5000 ms por defecto), los dos medidos en el equipo real el 30/09; margen de borde de ventana; banda de seguimiento y umbral del eco frontal; muestra de emisión. La ventana de búsqueda es Smin–Smax de la pestaña de adquisición, que el foco solo lee.
- **La ventana debe seguir al eco.** Al moverse 1 mm en el eje del haz, el eco se desplaza 2/c_w ≈ 1,33 µs. Se resuelve con el seguimiento del eco frontal (punto siguiente) dentro de una Smin–Smax ancha, con aviso si el eco se pega a un borde.
- **Tiempo estimado** antes de empezar, actualizado al cambiar los parámetros: por punto, movimiento (6,7 mm/s, medido a velocidad 100) + asentamiento + promedios × duración de un `GetAScan()`. Esa duración la cronometra `ecos_gui.py` en cada adquisición (media móvil); hasta la primera se supone 20 ms y se indica.
- Medida: pico de la envolvente del **eco de la cara frontal** en PE. Con muestras finas caen en Smin–Smax los ecos de las dos caras y el trasero puede ser el mayor: el máximo global salta de uno a otro a lo largo del barrido. Se sigue el frontal con `acquisition/echo_tracking.py` (29/09): en el primer punto, el primer pico de la envolvente que supera un umbral, no el mayor; en los siguientes, el máximo en una banda estrecha alrededor de t_previo + 2·Δx/c_w (signo según el lado PE). Si aparece un eco claro antes de la banda, se re-engancha a él y se re-miden los puntos previos. El A-scan marca en cada punto el eco usado.
- Algoritmo (cerrado el 30/09 tras las pruebas en hardware):
  1. Barrido grueso en el rango.
  2. Ajuste parabólico de la amplitud en dB sobre los puntos **del barrido grueso** que están a menos de 3 dB del máximo (el tramo contiguo alrededor de él, mínimo 3 puntos; si hay menos dentro de 3 dB se toman el máximo y sus vecinos y se avisa de que el paso grueso es grande para esa zona focal). Mínimos cuadrados ponderados: el ruido de cada punto se estima con su contraste de envolvente (suelo de ruido de Rayleigh) y se infla con el χ² reducido cuando hay grados de libertad.
  3. Se informa del óptimo ± 1σ del vértice, del residuo RMS del ajuste (dB) y de la **zona focal**, el tramo a menos de 1 dB del máximo según la parábola, que también se sombrea en la gráfica.
  4. **Curva demasiado plana**: si el ajuste no es cóncavo o la incertidumbre 1σ del vértice supera medio paso grueso, se avisa de que no se puede determinar el óptimo y no se mueve.
  5. **Tiempo de vuelo en el óptimo**: recta de ToF frente a posición sobre los puntos gruesos con eco claro (pico de envolvente interpolado bajo la muestra, ponderado por contraste), evaluada en el óptimo y referida al instante de emisión. Se da en muestras, µs y mm desde el transductor (c_w·t/2). La muestra de emisión es 0 por defecto, la convención de ECOS (el registro empieza en el disparo), y es configurable si el hardware tiene retardo.
  6. **Comprobación de la pendiente**: la de esa recta se muestra junto a la teórica 2/c_w, con el signo del lado PE. Con signo contrario se avisa de revisar el lado PE; con más de un 10 % de desviación, de revisar c_w y que el eco seguido sea el frontal.
  7. Barrido fino **opcional** (desactivado por defecto), ± un rango configurable alrededor del óptimo. Solo para inspección: **no entra en el ajuste**. Se informa de su máximo y de su desfase medio respecto a la parábola gruesa.
  8. Mover al óptimo.
- **c_w** se lee de los PT100 al lanzar el foco, como en el resto de ECOS (`water_temp2sos` sobre T1 y T2, su media; se actualiza también el estado y la etiqueta de temperatura). Nunca se abre el diálogo manual, porque es modal. Si los PT100 fallan se usa la última lectura, y si no hay ninguna, 1480 m/s. El origen del valor se muestra siempre. Con el SeDaq sintético se usa su propio c_w.
- **Sesgo de +0,2 dB entre barrido fino y grueso** (hardware, 30/09): en la misma posición, el barrido fino mide unos 0,2 dB más que el grueso. Mezclar los dos barridos en un ajuste deforma la parábola, y por eso el óptimo sale solo del grueso. El origen del sesgo no está caracterizado. El desfase medio del fino respecto al ajuste grueso se informa en cada ejecución para seguirlo.
- **Referencia pendiente**: la calibración del foco con un **reflector pequeño** (bola o punta de hilo en el eje) queda pendiente como método de referencia. Sirve para validar el foco hallado sobre la cara plana de la muestra, que integra toda la sección del haz, y la zona focal.
- Si el máximo cae en el borde del rango, avisar («amplía el rango») y no moverse.
- El rango se recorta a los límites de la sesión, avisando de ello.
- **Mensajes de eco perdido y de ventana estrecha, separados**:
  - Eco pegado a un borde de Smin–Smax: la ventana es estrecha, hay que ampliarla.
  - Eco frontal perdido (su posición prevista queda fuera de Smin–Smax): se sugiere revisar el lado PE, porque con el lado equivocado la predicción va en sentido contrario al eco. Si en la ventana sigue habiendo un eco claro lejos de la predicción, el mensaje lo dice y apunta directamente al lado PE.
  - Si el eco se re-engancha dos o más veces en el barrido grueso, también se sugiere revisar el lado PE.
- Gráfica: amplitud frente a posición, con el ajuste, el óptimo y la zona focal marcados. El estado final lista el informe: óptimo ± σ, ajuste, zona focal, ToF y pendiente.
- **No guarda resultados.** Solo un volcado de depuración opcional (casilla, activada por defecto, 30/09): un `.npz` por ejecución en `data/focus_debug/` (local, fuera de git) con, por punto, la posición, el registro PE, el array de la ventana y su envolvente, el pico elegido, su valor lineal y en dB, Smin–Smax, la banda y el motivo de la selección. Formato en `FocusDebugDump` (`focus_tool.py`).

### 5.5 Planitud
Implementada en `acquisition/flatness_tool.py` (fase 4, `task_scanner_phase4.md`).

**Alcance (07/10).** La planitud existe para **ayudar al usuario a orientar la pieza antes de un barrido**. Es una comprobación de **pasa o no pasa**, con una corrección a aplicar. **No es un estudio** de la forma, la curvatura ni las propiedades de la muestra: eso corresponde al procesado, con los datos del barrido, que tiene muchos más puntos y mejor relación señal-ruido. **Cualquier propuesta que añada aquí caracterización de la pieza queda fuera de alcance.**

- Parámetros:
  - rango ±N mm en el eje lateral y ±M mm en Z, alrededor de la posición actual, con el paso de cada eje; por defecto ±10 mm con paso 1 mm, y ±5 mm con paso 0,5 mm;
  - promedios y asentamiento, los de la fase 3 (100 y 5000 ms);
  - tolerancia en grados (0,3° por defecto, ver abajo), banda de seguimiento y volcado de depuración.
- **Tolerancia por defecto: 0,3°** (antes 0,1°, cambiada el 07/10). Tiene que cumplir dos condiciones a la vez, y quien la cambie debe comprobarla contra las dos:
  - **Lo que el ajuste puede aplicar** (cota inferior). Las correcciones son manuales, con el goniómetro GN1/M (Z) y la platina de rotación CR1/M (lateral), cuyas escalas están graduadas en grados: el ajuste más fino que se aplica a mano es de en torno a un cuarto de grado. Con 0,1° el usuario quedaba atrapado en un bucle de corregir y volver a medir sin llegar nunca al verde. Una tolerancia por debajo de ~0,25° no es alcanzable con estos ajustes.
  - **Lo que la medida necesita** (cota superior). La aceptación angular del transductor enfocado es del orden de 1,5°, y la amplitud del eco cae unos 1,4 dB por grado de inclinación (medido en el equipo el 06/10/2026). A 0,3° la pérdida es de unos 0,4 dB, muy por debajo de lo que afecta a la medida.
  - Si cambia el ajuste (otro goniómetro, un micrómetro) o el transductor, hay que revisar la condición correspondiente.
- Tiempo estimado antes de empezar, como en el foco.
- Mide dos líneas de tiempo de vuelo del **eco frontal**, lateral y Z. **El eje del haz no se mueve.** Reutiliza el secuenciador de la fase 2 y el seguimiento de la fase 3 (`FrontEchoTracker`), con un tracker por línea (regla del primer pico en su primer punto) y siempre la misma posición del haz: la predicción es t_previo y la banda absorbe el desplazamiento por la inclinación. La línea Z se hace con el lateral en el centro. Al terminar, el escáner vuelve al centro; con STOP no se mueve y solo informa.
- ToF de cada punto: pico de la envolvente interpolado bajo la muestra, desde la muestra de emisión.
- **Ajuste**: recta ponderada de ToF frente a posición en cada línea. Los pesos son proporcionales al contraste², porque el jitter del pico escala con 1/SNR, y la escala absoluta sale de los residuos (n − 2 grados de libertad). Ángulo θ = atan(c_w · Δt / (2 · Δx)), con c_w de los PT100 por el mismo mecanismo que el foco.
  - **La recta es suficiente; no se ajusta una parábola** (probado y revertido el 07/10, commits c684196 y 64867bc, revertidos en 10ba454 y 0008b47). Con los puntos repartidos simétricamente alrededor del centro, la recta ya da la inclinación en el centro sin sesgo, porque el término cuadrático es ortogonal al lineal. Comprobado sobre un barrido real: la pendiente de la recta y la pendiente en el centro de la parábola dan el mismo número, −19,674 µm/mm. La parábola solo reducía la dispersión, y con la tolerancia en 0,3° la recta ya daba una incertidumbre cuatro veces menor que la tolerancia. La curvatura de la cara es caracterización de la pieza y queda fuera de alcance (ver arriba).
- **Resultado por eje**, en este orden (07/10, por el alcance de arriba), tanto en la etiqueta de cada eje como en el informe:
  1. **el veredicto y la acción**: un indicador, verde (|θ| ≤ tolerancia), rojo (fuera), naranja (σ mayor que la mitad de la tolerancia, no se puede juzgar) o gris (sin resultado), y lo que hay que hacer a mano: nada si cumple; si no, cuántos grados girar, con qué control y en qué sentido (ver Correcciones);
  2. **el ángulo con su incertidumbre 1σ** (propagada desde la pendiente), que hace falta para no perseguir ruido: si |θ| < 2σ, dice «no distinguible de 0» en lugar de dar un número con falsa precisión, y no propone corrección. Los decimales se ajustan a la σ;
  3. los avisos del eje (puntos fuera del ajuste, cara que se acaba…);
  4. **el residuo RMS** como desplazamiento de la cara, en µm, como detalle secundario y solo en el informe: no sirve para orientar la pieza.
- **Mensaje de «indeterminado»** (naranja), una sola línea: la incertidumbre no permite juzgar la tolerancia, y se mejora con más puntos y, en segundo lugar, más promedios. Sin cálculos de recorrido ni diagnósticos sobre la forma de la cara.
- **Convenio de signo** (el mismo del SeDaq sintético): θ > 0 cuando la cara se **aleja** del transductor PE al crecer el contador lateral (o Z; Z crece hacia abajo). No depende del lado PE.
- **Correcciones, siempre manuales**: la herramienta mide e informa y no mueve ningún eje para corregir.
  - Inclinación lateral → platina manual de rotación alrededor del eje vertical: «gira θ° de modo que el extremo X+ (o Y+) de la cara se acerque/aleje del transductor PE».
  - Inclinación en Z → tilt manual: «inclina θ° de modo que el borde inferior de la cara (Z+) se acerque/aleje del transductor PE».
  - En los dos casos se da el Δθ con signo.
  - **R no se usa ni se propone** (1,8° por paso). El secuenciador tampoco puede moverlo.
- **Puntos poco fiables**, marcados en la gráfica y fuera del ajuste:
  - eco pegado a un borde de Smin–Smax → «ventana estrecha, amplíala»;
  - sin eco claro en la banda → «seguimiento perdido». Si hay un eco claro fuera de la banda, el desplazamiento por paso supera la banda y hay que reducir el paso o ampliar la banda;
  - saturación de Ch2 (criterio en la sección 5.7, cambiado el 06/10; Ch1 tiene su propia marca);
  - **atípicos** (07/10): tras el primer ajuste, los puntos cuyo residuo se aparta de la mediana de los residuos más de **4 σ robustas** (σ = 1,4826 × la desviación absoluta mediana, MAD) se marcan `outlier`, se excluyen y se rehace el ajuste una vez. El informe dice cuántos y en qué posiciones; quedan marcados en la gráfica y en el volcado (`flags`, y `outliers` en `meta_json`). **Motivo**: en el equipo, un solo punto en el extremo de la línea (el haz se sale de la pieza o pilla el borde del soporte) arrastraba el ajuste y dejaba el eje en «undetermined» aunque el resto fuera una recta limpia; pasó tres veces seguidas, siempre en el extremo Z−. **No es caracterizar la pieza**: un punto en el que el haz no estaba sobre la muestra no debe decidir si está bien orientada.
    - La escala es la σ robusta y no 4 × MAD a secas porque 4 × MAD equivale a unas 2,7σ: con ruido gaussiano de 1 µm se descartaba el 1,7 % de los puntos buenos (con 4σ robustas, el 0,17 %). La curvatura de una cara no dispara el descarte: los extremos de un residuo parabólico quedan por debajo del umbral (comprobado con la curvatura medida, ±5 y ±10 mm).
    - Solo se aplica con **6 puntos o más** (el doble del mínimo del ajuste): con menos, la MAD de unos pocos residuos no significa nada (con 3 puntos los residuos de una recta son proporcionales a 1, −2, 1 y la MAD es 0).
    - Suelo del umbral: 0,1 muestras (~0,75 µm), para que un ajuste casi perfecto no marque puntos por redondeo.
    - El mínimo de puntos del ajuste (3) se mantiene: si tras el descarte quedan menos, la línea no tiene resultado y se dice que la medida no vale. Como menos de la mitad de los puntos pueden superar el umbral, con 6 o más puntos siempre quedan al menos 3; la comprobación se deja igualmente.
- **La cara puede acabarse**: si el eco desaparece en los extremos de una línea, el ajuste se limita al tramo con eco claro, se dice y se sugiere un rango. Con menos de 3 puntos válidos no hay resultado para ese eje.
- Gráfica: las dos líneas como desplazamiento de la cara (µm, desde el ToF) frente a la posición relativa al centro, con sus rectas y los puntos poco fiables marcados.
- Botones Ejecutar y **Repetir** (mismos parámetros: corriges a mano y vuelves a medir).
- **No guarda nada** en la base de datos. Volcado de depuración opcional: un `.npz` por ejecución en `data/flatness_debug/`, con el formato del foco más las columnas `line`, `line_position`, `line_offset`, `tof_samples` y `tof_us`.

### 5.5 bis Test de estabilidad (pestaña Calibración)
Herramienta de **diagnóstico permanente**, no una fase. Está en `acquisition/stability_tool.py` (`StabilityTool`, `StabilityGroup`).

**Motivo.** El 05/10, seis barridos consecutivos de la misma línea en tres minutos mostraron una **deriva de −2,46 µm/min, lineal, con un residuo de 0,78 µm**, en el sentido de que la cara se acerca al transductor de pulso-eco. Hay que saber si satura y a qué se debe. En un barrido de superficie de dieciséis minutos la deriva acumulada sería de unos **39 µm**, comparable a la estructura real de la cara, y además se confundiría con una inclinación en el eje lento.

**Qué hace.** Se queda en la posición actual **sin mover ningún eje** y toma N medidas separadas por un intervalo de T segundos.
- Reutiliza el secuenciador con la opción `no_move`: no se envía al worker ni un movimiento nulo, así que no se energiza ningún motor entre medidas, que es justo lo que se mide. El intervalo lo marca el tiempo de asentamiento.
- Valores por defecto: **240 medidas cada 5 s (veinte minutos) y 20 promedios**. El tiempo total estimado se ve antes de empezar.
- Pide el escáner conectado, para registrar la posición.
- STOP activo: al parar se guarda lo medido hasta ese momento.

**Por punto:**
- **Ch2 (pulso-eco), eco frontal:** seguido con `FrontEchoTracker`. Su cambio de tiempo de vuelo respecto a la primera medida se mide por **correlación cruzada** (`CalcToFAscanCosine_XCRFFT`) de una puerta de ±banda alrededor del eco seguido, que deja fuera el eco trasero de una muestra fina. Se convierte en desplazamiento de la cara, c_w·Δt/2 (negativo: la cara se acerca al PE), y también se mide la amplitud. La interpolación del pico de la envolvente oscila ±0,3 muestras (±2 µm) con la SNR del simulador; vale para el foco, pero no para derivas de µm. Se guarda igualmente como referencia (`tof_ch2_samples`).
- **Ch1 (transmisión a través de la pieza):** cambio de tiempo de vuelo por correlación cruzada con el primer registro completo, y máximo de la envolvente.
- **Temperatura en cada punto**, con una sola instancia de `Arduino` durante toda la medida. La serie de temperatura es tan importante como la de tiempo de vuelo: la medida existe para saber si la temperatura explica la deriva. Si una lectura tarda más de 0,5 s, se lee cada pocos puntos (`temp_every`), se avisa y queda en los metadatos (`temp_read_s`, `temp_note`).
- **Registros completos de los dos canales.**

**Por qué los dos canales.** Si la pieza se hincha, la cara se acerca y el espesor crece, y Ch1 lo ve. Si lo que se mueve es el portamuestras, la cara se acerca y el espesor no cambia: Ch1 queda plano. Así la medida distingue las dos causas. Está comprobado con el simulador en los dos casos.

**Salida.** Cuatro paneles frente al tiempo (desplazamiento de la cara, ΔToF de Ch1, amplitudes y temperaturas) y las tasas de deriva en vivo (µm/min, ns/min, °C/min, con su residuo RMS). Además, el volcado de depuración, que se escribe siempre (`data/stability_debug/`):
- por punto: `record` (Ch2 completo), `record_ch1`, `t_s`, `epoch`, `T1`, `T2`, `temp_read`, `face_um`, `ch1_dtof_ns`, `tof_ch2_samples`, `amp_ch2_db`, `amp_ch1_db`, y las columnas del foco (ventana, envolvente, pico, banda, motivo);
- en `meta_json`: lo que escriben las otras herramientas (`settle_ms` = intervalo, `avg_n`, `gain_ch1_db`, `gain_ch2_db`, `temperature`), más la **posición**, el **intervalo** (`interval_s`), el **número de medidas** (`n_requested`, `n_measured`), `temp_every` y las tasas de deriva ajustadas.

### 5.6 Barridos
- Tipo: línea (lateral o Z) o superficie (lateral × Z).
- Rango de cada eje: inicio y fin, relativos al centro o absolutos, más el paso.
- Recorrido: zigzag o siempre en el mismo sentido, a elegir. El segundo evita que la holgura mecánica desplace las líneas alternas.
- Espera tras cada movimiento (ms), configurable. Número de promedios por punto.
- Tiempo estimado mostrado antes de empezar.
- Mapa en vivo con la magnitud que elija el usuario:
  - Espesor entre los ecos 1 y 2 (por defecto, fase 6).
  - Tiempo de vuelo.
  - Amplitud máxima en la ventana.
  - Energía en la ventana.
  - Ampliable a otras magnitudes.
- Pausa, continuar y parar. Al parar, se ofrece guardar lo adquirido hasta ese momento.

#### Referencias en agua (opcional)
Casilla «Tomar referencias en agua al inicio y al final». Parámetros en el panel: **ganancia de referencia por canal** (Ch1, Ch2) y número de promedios de la referencia.

- La ganancia de referencia de **Ch2** se rellena con la de Ch2 de la pestaña Acquisition, salvo que el usuario ya la haya cambiado. Una nota junto al campo explica que, con la pieza fuera, Ch2 recibe el eco del transductor opuesto y también puede saturar.
- **Repetir permite cambiar las ganancias de referencia** antes de volver a medir: se usan los valores de los campos en ese momento. La referencia aceptada se guarda con las ganancias con las que se midió.
- **Lo que se aprueba es lo que se guarda**: el A-scan mostrado es la señal promediada de la referencia, idéntica bit a bit a la guardada. Mientras espera OK / Repetir / Cancelar, el refresco en vivo queda retenido, para que no la sustituyan capturas sueltas. Se reanuda al aceptar o cancelar.

Flujo al pulsar Inicio:
1. La posición actual se guarda como **punto de inicio** del barrido.
2. Si faltan los PT100, se avisa: la temperatura se guardará como no disponible.
3. Mensaje: «Saca la pieza del eje con los controles manuales y pulsa Continuar». Durante este paso solo está activo el movimiento manual. El programa registra el **orden de los ejes** que se mueven.
4. Al pulsar Continuar: se aplica la ganancia de referencia (volviendo a fijar Gain2 tras cualquier cambio de Gain1, por el fallo del pulser), se toma un A-scan promediado de Ch1 y Ch2, y se muestra. Botones: **OK**, **Repetir** y **Cancelar**.
5. Al pulsar OK: la posición actual se guarda como **posición de referencia** y se restaura la ganancia del barrido. El programa vuelve al punto de inicio con un movimiento por eje, en orden inverso al registrado en el paso 3 (el último eje movido vuelve primero). Después empieza el barrido.
6. Al terminar el barrido, va a la posición de referencia con un movimiento por eje, en el orden registrado en el paso 3. Aplica la ganancia de referencia, toma la referencia final, restaura la ganancia y vuelve al punto de inicio en orden inverso.
7. Si el barrido se para a mitad, se pregunta si se toma la referencia final.

Cada referencia (inicial y final) se guarda en el archivo del barrido con: señales de Ch1 y Ch2, ganancias, posición, hora y temperatura.

#### Temperatura
- **No se lee en cada punto.** El agua de la vasija cambia despacio y cada lectura cuesta ~2 s, porque `Arduino.__init__` espera el reinicio del puerto. Se lee: al empezar el barrido, al terminarlo, en cada referencia en agua y, en un barrido de superficie, al acabar cada línea.
- Durante una secuencia se abre **una sola instancia de `Arduino`** y se reutiliza, cerrándola al final. El patrón actual de `_read_temperature` (crear y cerrar en cada lectura) no sirve aquí.
- Cada valor se guarda con su marca de tiempo y el índice del punto en que se tomó, para poder interpolar después.
- Si los PT100 no están disponibles, se guarda NaN y se avisa al empezar. **Nunca se abre el diálogo manual de temperatura durante un barrido**: `_read_temperature` cae hoy a `_ask_manual_temperature`, que es modal y bloquearía la secuencia. Hace falta un modo «no preguntar, marcar NaN y seguir».

#### Guardado
**Una carpeta por barrido**, siguiendo la convención del resto de ECOS:

```
PVA_10_PG_5_A_C005_SCAN_20260925_171200/
  meta.json    specimen, protocol, equipment (parámetros del pulser), bloque scanner_session,
               parámetros del barrido, conversión, operator y comentario. schema_version: "scan-32-3.0"
  scan.npz     señales (N_línea × N_punto × N_muestras) por canal, coordenadas reales de cada
               punto, temperaturas con su marca de tiempo e índice, las referencias en agua
               con su ganancia, posición, hora y temperatura, y la serie del punto testigo
```

- Sin `results.json`: en un barrido los resultados se calculan después, en el análisis.

#### Qué rango de muestras se guarda en cada sitio (06/10)
Son dos decisiones distintas, y las dos tienen motivo:
- **Base de datos (`database/<…>_SCAN_<ts>/scan.npz`): solo la ventana, muestras Smin..Smax−1**, de los dos canales; también en cada visita del testigo (`witness_*`) y en las referencias en agua (`ref_*`). Se guarda lo que se mide: todo lo que ECOS calcula sale de Smin–Smax, y la ventana está en `meta.json` (`equipment.device_1_ultrasound.params.Smin/Smax`). Lo único que procede de fuera de la ventana es el **desplazamiento por punto y canal** (`offsets_*`): es la media del registro **completo** que ECOS resta a cada captura, y por eso se guarda aparte (no se puede recalcular con la ventana).
- **Volcados de depuración (`data/*_debug/*.npz`, fuera de git): el registro completo**, porque sirven para diagnosticar y conviene que lo lleven todo. Foco, planitud y barrido: `record` (Ch2, todo el registro, la media de las capturas como flotante) más `window_signal` y `envelope` (Smin..Smax−1, el array exacto sobre el que se midió). Test de estabilidad: `record` (Ch2) y `record_ch1` (Ch1), los dos completos. Los volcados de foco, planitud y barrido no guardan Ch1.
- **Se guarda automáticamente en `../database`**, con el nombre de la convención de ECOS y `SCAN` como tipo, para que `analysis/ecos_loader.py` pueda catalogarlo. Un botón «Guardar en otra carpeta…» permite elegir otra ubicación.
- El bloque `scanner_session` es el diccionario que ya produce `ScannerPanel`, que es serializable a JSON.
- Hace falta **una función nueva** (p. ej. `save_scan_raw_32`): `save_experiment_raw_32` valida que haya exactamente tres señales 1D de igual longitud y no admite un cubo. Se reutiliza su esquema de metadatos, no su firma.
- `operator` está hoy fijo como «Sebas» en `BD_Experimentos_PVA.py`. En la función nueva debe ser un campo.

#### Implementación del barrido en línea (fase 5, `task_scanner_phase5.md`)
En `acquisition/scan_tool.py` (`ScanTool`, `ScanGroup`). Reutiliza el secuenciador de la fase 2 y el seguimiento del eco frontal de la fase 3.

**Parámetros y estimación**
- Eje lateral o Z (nunca el del haz ni R), con inicio, fin y paso, relativos a la posición al pulsar Inicio o absolutos. Los puntos fuera de [0, límite] se recortan, con aviso.
- Asentamiento y promedios propios del barrido, independientes de los del foco (5000 ms / 100, medidos con pasos de 1 mm):
  - **Asentamiento: 100 ms, medido** en el equipo real el 05/10. Se hicieron dos barridos iguales de 21 puntos con paso de 0,5 mm y 20 promedios, uno a 500 ms y otro a 100 ms. Coinciden punto por punto a 0,22 muestras RMS (2,2 ns, 1,5 µm) y los residuos del ajuste correlan a 0,988, así que a 500 ms no se gana nada. **Validado para pasos de 0,5 mm o menores**: no se ha comprobado para desplazamientos grandes.
  - Promedios: 20 por defecto, **pendientes de caracterizar**.
  - Los 100 promedios del foco no cambian: se midieron con pasos de 1 mm, que no es este caso.
- Tiempo estimado siempre visible y actualizado con cada parámetro, en rojo por encima de media hora. Incluye los movimientos (6,7 mm/s), el asentamiento, los promedios (`GetAScan` cronometrado) y las dos referencias, pero no los pasos manuales. Con el simulador, la estimación quedó un 12 % por debajo del tiempo real.

**Por punto**
- Se guardan los dos canales, muestras Smin..Smax−1, como el resto de ECOS.
- La posición guardada es la **real**, la que relee el worker con `getAxis` tras cada movimiento; la pedida va aparte.
- Si el eco frontal se pierde (el haz sale de la pieza), el punto se marca con ToF = NaN y el barrido sigue.

**Mapa en vivo:** registro extensible de magnitudes (`register_magnitude`): amplitud máxima de la envolvente en la ventana, ToF del eco frontal y energía en la ventana. Se calculan todas en cada punto y cambiar la que se muestra solo redibuja.

**Pausa, continuar y parar:** al parar no se mueve nada. Se ofrece guardar lo adquirido, tomar antes la referencia final (si hay referencias) o descartar.

**Referencias en agua (el flujo de arriba, con estas precisiones)**
- El orden registrado es el del **primer movimiento** de cada eje en el paso manual. También se guarda el registro completo de movimientos manuales.
- R nunca se devuelve automáticamente: si se movió, se avisa.
- Tras el barrido, el eje barrido vuelve primero a su inicio (el camino que se acaba de recorrer) y después se va a la referencia en el orden registrado.
- Cancelar la referencia inicial termina la sesión sin mover nada. Cancelar la final la omite y vuelve al inicio.
- Las ganancias se aplican siempre como Gain1 y después Gain2.

**Reserva del secuenciador:** durante toda la sesión, incluidos los pasos manuales entre secuencias, ni el foco ni la planitud pueden arrancar. La pestaña Acquisition queda bloqueada.

**Temperatura:** una sola instancia de `Arduino` para toda la sesión. Se lee al empezar, en cada referencia y al terminar, con `point` = índice del último punto adquirido (−1 antes del primero). c_w sale de esas lecturas con `water_temp2sos`. Sin PT100: NaN, aviso y nunca un diálogo.

**Guardado**
- `BD_Experimentos_PVA.save_scan_raw_32` / `load_scan_raw_32`, esquema **`scan-32-2.0`** (fase 5; desde la fase 6, `scan-32-3.0`, más abajo), carpeta `database/PVA_..._SCAN_<ts>/` con `meta.json` + `scan.npz` (comprimido). Contenido: coordenadas reales, tiempos, temperaturas (`temp_label`, `temp_point`, `temp_time`, `temp_T1`, `temp_T2`) y referencias `ref_<initial|final>_{sum1, sum2, offset1, offset2, avg_n, gains, coords, time, T1, T2}`.
- **Señales en enteros** (desde `scan-32-2.0`, 2026-10-05; `database/scan_counts.py`):
  - Lo que se mide en cada punto es la media de N capturas, cada una con su media del registro restada, como hace ECOS. Esa media no es un entero: el promediado da resolución por debajo del bit menos significativo, y eso es información real. Por eso no se guarda la media redondeada a cuentas, sino la **suma entera** de (cuenta − punto medio) de las N capturas, más un **desplazamiento por punto y canal**. El desplazamiento es la media del registro completo, que no se puede recalcular porque solo se guarda la ventana.
  - El flotante de ECOS es `x = suma / (fondo_escala · N) − desplazamiento`. Lo calcula la misma función (`counts_to_float`) al medir (`ecos_gui._seq_acquire`, que adquiere por sumas) y al leer, así que la lectura lo reconstruye **bit a bit**.
  - **Orden de las operaciones, de la captura al archivo** (verificado en el código el 06/10; ningún paso redondea):
    1. **Cada captura** (`ecos_gui._acquire_counts`): cuentas crudas en int64 **menos el punto medio** (512 a 10 bits). El punto medio es un entero fijo: la resta es exacta. **No se resta el desplazamiento de continua de la captura** y no se redondea nada. Una captura constante (digitalizador muerto) se descarta antes de sumarla.
    2. **Suma** de las N capturas en int64: exacta.
    3. **Desplazamiento de continua**: se calcula **después** de sumar, sobre la suma del registro **completo**: `media(suma) / (fondo_escala · N)`, en float64. **No se aplica a la suma**: se guarda aparte, como un dato más (`offsets_ch1/2`, por punto; `offset1/2` en las referencias y el testigo). Restar la media de cada captura y promediar es matemáticamente lo mismo que restar una vez la media de la suma; solo afecta al flotante, que calcula quien lee.
    4. **Guardado** (`save_scan_raw_32`): la suma, recortada a Smin..Smax−1, se convierte a int16 o int32 **después de comprobar** que |suma| ≤ punto medio · N, que es lo máximo que puede valer una suma de N capturas: la conversión nunca trunca, y una suma fuera de ese rango se rechaza.
    5. **Lectura** (`load_scan_raw_32`): devuelve las sumas tal cual (`signals_ch1/2_sum`) y calcula el flotante `x = suma / (fondo_escala · N) − desplazamiento`; la resta del desplazamiento la hace quien lee.
  - **Comprobado con un test** (`test_ecos_gui_session.TestExactCounts`): por el camino de adquisición real de la GUI, con los desplazamientos de continua del equipo (Ch2 −7,4 cuentas, Ch1 +1,2, modelados en el SeDaq sintético), la suma leída del archivo más punto medio · N es **exactamente** Σ de las cuentas crudas de las N capturas, calculada aparte con enteros de Python. El test falla si se resta la media de cada captura redondeada, o si se redondea la captura sin media antes de sumarla (comprobado introduciendo cada error).
  - Tipo: int16 si |suma| ≤ punto medio · N cabe (N ≤ 63 a 10 bits; los 20 promedios del barrido), int32 si no (las referencias con 100). El número de promedios nunca lo limita el formato.
  - Motivo: es exacto, no convierte nada al escribir y sin comprimir ocupa la mitad que float32. Comprimido, en un barrido simulado de 41 puntos × 3500 muestras × 2 canales: 0,34 MB frente a 0,52 MB en float32 (0,65×), porque deflate también reduce los float32. Sin comprimir: 0,57 MB frente a 1,15 MB.
  - `meta.json["conversion"]`: bits, punto medio, fondo de escala, N, tipo y **ganancia por canal**, más un bloque igual para cada referencia, con sus propios N y ganancias. La ganancia queda registrada pero no entra en la conversión: el flotante de ECOS es la señal a la salida del receptor, sin compensar la ganancia, como en el resto de ECOS.
  - `load_scan_raw_32` devuelve los flotantes con las mismas claves (`signals_ch1/2`, `ref_<x>_ch1/2`) y las sumas aparte (`*_sum`).
  - **Sin compatibilidad hacia atrás**: `scan-32-1.0` (float32) no se lee, porque no llegó a existir ningún barrido real en ese formato.
- **Resolución del ADC: supuesta.** El SeDaq no permite leerla: la DLL entrega búferes `uint16` y no hay función que la informe. Se suponen 10 bits (punto medio 512, fondo de escala 1024), el valor que ECOS usaba fijo. Es un parámetro (`ADC_BITS` en `ecos_gui.py`, `ADC_BITS_DEFAULT` en `scan_counts.py`) y queda escrito en cada barrido. `density_gui` y `pulser_gui` la dejan elegir al usuario, también con 10 bits por defecto.
- El nombre lo construye `experiment_name` (compartido; Compute & Save sigue dando el mismo nombre US).
- `operator` es editable, con «Sebas» por defecto.
- «Guardar en otra carpeta…» escribe una copia.
- `analysis/ecos_loader.py` reconoce `SCAN`: `load_scan`, `scan_database` y `build_scan_catalog`. `build_catalog` sigue siendo US + DENS, porque un barrido no tiene resultados que fusionar hasta analizarlo.

**Deriva entre referencias:** con las dos referencias tomadas, la final se compara con la inicial **en Ch1**, el canal de transmisión (el equivalente de la señal s_W de ECOS). Se calcula la diferencia de amplitud (máximo de la envolvente, en dB) y la de tiempo de vuelo (correlación cruzada, `CalcToFAscanCosine_XCRFFT`, en ns; positiva si la final llega más tarde). Si Ch1 no tiene señal clara en las dos referencias, la deriva se da como no medida. El resultado se muestra en pantalla (verde, rojo o gris si no se pudo medir), se guarda en `meta.json["scan"]["reference_drift"]` y avisa si supera los umbrales configurables, por defecto 0,5 dB y 20 ns; 20 ns es del orden de 0,1 °C de agua en 60 mm de camino. Ch2 (pulso-eco) se sigue guardando en cada referencia, pero no se compara. **La métrica es la deriva del camino de transmisión** (temperatura del agua, ganancia y acoplo de Ch1) y **no cubre una deriva propia del canal de pulso-eco**, por ejemplo de la ganancia de Ch2 o del transductor PE.

**Volcado de depuración** opcional (desactivado por defecto: guarda registros completos, a diferencia de la base de datos; ver «Qué rango de muestras se guarda en cada sitio»), en `data/scan_debug/`.

**Parámetros de medida en los volcados** (foco, planitud y barrido, 05/10): los tres escriben en `meta_json`, con las mismas claves, `settle_ms`, `avg_n`, `gain_ch1_db`, `gain_ch2_db` y `temperature`. Este último es un diccionario con `T1`, `T2`, `time` y `source` de la última lectura real de los PT100, o `null` si no la hay; las temperaturas supuestas o manuales no cuentan. Así se pueden comparar volcados entre sí sin deducir por la hora del archivo con qué se midió cada uno. En el foco y la planitud la temperatura es la leída al lanzar la herramienta; en el barrido, la lectura de inicio.

#### Implementación del barrido en superficie (fase 6, `task_scanner_phase6.md`)
En `acquisition/scan_tool.py`, sobre el mismo `ScanTool`: una línea es el caso de una sola línea. Reutiliza el secuenciador (fase 2), el seguimiento del eco frontal (fase 3) y el barrido en línea (fase 5); no hay bucle nuevo ni detector de ecos nuevo.

**Qué lo motiva (medidas del 05/10, línea de 21 puntos con paso de 0,5 mm):** el ruido sigue 1/√N y es electrónico (0,93–0,99 µm de temblor con 20 promedios; asentar 1000 ms no mejora a 100 ms); el temblor lo manda la SNR del eco (0,41 µm sobre acero a 0 dB, 0,99 µm sobre PVA), así que no será uniforme en el mapa; el PVA **deriva −4,34 µm/min a tirones** (97,5 µm en 21 min, saltos aislados de 5–7 µm; el acero, +0,32 µm/min sin saltos: es la muestra, no el escáner); y el **espesor entre los ecos 1 y 2 es inmune a esa deriva** (residuo de 0,20 µm frente a 2,4 µm de la posición de la cara).

**Secuencia (`scan_schedule`)**
- Todo el barrido es **una sola secuencia** del secuenciador: los puntos de todas las líneas en el orden del recorrido y las visitas al testigo. Pausa, continuar y parar funcionan en cualquier punto.
- **Recorrido**: zigzag por defecto; un solo sentido como opción.
- **Orden de ejes fijo**: dentro de una línea solo se mueve el eje de la línea; en un cambio de línea, en una visita al testigo y al volver de él se mueve **primero el otro eje** y después el de la línea; al volver al inicio, primero el eje de la línea y después el otro. Queda escrito en `meta.json["scan"]["axis_order"]`.
- **Asentamiento por punto**: el secuenciador admite un asentamiento por posición. Tras un **movimiento largo** (primer punto de cada línea, incluido el primero del barrido, y cada visita al testigo) se usa `line_settle_ms`, **1000 ms por defecto, no caracterizado**; entre puntos vecinos, los 100 ms medidos (válidos para pasos ≤ 0,5 mm).
- Se guarda la posición **real** releída en cada punto, como en la fase 5.

**Espesor por punto (`echo_tracking.echo_pair_delay`)**
- Eco 1: el frontal seguido. Eco 2: el **primer lóbulo claro** de la envolvente después del eco 1 (`echo_lobes`, la misma regla que el primer pico), con las dos puertas de ±banda sin solaparse. Retardo = distancia entre picos + desplazamiento por **correlación cruzada** de las dos puertas (`CalcToFAscanCosine_XCRFFT`, que toma el máximo de |xcorr|, así que mide también un eco 2 invertido; la polaridad se guarda).
- **Coeficiente de correlación** de las puertas alineadas en cada punto, como indicador de calidad: por debajo de `min_corr` (0,9) el punto se marca `low_corr` (eco deformado: cara inclinada).
- **Comprobación antes de empezar**: una adquisición en la posición de inicio; si el eco 2 no está dentro de Smin–Smax (o toca el margen de borde), se avisa antes de mover nada, el espesor queda **deshabilitado** para todo el barrido y la magnitud no se ofrece en el mapa. En cada punto, sin eco 2: NaN y marca `no_back`. Nunca se da un número medido contra el borde de la ventana.
- Espesor en mm con una velocidad **nominal** de la muestra (1540 m/s, editable), solo para el mapa en vivo; lo que se mide y se guarda es el retardo (`echo_delay_us`). Es la **magnitud por defecto** del mapa.
- Comprobado sobre los seis barridos reales consecutivos del 05/10 (13:51–13:53): eco 2 encontrado en los 21 puntos, polaridad invertida, correlación 0,89–0,99 y repetibilidad punto a punto de **0,21 µm** (mediana), la misma que se midió.

**Punto testigo**
- Opcional, **activado por defecto**. Posición: el primer punto del barrido (por defecto), la posición al pulsar Inicio o una absoluta (lateral, Z). Se visita **antes de la primera línea, cada N líneas (N = 1 por defecto) y después de la última**.
- Cada visita se mide como un punto normal, con su propio seguimiento (las líneas conservan su ancla), y se guarda con su posición real, tiempo de vuelo, amplitud, espesor, marca de tiempo e índice de línea (las líneas completadas antes de la visita), más sus señales.
- **Desplazamiento de la cara** respecto a la primera visita por **correlación cruzada** de una puerta de ±banda alrededor del eco seguido, como en el test de estabilidad: el pico de la envolvente oscila ±0,3 muestras (±2 µm) en el simulador, que vale para un mapa pero no para saltos de pocos µm. El tiempo de vuelo de cada visita sigue siendo el del pico de la envolvente, como en cualquier punto: el estimador del barrido no cambia.
- **Saltos**: tendencia = mediana de la velocidad de todos los intervalos entre visitas (robusta al propio salto); un intervalo cuyo desplazamiento se aparta de ella más que el umbral deja **en duda las líneas medidas en él**. Una visita sin eco también. Con menos de tres intervalos la tendencia no es robusta.
- **Umbral del salto, de la propia serie** (06/10): el temblor depende de la amplitud del eco y cambia con la muestra (05/10: 0,41 µm con acero, 1,0–1,4 µm con PVA), así que no es fijo. Es **3 × la dispersión de las diferencias entre visitas consecutivas** (sin la tendencia), con **4 µm como suelo** (≈ 3σ de la diferencia de dos visitas con ~1 µm por medida, por debajo de los saltos de 5–7 µm del PVA); con menos de tres intervalos, el suelo. La dispersión es 1,4826·MAD, igual a la desviación típica con ruido gaussiano pero sin inflarse con el propio salto: con cinco intervalos y un salto de 40 µm la desviación típica sale ~16 µm y 3σ lo ocultaría. Se guardan el umbral usado, el suelo y la dispersión (`jump_threshold_um`, `jump_floor_um`, `jitter_sigma_um`).
- **No se corrige nada en el archivo.** La corrección de deriva es del análisis y **nunca se aplica al espesor**. El mapa en vivo puede mostrar el tiempo de vuelo corregido (casilla, interpolando el testigo en el tiempo), indicándolo en el título.
- El tiempo estimado cuenta las visitas y sus movimientos.

**Temperatura:** además del inicio, el final y las referencias, **al acabar cada línea** de una superficie, con su marca de tiempo, el índice del último punto y el **índice de línea** (`temp_line`). Sin PT100, NaN y aviso al empezar, sin diálogos. Cada archivo lleva en `meta.json["scan"]["temperature_note"]` que **el PT100 está en el fondo de la vasija y no en el camino del haz**: 0,07 K en la capa límite alrededor de una pieza recién metida valen 5 µm de tiempo de vuelo (05/10), así que sigue la tendencia pero no da la temperatura del agua que atraviesa el haz. Es una limitación del montaje, no del programa.

**Mapa en vivo 2-D (`SurfaceMap`, pestaña «Scan map»)**
- Lateral en horizontal y Z en vertical, creciendo hacia abajo, como ve la cara el transductor PE. Se dibuja según llegan los puntos (línea a línea), no al final.
- Magnitudes: espesor (por defecto), tiempo de vuelo de la cara, amplitud, energía y **«Thickness quality (r)»**: el coeficiente de correlación entre los ecos 1 y 2 en cada punto, sin unidades, de 0 a 1, para saber en qué zonas del mapa de espesor fiarse (no es otra forma de medir el espesor; se llamaba «correlation» y se confundía). El registro de la fase 5 sigue permitiendo añadir más sin tocar el barrido; cada magnitud puede llevar su tooltip.
- **Mapa de amplitud al lado** (casilla, activada): la amplitud dice dónde fiarse del otro.
- Barra de color con unidades; escala automática o fija.
- pyqtgraph 0.11: `ImageItem` alimentado con una imagen RGBA coloreada aquí, colores como tuplas RGB; la barra de color es otro `ImageItem` (`ColorBarItem` no existe en 0.11). Gris: medido sin valor; transparente: aún sin medir. El rectángulo del `ImageItem` es el del barrido con medio paso a cada lado, para que cada píxel quede centrado en su punto.
- **Corregido el 06/10: el mapa no se dibujaba.** Ejes, barras de color y marcas eran correctos, y el rectángulo también. El fallo estaba en el pintado: pyqtgraph 0.11 pinta todo `ImageItem` con `functions.makeARGB`, que llama a `np.float`, eliminado en numpy 1.24 (el `.venv32` del portátil); la excepción salta dentro de `paint()`, Qt se la traga y el `ImageItem` queda vacío, sin ningún error visible. Con numpy anterior (≈1.20, el entorno del despacho) sí se pintaba. `RGBAImageItem` construye la `QImage` directamente desde la imagen RGBA y no depende de la versión de numpy. Un test pinta el mapa y comprueba los píxeles: color, posición en mm y orientación (Z hacia abajo).
- Si una magnitud no tiene ningún valor válido que dibujar, el mapa lo dice en el propio panel («No point measured yet», o «No valid value to draw» con el motivo: espesor no disponible en este barrido, ningún eco claro…) en vez de quedarse en blanco.

**Tiempo estimado:** sobre la secuencia completa: recorrido de cada movimiento (6,7 mm/s), asentamiento de cada entrada (con el del cambio de línea), promedios de cada punto y visita, una **sobrecarga por movimiento de 0,2 s** (medida el 05/10: 0,43 s por punto con 5 promedios y 0,57 s con 20, de los que unos 0,28 s son movimiento y proceso, 0,075 s de ellos el recorrido, 9,5 ms cada A-scan y el resto el asentamiento), la lectura de temperatura de cada línea (cronometrada; hasta la primera no se cuenta, y se dice) y las referencias. Aviso por encima de media hora. Con el escáner de prueba de los tests coincide con el real a un 3 %; en la GUI con el escáner simulado (que pasa por el sondeo de 0,1 s del driver) queda un 22–28 % por debajo.

**Formato `scan-32-3.0`** (`save_scan_raw_32` / `load_scan_raw_32`)
- El cubo va en **orden espacial**: `[k, j]` es la línea k en la posición j de `positions_requested`, sea cual sea el recorrido (una línea en zigzag se adquiere con j decreciente). `acq_index` y `point_time` dan el orden de adquisición. `N_línea` = líneas con algún punto adquirido.
- **Línea parcial**: al parar a mitad se guarda la línea entera, con los puntos que faltan rellenos (señales 0; offsets, coordenadas y tiempos NaN, así que al leer las señales salen NaN); `point_valid` marca lo adquirido, y `line_partial`, `meta.json["scan"]["line_status"]` y `partial_line` marcan la línea. Vale también para una línea suelta parada.
- Nuevo en `scan.npz`: `point_valid`, `acq_index`, `positions_requested` (N_línea × N_punto), `line_position_requested`, `line_partial`, `line_doubtful`; `live_<magnitud>` (los valores del mapa en vivo, como metadatos), `echo_delay_us` y `echo_polarity`; `temp_line`; y la serie del testigo `witness_*` (señales con la misma conversión, `witness_ch1/2` al leer, offsets, coordenadas reales y pedidas, tiempo, línea, visita, `tof_us`, `amplitude`, `face_um`, `thickness_mm`, `thickness_corr`, `lost`).
- Nuevo en `meta.json["scan"]`: `type` (`line` o `surface`), `axis2`, `path`, rango del segundo eje, `lines_requested`, `n_lines`, `n_lines_acquired`, `line_status`, `partial_line`, `array_order`, `axis_order`, `temperature_note`, `line_settle_ms`, `thickness` (método, puerta, c nominal, correlación mínima, si estaba habilitado y por qué no) y `witness` (modo, posición, periodo, umbral, visitas, tendencia, desviación de cada intervalo, líneas en duda y líneas posteriores a la última visita). `flags` se indexa ahora por `"línea,j"`.
- `load_scan_raw_32` sigue leyendo los `scan-32-2.0` (los barridos en línea del 05/10): una línea con todos los puntos válidos (`point_valid` se añade al leer).
- **Cambio incompatible**: el número de puntos medidos ya no es `shape[1]` (una línea parada va rellena hasta su longitud completa); es `point_valid.sum()` en los arrays, o `n_acquired` en `meta.json`. Revisado el repositorio el 06/10: nadie usaba `shape[1]` así. El `load_scan_raw_32` anterior solo aceptaba `scan-32-2.0` y **rechaza** un 3.0 con un error; solo leería el relleno como medidas un código que abriera `scan.npz` directamente. `analysis/ecos_loader.load_scan` lo advierte y añade al catálogo `scan_completed`, `scan_n_lines`, `scan_n_lines_acquired`, `scan_n_points_per_line`, `scan_line_status`, `scan_partial_line`, `scan_path` y `scan_doubtful_lines`; `scan_shape` es la forma guardada, relleno incluido.

**Modo simulador de la GUI (06/10):** la ventana Smin–Smax por defecto la da el propio SeDaq sintético (`SimSeDaq.default_window`): contiene el eco frontal y el de la cara trasera de la muestra en el foco, y deja fuera el disparo y la primera reverberación. La sesión del simulador va en su propio archivo, `ecos_gui_session_sim.json` (fuera de git), y nunca toca la sesión del equipo real (`ecos_gui_session.json`, con la Smin–Smax y las ganancias del montaje: era la que el modo demo restauraba y sobrescribía). `--session FILE` o la variable `ECOS_GUI_SESSION` eligen otro archivo; los tests de la GUI usan uno temporal y comprueban que los dos reales no cambian.

### 5.7 Saturación (06/10)
**Una sola detección para todo ECOS**, en `database/scan_counts.py`: `top_mask(raw, bits)` marca las muestras de **una captura** en el tope del cuantizador (código 0 o fondo de escala − 1), sobre las **cuentas crudas**, antes de restar la media y de promediar; las adquisiciones la acumulan con OR sobre todas sus capturas. `count_at_top(mask, span)` cuenta las marcadas en el **rango que da quien la llama**. Siempre **por canal**: Ch1 y Ch2 nunca se combinan.

**Indicador en vivo** (gráfica de tiempo real, junto al nombre de cada canal, en rojo y solo cuando ocurre, con el número de muestras al tope). Se calcula en el refresco en vivo y en cada adquisición de una secuencia, y mira **solo Smin–Smax**, igual que las marcas de las herramientas: lo que queda fuera de la ventana ni se mide ni se guarda (el disparo, antes de Smin; el retorno de pulso-eco tras rebotar en el transductor opuesto, hacia la muestra 14000, después de Smax), así que un aviso sobre ello no se podría atender ni correspondería a ningún dato.
- *Retirado el 06/10:* existió un «cegado de la emisión» (campo «Emission blanking» de la pestaña Acquisition, con «Auto», guardado en la sesión y anotado en los metadatos) para que un indicador que miraba el registro entero no contara el disparo. Se quitó al limitar el indicador a Smin–Smax: el disparo queda fuera por estar antes de Smin, y el aviso que quedaba, el retorno de pulso-eco después de Smax, era ruido que no se podía atender. No volver a proponerlo.

**Marcas de las herramientas** (foco, planitud, test de estabilidad y barridos): **solo Smin–Smax**, como el indicador, y **una por canal**, guardadas por separado:
- **`saturated_ch2`** (pulso-eco): invalida la medida del eco, que se hace sobre Ch2. Es la que va en la lista de marcas de cada punto (antes se llamaba `saturated`): sacarla del ajuste en la planitud, no mover en el foco, cruz en el mapa.
- **`saturated_ch1`** (transmisión): **no** invalida una medida de pulso-eco, así que no entra en esa lista; se guarda aparte (`PeakMeasure.saturated_ch1`, `n_top_ch1`) y avisa por su cuenta. Invalida lo que usa Ch1: **las referencias en agua** (se avisa al revisarlas, «not valid», y la deriva entre referencias se da como no medida si alguna tiene Ch1 recortado) y el ΔToF y la amplitud de Ch1 del test de estabilidad (aviso).
- El secuenciador guarda la máscara de la última adquisición (`top_fn` del anfitrión) y cada herramienta pide el recuento de su ventana para cada canal (`ScanSequencer.top_count`); el seguimiento del eco lo recibe (`FrontEchoTracker.measure(..., n_top, n_top_ch1)`) y lo conserva al re-enganchar.
- En los archivos: barridos, `saturated_ch1`, `saturated_ch2`, `n_top_ch1`, `n_top_ch2` (N_línea × N_punto; −1 si no se comprobó), `witness_n_top_ch1/ch2` y `ref_<initial|final>_n_top_ch1/ch2`; volcados, columnas `n_top_ch1` y `n_top_ch2`.

**Cambio de criterio.** Hasta el 05/10 había una sola bandera `saturated`: un **umbral de 0,49 sobre la señal de Ch2 promediada y sin media, en la banda alrededor del eco seguido**. Desde el 06/10 son **dos marcas, una por canal, con el recuento de muestras al tope del cuantizador en cualquier captura individual, en Smin–Smax**. Son cosas distintas:
- el umbral podía no ver una captura recortada entre varias (el promedio queda por debajo), no miraba fuera de la banda del eco y no miraba Ch1;
- el recuento no depende de la desviación de continua del canal (Ch2: −7 a −8 cuentas en el equipo real) y ve, por ejemplo, un eco trasero que recorta donde la cara trasera está en foco (caso real del simulador con una muestra fina: 2,5 × A₀ = 0,5, justo el fondo de escala).

**Los archivos anteriores no son comparables en ese campo.** Para distinguirlos sin mirar fechas, los barridos pasan al esquema **`scan-32-3.2`** (se siguen leyendo 2.0, 3.0 y 3.1; la 3.1 solo duró unas horas, con una única marca de Ch2) y llevan el criterio en `meta.json["scan"]["saturation_criterion"]`; los volcados, en `meta_json["saturation_criterion"]` (`measurement_meta`). Un archivo sin esa clave usa el criterio antiguo.

## 6. Seguridad

- `SN` (`unlimitedDiffMove*`) solo se usa en el **modo de movimiento libre**, activado explícitamente por el usuario con confirmación y con aviso visible en pantalla. Nunca en foco, planitud ni barridos.
- `SW` (direcciones) no se usa nunca: afecta solo a los movimientos absolutos, no a los relativos, y se pierde al cortar la tensión.
- Todo destino se comprueba contra los límites en la GUI **antes** de enviarlo, además de la comprobación del firmware.
- Rangos de foco, planitud y barridos recortados a los límites, con aviso.
- El STOP siempre está activo.
- Recordatorio en la sesión: los límites del eje del haz deben dejar margen respecto a **los dos** transductores.

## 7. Fases

1. `scanner_panel.py` independiente: worker, estado, sesión, movimiento manual y STOP.
2. Integración como pestaña en `ecos_gui.py` y acceso compartido al SeDaq.
3. Foco.
4. Planitud.
5. Barrido en línea, referencias en agua y guardado (el guardado se adelantó desde la fase 6: el formato ya admite las dos dimensiones y la línea es el caso de una fila).
6. Barrido en superficie (añade la segunda dimensión y la lectura de temperatura al acabar cada línea), con el espesor por punto y el punto testigo (`task_scanner_phase6.md`, sección 5.6).
   - El cambio de línea tiene su propio asentamiento (1000 ms por defecto, **no caracterizado**): en un solo sentido es un retorno de decenas de milímetros. El zigzag, el recorrido por defecto, no tiene retorno.

Cada fase termina con prueba en hardware y commit.

## 8. Puntos abiertos

- **Calibración del foco con reflector pequeño** como método de referencia (sección 5.4): pendiente.
- **Origen del sesgo de +0,2 dB** entre barrido fino y grueso en la misma posición (sección 5.4).
- Confirmar que `import ECOS_US_ToolBox` funciona en el Python de la máquina de adquisición (sección 3).
- Estimador de tiempo de vuelo que se reutiliza de ECOS: `LongVelocity_Thickness` usa `CalcToFAscanCosine_XCRFFT`, que es el candidato.
- **Resolución real del ADC**: no se puede leer del equipo y se suponen 10 bits (sección 5.6). Confirmarla con la documentación del SeDaq.
- Relación entre el parámetro de velocidad y los mm/s de cada eje: calibrar si se necesita una velocidad concreta.
- **Asentamiento del cambio de línea** (fase 6): 1000 ms supuestos, sin caracterizar. Medirlo como el de los 100 ms (dos barridos iguales con valores distintos), en zigzag y en un solo sentido.
- **Umbral de salto del testigo**: 3 × la dispersión de la serie, con suelo de 4 µm; comprobar en hardware la tasa de falsos saltos con PVA y con acero.
- **Sobrecarga por movimiento** del tiempo estimado (0,2 s): medida con pasos de 0,5 mm; comprobar en superficie, con los cambios de línea y las visitas al testigo.

### Resueltos
- `BITS_OPTIONS` en `ecos_gui.py` era código muerto: se ha sustituido por el parámetro `ADC_BITS` (10 bits supuestos), que usan `_update_plots`, `_acquire_avg` y la adquisición por sumas, y que se escribe en cada barrido (05/10).
- Tiempo de asentamiento y número de promedios: medidos en el equipo real, 5000 ms y 100 (30/09). La duración de `GetAScan()` se cronometra en ejecución para el tiempo estimado.
- Formato y ubicación del guardado de barridos: sección 5.6 (25/09).
- Hilo del secuenciador: dirigido por eventos en el hilo de la GUI, sección 3 (25/09).
- scipy: no hay que portar nada, sección 3 (25/09).
- El STOP funciona con el worker bloqueado en `write()`: verificado en hardware (22–24/09).
