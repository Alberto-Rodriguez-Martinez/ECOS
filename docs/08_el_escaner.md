# 8. El escáner

*[Pendiente: captura de la subpestaña **Motion** con los bloques numerados y esquema de los ejes sobre el montaje (eje del haz, eje lateral, Z y R).]*

El escáner mueve la muestra respecto a los transductores en cuatro ejes: **X**, **Y**, **Z** y **R** (rotación). Se controla desde la pestaña del escáner de ECOS, que tiene tres subpestañas: **Motion** (este capítulo), **Calibration** (foco, planitud y estabilidad, capítulo 9) y **Scans** (barridos, capítulo 10). Sobre la pantalla siempre están visibles la **posición**, el botón **STOP** y el **estado**.

> **Los ejes se nombran por su papel, no por su letra.** «Eje del haz» y «eje lateral» son papeles; qué eje físico hace cada uno se define al iniciar la sesión (**Beam axis**). No des por hecho que el eje del haz es siempre Y.

## 8.1. Conectar

El escáner se conecta por puerto serie.

| Control | Qué hace |
|---|---|
| **Puerto** | Puerto COM del controlador |
| **↺** | Vuelve a buscar los puertos disponibles |
| **Connect** / **Disconnect** | Abre y cierra la conexión |

Al conectar, el programa lee los límites del controlador y comprueba si los ha perdido (porque se cortó la tensión). Si es así, lo avisa y ofrece **reenviar los de la sesión**. **Mientras no aceptes los avisos que salen al conectar, los controles de sesión (apartado 8.2) y los de movimiento permanecen desactivados.** Un corte de tensión con la sesión ya conectada **no se detecta**: después de un corte, desconecta y vuelve a conectar.

> Para probar sin el equipo, arranca ECOS con `--scanner-sim`: usa un escáner simulado y su propio archivo de sesión (capítulo 4).

## 8.2. La sesión

Antes de mover nada hay que **iniciar la sesión**: decir al programa qué eje es cada cosa, dónde están los límites y dónde está el cero.

| Control | Qué hace | Por defecto |
|---|---|---|
| **Beam axis** | Eje físico (X o Y) que hace de haz; el otro es el lateral. Reetiqueta las filas y reparte límites, pasos y velocidades por eje físico | Y |
| **PE side** | **En qué extremo del recorrido del eje del haz está el transductor de pulso-eco**, es decir, desde dónde sale el haz hacia la muestra: **Origin** (extremo de valores bajos del contador) o **Max** (extremo de valores altos). Solo cambia el sentido en que se predice que se mueve el eco al desplazar la muestra en el foco (apartado 8.3) | Max |
| **Limit** (con **Apply**) | Recorrido máximo permitido de cada eje. Escribe el máximo del eje y pulsa **Apply**: envía el límite al controlador y relee los cuatro. **Si el eje está ahora por encima del nuevo límite, el programa no lo envía y avisa**: muévelo antes | X 110, Y 110, Z 60 mm; R 360° |
| **Zero** / **Zero all** | Redefinen la posición actual de un eje, o de los cuatro, como 0. **No mueven nada** y no piden confirmación | — |
| **Apply speeds** | Envía la velocidad de X, Y y Z | 100 |
| **Reread limits** | Vuelve a leer los límites del controlador | — |
| **Save session** / **Load session** | Guardan y cargan los ajustes de la sesión | — |

La sesión se guarda en un archivo (`scanner_session.json`) y se restaura al volver a abrir el programa. Si el archivo está dañado, el programa **lo copia a un `.bak`, usa los valores por defecto y avisa** en la etiqueta de la conexión y, dentro de ECOS, en la barra de estado. **Load session** con un archivo dañado muestra el aviso y conserva los valores en uso.

> **Los límites son el seguro del montaje.** Cada destino se comprueba contra ellos **antes** de enviarse, y el controlador además rechaza lo que se salga. Ajústalos al espacio libre real alrededor de la muestra y de los transductores, no al máximo mecánico.

> **Zero cambia la ventana física permitida.** El controlador compara los destinos con `[0, límite]` en su propio contador. Al redefinir el cero, el número del límite no cambia, pero la zona física permitida se desplaza con él. Vuelve a comprobar los límites después de usar **Zero**.

**Velocidades.** Son un parámetro del firmware, no mm/s: con 100, el eje X se mueve a unos 6,7 mm/s. Cada valor tiene que estar entre 1 y 65536; si alguno no lo está, no se envía ninguno. **R no tiene velocidad configurable** (la orden no tiene efecto sobre él).

*[Pendiente: relación entre el parámetro de velocidad y los mm/s en Y y Z; solo está medido X.]*

## 8.3. Mover

| Control | Qué hace | Por defecto |
|---|---|---|
| **− / +** (X, Y, Z) | Mueve el eje un paso (campo **Jog**, leído al pulsar), calculado como destino absoluto: posición actual ± paso. Antes se comprueba que el destino cabe en `[0, límite]` | X e Y 1 mm, Z 0,5 mm |
| **− / +** (R) | Mueve R un paso relativo, redondeado a un múltiplo de 1,8° (con aviso). Comprueba `posición + paso` en `[0, límite]` de forma lineal | 1,8° |
| **Go** (X, Y, Z) | Mueve el eje a la posición escrita, **absoluta** en coordenadas de sesión (respecto al cero fijado). Valida `[0, límite]`; el controlador también rechaza lo que se salga | — |
| **Go** (R) | Normaliza el destino a [0, 360) y a múltiplos de 1,8°, y gira por el **camino más corto**. **No valida contra el límite de R** | — |
| **Go to origin (R, Z, X, Y)** | Pide confirmación y lleva a 0 los ejes que no lo estén, **uno tras otro, en el orden fijo R, Z, X, Y**, sea cual sea el eje del haz. STOP corta toda la secuencia | — |

**Por qué ese orden.** Z = 0 es la altura segura, arriba (Z positivo va hacia abajo). Se sube Z antes de los movimientos horizontales para no arrastrar la muestra contra los transductores, y R se lleva al origen antes de nada.

### Movimiento libre y rotación paso a paso

| Control | Qué hace |
|---|---|
| **Free movement (no limits)** | Tras confirmar, **− / +** usan un movimiento relativo que salta la protección del controlador y la comprobación de la GUI. Desactiva **Go** y **Go to origin**, bloquea los barridos y las herramientas, y muestra un aviso visible. **STOP sigue activo**. Al salir del modo, si algún eje queda fuera de `[0, límite]`, ofrece **Zero here**, **Keep position** o **Stay in free movement** |
| **Move R step by step** | Marcado por defecto. Trocea cada movimiento de R en órdenes sueltas de 1,8° con una pausa entre ellas (**Pause between R steps (ms)**, 100 por defecto, de 0 a 2000). Un giro continuo largo **pierde pasos con el portamuestras montado**; las órdenes sueltas no. Al bajar de 0, el programa redefine antes el contador a una vuelta, porque el controlador no deja cruzar 0 hacia abajo |

> **El movimiento libre desactiva la protección de los límites.** Nada en **− / +** comprueba el recorrido. Úsalo solo si sabes que el camino está libre y desmárcalo en cuanto termines.

> **Desmarca «Move R step by step» solo sin portamuestras.** Con el portamuestras montado, un giro continuo pierde pasos y la posición de R deja de ser fiable.

> **Límite de R.** El contador de R es circular (0–360°), así que un límite de 360° o más no tiene efecto práctico. No pongas un límite de R menor que una vuelta: el controlador rechazaría pasos y el cruce de 0 hacia abajo dejaría de funcionar. **Apply** no comprueba R.

*[Pendiente de laboratorio: confirmar con el firmware real el paso de 199 a 200 pasos con el límite de R en 360°.]*

### Convenio de ejes y de signos

- **X e Y:** positivo es el sentido en que crece el contador. Resolución: 0,01 mm por paso.
- **Z:** **positivo es hacia abajo**. Z = 0 es la altura segura, arriba. Resolución: 0,005 mm por paso.
- **R:** 1,8° por paso, 200 pasos por vuelta. El contador es circular hacia arriba y el controlador no deja cruzar 0 hacia abajo (por eso el programa redefine el contador en esos casos).
- **Eje del haz y PE side.** Con **Max** (el valor por defecto, y el del montaje habitual), mover la muestra hacia + en el eje del haz la **acerca** al transductor PE y el tiempo de vuelo del eco frontal disminuye. Con **Origin** ocurre lo contrario: el + la aleja y el tiempo de vuelo crece. **PE side** solo afecta al foco; **no afecta** a la planitud ni a los barridos, que mueven el eje lateral y Z, no el del haz.
- **Planitud:** θ > 0 cuando la cara se aleja del PE al crecer el contador lateral (o Z). No depende de PE side.

*[Pendiente: en qué sentido físico gira R con valores positivos; no consta en ningún documento.]*

## 8.4. Seguridad

- **STOP** detiene el escáner de inmediato, en seco, y deja el contador en la posición real. Escribe la orden de parada **directamente** por el puerto, sin pasar por la cola de órdenes, así que interrumpe un movimiento en curso. Aborta cualquier secuencia en marcha (foco, planitud, estabilidad, barrido o **Go to origin**) y relee la posición. Está siempre visible y siempre activo.
- **Límites.** Véase 8.2.
- **Fallo del puerto serie.** Si falla la comunicación a mitad de un movimiento, la secuencia en marcha termina con el mensaje «The scanner did not reach the requested position.». El escáner **no se desconecta por sí solo**: comprueba el cable y el estado antes de seguir. Un movimiento que tarda más de 120 s se interrumpe con un error.
- **Corte de tensión.** El controlador conserva la posición, pero los límites vuelven a su valor de fábrica. Se detecta al conectar (apartado 8.1).

## 8.5. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Los controles de sesión o de movimiento están desactivados | No has aceptado los avisos de la conexión, hay un movimiento en curso o hay una secuencia activa | Acepta los avisos; espera a que termine o pulsa STOP |
| Un movimiento se rechaza («out of range») | El destino sale de `[0, límite]` | Comprueba los límites y la posición actual |
| «The scanner did not reach the requested position.» | Fallo de comunicación o límite del controlador | Comprueba el cable y los límites; vuelve a conectar |
| Tras un corte de tensión, el escáner rechaza movimientos que antes aceptaba | El controlador recuperó sus límites de fábrica | Desconecta, conecta y acepta reenviar los límites |
| Aviso al abrir de que la sesión no se pudo leer | Archivo de sesión dañado | Se ha guardado una copia `.bak`; revisa los valores por defecto aplicados |
| Tras usar **Zero**, un movimiento que antes cabía se rechaza | La ventana física permitida se desplazó con el nuevo cero | Vuelve a comprobar los límites |
| La posición de R se pierde tras girar | Giro continuo con el portamuestras montado | Activa **Move R step by step** |
| Nada se mueve en modo simulador | Estás en `--scanner-sim` o `--demo` | Arranca sin esos argumentos |

*[Pendiente: añadir las entradas que surjan al probar con hardware.]*
