# Tarea: movimiento manual con Jog y simplificación de la sesión (`acquisition/scanner_panel.py`)

Revisión del 22/09. Intervención mínima. **El modo «fuera de límites» NO forma parte de esta tarea**: se especificará cuando se verifique en el laboratorio qué hace el contador por debajo de 0.

## 1. Sesión: quitar columnas
- Eliminar la columna **Step** de la tabla de sesión.
- Eliminar la columna **Set value** (el campo N y el botón «=N»), junto con su lógica.
- Mantener Limit + Apply, Speed, Zero, Zero all, Apply speeds, Save/Load session y Reread limits.
- Ajustar los encabezados a las columnas que quedan.

## 2. Manual movement: nuevas columnas
Orden de columnas por eje:

`Eje | Jog [campo] | − | + | Move to [campo] | Go`

- Encabezados: **«Jog (mm / °)»** sobre el campo de jog y **«Move to (mm / °)»** sobre el campo de destino.
- Los botones − y + mueven el eje (relativo, limitado) la cantidad escrita en el campo Jog de **esa fila**. Se lee al pulsar; no hace falta Enter.
- R: el jog se redondea a múltiplos de `Scanner.uStepR`, con aviso si cambia (misma lógica que ya existe). El valor por defecto de R es 1.8.
- Valores por defecto: X e Y 1,0 mm; Z 0,5 mm; R 1,8°.
- El botón Go deja de ocupar todo el ancho sobrante: anchos proporcionados, sin huecos grandes.
- El valor de Jog de cada eje se guarda y se carga con la sesión (`scanner_session.json`). Sustituye al antiguo Step.
- Compatibilidad: si un JSON antiguo trae «step», se usa como jog inicial, y en el siguiente guardado se escribe solo «jog».
- Se mantienen la comprobación de límites en la GUI antes de enviar, el bloqueo durante el movimiento y «Go to origin».

## Verificación (simulador)
- La tabla de sesión ya no muestra Step ni Set value, y los encabezados están alineados.
- Jog X = 2 → + dos veces → X = 4,00. Jog X = 0,5 → − → X = 3,50.
- Jog R = 1 → queda 1,8 con aviso.
- Guardar la sesión, cambiar los jogs, cargar la sesión → se recuperan los jogs.
- Un JSON antiguo con «step» carga sin error.
- `python -m unittest hardware/scanner/test_sim_scanner.py` pasa.
- Commit propuesto: `feat(scanner-panel): per-axis jog field, remove session step and set-value columns`
