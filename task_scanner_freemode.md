# Tarea: modo fuera de límites, puertos y modelo verificado del firmware

Revisión del 23/09 tras pruebas en el laboratorio con el escáner real (`check_negative.py`). Intervención mínima.

## 0. Modelo verificado del firmware (hechos, no suposiciones)

| Orden | Signo negativo en el valor | Respeta los límites [0, limit] |
|---|---|---|
| `SM` (absoluto) | no aplica | sí |
| `SD` (relativo, `diffMove*`) | **sí** | **sí** — rechaza con `ER` |
| `SN` (relativo, `unlimitedDiffMove*`) | sí | no |
| `SW` (dirección) | invierte el sentido de los **absolutos**; **no afecta a los relativos** | — |

- Respuesta de rechazo: `b'ER' + eje + 6 caracteres + b'\r'` (10 bytes). Ejemplo real: `SDX-10` desde 0 → `b'ERX000000\r'`.
- Posición negativa: el signo ocupa el lugar de un dígito, **siguen siendo 10 bytes**. Ejemplo real: `b'OKX-00010\r'` = −0,1 mm. La lectura actual de la librería es correcta.
- `SW` **no se usa nunca** en el panel: es un estado oculto que se pierde al cortar la tensión y su efecto es asimétrico (absolutos sí, relativos no).

## 1. `hardware/scanner/Scanner.py`: docstrings
Corregir los docstrings de `diffMove*`, `unlimitedDiffMove*`, `diffMoveAxis` y `unlimitedDiffMoveAxis`: eliminar «in the current direction» y decir que el sentido lo determina el signo del valor, verificado en hardware el 23/09/2026. Añadir a `setDirections` / `setAxisDirection` una advertencia: afecta solo a los movimientos absolutos, no persiste al cortar la tensión y el panel no lo usa. **Solo docstrings y comentarios; ninguna línea de código.**

## 2. `hardware/scanner/sim_scanner.py`: ajustar a lo verificado
- Prefijo de rechazo `ER` (ya lo usaba: pasa de supuesto a verificado en el comentario).
- `SD`: acepta signo y rechaza con `ER` si el destino sale de [0, límite].
- `SN`: acepta signo, sin límites, y permite posiciones negativas.
- Formato de posición negativa: signo en lugar del primer dígito, siempre 10 bytes (`OKX-00010`).
- `SW`: se registra, pero no afecta a los relativos. No hace falta simular su efecto en los absolutos; comenta por qué.
- Tests nuevos en `test_sim_scanner.py`: `SD` negativo dentro de rango funciona; `SD` que saldría de rango es rechazado; `SN` negativo lleva a posición negativa y `SCX` la devuelve en 10 bytes; leer una posición negativa con `Scanner.X` da el valor correcto (comprueba que `float(r[3:])` funciona con el signo).

## 3. `acquisition/scanner_panel.py`: desplegable de puertos
No dar por supuesto qué puerto es el del Arduino. En el desplegable se muestra solo la descripción del sistema. La etiqueta de posible conflicto (si se mantiene) no puede afirmar que un puerto sea el Arduino: como mucho, un aviso genérico de que puede haber otros dispositivos serie. Al verificar la identidad del escáner al conectar, cualquier marca desaparece para ese puerto.

## 4. `acquisition/scanner_panel.py`: modo fuera de límites

Sustituye a la maniobra con «=N» (ya eliminada) para colocar el cero y los límites del volumen de trabajo.

### Activación
- Casilla o interruptor **«Movimiento libre (sin límites)»** en Manual movement.
- Al activarlo, diálogo de confirmación: explica que el firmware deja de proteger el recorrido, que la responsabilidad es del usuario y que hay riesgo de colisión con los transductores. Botones Activar y Cancelar.
- Mientras está activo, **franja o banda roja bien visible** en el panel, con el texto «MOVIMIENTO LIBRE — sin protección de límites».

### Comportamiento
- Los botones − y + usan `unlimitedDiffMove*` (`SN`) con el signo del jog, en lugar de `diffMove*`.
- Se omite la comprobación de límites de la GUI para esos movimientos.
- **«Move to» y «Go to origin» se deshabilitan** en modo libre: son absolutos y el firmware no admite destinos negativos.
- El modo se desactiva automáticamente al desconectar. **No se guarda en la sesión.**
- Cuando existan (fases posteriores), foco, planitud y barridos quedan bloqueados mientras el modo esté activo. Deja el punto único donde comprobarlo.

### Al desactivar
- Si todos los ejes están dentro de [0, límite], se desactiva sin más.
- Si algún eje está fuera, diálogo que lista los ejes afectados con su posición y ofrece:
  - **Fijar cero aquí** (`setZero` de los ejes fuera de rango, o de todos; que el diálogo lo aclare),
  - **Mantener la posición** y desactivar igualmente, avisando de que los destinos absolutos fallarán hasta corregirlo,
  - **Seguir en modo libre** (cancela la desactivación).

### Verificación (simulador)
- Activar el modo: confirmación y banda roja visibles.
- Con X en 0 y jog 1: `−` lleva a −1,00 (en modo normal, la GUI lo impide).
- «Move to» y «Go to origin» deshabilitados en modo libre.
- Desactivar con X en −1: aparece el diálogo con las tres opciones; «Fijar cero aquí» deja X en 0,00.
- Desconectar en modo libre: al reconectar, el modo está desactivado.
- `python -m unittest hardware/scanner/test_sim_scanner.py` pasa.

## Commits propuestos
- `docs(scanner): correct diffMove/SW docstrings after hardware verification`
- `fix(sim-scanner): signed relative moves, ER rejection, negative positions`
- `feat(scanner-panel): free-movement mode; port list no longer assumes Arduino`
