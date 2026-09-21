# Tarea: corrección de bugs en `hardware/scanner/Scanner.py`

## Contexto
`Scanner.py` es la librería de control por puerto serie del escáner XYZR (autor original: Arnau Busqué, 2023). Se usa para posicionar muestras en la vasija de ultrasonidos. Está probada y funciona, con estos datos verificados en hardware:

- Puerto COM3, 19200 baud. Respuestas de 10 bytes: `OK` + eje + 6 dígitos + `\r` (p. ej. `b'OKX000000\r'`).
- Los movimientos (`SM`, `SD`…) **bloquean hasta el final del movimiento**: el `OK` llega al terminar (20 mm en X ≈ 3,2 s con speed=100).
- El firmware rechaza destinos < 0 o > límite (`SL`). Límites por defecto: 10000 pasos en todos los ejes.

## Reglas
- **Intervención mínima.** No reestructurar, no renombrar métodos, no cambiar la API pública ni el estilo del autor. Solo los cambios listados.
- Comentarios en inglés. Marca cada cambio con `# FIX (2026-09):` y una frase.
- Antes de editar, confirma que el original está commiteado (`git status`), para que el diff sea revisable.

## Cambios

1. **`value2uSteps`: redondeo en vez de truncado.**
   `int(value / self.getuSteps(axis))` trunca: 0.29/0.01 = 28.999… → 28 pasos. Cambiar a `int(round(value / self.getuSteps(axis)))`. Mantener el aviso de no-múltiplo tal cual.

2. **`write`: límite de tiempo en la espera de respuesta.**
   El bucle `while response == b''` para `SM/SL/SC/SD/SN/SA/SG` no tiene salida. Añadir parámetro `move_timeout=120` (s) en `__init__` guardado como `self.move_timeout`. Si se supera: enviar `SSF\r`, imprimir aviso y lanzar `TimeoutError`.

3. **`write`: no devolver `None` en silencio tras un error de comunicación.**
   Ahora, si falla, cierra el puerto y devuelve `None`; luego los getters fallan con `TypeError` en `x[3:]`. Mantener los `print` y el cierre de puerto, pero después lanzar `ConnectionError` con el mensaje original (en los dos `except` genéricos y cuando el puerto no se pudo abrir). No tocar el manejo de `KeyboardInterrupt`.

4. **`X/Y/Z/RRandomSpeed` setters: falta la `f` del f-string.**
   `self.write('SRX{value}')` → `self.write(f'SRX{value}')` (los cuatro ejes).

5. **`diffMove*` y `unlimitedDiffMove*`: caché incorrecta.**
   Guardan el desplazamiento relativo en `self._X` como si fuera la posición absoluta. Sustituir `self._X = value` (y equivalentes en Y, Z, R) por `self._X = None` con comentario: la posición real se obtiene leyendo la propiedad. (La caché `_X` no se lee en ningún sitio; no añadir lecturas extra.)

6. **`_parseSpeedtype`: nombre inválido provoca `UnboundLocalError`.**
   Si es `str` pero no está en la lista, no se asigna `code`. Añadir el `else` que imprime el aviso y devuelve 0, igual que la rama existente.

7. **Getters de ramping/random speed: `AttributeError` si nunca se fijaron.**
   Inicializar en `__init__` `self._XRampingSpeed = self._YRampingSpeed = self._ZRampingSpeed = self._RRampingSpeed = None` y lo mismo para `_XRandomSpeed`… (antes de las llamadas a `setSpeedtypes`).

## No tocar (documentado, fuera de alcance)
- `read(10)`: funciona con el formato actual de 10 bytes.
- Puerto por defecto `COM4` en `__init__`: se pasa explícitamente.
- `uStepR = 1.8` y su comentario.
- `findEdge`, `findEdge2`, `makeScanPattern` y auxiliares.
- El constructor sigue habilitando motores y fijando velocidades al conectar.

## Verificación
1. `python -c "import ast,sys; ast.parse(open('hardware/scanner/Scanner.py').read())"` (sintaxis).
2. Sin hardware: comprobar `value2uSteps('X', 0.29) == 29` y `_parseSpeedtype('foo') == 0` instanciando sin constructor (`Scanner.__new__(Scanner)` y asignando `uStepX` a mano).
3. Con hardware (lo ejecuta Alberto): `python hardware/scanner/test_connection.py` debe dar la misma salida que antes.
4. Mostrar `git diff` al terminar y proponer mensaje de commit: `fix(scanner): rounding, timeouts, error propagation and minor bugs`.
