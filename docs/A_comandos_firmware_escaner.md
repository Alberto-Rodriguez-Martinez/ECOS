# Anexo A. Comandos del controlador del escáner

Controlador SE SC-03-00, comunicación serie a 19200 baudios. Los comandos se envían como texto terminado en retorno de carro (`\r`). El programa los usa a través de la clase `Scanner` (`hardware/scanner/Scanner.py`).

**Cómo se envía una orden.** Se escribe la orden, se espera 0,1 s y se leen 10 bytes. Las órdenes `SM`, `SL`, `SC`, `SD`, `SN`, `SA` y `SG` **bloquean** hasta recibir respuesta, como máximo 120 s: si se agota, se envía `SSF` y se lanza un error de tiempo agotado. Ante un fallo de comunicación se lanza un error de conexión.

**Respuestas.** `OK` + eje + 6 dígitos + `\r`, o `ER` + eje + 6 caracteres + `\r`. En valores negativos, el signo ocupa una de las cifras.

| Orden | Parámetros | Respuesta | Método de `Scanner` |
|---|---|---|---|
| `SC{X\|Y\|Z\|R}` | — | `OK` + posición en pasos | `X`/`Y`/`Z`/`R`, `getCoords`, `getAxis` (también comprueba la identidad al conectar) |
| `SA{eje}{pasos}` | posición en pasos | `OK` / `ER` | setters de eje, `setAxis`, `setCurrent`, `setZero` |
| `SM{eje}{pasos}` | destino absoluto, limitado | `OK` al **terminar** el movimiento; `ER` si está fuera de `[0, límite]` | `moveX`…`moveR`, `moveAxis`, `move`, `goHome` |
| `SD{eje}{±pasos}` | relativo con signo, limitado | `OK` / `ER` | `diffMoveX`…, `diffMoveAxis`, `diffMove` |
| `SN{eje}{±pasos}` | relativo con signo, **sin límites** | `OK` | `unlimitedDiffMoveX`…, `unlimitedDiffMoveAxis` |
| `SG{eje}` | — | `OK` + límite en pasos | `XLimit`…`RLimit`, `getLimits`, `getAxisLimit` |
| `SL{eje}{pasos}` | límite | `OK` / `ER` | setters de límite, `setLimits`, `setAxisLimit` |
| `SW{eje}{+\|-}` | sentido | sin comprobar | `Xdirection`…, `setDirections`. Solo afecta a `SM`; se pierde al cortar la tensión. El panel no lo usa |
| `ST{eje}{0..3}` | tipo de velocidad: 0 rectangular, 1 gaussiana, 2 aleatoria, 3 triangular | sin comprobar | `setSpeedtypes` (el constructor pone 0), `setAxisSpeedtype` |
| `SP{eje}{1..65536}` | velocidad (parámetro del firmware, no mm/s) | sin comprobar | `setSpeeds` (el constructor pone 100), `setAxisSpeed`. Sin efecto sobre R |
| `SO{eje}{µs}` | rampa (solo con los tipos 1 y 3) | sin comprobar | `setRampingSpeeds`, `setAxisRampingSpeed`. No se usa |
| `SR{eje}{valor}` | velocidad aleatoria (tipo 2) | sin comprobar | `setRandomSpeeds`. No se usa |
| `SE{eje}{+\|-}` | habilitar o deshabilitar el motor | sin comprobar | `enableX`…, `enableAll` (en el constructor), `disableAll` |
| `SSF` | — | sin comprobar | `stop()`; el botón **STOP** del panel la escribe directamente |

**Al crearse, `Scanner`** lee las coordenadas, habilita los motores, fija los sentidos `+, +, −, +` (X, Y, Z, R), el tipo de velocidad rectangular y la velocidad 100. Tarda unos 4 s.

*[Pendiente: qué responde el controlador a `SW`, `ST`, `SP`, `SE` y `SSF`; `Scanner.write` no comprueba su respuesta. Qué responde a un movimiento interrumpido por STOP.]*
