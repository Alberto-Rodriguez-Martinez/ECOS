# Tarea: ajustes de la fase 1 en `acquisition/scanner_panel.py`

Tras la revisión con el simulador (22/09). Intervención mínima: solo estos cambios.

1. **Paso de R en múltiplos de 1,8°.**
   - El paso por defecto de R es 1.8.
   - El campo Step de R solo admite múltiplos de 1,8°. Si se introduce otro valor, se redondea al múltiplo más cercano (mínimo 1,8), se muestra el valor corregido en el campo y un aviso breve.
   - Lo mismo en el «Go» de R y en el «=N» de R: el destino o el valor se redondea al múltiplo de 1,8° más cercano, avisando si cambia.
   - Constante derivada de `Scanner.uStepR`, no escrita a mano.

2. **Encabezados de la tabla de sesión alineados.**
   Ahora «Zero» aparece sobre el campo de N y «=N» sobre su botón. Cada encabezado debe quedar sobre su columna: «Zero» sobre el botón Zero, y un encabezado «N» (o «Set value») sobre el campo más el botón «=N».

3. **Límite por defecto de R: 360°.**
   - En una sesión nueva (sin JSON), el límite de R de la tabla es 360.
   - Al detectar un reinicio del controlador (límites a 10000 pasos) y no haber sesión guardada, se proponen estos valores por defecto (100 / 100 / 50 / 360) en lugar de los del firmware.

4. **Unidades en la columna Step.**
   Encabezado «Step (mm)». En la fila de R, unidad «°» visible junto al campo (o encabezado «Step (mm / °)», lo que quede más claro).

5. **Botón «Go to origin».**
   - Lleva todos los ejes a 0 con un movimiento por eje, en este orden fijo de ejes físicos: **R, Z, X, Y**. Mismo orden sea cual sea el eje del haz.
   - Antes de moverse, diálogo de confirmación con el orden y las posiciones actual y final de cada eje.
   - Ejes que ya están en 0: se omiten.
   - Pasa por el worker como cualquier movimiento. STOP interrumpe la secuencia completa (no sigue con el siguiente eje).
   - Controles deshabilitados durante la secuencia (salvo STOP). Posición actualizada tras cada eje.
   - Ubicación: en la sección Manual movement.

## Verificación (simulador)
- Poner 1 en el Step de R → queda 1.8 con aviso. «Go» R a 10 → va a 10.8 con aviso.
- Encabezados alineados.
- Borrar `scanner_session.json` y conectar: el aviso de reinicio propone 360 para R.
- Mover X, Y, Z y R fuera de 0 → «Go to origin» → confirmar → orden R, Z, X, Y. Repetir y pulsar STOP durante Z: X e Y no se mueven.
- `python -m unittest hardware/scanner/test_sim_scanner.py` sigue pasando.
- Commit propuesto: `fix(scanner-panel): R step multiples, header alignment, R limit default, go-to-origin`
