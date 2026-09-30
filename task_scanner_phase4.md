# Tarea: Fase 4 — herramienta de Planitud

Lee antes `scanner_tab_spec.md` (secciones 3, 4, 5.1 y 5.5) y `task_scanner_phase3.md`. Se desarrolla en el entorno de adquisición de 32 bits que indica `CLAUDE.md`, y se prueba primero con el SeDaq sintético.

Reutiliza lo que ya existe: el **secuenciador dirigido por eventos** de la fase 2 y el **seguimiento del eco frontal** (`echo_tracking.py`) de la fase 3. No escribas un bucle nuevo ni un detector de ecos nuevo.

## 1. Qué mide

Dos líneas de tiempo de vuelo de la cara frontal, alrededor de la posición actual:
- **Línea lateral**: recorre ±N mm en el eje lateral. Una inclinación de la cara alrededor del eje vertical hace que el tiempo de vuelo varíe con la posición lateral.
- **Línea en Z**: recorre ±M mm en Z. Una inclinación alrededor del eje lateral hace que varíe con Z.

El eje del haz **no se mueve** en ninguna de las dos. Para el seguimiento del eco eso significa que la predicción es `t_previo` sin término de desplazamiento, y la banda absorbe la variación por inclinación, que entre puntos contiguos es pequeña.

Ángulo de cada línea: `θ = atan(c_w · Δt / (2 · Δx))`, con la pendiente del ajuste lineal de tiempo de vuelo frente a posición.

**No guarda nada** en la base de datos, pero sí escribe el volcado de depuración, igual que el foco.

## 2. Correspondencia entre inclinación y corrección

**Las dos correcciones son manuales. La herramienta mide e informa; no mueve ningún eje para corregir.**

- **Inclinación lateral** → platina manual de rotación alrededor del eje vertical.
- **Inclinación en Z** → tilt manual.

Junto a cada ángulo, en la interfaz, debe indicarse con qué control se corrige y **en qué sentido hay que girar**, con su signo, para que el usuario sepa hacia dónde mover sin deducirlo.

**El eje R no se usa para corregir la planitud**: su resolución es de 1,8° por paso, insuficiente para esto. R queda para orientar la pieza de forma gruesa. No propongas movimientos de R en esta herramienta.

## 3. Interfaz
- Parámetros: rango lateral ±N mm, rango en Z ±M mm, paso de cada eje, promedios, y tolerancia en grados.
- Valores por defecto de asentamiento y promedios, los de la fase 3 (5000 ms, 100). **Muestra el tiempo estimado antes de empezar**: con esos valores, dos líneas de veinte puntos no son inmediatas, y conviene que se vea antes de lanzarlas.
- Botones Ejecutar y Repetir. Repetir es el uso normal: corriges y vuelves a medir.
- Al lanzarla, la gráfica grande pasa a la pestaña del escáner.
- Al terminar, el escáner vuelve al centro. Si se aborta con STOP, no se mueve; solo informa.

### Resultado
Por cada eje: el ángulo, **su incertidumbre (1σ) a partir del ajuste** y el residuo RMS, más un indicador verde o rojo según la tolerancia.

Esto es importante por lo aprendido en la fase 3: un ángulo sin su incertidumbre invita a perseguir ruido. Si la incertidumbre es comparable al propio ángulo, que lo diga en vez de dar un número con falsa precisión.

### Gráfica
Las dos líneas de tiempo de vuelo frente a posición, con su recta ajustada. Eje vertical en µs, o en µm de desplazamiento de la cara, lo que resulte más legible. Marca los puntos que el seguimiento haya dado por poco fiables.

## 4. Detalles que vienen de la fase 3
- **c_w de los PT100**, con el mismo mecanismo del foco.
- Si el eco se pierde o se sale de la ventana, los mismos mensajes diferenciados: ventana estrecha frente a seguimiento perdido.
- La cara puede acabarse: al recorrer lateralmente o en Z, el haz puede salirse de la muestra. Si el eco desaparece en los extremos, que lo señale y ajuste el rango en vez de dar un ajuste con puntos malos.
- Bloqueo durante la secuencia igual que en el foco, y STOP siempre activo.

## 5. Simulador
El SeDaq sintético ya modela la inclinación con `θ_lat` y `θ_z`. Comprueba que el signo y la geometría son los que usa esta herramienta, y si no coinciden, arréglalo en el simulador, no en la medida. Añade en el panel de depuración la posibilidad de fijar los dos ángulos en caliente.

## Verificación (simulador)
1. Con `θ_lat` y `θ_z` conocidos, la herramienta los recupera con un error menor que la incertidumbre que ella misma declara. Varios valores, incluidos ángulos de signo opuesto y un caso con los dos a cero.
2. El sentido de giro que indica es coherente con el signo del ángulo: corregir en el sentido indicado reduce la inclinación medida. Compruébalo en el simulador cambiando `θ_lat` y `θ_z` como lo haría la corrección manual.
3. Con el eco perdido en algunos puntos, los marca y no los usa en el ajuste.
4. STOP a mitad: se detiene, no mueve y el refresco en vivo vuelve.
5. La herramienta no mueve R en ningún caso.
6. El volcado de depuración contiene las dos líneas con sus tiempos de vuelo.
7. Todos los tests del proyecto siguen pasando.

## No hacer
- Barridos (fases 5 y 6).
- Mover R, ni proponer correcciones con R.
- Sintaxis posterior a Python 3.9 ni API de pyqtgraph posterior a 0.11.

## Commit propuesto
`feat(scanner): flatness measurement tool (phase 4)`
