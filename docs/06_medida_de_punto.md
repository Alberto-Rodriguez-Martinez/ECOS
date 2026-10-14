# 6. Medida de punto

*[Pendiente: captura de la pestaña **Acquisition** con los bloques numerados (excitación, adquisición, ventana, resultados).]*

La medida de punto da la **velocidad longitudinal (Cl)** y el **espesor (L)** de una muestra en un solo punto, con el método de tres señales (capítulo 3). Se hace en la pestaña **Acquisition** y no necesita el escáner: la muestra se coloca a mano entre los dos transductores.

> **Qué hace falta para que salga un resultado**
> Las tres señales (**PE**, **TT** y **WP**), una temperatura del agua (de las sondas o escrita a mano) y la ventana de análisis puesta. Sin alguna de ellas, **Apply window** no calcula y lo dice.

## 6.1. Las tres señales

| Señal | Qué es | Canal |
|---|---|---|
| **PE** | Pulso-eco: el eco que vuelve a la cara frontal y a la trasera de la muestra | Ch2 |
| **TT** | Transmisión: el pulso que atraviesa la muestra y llega al otro transductor | Ch1 |
| **WP** | Camino en agua: el pulso entre los dos transductores **sin la muestra** | Ch1 |

El espesor sale de los tiempos de vuelo de las tres. La exactitud depende sobre todo de dos cosas: el **c_w** del agua, que se calcula con la temperatura, y que el agua tenga la **misma temperatura** al medir TT y WP (apartado 6.6).

## 6.2. Antes de empezar

1. **Arranca la aplicación** con el hardware conectado (capítulo 4). Con `--demo` la medida funciona con una señal simulada y da siempre el mismo resultado, y **no guarda** nada.
2. **Pulso.** Pulsa **Generate && Upload** para cargar la excitación en el equipo. Por defecto es un pulso de 5 MHz, pero **la frecuencia y la excitación adecuadas dependen del transductor que uses**: ajústalas a su frecuencia central.
3. **Ganancias y registro.** Los valores por defecto del programa son **65 dB** en Ch1, **35 dB** en Ch2, tensión de **50 V** y longitud de registro de 16384 muestras. **Empieza con una tensión baja** y sube solo si la señal lo necesita. Ajusta ganancias y tensión para que los ecos se vean bien y **no lleguen al fondo de escala** (apartado 6.6).
4. **Ventana Smin–Smax** (capítulo 5): déjala sobre los ecos que vas a usar.
5. **Transductores.** Rellena **Transducer PE** y **Transducer TT** con la identificación de los dos transductores que usas (modelo y frecuencia, por ejemplo). Son los mismos campos que usan los barridos y se guardan con la medida. Si los dejas vacíos, se guardan vacíos.
6. **Sonda de temperatura.** El puerto del Arduino por defecto es **COM3**. Si no responde, el programa te pide la temperatura a mano.
7. **Promedios.** **Averages (N)** viene en **25**. Es el número de capturas que se promedian en cada señal.

> **La temperatura se lee en cada botón de adquisición.** Cada vez que adquieres PE+TT o WP, el programa lee la temperatura de nuevo. Las dos lecturas se guardan por separado (apartado 6.5).

## 6.3. Paso a paso

| Paso | Botón | Qué hace | Qué deja listo |
|---|---|---|---|
| 1 | **Acquire s_PE + s_TT (sample, 0°)** | Lee la temperatura, promedia N capturas de Ch2 (PE) y de Ch1 (TT) y recorta a Smin–Smax | PE, TT y la primera lectura de temperatura |
| 2 | **Acquire s_W (WaterPath)** | **Con la muestra retirada del haz.** Lee de nuevo la temperatura y adquiere Ch1 | WP y la segunda lectura |
| 3 | **Preview window** | Abre una figura con las tres señales y la ventana. Es **bloqueante**: hay que cerrarla para seguir | Nada; sirve para comprobar |
| 4 | **Apply window** | Aplica la ventana y **calcula** Cl y L | Resultados en pantalla |
| 5 | **Compute && Save** | Pide una carpeta y **guarda** | Carpeta de la medida |

> **Aunque se llame «Compute && Save», no calcula.** Guarda lo que ya calculó **Apply window**. Si no has pulsado **Apply window**, el botón no está activo.

El botón **Acquire s_G (Angular / Shear)** está desactivado.

Si cancelas el diálogo de temperatura manual, la adquisición **no se hace** y el estado dice «NOT acquired: no temperature». Si cancelas el de la carpeta, dice «Not saved: no folder chosen».

## 6.4. La ventana de análisis

| Control | Por defecto | Qué hace |
|---|---|---|
| **Window length (samples)** | 200 | Longitud de la ventana que se aplica a cada eco, centrada en el máximo de la envolvente. La ventana es de tipo Tukey (α = 0,2) |
| **Show Ch1 (TT) / Show Ch2 (PE)** | Marcados | Qué canales se dibujan |
| **X-axis** | samples | Eje horizontal en muestras, µs o mm. En mm se usa el c_w de la última lectura |
| **Cursor** | Marcado | Cruz con la lectura de cada punto |
| **Full scale** | Marcado | Dibuja las líneas de ±0,5 de fondo de escala |

### Cómo elegir la longitud de la ventana

La longitud **no se fija con una fórmula: se decide mirando las señales** en **Preview window**. El criterio es doble:

- **Que el eco entre entero**, con su cola, y que los bordes de la ventana caigan en ruido. Una ventana corta recorta el pulso y cambia su forma, lo que falsea el tiempo de vuelo.
- **Que el eco quede aislado**: la ventana no debe incluir parte de otro eco (el segundo eco de PE, o el eco de las caras de la muestra en TT).

Cuánto dura un eco **depende del tipo de excitación y de la frecuencia**: un pulso corto dura pocos ciclos, un burst o un chirp duran más, y a frecuencia más baja el mismo número de ciclos ocupa más tiempo. Por eso hay que revisar la ventana cada vez que cambies de transductor o de excitación.

> **Un orden de magnitud, no una regla.** Con la frecuencia de muestreo de 100 MHz, un espesor de 3 mm en una muestra con velocidad cercana a 1540 m/s separa los dos primeros ecos de PE unos 4 µs, es decir, unas 390 muestras. La ventana de 200 muestras por defecto cabe con holgura. Si la muestra es más fina, la separación se reduce y puede que haya que acortar la ventana.

Comprueba el resultado en **Preview window** con las tres señales (PE, TT y WP) y repite el cálculo con una ventana algo mayor y otra algo menor. Si Cl y L cambian de forma apreciable, la ventana no está bien elegida.

## 6.5. Resultados y qué se guarda

**En pantalla:** **Cw** [m/s], **T1**, **T2**, **Cl** [m/s] y **d** [mm]. Una línea **Readings** muestra las dos lecturas de temperatura (PE+TT y WP).

**En disco**, en la carpeta que eliges:

| Fichero | Contenido |
|---|---|
| `results.json` | T1, T2, Cw1, Cw2, **Cw_mean**, **Cl** y **d** (en metros), más las dos lecturas de temperatura por separado (`temperature_pett`, `temperature_wp`) y de cuál sale el c_w (`cw_used_from`) |
| `meta.json` | Parámetros de la adquisición, los transductores (`transductor_pe`, `transductor_tt`) y las temperaturas (`temperatures`, con el modelo de c_w usado) |
| `signals/signals.npz` | Las señales **sin enventanar**, para poder recalcular |

El detalle de campos y versiones (esquema `raw-32-1.1`) está en el capítulo 11.

> **Qué c_w se usa en el cálculo**
> El de la **última lectura** de temperatura: la del último botón que hayas pulsado entre **Acquire s_PE + s_TT**, **Acquire s_W** y **Read from Arduino**. Se calcula con el modelo `water_temp2sos` como media de los valores de T1 y T2. Como las dos lecturas y las señales quedan guardadas, el análisis puede recalcular con otro criterio.

> **Identifica siempre los transductores.** El programa no rellena ni supone nada: lo que escribas en **Transducer PE** y **Transducer TT** es lo único que dice después con qué transductor se hizo la medida. Las medidas antiguas llevan el texto fijo «No enfocado 10MHz», que no es una identificación.

## 6.6. Comprobar que la medida es buena

- **Saturación.** Si algún canal llega al fondo de escala dentro de Smin–Smax, aparece en rojo **SATURATED: n samples…** junto a ese canal. Baja la ganancia y repite. Una señal saturada falsea el tiempo de vuelo.
- **Las dos temperaturas.** Si las medias de las dos lecturas difieren más de **0,1 °C**, aparece un aviso naranja en **Readings**. No bloquea, pero merece repetir: el método supone que el agua está a la misma temperatura en TT y en WP, y 0,1 °C de diferencia equivalen a unos 15 ns en el tiempo de vuelo a través de la muestra, es decir, unos 22 µm en un espesor de 3 mm.
- **Vista previa.** Mira siempre **Preview window** una vez: comprueba que la ventana contiene el eco entero y que WP no tiene eco de la muestra.
- **Repetir.** Para saber la dispersión de la medida, repite el ciclo completo (PE+TT, WP, **Apply window**) varias veces con la muestra recolocada.

> **Supuestos del método.** Incidencia normal, caras paralelas y velocidad independiente de la frecuencia. Si la muestra está inclinada o sus caras no son paralelas, el resultado de L y Cl tiene un error que esta medida no detecta. Para comprobarlo, usa la planitud del capítulo 9.

## 6.7. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| **Apply window** avisa de que falta c_w | No hay temperatura | Adquiere PE+TT con la sonda conectada o escribe la temperatura a mano |
| El estado dice «NOT acquired: no temperature» | Cancelaste el diálogo de temperatura manual | Vuelve a pulsar el botón y escribe un valor |
| La temperatura sale fija en todas las medidas | El Arduino no responde y se está usando una temperatura manual | Comprueba el puerto (por defecto COM3) |
| El resultado es siempre Cl = 1540 y L = 10 mm | Estás en modo `--demo` | Arranca con el hardware |
| El botón **Compute && Save** no se activa | No has pulsado **Apply window** | Hazlo primero |

*[Pendiente: añadir las entradas que surjan al probar con hardware.]*
