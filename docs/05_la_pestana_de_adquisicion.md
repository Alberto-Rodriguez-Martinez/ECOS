# 5. La pestaña de adquisición

*[Pendiente: captura de la pestaña **Acquisition** con los bloques numerados (excitación, ganancias y registro, ventana Smin–Smax, gráficas, resultados).]*

La pestaña **Acquisition** es donde se configura el equipo y se adquieren las señales. Este capítulo explica **cada control y su efecto**; el flujo completo de una medida está en el capítulo 6 (punto) y los barridos usan los mismos parámetros comunes (capítulos 9 y 10). La densidad tiene su propia ventana, con controles parecidos (capítulo 7).

> **Los valores por defecto son un punto de partida, no una receta.** Ganancias, tensión, excitación y región dependen del transductor y de la muestra. Se ajustan **mirando la señal** (apartado 5.6).

## 5.1. Excitación

| Control | Por defecto | Qué hace |
|---|---|---|
| **Excitation** | Pulse | Forma de la señal que emite el pulser: **Pulse** (frecuencia, 5 MHz, bipolar), **Chirp** (de 2 a 15 MHz, 3 µs) o **Burst** (5 ciclos a 10 MHz) |
| **Generator Fs** | 200 MHz | Reloj del generador de la excitación |
| **Generate && Upload** | — | Calcula la señal y la **carga en el equipo**. Hay que pulsarlo cada vez que cambias la excitación |

- La frecuencia de la excitación debe estar en la **frecuencia central del transductor** que uses.
- La forma cambia la **duración del eco**: un pulso corto da ecos breves, un burst o un chirp los alargan. Eso condiciona la ventana de análisis (apartado 6.4).

*[Pendiente: parámetros editables de cada tipo de excitación y su rango.]*

## 5.2. Ganancias, tensión y registro

| Control | Por defecto | Qué hace |
|---|---|---|
| **Gain Ch1 (dB)** | 65 | Ganancia del canal de transmisión (TT y WP) |
| **Gain Ch2 (dB)** | 35 | Ganancia del canal de pulso-eco (PE) |
| **Voltage** | 50 V | Tensión de excitación del pulser |
| **RecLen** | 16384 | Longitud del registro en muestras. Al cambiarla se ajusta la región (apartado 5.3) |
| Frecuencia de muestreo del registro | 100 MHz | Una muestra cada 10 ns. Es distinta del reloj del generador (**Generator Fs**, 200 MHz) |
| **RELAY** | ON | Relé del pulser. El programa lo pone en ON al arrancar |
| **Averages (N)** | 25 | Capturas que se **promedian** en cada señal; se guarda con la sesión |

- Las ganancias se escriben como enteros y no tienen rango comprobado: **el programa no avisa si te pasas**.
- Al cambiar la ganancia del Ch1 el equipo reinicia la del Ch2 (apartado 2.2); el programa la reaplica.
- En el escáner los promedios son otros: foco y planitud 100, barrido 20 y estabilidad 20.
- El refresco en vivo hace **una captura cada 34 ms**.

## 5.3. La región Smin–Smax

Es el **tramo del registro** que se adquiere, se guarda y se analiza. Todo lo que queda fuera se descarta.

- Por defecto es de **0 a RecLen ÷ 4**.
- Debe tener **al menos 16 muestras**; con menos no se guarda la sesión.
- **Déjala sobre los ecos que vas a usar**, con margen a ambos lados. Si un eco queda pegado a un borde, la medida se marca como **ventana estrecha** (capítulo 13).
- La saturación solo se vigila **dentro** de la región (apartado 5.5).

**Cómo se fija.** De dos formas:

- **Escribiendo** los valores en los campos **Smin** y **Smax** de la pestaña. Por defecto se expresan en **muestras** del registro; el control **X-axis** (apartado 5.4) cambia el dominio.
- **Con el ratón** sobre la **gráfica inferior**, que muestra **todo el registro**. La región aparece **sombreada**:
  - **Arrastrando el interior** de la zona sombreada se **desplaza entera**, con el mismo ancho.
  - **Arrastrando un borde** se cambia solo el **inicio** o el **final**.

*[Pendiente: si los campos Smin y Smax pasan a µs o mm al cambiar **X-axis**, o siempre quedan en muestras; y si se actualizan al arrastrar con el ratón.]*

> No confundir con la **ventana de análisis** (**Window length**), que se aplica después a cada eco dentro de la región. Véase 6.4.

## 5.4. Las gráficas

| Control | Por defecto | Qué hace |
|---|---|---|
| **Show Ch1 (TT)** / **Show Ch2 (PE)** | Marcados | Qué canales se dibujan |
| **X-axis** (control en la parte superior de la pantalla) | samples | Cambia el **dominio** del eje horizontal: **muestras**, **tiempo (µs)** o **distancia (mm)**. En mm se usa el c_w de la última lectura; sin lectura, **1480 m/s** |
| **Retake c_w** | — | Relacionado con el c_w que usa el eje en mm *[pendiente: efecto exacto]* |
| **Cursor** | Marcado | Cruz con la lectura de cada punto |
| **Full scale** | Marcado | Líneas a ±0,5 del fondo de escala |

*[Pendiente: escala vertical de la gráfica.]*

## 5.5. Saturación

Junto a cada canal aparece, en rojo, **SATURATED: n samples…** cuando hay muestras en el fondo de escala **dentro de la región Smin–Smax**. Una señal saturada falsea el tiempo de vuelo.

- Si aparece, **baja la tensión o la ganancia** del canal hasta que desaparezca.
- Las líneas de **Full scale** ayudan a ver cuánto margen queda.

*[Pendiente: umbral exacto a partir del cual una muestra cuenta como saturada.]*

## 5.6. Cómo elegir ganancia, tensión y región

No hay valores fijos: se repiten **cada vez que cambias de transductor, de muestra o de excitación**.

> **Ajusta pensando en todo el análisis, no en la primera captura.** Si la pieza se **mueve** (barridos, foco, planitud), se **gira** o simplemente se **recoloca**, el nivel de la señal puede **cambiar de forma significativa**: varía la distancia al transductor, la inclinación de la cara o la zona de la muestra que se ilumina. Antes de empezar, ten claro **qué va a pasar durante toda la medida** (qué ejes se moverán y cuánto) y elige ganancia y tensión para que **no se sature en ninguna etapa**, si es posible. Una señal saturada en un solo punto falsea el tiempo de vuelo de ese punto. Por eso conviene probar los **extremos del recorrido** antes de lanzar la medida larga.

1. **Tensión.** Empieza baja y sube solo si hace falta.
2. **Ganancia.** Las justas para que el eco sea claro, sin llegar al fondo de escala.
3. **Región.** Que contenga los ecos que usarás y deje margen a los lados; comprueba que el eco no se pega a un borde.
4. **Promedios.** Más promedios reducen el ruido y alargan la adquisición.

## 5.7. Otros campos

| Control | Qué hace |
|---|---|
| **Arduino COM** | Puerto de las sondas de temperatura. Por defecto **COM3** (apartado 2.5) |
| **T1 / T2 probe** (identificación, posición, clase) | Metadatos de las sondas; se guardan en los barridos |
| **Transducer PE** / **Transducer TT** | Identificación de los transductores; se guardan con la medida de punto y los barridos |
| Descriptor de la muestra | Datos de la muestra que dan nombre a la carpeta de la medida (capítulo 11) *[pendiente: lista de campos]* |

## 5.8. La sesión de la pestaña

El programa **guarda en `ecos_gui_session.json`** (carpeta `acquisition/`, fuera de git) los ajustes de esta pestaña: ganancias, tensión, RecLen, relé, región Smin–Smax, excitación, puerto del Arduino, promedios, ventana, descriptor, sondas y transductores. Se restauran al arrancar. Con `--demo` y con `--scanner-sim` se usan ficheros de sesión propios. Si el fichero está dañado, el programa lo avisa, conserva una copia `.bak` y arranca con los valores por defecto.
