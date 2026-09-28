# Tarea: Fase 3 — SeDaq sintético y herramienta de Foco

Lee antes `scanner_tab_spec.md` (secciones 3, 4, 5.1 y 5.4). Se desarrolla **sin hardware**, en el `.venv` de 64 bits.

Son dos partes: un generador de ecos sintéticos que sustituya al `_DemoSeDaq` actual, y la herramienta de Foco construida sobre él. La primera existe para que la segunda se pueda validar contra una respuesta conocida.

## Restricción de compatibilidad
El código de gráficas se ejecutará en la máquina de adquisición, que tiene **pyqtgraph 0.11**. En desarrollo hay 0.13.7. Cíñete al subconjunto de API que funciona en 0.11:
- Colores como tuplas RGB, nunca como nombres (`'r'`, `'blue'`).
- `enableAutoSIPrefix(False)` explícito en los ejes con unidades.
- Nada de API añadida después de 0.11. Si dudas de un método, no lo uses.
Anota en el código cualquier punto donde hayas tenido que elegir por esto.

## 1. SeDaq sintético: `acquisition/sim_sedaq.py`

Clase `SimSeDaq` con la misma interfaz que usa `ecos_gui.py` (`GetAScan`, `SetRecLen`, `SetGain1`, `SetGain2`, buffers `DataADC1`/`DataADC2`, y lo que haga falta según el uso real). Sustituye a `_DemoSeDaq` cuando se arranca en modo simulador; el `_DemoSeDaq` actual puede desaparecer o quedar como caso trivial.

### Modelo físico
Conoce la posición del escáner (se la inyecta el panel tras cada movimiento) y genera los ecos en consecuencia.

**Eco de cara frontal, canal PE (Ch1):**
- Tiempo de vuelo: `t = 2·d(pos) / c_w`, donde `d` es la distancia del transductor PE a la cara de la muestra.
  - `d` depende de la posición en el eje del haz, con el signo que marque **PE side** (spec sección 2).
  - La inclinación añade un término lineal: `d += tan(θ_lat)·(lat − lat₀) + tan(θ_z)·(z − z₀)`.
- Amplitud: gaussiana centrada en el foco, `A = A₀·exp(−(x_haz − x_foco)² / (2σ²))`.
- Forma de onda: senoidal a `f₀` con envolvente gaussiana, de ancho de banda realista.

**Canal de transmisión (Ch2):** pulso que atraviesa la muestra, con su propio tiempo de vuelo y una amplitud que depende de la posición lateral y de Z, para que los barridos den un mapa con estructura y no una superficie plana.

**Ruido:** gaussiano, con relación señal-ruido configurable.

**Ganancia:** las llamadas a `SetGain1`/`SetGain2` escalan la señal, y hay saturación al fondo de escala del cuantizador. Así se puede probar de verdad el cambio de ganancia de las referencias en agua.

### Parámetros y verdad de referencia
- Todos los parámetros del modelo en una dataclass: `x_foco`, `σ`, `θ_lat`, `θ_z`, `c_w`, `f₀`, `A₀`, SNR, espesor de la muestra.
- Valores por defecto realistas para el montaje: transductor enfocado, agua a ~25 °C.
- **Los parámetros son accesibles desde fuera**, para que los tests comprueben que el foco encontrado coincide con `x_foco` y los ángulos de planitud con `θ_lat` y `θ_z`.
- Panel de depuración, solo en modo simulador, para editarlos en caliente: así puedes ver cómo responde la herramienta a una muestra muy inclinada o con poco ruido.

## 2. Herramienta de Foco (spec 5.4)

### Interfaz, en la pestaña Escáner
- Parámetros: rango ±N mm en el eje del haz alrededor de la posición actual, paso grueso, paso fino, número de promedios y ventana temporal de búsqueda del eco.
- Botón Ejecutar, y el STOP de siempre.
- Al lanzarla, la gráfica grande pasa a la pestaña Escáner.

### Ventana de búsqueda que sigue al eco
Al moverse 1 mm en el eje del haz, el eco se desplaza `2/c_w ≈ 1,33 µs`. Con una ventana fija, el eco se sale a los pocos milímetros. Implementa la ventana ancha con búsqueda del máximo dentro de ella, y deja la recolocación predictiva anotada como alternativa si el ruido resulta ser un problema. Explica en el código por qué se elige.

### Algoritmo
1. Barrido grueso en todo el rango, recortado a los límites de sesión, avisando si se recorta.
2. Barrido fino alrededor del máximo.
3. Ajuste parabólico **sobre la amplitud en dB**, con 3–5 puntos alrededor del máximo. El perfil axial cerca del foco se aproxima a una gaussiana, y una gaussiana en logaritmo es una parábola, así que el ajuste es el adecuado y no una aproximación de conveniencia.
4. Mover al óptimo.
- Medida por punto: pico de la envolvente (`Envelope` de `ECOS_US_ToolBox`, que ya usa Hilbert) del eco dentro de la ventana.
- Si el máximo cae en el borde del rango: avisar («amplía el rango») y **no moverse**.
- No guarda nada.

### Gráfica
Amplitud frente a posición: los puntos medidos, la parábola ajustada y una marca en el óptimo. Ejes rotulados con unidades.

### Ejecución
Usa el secuenciador de la fase 2 tal cual. No escribas un bucle nuevo.

## 3. Valores por defecto pendientes de medir
El tiempo de asentamiento y el número de promedios no están caracterizados en el equipo real. Pon valores razonables (por ejemplo, 200 ms y 10 promedios), **marcados en el código como pendientes de medir**, y que sean editables desde la interfaz.

## Verificación
1. `python acquisition/ecos_gui.py --scanner-sim` arranca con el SeDaq sintético y se ve el A-scan en vivo, con el eco cambiando al mover el escáner a mano.
2. Con `x_foco` fijado en un valor conocido y un rango que lo contenga, Foco lo encuentra **con un error menor que el paso fino**. Test automático que lo compruebe con varios valores de `x_foco` y de SNR.
3. Con el foco fuera del rango, avisa y no mueve el escáner.
4. Con el rango saliéndose de los límites de sesión, lo recorta y avisa.
5. STOP a mitad: se detiene, el refresco en vivo vuelve y el escáner no se mueve al óptimo.
6. La gráfica se ve correctamente, con la parábola y el óptimo marcados.
7. `python -m unittest` de todos los tests del proyecto sigue pasando.

## No hacer
- Planitud y barridos (fases 4 a 6).
- Tocar el driver del escáner ni su simulador serie.
- Usar API de pyqtgraph posterior a 0.11.

## Commits propuestos
- `feat(sim): synthetic SeDaq with focus and tilt model`
- `feat(scanner): focus search tool (phase 3)`
