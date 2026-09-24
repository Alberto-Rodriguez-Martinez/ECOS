# Tarea: eje R por pasos, sin velocidad, y unidades en Limit

Revisión del 23/09 tras pruebas en el laboratorio. Intervención mínima.

## 0. Hechos verificados sobre R (23/09)
- `uStepR = 1.8` es **correcto**: 100 pasos = 180°, 200 pasos = una vuelta.
- El contador de R es **circular**: al completar 200 pasos vuelve a 0 (`SDR100` dos veces desde 0 → 100 → 0). La pantalla del controlador muestra grados, no pasos.
- **`SPR` (velocidad) no tiene ningún efecto sobre R.** Se comprobó con varios valores.
- Con el soporte de muestras montado, un giro continuo **pierde pasos**: el ángulo real no se repite entre repeticiones del mismo comando. Paso a paso (órdenes de 1,8° sueltas) gira correctamente **con el soporte puesto**.

## 1. Movimientos de R troceados
Todo movimiento del eje R (jog − / +, «Move to», «Go to origin» y cualquier movimiento futuro de foco/planitud/barridos) se ejecuta como una **secuencia de órdenes de un paso** (1,8°), no como un único movimiento.

- Cada paso es un `diffMoveR(±uStepR)` independiente, o `unlimitedDiffMoveR` en modo libre.
- Pausa configurable entre pasos: campo **«Pausa entre pasos de R (ms)»** en la sesión, por defecto 100 ms, guardado en el JSON. Rango 0–2000.
- Casilla **«Mover R paso a paso»**, activada por defecto y guardada en la sesión. Si se desactiva, R se mueve con una sola orden (útil sin soporte montado). Aviso junto a la casilla: sin trocear y con el soporte montado, el eje pierde pasos.
- La secuencia va por el worker. **STOP la interrumpe entre pasos**; no se envían más pasos y se lee la posición real.
- Durante la secuencia, indicador de progreso (por ejemplo, «R: paso 12/25»).
- El contador circular no necesita tratamiento especial: cada paso relativo es pequeño y el firmware lo gestiona.

## 2. «Move to» de R: eje circular
- El destino se normaliza a [0°, 360°).
- Se calcula el **camino más corto** desde la posición actual, en número de pasos y sentido.
- Antes de ejecutar, aviso en el mensaje de estado, no un diálogo bloqueante: sentido, grados y número de pasos. Por ejemplo: «R: 315° → 45°, girando +90° (50 pasos)».

## 3. Quitar el control de velocidad de R
- `SPR` no hace nada: eliminar el campo Speed de la fila de R en la tabla de sesión (dejar la celda vacía o con «—»).
- No enviar `SPR` en ningún caso. «Apply speeds» solo actúa sobre X, Y y Z.
- Si un JSON de sesión antiguo trae una velocidad de R, se ignora sin error.
- Comentario en el código explicando por qué: verificado el 23/09, sin efecto en el firmware.

## 4. Unidades en la etiqueta Limit
El encabezado de la columna Limit perdió las unidades al reorganizar las columnas. Debe ser **«Limit (mm / °)»**, igual que Jog y Move to.

## 5. Latencia de los botones de jog
Al pulsar − o + repetidamente, el panel tarda en volver a admitir una pulsación. Revisar de dónde viene el retardo (rehabilitación de controles, lectura de posición tras cada movimiento, el `sleep(0.1)` de `Scanner.write`) y reducirlo si se puede **sin tocar `Scanner.py`**: por ejemplo, no releer las cuatro coordenadas tras un movimiento de un solo eje, o rehabilitar los botones en cuanto llega el `OK`. No es crítico: si el análisis concluye que el retardo es inherente al protocolo, documentarlo y no forzar nada.

## Verificación (simulador)
- Jog R con 5 pasos: se envían 5 órdenes de un paso con la pausa configurada; el progreso se ve; el total es el esperado.
- STOP durante una secuencia de R: se detiene a mitad y la posición corresponde a los pasos ejecutados.
- Desactivar «Mover R paso a paso»: se envía una sola orden.
- «Move to» R desde 315° a 45°: mensaje de +90° y 50 pasos.
- La fila de R no tiene campo Speed; «Apply speeds» no envía `SPR`.
- Un JSON antiguo con velocidad de R carga sin error.
- Encabezado «Limit (mm / °)».
- `python -m unittest hardware/scanner/test_sim_scanner.py` pasa.

## Commit propuesto
`feat(scanner-panel): stepwise R moves, circular shortest path, drop R speed, limit units`
