# Tarea: Fase 1 de la pestaña Escáner — simulador + panel independiente

Lee antes `scanner_tab_spec.md` (secciones 1–3, 5.1–5.3 y 6). Esta tarea implementa **solo la fase 1**. No toques `ecos_gui.py` (la integración es la fase 2).

## Entorno
- Python 3.12 **32 bits** (`.venv32`). Solo numpy, pyserial, PyQt5 y pyqtgraph 0.11. **Sin scipy.**
- Se desarrolla sin hardware: todo debe poder probarse con el simulador.
- Comentarios y nombres en inglés. Textos de la GUI en el mismo idioma que usa `ecos_gui.py` (compruébalo).

## 1. Cambio mínimo en `hardware/scanner/Scanner.py`
- Añadir un parámetro opcional `ser=None` a `__init__`. Si se pasa, se usa ese objeto en lugar de crear `serial.Serial(port, baudrate, timeout=timeout)`.
- Nada más. Marca el cambio con `# FIX (2026-09):` (o `# ADD (2026-09):`).

## 2. Simulador: `hardware/scanner/sim_scanner.py`
Clase `FakeSerial` que imita la interfaz de `serial.Serial` que usa `Scanner` (`write`, `read`, `isOpen`, `open`, `close`, `flushInput`, `flushOutput`, `reset_input_buffer`, `reset_output_buffer`, atributos `port` y `timeout`) y el comportamiento **verificado** del controlador:

- **Estado interno** por eje: posición y límite en pasos, dirección, tipo de velocidad, velocidad y habilitado.
- **Respuestas**: `SC{ax}` y `SG{ax}` → `b'OK' + ax + 6 dígitos + b'\r'` (10 bytes). Para las órdenes que el firmware acepta, `b'OK' + ax + ...` con el mismo formato (por ejemplo, la posición). **Supuesto no verificado**: para las que rechaza, algo que no empiece por `OK` (usa `b'ER' + ax + '000000\r'`). Déjalo como constante con un comentario.
- **Rechazo**: `SM` (absoluto) y `SD` (relativo) rechazan destinos < 0 o > límite, sin moverse. `SN` ignora los límites. `SA` fija la posición sin moverse.
- **Movimiento con duración real**: la respuesta a `SM`/`SD`/`SN` no está disponible (`read` devuelve `b''`) hasta que acaba el movimiento. Duración = pasos / velocidad_en_pasos_por_s. Calibración verificada: X con speed=100 ≈ 6,7 mm/s ≈ 670 pasos/s. Supón que es proporcional al parámetro de velocidad y que es igual en todos los ejes en pasos/s (en Z sale la mitad de mm/s). Deja la constante configurable y marcada como supuesto.
- **Parada**: `SSF` detiene el movimiento en curso. La posición queda en la que corresponda al tiempo transcurrido y la respuesta pendiente del movimiento se libera. Debe funcionar si `SSF` llega **desde otro hilo** mientras el hilo principal está esperando en `read`: usa un lock y cálculo por tiempo, no bucles bloqueantes.
- **Reinicio por corte de tensión**: método `power_cycle()`. La posición se conserva y los límites vuelven a 10000 pasos en todos los ejes.
- **Latencia**: pequeña pausa configurable por orden. Por defecto ninguna extra, porque `Scanner.write` ya duerme 0,1 s.
- Tests con `unittest` en `hardware/scanner/test_sim_scanner.py`, **usando la clase `Scanner` real** sobre `FakeSerial`:
  - Lectura de coordenadas y límites.
  - Rechazo de −0,5 mm y de límite + 0,5 mm.
  - Duración aproximada de un movimiento de 20 mm en X (≈ 3 s; permite acelerar el tiempo con un factor para que los tests sean rápidos).
  - `SSF` desde otro hilo a mitad de movimiento: la posición queda intermedia y `write` vuelve sin esperar al timeout.
  - `power_cycle()` restablece los límites y conserva la posición.
  - `value2uSteps('X', 0.29) == 29`.

## 3. Panel: `acquisition/scanner_panel.py`
QWidget `ScannerPanel`, ejecutable de forma independiente: `python acquisition/scanner_panel.py` (hardware) o `... --sim` (simulador). Diseñado para insertarse después como pestaña.

### Worker
`ScannerWorker` en un `QThread`, **único** que llama a métodos de `Scanner`. Cola de órdenes. Señales: `connected(str)`, `disconnected()`, `moved(tuple)`, `limits(tuple)`, `busy(bool)`, `error(str)`, `message(str)`.

### STOP
Botón siempre activo. **No pasa por la cola**: escribe `b'SSF\r'` directamente en el puerto desde el hilo de la GUI, protegido con un lock propio del panel. Justo después, el worker lee la posición y la emite. Documenta en el código que en hardware real **no está verificado** qué responde el controlador al movimiento interrumpido. Es la prueba principal de la fase 1 en el laboratorio.

### Conexión (spec 5.1)
- Desplegable de puertos (`serial.tools.list_ports`, con descripción) y botón de refresco. En modo `--sim`, una única entrada «Simulador».
- **Verificación de identidad antes de crear `Scanner`**: abrir con pyserial, enviar `SCX\r` y exigir que la respuesta coincida con `^OKX\d{6}\r$`. Si no coincide, mostrar «El dispositivo en COMx no es el escáner» y cerrar el puerto. Solo si pasa la verificación, crear `Scanner(port=...)`, o `Scanner(ser=FakeSerial())` en el simulador.
- Mensaje de resultado siempre visible.
- Tras conectar:
  1. Leer los límites. Si los cuatro valen 10000 pasos, avisar de que el controlador se ha reiniciado y ofrecer reenviar los de la sesión guardada.
  2. Mostrar el aviso de movimiento manual de ejes.
  3. Mientras no se confirmen estos avisos, solo se permite el movimiento manual (preparado para las fases siguientes).

### Estado
Posición X/Y/Z/R etiquetada según su papel (haz, lateral, Z), limitada a la resolución de cada eje. Estado «Libre» o «Moviendo». Se actualiza al terminar cada movimiento.

### Sesión (spec 5.2)
- Eje del haz (Y o X). Lado PE (origen, que es el valor por defecto, o máximo).
- Límites por eje: aplicar y releer del firmware.
- Paso manual por eje y velocidad por eje.
- Fijar cero (por eje y todos). «Esta posición vale N» por eje, comprobando antes que N ≤ límite.
- Guardar y cargar `hardware/scanner/scanner_session.json`: eje del haz, lado PE, límites, pasos, velocidades y último puerto. Añádelo al `.gitignore`.

### Movimiento manual (spec 5.3)
- Botones +/− por eje con el paso configurado. Ir a una posición absoluta, por eje.
- **Comprobación en la GUI antes de enviar** cualquier destino: 0 ≤ destino ≤ límite. Si no se cumple, mensaje y no se envía.
- Controles deshabilitados mientras hay movimiento (excepto STOP).
- Nunca usar `unlimitedDiffMove*` ni `SN`.

## No hacer
- No integrar en `ecos_gui.py`.
- No implementar foco, planitud ni barridos.
- No tocar el SeDaq ni el Arduino.
- No cambiar la API de `Scanner` más allá del parámetro `ser`.

## Verificación
1. `python -m unittest hardware/scanner/test_sim_scanner.py`: todos los tests pasan.
2. `python acquisition/scanner_panel.py --sim`, a mano:
   - Conectar.
   - Mover ±.
   - Intentar salir de los límites (debe bloquearlo la GUI).
   - STOP a mitad de un movimiento de 20 mm.
   - Llamar a `power_cycle()` desde un botón de depuración, visible solo con `--sim`, y reconectar: debe aparecer el aviso de reinicio.
   - Guardar y cargar la sesión.
3. Mostrar `git diff --stat` y proponer los commits por separado:
   - `feat(scanner): serial simulator + tests`
   - `feat(scanner): standalone ScannerPanel (phase 1)`
