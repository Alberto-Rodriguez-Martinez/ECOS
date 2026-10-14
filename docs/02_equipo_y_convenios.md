# 2. El equipo y los convenios

*[Pendiente: esquema general del montaje (figura 2.1): PC, pulser/receiver, transductores PE y TT enfrentados, muestra en el escáner, vasija, sondas de temperatura.]*

Este capítulo describe qué hay en el montaje de ECOS, qué papel tiene cada elemento y qué convenios de nombres, signos y unidades usa el resto del manual. Los capítulos siguientes lo dan por sabido.

## 2.1. Visión general

| Elemento | Para qué sirve | Capítulo |
|---|---|---|
| **Pulser/receiver de dos canales** | Genera el pulso y digitaliza las señales. Su forma de onda es programable | 5 |
| **Transductor PE** | Emite y recibe: da los ecos de la muestra (pulso-eco) | 5, 6 |
| **Transductor TT** | Enfrentado al PE: recibe lo que atraviesa la muestra (transmisión) | 5, 6 |
| **Vasija con agua** | Medio de acoplamiento. Contiene los transductores y la muestra | 2.4 |
| **Sondas PT100 (T1 y T2) y Arduino** | Miden la temperatura del agua, de la que sale c_w | 2.5 |
| **Escáner XYZ + R** | Mueve la muestra entre los transductores para foco, planitud y barridos | 8 |
| **PC con ECOS** | Controla todo, guarda los datos y los analiza | 4 |

La **medida de punto** (capítulo 6) y la **densidad** (capítulo 7) no necesitan el escáner. Los **barridos** (capítulo 10) sí.

## 2.2. El pulser/receiver

Es un equipo de **dos canales**, con forma de onda de excitación programable y buena resolución temporal. Se controla desde ECOS (pestaña **Acquisition**, capítulo 5).

| Canal | Qué recibe |
|---|---|
| **Ch1** | Transmisión: **TT** y **WP** (transductor TT) |
| **Ch2** | Pulso-eco: **PE** (transductor PE) |

- Los valores por defecto del programa son **65 dB** en Ch1, **35 dB** en Ch2, **50 V** de tensión y **16384** muestras de registro.
- La excitación (pulso, burst o chirp) y su frecuencia se ajustan **a la frecuencia central del transductor** que se use (capítulo 5).

*[Pendiente: modelo y fabricante del pulser/receiver, frecuencia de muestreo, ancho de banda y tensión máxima.]*

> **Un fallo conocido del firmware del equipo:** cada cambio de ganancia del Ch1 reinicia la del Ch2. El programa vuelve a aplicar la del Ch2 después; hay que tenerlo en cuenta si se usa la librería sin la interfaz (capítulo 15).

## 2.3. Los transductores

El laboratorio dispone de transductores de **5 MHz** y de **10 MHz**, cada uno **enfocado** y **no enfocado**. El rango de 5 a 10 MHz es el que se explota.

- Cada transductor tiene un **papel fijo**: uno hace siempre de PE y otro de TT. En la interfaz hay dos campos, **Transducer PE** y **Transducer TT**, donde se escribe la identificación (modelo y frecuencia, por ejemplo). Se guardan con cada medida (capítulos 6 y 11).
- Para el **método de tres señales** los dos transductores deben estar **enfrentados y alineados** con la muestra en medio (capítulo 3).
- Con un transductor **enfocado** hay que buscar el foco antes de barrer (capítulo 9).
*[Pendiente: qué transductor (enfocado o no, 5 o 10 MHz) hace de PE y cuál de TT.]*

*[Pendiente: tabla con modelo, fabricante, frecuencia central, diámetro del elemento, distancia focal (los enfocados) y ancho de banda de cada transductor disponible.]*

## 2.4. Las vasijas

| Vasija | Contenido | Uso |
|---|---|---|
| **Pequeña** | Transductores enfrentados y giróscopo para alinearlos | *[Pendiente: uso]* |
| **Grande** | Escáner XYZ + giro y dos transductores enfrentados | Barridos y mapeo 2D de piezas |

> **El control de temperatura no forma parte de las vasijas.** Es un equipo externo que se añade a cualquiera de ellas (también al escáner) y que puede estar o no. Todo funciona sin él; en ese caso la temperatura del agua es la que haya y se mide con las sondas (apartado 2.5), o se escribe a mano.

La **densidad** (capítulo 7) se mide en un vaso aparte, con una columna de agua cuyo radio se calibra.

*[Pendiente: dimensiones y volumen de las vasijas; cuál se usa para cada capítulo; si el giróscopo sustituye al eje R cuando llegue.]*

## 2.5. La medida de temperatura

La temperatura del agua determina **c_w**, que entra directamente en el espesor y en la velocidad (capítulo 3). Se mide con **dos sondas PT100 de cuatro hilos**, **T1** y **T2**, leídas por un **Arduino** con convertidores **MAX31865**.

- **Comunicación:** puerto serie (por defecto **COM3**). El firmware del Arduino debe ser el de **115200 baudios**; el antiguo de 9600 no es compatible. Con el puerto cerrado la placa se reinicia al abrirlo, y por eso la lectura tarda unos 2 s.
- **Resolución y ruido:** unos **0,03 °C** de resolución y unos **0,05 °C** de ruido por sonda.
- **Qué temperatura se usa:** la media de T1 y T2. En las medidas de punto y de densidad se lee en cada botón de adquisición; en los barridos se registra una serie durante el barrido (capítulo 10).
- **c_w:** se calcula siempre con el mismo modelo del programa (`water_temp2sos`), en cualquier medida. Si el Arduino no responde, la temperatura puede escribirse a mano.

> **Por qué importa tanto.** Cerca de 23 °C, c_w cambia un 0,19 % por kelvin, y una diferencia de 0,1 °C entre TT y WP ya desplaza el espesor en unas 22 µm para una muestra de 3 mm (capítulo 13).

*[Pendiente: dónde está cada sonda en el montaje (T1, T2), clase de las PT100 (A, B, 1/3 DIN) y calibración, si se ha hecho.]*

## 2.6. El escáner

Mueve la **muestra** (no los transductores) en cuatro ejes: **X**, **Y**, **Z** y **R**. Se explica en el capítulo 8. Aquí solo los convenios que el resto del manual da por sabidos.

## 2.7. Convenios

### Señales y canales

| Nombre | Qué es | Canal |
|---|---|---|
| **PE** | Pulso-eco con la muestra | Ch2 |
| **TT** | Transmisión a través de la muestra | Ch1 |
| **WP** | Camino en agua, sin muestra | Ch1 |

En el código y en las pantallas aparecen como `s_PE`, `s_TT` y `s_WP` (o `s_W` en algunos botones). El manual usa **PE**, **TT** y **WP**.

### Magnitudes y unidades

| Símbolo | Qué es | Unidad |
|---|---|---|
| **c_w** | Velocidad del sonido en el agua | m/s |
| **Cl** | Velocidad longitudinal en la muestra | m/s |
| **L** o **d** | Espesor de la muestra | mm en pantalla; m en `results.json` |
| **T** | Temperatura | °C |
| **ρ** | Densidad | g/cm³ |

> En pantalla el espesor aparece como **d**; en las ecuaciones del manual, como **L**. Son la misma magnitud.

### Ejes del escáner

- **X, Y:** positivo es el sentido en que crece el contador.
- **Z:** **positivo hacia abajo**. Z = 0 es la altura segura, arriba.
- **R:** rotación, de 1,8° por paso.
- **Eje del haz** y **eje lateral:** son papeles; qué eje físico hace cada uno se define al iniciar la sesión (capítulo 8). **PE side** indica en qué extremo del eje del haz está el transductor PE.

Los detalles (signos, límites, origen, PE side) están en el apartado 8.3.

*[Pendiente: esquema de ejes sobre el montaje real (figura 2.2).]*
