# Especificación: pestaña Escáner en ECOS

Estado: aprobada. Fase 1 implementada y probada en hardware (21–24/09). Última revisión: 2026-09-25.

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
- **Eje R** (verificado el 23/09): `uStepR = 1.8` es correcto (200 pasos = una vuelta) y el contador es **circular** (al completar la vuelta vuelve a 0). `SPR` **no tiene efecto** sobre R. Con el soporte de muestras montado, un giro continuo **pierde pasos**; paso a paso (órdenes de 1,8° sueltas) gira bien. Por eso todo movimiento de R se trocea en pasos con una pausa configurable. Antes de usar R para corregir la orientación en la planitud, hay que comprobar su repetibilidad con la carga real.

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

## 5. Pestaña Escáner (columna derecha)

### 5.1 Estado (fijo, arriba)
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
- Parámetros: rango ±N mm en el eje del haz, alrededor de la posición actual; paso grueso; paso fino; número de promedios; ventana temporal de búsqueda del eco.
- **La ventana debe seguir al eco.** Al moverse 1 mm en el eje del haz, el eco se desplaza 2/c_w ≈ 1,33 µs. Opciones: ventana ancha con búsqueda del máximo, o ventana que se recoloca según el tiempo de vuelo previsto.
- Medida: pico de la envolvente del eco en PE.
- Algoritmo:
  1. Barrido grueso en el rango.
  2. Barrido fino alrededor del máximo.
  3. Ajuste parabólico de la amplitud en dB con 3–5 puntos alrededor del máximo.
  4. Mover al óptimo.
- Si el máximo cae en el borde del rango, avisar («amplía el rango») y no moverse.
- El rango se recorta a los límites de la sesión, avisando de ello.
- Gráfica: amplitud frente a posición, con el ajuste y el óptimo marcados.
- **No guarda nada.**

### 5.5 Planitud
- Parámetros: rango ±N mm en el eje lateral, rango ±M mm en Z (ambos alrededor del centro), paso, promedios y tolerancia en grados.
- Mide dos líneas, lateral y Z, con el tiempo de vuelo de la cara de la muestra en PE. Estimador de ECOS.
- Ajuste lineal del tiempo de vuelo frente a la posición en cada línea. Ángulo θ = atan(c_w · Δt / (2 · Δx)), con c_w calculada a partir de los PT100.
- Gráfica: las dos líneas con su ajuste, el ángulo de cada eje y un indicador verde o rojo según la tolerancia. Leyenda: inclinación lateral → corregir con R; inclinación en Z → corregir con el tilt manual.
- Botón Repetir, para iterar mientras se corrige.
- **No guarda nada.**

### 5.6 Barridos
- Tipo: línea (lateral o Z) o superficie (lateral × Z).
- Rango de cada eje: inicio y fin, relativos al centro o absolutos, más el paso.
- Recorrido: zigzag o siempre en el mismo sentido, a elegir. El segundo evita que la holgura mecánica desplace las líneas alternas.
- Espera tras cada movimiento (ms), configurable. Número de promedios por punto.
- Tiempo estimado mostrado antes de empezar.
- Mapa en vivo con la magnitud que elija el usuario:
  - Amplitud máxima en la ventana.
  - Tiempo de vuelo.
  - Energía en la ventana.
  - Ampliable a otras magnitudes.
- Pausa, continuar y parar. Al parar, se ofrece guardar lo adquirido hasta ese momento.

#### Referencias en agua (opcional)
Casilla «Tomar referencias en agua al inicio y al final». Parámetros en el panel: **ganancia de referencia por canal** (Ch1, Ch2) y número de promedios de la referencia.

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
               parámetros del barrido, operator y comentario. schema_version: "scan-32-1.0"
  scan.npz     señales (N_línea × N_punto × N_muestras) por canal, coordenadas reales de cada
               punto, temperaturas con su marca de tiempo e índice, y las referencias en agua
               con su ganancia, posición, hora y temperatura
```

- Sin `results.json`: en un barrido los resultados se calculan después, en el análisis.
- **Se guarda automáticamente en `../database`**, con el nombre de la convención de ECOS y `SCAN` como tipo, para que `analysis/ecos_loader.py` pueda catalogarlo. Un botón «Guardar en otra carpeta…» permite elegir otra ubicación.
- El bloque `scanner_session` es el diccionario que ya produce `ScannerPanel`, que es serializable a JSON.
- Hace falta **una función nueva** (p. ej. `save_scan_raw_32`): `save_experiment_raw_32` valida que haya exactamente tres señales 1D de igual longitud y no admite un cubo. Se reutiliza su esquema de metadatos, no su firma.
- `operator` está hoy fijo como «Sebas» en `BD_Experimentos_PVA.py`. En la función nueva debe ser un campo.

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
5. Barrido en línea.
6. Barrido en superficie y guardado.

Cada fase termina con prueba en hardware y commit.

## 8. Puntos abiertos

- **Duración real de `GetAScan()`**, con y sin promediado, para el `RecLen` que use el escáner. Hay que medirla en el hardware: de ella dependen el número de promedios y el tiempo estimado de un barrido.
- **Tiempo de asentamiento tras un movimiento.** No hay ningún valor de referencia; hay que caracterizar la vibración residual del soporte en el equipo real.
- Confirmar que `import ECOS_US_ToolBox` funciona en el Python de la máquina de adquisición (sección 3).
- Estimador de tiempo de vuelo que se reutiliza de ECOS: `LongVelocity_Thickness` usa `CalcToFAscanCosine_XCRFFT`, que es el candidato.
- `BITS_OPTIONS` en `ecos_gui.py` parece código muerto: el cuantizador está fijo a 1024 en `_update_plots` y `_acquire_ch_avg`. Aclararlo si el foco necesita conocer la resolución real del ADC.
- Relación entre el parámetro de velocidad y los mm/s de cada eje: calibrar si se necesita una velocidad concreta.

### Resueltos
- Formato y ubicación del guardado de barridos: sección 5.6 (25/09).
- Hilo del secuenciador: dirigido por eventos en el hilo de la GUI, sección 3 (25/09).
- scipy: no hay que portar nada, sección 3 (25/09).
- El STOP funciona con el worker bloqueado en `write()`: verificado en hardware (22–24/09).
