# Tarea: cruce del cero en el eje R

Revisión del 24/09 tras probar el movimiento troceado de R con el escáner real. Intervención mínima, solo en `acquisition/scanner_panel.py`.

## 0. Hechos verificados (24/09)
- El movimiento troceado de R funciona **con el soporte montado**: no pierde pasos.
- El camino más corto se calcula bien, pero **el firmware bloquea el cruce del 0 hacia abajo**: al llegar a 0, el siguiente paso pediría −1,8° y se rechaza con `ER`. Caso real: de 45° a 340° por el camino corto (−65°), el eje se detuvo en 0.
- El contador es circular **solo hacia arriba**: al pasar de 200 pasos vuelve a 0, pero al bajar de 0 no salta a 199.
- **`SAR` resuelve el cruce**: con R en 0 pasos, `SAR200` deja el contador en 200 sin mover nada, y `SDR-1` baja a 199 girando 1,8° hacia atrás. Verificado.
- Contador y pantalla del controlador van sincronizados (199 pasos ↔ 358,20°). Una lectura discrepante puntual se atribuye al refresco de la pantalla.

## 1. Cruce del cero hacia abajo
Cuando la secuencia de pasos de R en sentido negativo vaya a cruzar el 0:
1. Bajar paso a paso hasta 0.
2. Enviar `setAxis('R', 360°)` (`SAR` con el límite en pasos, equivalente a una vuelta completa): **no mueve nada**, solo redefine el contador.
3. Continuar bajando paso a paso hasta el destino.

- El troceado, la pausa entre pasos, el progreso y el STOP siguen igual. Si se pulsa STOP justo después del `SAR`, la posición leída es la real y coherente.
- El progreso sigue contando sobre el total de pasos del giro, sin reiniciarse en el cruce.

## 2. Cruce del cero hacia arriba
Al subir, el firmware devuelve el contador a 0 por sí solo al completar la vuelta, pero **el paso que va de 199 a 200 puede chocar con el límite** si `RLimit` es exactamente 200 pasos. Comprobar el comportamiento en el simulador y, si el paso se rechaza, aplicar la solución simétrica: al llegar al límite, `setAxis('R', 0)` y seguir subiendo. Documentar cuál de los dos casos se da.

## 3. Reserva
Si por cualquier motivo el cruce con `SAR` falla en ejecución (respuesta `ER` inesperada), la secuencia no debe quedarse a medias en silencio: abortar, avisar en el mensaje de estado y leer la posición real. El usuario puede entonces repetir el giro en sentido contrario, que nunca cruza el 0 hacia abajo.

## 4. Simulador
Reproducir en `sim_scanner.py` lo verificado en R:
- `SD` con destino < 0 en R se rechaza con `ER` (no da la vuelta hacia abajo).
- Al superar el límite hacia arriba, el contador vuelve a 0 (comportamiento circular ya existente: comprobar que coincide con el hardware).
- `SA` fija el contador sin mover, también en valores iguales al límite.
- Tests: bajar de 0 en R se rechaza; la maniobra completa `SAR(límite)` + paso negativo funciona.

## Verificación (simulador)
- R en 45° → «Move to» 340°: la secuencia baja hasta 0, redefine el contador y sigue hasta 340°, girando 65° en total.
- El progreso es continuo y el total de pasos coincide con el anunciado en el mensaje.
- STOP a mitad del segundo tramo: la posición leída es coherente.
- `python -m unittest hardware/scanner/test_sim_scanner.py` pasa, con los tests nuevos.

## Commit propuesto
`fix(scanner-panel): handle R zero crossing with SAR counter redefinition`
