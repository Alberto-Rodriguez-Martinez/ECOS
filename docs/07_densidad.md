# 7. Densidad

*[Pendiente: esquema del montaje —vaso, transductor, muestra sumergida y nivel del agua— con leyenda numerada, y captura de la ventana de densidad con los controles numerados.]*

La densidad se mide por el método de Arquímedes con ultrasonidos: al sumergir la muestra en el vaso, el nivel del agua sube; el aumento de nivel, que se mide con el tiempo de vuelo de un eco, da el **volumen desplazado**, y con la masa se obtiene la densidad. Se hace en un programa propio, **`density_gui`**, que no es la pestaña Acquisition de la medida de punto (capítulo 6).

> **Qué necesitas**
> El **radio del vaso** (medido o calibrado, apartado 7.4), la **masa** de la muestra, una **temperatura del agua** y las dos señales: la del vaso con agua sola (**sW1**) y la del vaso con la muestra sumergida (**sW2**).

## 7.1. Cómo se calcula

1. Se compara el eco de **sW2** con el de **sW1** y se obtiene la diferencia de tiempo de vuelo, **ΔToF**.
2. El aumento de nivel es **Δh = c_w · ΔToF / 2**, con c_w calculado de la temperatura del agua.
3. El volumen desplazado es **V = π · r² · Δh**, con r el radio del vaso.
4. La densidad es **masa / V**.

Dos consecuencias prácticas:

- **El radio del vaso entra al cuadrado.** Un error del 1 % en el radio da un 2 % en la densidad. Por eso conviene calibrarlo (apartado 7.4).
- **c_w entra directamente en Δh.** La temperatura del agua debe ser la de la medida y la misma al tomar sW1 y sW2.
- **La muestra debe estar atemperada** a la misma temperatura que el agua del vaso. Si no lo está, al sumergirla el agua cambia de temperatura de golpe y con ella c_w; como ΔToF sale de comparar sW2 con sW1, ese cambio se confunde con una subida de nivel y falsea el volumen.

## 7.2. Antes de empezar

1. **Arranca el programa** con el hardware conectado (capítulo 4). Con `--demo` funciona con señales simuladas.
2. **Valores por defecto** (se recuerdan entre sesiones):

| Control | Por defecto |
|---|---|
| **Gain Ch2** | 0 dB |
| **Voltage** | 20 |
| **RecLen** | 16384 |
| **Bits/sample** | 10 bit (también 8 o 12) |
| Excitación | Pulso a 10 MHz |
| **N avg** | 20 (capturas promediadas por señal) |
| Puerto del Arduino | COM4 |
| **T manual (°C)** | 20,0 |

3. **Región Smin–Smax** (capítulo 5): déjala sobre el eco que se usa para medir el nivel.
4. **Descriptor de la muestra.** Rellena los datos de la pieza (composición, letra, ciclo…); con ellos se forma el nombre de la carpeta (capítulo 11). El campo **Additive** viene en «PG».

### Cómo elegir ganancia, tensión y región

No hay valores fijos: se eligen **mirando la señal**, y hay que repetirlo si cambias de transductor o de excitación.

- **Ganancia y tensión:** las justas para que haya **señal suficiente** y el **eco sea claro**, sin llegar al fondo de escala. Parte de los valores por defecto y ajústalos viendo el eco del nivel del agua.
- **Región Smin–Smax:** debe dejar **margen para que el eco aparezca una vez introducida la muestra**, porque el nivel sube y el eco se desplaza. Comprueba que, con la muestra sumergida, el eco sigue dentro de la región y bien separado de los bordes.
- **Frecuencia y excitación:** tenlas en cuenta en todo lo anterior. Un transductor de otra frecuencia, o una excitación distinta (pulso, burst, chirp), cambia la amplitud y la duración del eco. Ajusta la excitación a la frecuencia del transductor usado.

## 7.3. Temperatura y c_w

La temperatura se puede introducir de dos formas:

- **T manual (°C)**: escribe el valor y pulsa Enter.
- **Read from Arduino**: lee las sondas PT100 y calcula c_w con ellas.

Junto a los campos aparece siempre el **T y el c_w que se usarán en el cálculo y de dónde salen**: `(default)`, `(manual)` o `(Arduino)`. Si el campo está vacío o no es un número, se conserva el valor anterior y la etiqueta lo avisa en naranja. En todos los casos, c_w se calcula con el mismo modelo que el resto de ECOS (`water_temp2sos`).

> **Dos lecturas, una media.** Al adquirir **sW1** y al adquirir **sW2** el programa lee la temperatura automáticamente (con las sondas si hay Arduino; si no, con el valor del campo **T manual**) y debajo de T y c_w muestra **las dos lecturas y su media**. Pero el cálculo usa **un único c_w, el del campo T y c_w**, no el de las lecturas: si quieres usar la media, **escríbela en T manual antes de Compute && Save**. La media corrige el factor c_w, pero **no elimina el efecto de un cambio real de temperatura entre las dos señales**: eso solo se evita con la muestra atemperada y el agua estable.

**Límite aceptable: que las dos temperaturas no difieran más de 0,1 °C.** Si difieren más, aparece un **aviso naranja** (no bloquea): repite la medida tras esperar a que el agua se estabilice.

> **De dónde sale el 0,1 °C.** Con una muestra de unos 3 × 30 × 30 mm (2,7 cm³) y una columna de 4 a 5 cm de diámetro, el nivel sube de 1,4 a 2,2 mm. Cerca de 23 °C, c_w cambia un 0,19 % por kelvin, y ese cambio se mezcla con el nivel en todo el camino hasta la superficie: con un camino de 5 a 10 cm, 0,1 °C equivalen a 9–18 µm de nivel aparente, entre el 0,4 y el 1,3 % de la subida, y el mismo porcentaje pasa a la densidad. Además, las PT100 tienen una resolución de unos 0,03 °C y un ruido de unos 0,05 °C, así que no tiene sentido exigir menos. Si cambia la geometría (otra muestra, otra columna u otro camino), el límite se recalcula igual.

> **Si el Arduino no responde**, aparece un mensaje y T y c_w no cambian. La lectura abre y cierra el puerto en cada pulsación, así que se puede repetir.

## 7.4. Calibrar el radio del vaso

El radio se puede medir con un calibre y escribirlo a mano, o **calibrarlo** con un objeto de volumen conocido. Calibrar es lo recomendable, porque absorbe errores de forma del vaso.

1. Escribe el volumen del objeto en **V_cal** y el número de repeticiones en **N_cal** (3 por defecto).
2. Pulsa **Calibrate vessel**. Aparecen dos diálogos: primero **vaso vacío** (solo agua) y después **objeto sumergido**. En cada uno se promedian **N_cal** capturas.
3. El programa calcula el radio con r = √(V_cal / (π · Δh)) y lo muestra.
4. Pulsa **Use this value →** para copiarlo a **r_vessel**.

> **La calibración no se puede cancelar una vez empezada**, y promedia las capturas aunque sean cero sin descartarlas. Comprueba que la señal es buena antes de lanzarla.

## 7.5. Medir una muestra

| Paso | Control | Qué hace |
|---|---|---|
| 1 | **T manual** o **Read from Arduino** | Fija T y c_w (apartado 7.3) |
| 2 | **r_vessel (cm)** y **Mass (g)** | Entrada manual del radio (o el calibrado) y de la masa |
| 3 | **Acquire sW1 (reference)** | Lee la temperatura y promedia **N avg** capturas del vaso **sin la muestra** |
| 4 | **Acquire sW2 (sample submerged)** | Lo mismo con la **muestra sumergida** |
| 5 | **Compute && Save** | Calcula, muestra el resultado y pide la carpeta |

> **Con el Arduino conectado, cada adquisición tarda unos 2 s más**, porque la placa se reinicia al abrir el puerto. Si la adquisición se cancela o falla, no se guarda la lectura de temperatura.

**Si la adquisición no encuentra capturas válidas**, el programa se detiene tras un máximo de **4 × N** intentos y avisa de cuántas capturas válidas ha obtenido. Si tarda más de medio segundo aparece un diálogo con **Cancel**; si cancelas, no se guarda nada.

Sin masa, el programa calcula el volumen y guarda la densidad como `null`.

*[Pendiente: describir qué hay que hacer físicamente entre sW1 y sW2 (esperar a que el nivel se estabilice, sin burbujas, mismo nivel de partida) una vez confirmado el procedimiento.]*

## 7.6. Qué se guarda

En la carpeta que eliges se crea una subcarpeta `PVA_…_DENS_<fecha y hora>` con:

| Fichero | Contenido |
|---|---|
| `density.json` | Resultado, parámetros y datos de la pieza. `r_vessel_cm` y `mass_g` se guardan como texto. Incluye las dos lecturas de temperatura (`temperature_sW1`, `temperature_sW2`, cada una con T1, T2, c_w, hora y origen) y el modelo de c_w (`cw_model`). `T_C` y `cw_ms` son los valores usados en el cálculo |
| `sW1.npy`, `sW2.npy` | Las dos señales promediadas |

> **Limitaciones del formato actual.** El fichero de densidad **no lleva versión de esquema** y **no guarda Smin, Smax ni la resolución del ADC**, así que no se puede saber a posteriori si hubo saturación. El formato único en enteros (capítulo 11) lo resolverá.

La densidad que se obtiene aquí es la **medida directa**. El análisis (capítulo 12) puede aplicar una recalibración del radio sobre un conjunto de piezas; esa recalibración **no es una medida** y se explica allí.

## 7.7. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| La densidad sale con un c_w de 1480 m/s | Versión antigua: no se aplicaba la temperatura restaurada de la sesión | Actualiza el programa. En la versión actual, c_w y su origen se ven junto a T |
| «Read from Arduino» falla la segunda vez | Puerto ocupado (versión antigua) | Actualiza el programa |
| La adquisición no termina | Capturas a cero | Comprueba el transductor y la ganancia; en la versión actual se detiene a los 4 × N intentos |
| Densidad muy distinta de la esperada | Radio del vaso mal medido o temperatura distinta entre sW1 y sW2 | Calibra el radio y comprueba la temperatura |
| El programa se cierra al arrancar en 64 bits | `density_gui` no protege el arranque sin hardware en 64 bits | Usa `--demo` o el entorno de 32 bits |

*[Pendiente: añadir las entradas que surjan al probar con hardware.]*
