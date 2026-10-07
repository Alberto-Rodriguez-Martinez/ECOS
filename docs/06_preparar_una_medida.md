# 6. Preparar una medida

*[Pendiente: esquema del montaje —muestra colgada entre los dos transductores, goniómetro y platina de rotación por encima del agua— con leyenda numerada.]*

> **Los ejes se nombran por su papel, no por su letra.** «Eje del haz» y «eje lateral» son papeles; qué eje físico del escáner hace cada uno se define al iniciar la sesión. No des por hecho que el eje del haz es siempre Y.

Antes de medir una muestra hay que dejar el montaje en condiciones. Son tres herramientas, en la subpestaña **Calibration** del escáner, y conviene usarlas en este orden:

1. **Foco** — colocar la muestra a la distancia a la que el transductor concentra el haz.
2. **Planitud** — comprobar que la cara de la muestra está perpendicular al haz, y corregirla a mano si no lo está.
3. **Estabilidad** — comprobar que la muestra está quieta antes de empezar a medir.

Las tres miden e informan. **Ninguna corrige nada por su cuenta**: el foco mueve el escáner al óptimo si se lo pides, la planitud te dice qué girar y en qué sentido, y la estabilidad solo observa. Las correcciones de inclinación son manuales.

> **Antes de nada**
> El escáner tiene que estar conectado y con la sesión iniciada (capítulo 5), y la ventana de análisis **Smin–Smax** puesta sobre el eco de la cara frontal (capítulo 4). Las tres herramientas miden dentro de esa ventana y **ninguna la modifica**.

---

## 6.1. Foco

### Qué es y por qué importa

El transductor está enfocado: concentra la energía a una distancia determinada. En el foco, el eco es más fuerte y la mancha del haz sobre la muestra es más pequeña, así que se gana en relación señal-ruido y en resolución lateral.

Esto importa más de lo que parece. **El ruido de la medida del tiempo de vuelo lo marca la amplitud del eco**, no el número de promedios: medido el 5/10/2026, un eco fuerte da 0,41 µm de dispersión punto a punto y uno débil 1,0 µm. Mejorar el foco rinde más que duplicar los promedios.

### Cuándo hay que hacerlo

- Al montar una muestra nueva, si su cara queda a distinta distancia del transductor.
- Al cambiar de transductor.
- No hace falta repetirlo entre barridos de la misma muestra sin tocar el montaje.

### Antes de lanzarlo

- **Comprueba que el eco frontal está dentro de Smin–Smax** y bien separado de los bordes. La herramienta mueve la muestra a lo largo del eje del haz, y el eco se desplaza con ella: **1 mm de recorrido son unos 1,33 µs**. En un barrido de ±5 mm el eco recorre unos 13 µs. Si la ventana es estrecha, el eco se sale por un extremo y la curva de foco queda cortada, con un máximo falso en el borde.
- **Ajusta la ganancia** para que el eco se vea bien pero con margen hasta el fondo de escala. Recuerda que en el foco la amplitud va a crecer: si partes al límite, saturarás en el óptimo.
- **Coloca la muestra aproximadamente donde esperas el foco**, porque el barrido se hace alrededor de la posición actual.

### Los controles, uno a uno

**Recorrido**

| Control | Qué hace |
|---|---|
| **Range (beam, ±)** | Recorrido a cada lado de la posición actual, a lo largo del eje del haz. El barrido se recorta a los límites de sesión del escáner, avisando si lo hace. |
| **Coarse step** | Separación entre puntos del barrido principal. Es el barrido **sobre el que se hace el ajuste**. |
| **Fine sweep around the optimum (inspection only)** | Activa un segundo barrido, más fino, alrededor del máximo encontrado. Viene desactivado. |
| **Fine range (±)** y **Fine step** | Recorrido y paso de ese barrido fino. Solo se habilitan si la casilla está marcada. |

> **El barrido fino no entra en el ajuste, y por eso dice «inspection only».**
> Sirve para mirar con detalle la zona del óptimo, no para refinarlo. El ajuste se hace siempre sobre el barrido grueso. La razón es que un barrido fino con pocos puntos daba resultados que parecían mejores pero no lo eran: con un perfil de foco plano, unos pocos puntos muy juntos ajustan sobre todo el ruido.

**Medida en cada punto**

| Control | Qué hace |
|---|---|
| **Averages** | Capturas que se promedian en cada punto. El ruido baja como la raíz del número de promedios. |
| **Settle** | Espera tras cada movimiento, antes de medir, para que la mecánica deje de vibrar. |

Los valores de referencia, **100 promedios y 5000 ms**, se midieron con pasos de 1 mm. Son altos a propósito: un paso grande excita mucho más la mecánica que los pasos de un barrido, y el foco es sensible a ello. **No los copies a un barrido**, que tiene sus propios valores, mucho más bajos.

**Detección del eco**

| Control | Qué hace | Valor razonable y por qué |
|---|---|---|
| **Emission at** | **Instante de emisión**, en muestras desde el principio del registro. Es el origen de tiempos: el tiempo de vuelo absoluto se cuenta desde aquí. | **0** si el registro empieza en la emisión, que es el caso habitual. Solo se cambia si el equipo empieza a registrar antes de disparar. Un valor equivocado **no afecta al foco**, que compara amplitudes, pero falsea el tiempo de vuelo absoluto que se informa. |
| **Window edge margin** | Margen, en porcentaje del ancho de Smin–Smax, dentro del cual se considera que el eco está «pegado al borde». | **5 %**. Sobre una ventana de 3000 muestras son 150, algo más de un milímetro de recorrido. Subirlo hace que avise antes, bajarlo que deje pasar curvas cortadas. |
| **Tracking band (±)** | Semiancho de la banda en la que se busca el eco en cada punto, alrededor de donde se predice que estará a partir del punto anterior. | **0,5 µs**, y el criterio es claro: **la banda tiene que ser bastante más estrecha que la separación hasta el eco siguiente**, o el seguimiento se engancha a él. En una lámina de PVA de 3 mm el eco de la cara trasera llega 3,95 µs después, así que ±0,5 µs va sobrado. Con muestras más finas hay que reducirla. Por abajo, tiene que absorber el error de la predicción, no el desplazamiento del eco: ±0,5 µs tolera unos 0,37 mm de movimiento inesperado. |
| **Front-echo threshold** | Umbral, en porcentaje del máximo de la ventana, para localizar el eco frontal **en el primer punto**, donde todavía no hay predicción de la que partir. | **10 %**. Súbelo si el ruido dispara una detección falsa antes del eco; bájalo si el eco frontal es mucho más débil que otro posterior dentro de la ventana y el seguimiento arranca en el que no es. |

> **Cuidado: «Emission at» no es «Emission blanking».**
> En la pestaña de adquisición hay un control llamado **Emission blanking**, que vale varios cientos o miles de muestras y sirve para otra cosa completamente distinta: decirle al indicador de saturación qué zona del principio del registro debe ignorar. Poner aquí ese valor desplazaría el origen de tiempos y daría tiempos de vuelo absolutos sin sentido. **Este campo es casi siempre 0.**

**Guardado**

| Control | Qué hace |
|---|---|
| **Save debug dump** | Escribe un `.npz` en `data/focus_debug` con los puntos medidos, las señales y todos los parámetros. El foco **no guarda nada en la base de datos**; esto es lo único que deja. Déjalo activado: no estorba y permite revisar después un foco que haya salido raro. |

**Información, no editable**

Debajo de los controles, en gris, aparecen dos líneas:

- **Search window**: la ventana Smin–Smax vigente, que la herramienta **solo lee**. Si hay que cambiarla, se cambia en la pestaña de adquisición.
- **Estimated time**: la duración prevista, con el desglose de dónde se va el tiempo. Míralo antes de pulsar: con los valores por defecto son algo más de un minuto, pero subir los promedios o el asentamiento lo dispara deprisa.

**Run focus** lanza la medida. El STOP del encabezado la aborta en cualquier momento; al abortar, el escáner **no se mueve** al óptimo.

### Qué se ve mientras corre

Al pulsar **Run focus**, la gráfica grande cambia a la vista de foco y **los puntos se dibujan según se miden**. Eso permite abortar con el STOP en cuanto se ve que la curva va mal, en lugar de esperar los dos minutos largos que dura.

![Resultado de una búsqueda de foco: la curva medida, la parábola ajustada, el óptimo y la zona focal.](img/06_foco_resultado.png)

En la gráfica hay cinco cosas, y conviene saber cuál es cuál porque no hay leyenda:

| En la gráfica | Qué es |
|---|---|
| Puntos grises unidos por una línea fina | Las amplitudes medidas, una por posición |
| Curva amarilla | La parábola ajustada a esos puntos |
| Estrella verde | El óptimo, el vértice de la parábola |
| Línea vertical a trazos | La posición del óptimo, para leerla en el eje |
| Banda verde de fondo | La zona focal a −1 dB |

Debajo, la gráfica de **Overview** muestra el registro completo con la ventana Smin–Smax resaltada en azul. Sirve para comprobar de un vistazo que la ventana sigue conteniendo el eco frontal y que no ha entrado ningún otro.

### Cómo leer el resultado

![Dos curvas de foco problemáticas: a la izquierda, una que hay que descartar porque el eco se ha salido de la ventana; a la derecha, una válida pero con un máximo poco marcado.](img/06_foco_ejemplos.png)

*Dos casos reales del banco, 30/09/2026. **Izquierda:** los puntos marcados con aspa tienen el eco fuera de Smin–Smax, así que su amplitud es la del borde de la ventana, no la del eco: la curva no vale y hay que ampliar la ventana. **Derecha:** curva válida, pero con solo 1,8 dB entre el máximo y los extremos, que es lo que da un reflector plano.*

**Antes de fijarse en los números, mira la forma de la curva.** Una curva buena tiene:

- **un máximo claro y dentro del rango**, no en un extremo;
- **profundidad**: varios dB entre el máximo y los extremos. Cuanto más plana sea la curva, peor determinado queda el óptimo, por mucho que el ajuste dé un número con dos decimales;
- **ningún punto marcado como fuera de la ventana**;
- **puntos que siguen una tendencia**, no una nube. Si los puntos saltan, faltan promedios o sobra vibración.

Si la curva no cumple esto, el número del óptimo no significa gran cosa, y es preferible repetir que apuntarlo.

El panel de resultados da cinco líneas. Con los valores de la figura:

```
Focus at 31.18 ± 0.10 mm (-8.48 dB). Moved there.
Fit: 21 coarse points within 3 dB of the maximum, RMS residual 0.11 dB, vertex 1σ 0.10 mm.
Focal zone (−1 dB): 26.68–35.68 mm (9.00 mm).
ToF at the optimum: 6108.2 samples = 61.082 µs = 45.60 mm from the transducer
  (c_w = 1493.2 m/s, PT100 T1 = 23.70 °C, T2 = 23.73 °C; line on 21 points, RMS 0.30 samples).
ToF slope -1.3323 µs/mm vs 2/c_w = -1.3394 µs/mm (-0.5 %).
```

**Línea 1.** La posición del óptimo con su incertidumbre, la amplitud que se alcanza allí, y si el escáner se ha movido o no. No se mueve si el máximo cayó en un borde del rango o si se abortó.

**Línea 2.** De qué puntos sale el ajuste: solo entran los que están **dentro de 3 dB del máximo**, para que las colas no arrastren la parábola. El **residuo RMS** mide cuánto se apartan los puntos de la curva ajustada, y la **1σ del vértice** es la incertidumbre de la posición del óptimo.

**Línea 3.** La **zona focal a −1 dB**: el tramo dentro del cual la amplitud no baja más de 1 dB respecto del máximo. Es el margen práctico de colocación. Nueve milímetros, como aquí, significa que dentro de ese recorrido da casi igual dónde pongas la muestra.

**Línea 4.** El **tiempo de vuelo en el óptimo**, en muestras, en microsegundos y convertido a distancia al transductor. Indica de dónde sale c_w: del PT100 con las dos temperaturas, o el nominal de 1480 m/s si no hay lectura. El RMS en muestras es la dispersión de la recta de tiempo de vuelo frente a posición.

**Línea 5.** La **comprobación de coherencia**. Al alejar la muestra un milímetro, el eco debe retrasarse exactamente 2/c_w microsegundos, porque el camino de ida y vuelta crece dos milímetros. La herramienta compara la pendiente medida con ese valor teórico y da la discrepancia en porcentaje.

> **Qué significa una discrepancia en la línea 5.** Es la comprobación más valiosa del foco, porque **relaciona dos cosas medidas por caminos independientes**: los milímetros que dice el escáner y la velocidad del sonido que dice el PT100. Si discrepan, una de las dos está mal.
>
> Una discrepancia del 1 % puede ser c_w: entre 1480 y 1493 m/s hay un 0,9 %, es decir, usar el nominal en vez del PT100 ya produce esa diferencia. Una discrepancia que persiste con el PT100 conectado apunta a otra cosa: a que la escala en milímetros del escáner no es exacta, o a que el agua del camino del haz no está a la temperatura que marca la sonda del fondo de la vasija.
>
> Por debajo del 1 % no afecta a ninguna medida relativa, que es casi todo lo que se hace con el sistema. Importa si algún día se quiere velocidad de propagación absoluta.

**Qué valores son buenos:**

| Indicador | Bien | Mal, y qué hacer |
|---|---|---|
| Posición del óptimo | Dentro del rango, no en un extremo | En el borde: amplía **Range** y repite |
| Incertidumbre del óptimo | Mucho menor que la zona focal a −1 dB | Comparable a ella: el óptimo no está determinado; sube los promedios o usa un reflector pequeño |
| Profundidad de la curva | Varios dB entre el máximo y los extremos | Menos de 2–3 dB: curva plana, típico de reflector plano |
| Residuo del ajuste | Del orden de la dispersión entre puntos vecinos | Mucho mayor: la parábola no describe la curva; mira si hay puntos marcados o si el máximo es doble |
| Coherencia de la pendiente | Pendiente medida ≈ 2/c_w | Discrepa: revisa el lado del pulso-eco y el convenio de ejes (capítulo 2) |

Si el máximo cae en el borde del rango, la herramienta **avisa y no se mueve**: amplía el rango y repite.

> **Aviso de ventana estrecha**
> Si en algún punto el máximo de la envolvente cae dentro del **Window edge margin** de un borde de Smin–Smax, la herramienta lo avisa **durante el barrido**, no al final, y marca esos puntos en la gráfica. Amplía la ventana en la pestaña de adquisición y repite.

### Límites que hay que conocer

**Con un reflector plano el perfil del foco sale casi plano.** Una superficie plana devuelve energía desde toda la zona iluminada, así que no reproduce el perfil del haz: se han medido curvas con solo 3 dB de variación en 10 mm. Eso hace que el óptimo esté mal determinado aunque el ajuste parezca bueno.

Para determinar el foco de verdad hace falta un **reflector pequeño**: una bola o un hilo fino, que devuelve señal solo desde el punto donde está. **Esta calibración está pendiente.** Mientras tanto, trata el foco medido como aproximado, y fíate más de la zona focal a −1 dB que del valor puntual del óptimo.

**El ajuste se hace sobre la amplitud en dB.** El perfil axial cerca del foco se aproxima a una gaussiana, y una gaussiana en logaritmo es una parábola: el ajuste es el adecuado, no una aproximación de conveniencia.

**No guarda nada en la base de datos**, pero sí escribe un volcado de depuración en `data/`, con los puntos medidos y los parámetros usados.

---

## 6.2. Planitud

### Qué mide

Si la cara de la muestra no está perpendicular al haz, el tiempo de vuelo cambia al desplazarse por la superficie. La herramienta recorre dos líneas alrededor de la posición actual y mide ese cambio:

- **Línea lateral**: detecta la inclinación alrededor del eje vertical.
- **Línea en Z**: detecta la inclinación alrededor del eje lateral.

**El eje del haz no se mueve en ninguna de las dos.** El ángulo sale de la pendiente del ajuste lineal:

```
θ = atan( c_w · Δt / (2 · Δx) )
```

### Cómo se corrige

**Las dos correcciones son manuales. La herramienta mide e informa; no mueve ningún eje para corregir.**

| Inclinación medida | Se corrige con | Qué hace |
|---|---|---|
| **Lateral** | Platina de rotación **Thorlabs CR1/M** | Gira la muestra alrededor del eje vertical |
| **En Z** | Goniómetro **Thorlabs GN1/M** | Inclina la muestra alrededor de un eje horizontal |

Las dos están graduadas, así que la corrección **se aplica leyendo un número, no a tientas**: la herramienta dice cuántos grados y en qué sentido, y se llevan a la escala. Junto a cada ángulo, la interfaz indica con qué control se corrige y hacia dónde girar, para que no haya que deducirlo.

> **Al corregir la inclinación, la muestra también se desplaza a lo largo del haz.**
> El goniómetro no gira alrededor del punto donde incide el haz, sino alrededor de un centro situado por encima. Con la muestra a unos 50 mm de ese centro, el desplazamiento es
>
> ```
> Δ ≈ L · θ  =  50 mm · θ(rad)  ≈  0,87 mm por grado
> ```
>
> lo que mueve el eco unos 1,2 µs por grado.
>
> **Para una corrección normal esto es despreciable**: medio grado son 0,44 mm, un 5 % de la zona focal y menos de 0,6 µs en una ventana de más de 40 µs. **Solo importa si has tenido que corregir dos grados o más**, y entonces conviene volver a mirar que el eco siga bien centrado en Smin–Smax y repetir el foco. Una corrección de ese tamaño suele significar que la muestra está mal colocada en el soporte, y sale más a cuenta recolocarla que compensarla con el goniómetro.

> **El eje R no se usa para corregir la planitud.** Su resolución es de 1,8° por paso, insuficiente para esto, y además pierde pasos con el portamuestras montado. R sirve para orientar la pieza de forma gruesa, nada más.

### Los controles, uno a uno

| Control | Qué hace | Valor razonable y por qué |
|---|---|---|
| **Lateral range (±)** y **Z range (±)** | Recorrido a cada lado del centro en cada una de las dos líneas. | **El parámetro que más influye en la calidad del resultado.** La incertidumbre del ángulo baja de forma inversamente proporcional a la longitud de la línea, así que doblar el recorrido la reduce a la mitad. El límite lo pone la muestra: si el haz se sale de la pieza, los puntos de los extremos no valen. |
| **Lateral step** y **Z step** | Separación entre puntos. | Con el recorrido fijo, más puntos reducen la incertidumbre solo como la raíz del número de puntos. Rinde menos que alargar la línea, pero suma. |
| **Averages** | Capturas promediadas en cada punto. | **Rinde mucho menos de lo que parece aquí**, por el motivo que se explica más abajo. |
| **Settle** | Espera tras cada movimiento. | Como en el foco, 5000 ms de referencia. |
| **Tolerance** | Umbral por debajo del cual se considera que la cara está suficientemente perpendicular. | Debe fijarse según **lo fino que se pueda ajustar a mano** con el goniómetro y la platina. Una tolerancia más estricta que el ajuste más pequeño que puedes aplicar condena a no llegar nunca. |
| **Tracking band (±)** | Igual que en el foco: semiancho de la banda de búsqueda del eco. | 0,5 µs, con el mismo criterio: muy por debajo de la separación al eco siguiente. |
| **Save debug dump** | Escribe el `.npz` en `data/flatness_debug`. | Actívalo. |

**Run flatness** lanza la medida y **Repeat** la repite: ese es el uso normal, corriges a mano y vuelves a medir. Al terminar el escáner vuelve al centro; si se aborta con el STOP, **no se mueve**.

### Cómo leer el resultado

![Resultado de una medida de planitud: las dos líneas de desplazamiento de la cara con sus rectas ajustadas, y el texto con los dos ángulos.](img/06_planitud_resultado.png)

En la gráfica, el desplazamiento de la cara frente a la posición: **en azul la línea lateral y en naranja la línea en Z**, cada una con su recta ajustada. El eje vertical son micras de desplazamiento de la cara, no microsegundos, que es más fácil de interpretar.

Por cada eje, el texto da **el ángulo, su incertidumbre a 1σ y el residuo RMS**, y, cuando procede, la corrección a aplicar. Con los valores de la figura:

```
Lateral (X): not distinguishable from 0 (θ = +0.12° ± 0.17°, |θ| < 2σ), RMS residual 27.3 µm.
Z (Z): θ = +0.807° ± 0.084° (1σ), RMS residual 13.1 µm.
  → Tilt by 0.807° so that the lower edge of the face (Z+, Z grows downwards)
    comes closer to the PE transducer (Δθ = -0.807°).
```

**Lateral: no distinguible de cero.** El ángulo, 0,12°, es menor que dos veces su propia incertidumbre, 0,17°. Eso no significa que la cara esté perpendicular, significa que **esta medida no puede afirmar que no lo esté**. No hay nada que corregir con ese dato.

**En Z: inclinación real.** 0,807° con una incertidumbre de 0,084°, es decir casi diez veces el error. Y la corrección viene dicha entera: cuánto, con qué control y en qué sentido, señalando qué borde de la cara tiene que acercarse al transductor de pulso-eco. No hay que deducir nada.

> **Lee siempre el ángulo con su incertidumbre.** Un ángulo sin su error invita a perseguir ruido. Por debajo de 2σ la herramienta dice directamente que **no es distinguible de cero** en lugar de dar un número con falsa precisión.

### Cuando dice «undetermined against the tolerance»

Significa que **la incertidumbre de la medida es del orden de la tolerancia que se le pide juzgar**, así que no puede decir si se cumple o no. En la figura ocurre con las dos líneas: 1σ vale 0,170° y 0,084° frente a una tolerancia de 0,100°.

No es un fallo: es la herramienta negándose a dar un veredicto que no sostiene. Lo que hay que hacer es **mejorar la medida o aflojar la tolerancia**.

> **Y aquí el programa da un consejo incompleto.** Dice «increase the averages or the range», pero **subir los promedios no va a servir de nada** en la mayoría de los casos, por una razón de fondo:
>
> **Lo que limita la incertidumbre del ángulo no es el ruido de medida, es la forma real de la cara.** El residuo RMS de la figura, 27,3 y 13,1 µm, es casi todo estructura de la superficie: la cara no es un plano, y la recta ajustada no la describe. El ruido de medida, en cambio, es de en torno a 1 µm. Promediar más reduce ese micrómetro y deja intactas las veintisiete.
>
> **Lo que sí funciona es alargar la línea.** La incertidumbre del ángulo cae de forma inversamente proporcional al recorrido, así que pasar de ±5 a ±10 mm la reduce a la mitad; y como con el mismo paso eso duplica además el número de puntos, el efecto total es de unas 2,7 veces. En el caso de la figura, eso bajaría la 1σ en Z de 0,084° a unos 0,031°, un tercio de la tolerancia, que ya permite juzgar.
>
> El coste son diez puntos más por línea, alrededor de un minuto. Subir los promedios al doble costaría más tiempo y no cambiaría el resultado.

### Límites que hay que conocer

**La herramienta ajusta una recta, y las muestras reales no son planas.** En las láminas de PVA medidas se ha encontrado una curvatura con radio de unos 80–90 mm y hasta 280 µm de variación en 10 mm. Sobre una cara curva, la recta ajustada da la inclinación *media* del tramo recorrido, que depende de dónde lo recorras.

En la práctica esto significa que **conviene medir la planitud siempre en la misma zona de la muestra**, y que el residuo RMS no es solo ruido: lleva dentro la forma real de la cara. Un residuo grande con un ángulo pequeño suele querer decir que la pieza es curva, no que la medida sea mala.

**La cara se puede acabar.** Al recorrer lateralmente o en Z, el haz puede salirse de la muestra. Si el eco desaparece en los extremos, la herramienta lo señala; reduce el rango y repite en vez de dar por bueno un ajuste con puntos malos.

**No guarda nada en la base de datos**, pero sí escribe volcado de depuración.

---

## 6.3. Test de estabilidad

### Para qué sirve

Comprueba si la muestra está quieta. El escáner **no mueve ningún eje**: se queda en la posición actual y mide el mismo punto repetidamente durante el tiempo que se le indique.

Hace falta porque **una muestra recién colocada se mueve**. En las láminas de PVA medidas el 5/10/2026, la cara se desplazó **97 µm en veintiún minutos** justo después de montarla, con episodios de hasta 9 µm/min alternando con pausas. Dos horas después, la misma pieza se movía seis veces menos.

Eso importa porque **un barrido de superficie dura entre cinco y veinte minutos**: si la muestra se mueve mientras tanto, y el tiempo avanza con el número de línea, la deriva aparece en el mapa como una inclinación que no existe.

### Cuándo hacerlo

- Siempre que montes una muestra nueva, antes del primer barrido.
- Al cambiar el soporte o la forma de sujetar.
- Si un mapa muestra una inclinación sospechosa en el eje lento.

### Parámetros

Número de medidas e intervalo entre ellas. Los valores de referencia son **240 medidas cada 5 s**, es decir veinte minutos, con 20 promedios. El tiempo total se muestra antes de empezar.

### Qué registra

En cada punto, y durante todo el ensayo:

- **el desplazamiento de la cara**, por correlación cruzada del eco frontal;
- **el cambio de tiempo de vuelo en transmisión** (Ch1);
- las amplitudes de los dos canales;
- **la temperatura**, en cada punto;
- **los registros completos de los dos canales**, que permiten recalcular cualquier otra cosa después.

### Cómo leer el resultado

Las cuatro gráficas frente al tiempo, y los ritmos de deriva en vivo con su residuo.

**Lo que hay que mirar primero es si la deriva es monótona o va y viene.** Una muestra que se asienta se mueve siempre en el mismo sentido y poco a poco frena. Un vaivén que cambia de signo es otra cosa: vibración del entorno, alguien trabajando en la misma mesa.

**Y lo segundo, si la temperatura explica algo.** Si T está plana y la cara se mueve, la deriva es mecánica. Para que fuera térmica harían falta cambios de temperatura que el PT100 vería.

### Qué distingue deslizamiento de hinchamiento

Si los registros contienen el eco de la cara posterior, el test distingue dos causas que se parecen:

- **La pieza se desplaza o se arquea**: la cara se mueve y **el espesor no cambia**, porque las dos caras van juntas.
- **La pieza se hincha**: el espesor crece, y se mide entre el eco 1 y el eco 2.

En las medidas del 5/10/2026 la cara se movió 97 µm y el espesor creció 4,3 µm: el movimiento era mecánico casi por completo, con un hinchamiento pequeño y constante por debajo.

> **Control con reflector rígido**
> Si no queda claro si lo que se mueve es la muestra o el montaje, repite el test con una pieza rígida —acero, vidrio— en el mismo soporte. Si la deriva desaparece, el problema es la muestra o su sujeción; si persiste, es la mecánica del escáner.

### Qué hacer con lo que salga

- **Si la deriva es grande y monótona**, espera y repite. Si no frena en veinte minutos, esperar no es la solución.
- **Si no frena**, revisa la sujeción. Una lámina blanda que se sostiene a sí misma se arquea bajo su propio peso; apoyarla elimina el problema en origen, que es mejor que corregirlo después.
- **Si vas a medir espesor, puedes seguir igualmente.** El espesor es inmune a este movimiento, porque afecta por igual a los dos ecos y se cancela en la diferencia. Solo la topografía de la cara necesita el punto testigo (apartado 7.x).

---

## 6.4. Secuencia recomendada

1. Monta la muestra y espera a que el agua y la pieza se templen.
2. Ajusta Smin–Smax sobre el eco frontal y la ganancia con margen hasta el fondo de escala.
3. **Foco.** Mueve al óptimo.
4. **Planitud.** Corrige con el goniómetro y la platina de rotación, y repite hasta verde.
5. **Solo si la corrección ha pasado de un par de grados**, comprueba que el eco sigue centrado en Smin–Smax y repite el foco. Con correcciones normales no hace falta.
6. **Estabilidad**, veinte minutos, sin tocar nada.
7. Si la deriva es aceptable, mide.

Los pasos 3 a 5 se repiten; el 6 se hace una vez por montaje.

---

## 6.5. Cifras de referencia

Medidas en el banco el 5 y 6 de octubre de 2026. Sirven para saber si lo que estás viendo es normal.

| Magnitud | Valor | Condiciones |
|---|---|---|
| Ruido de tiempo de vuelo, eco fuerte | 0,41 µm | Reflector de acero, 20 promedios |
| Ruido de tiempo de vuelo, eco débil | 1,0 µm | PVA, 20 promedios |
| Ruido del espesor | 0,09 µm | PVA, 20 promedios, punto fijo |
| Asentamiento suficiente, paso ≤ 0,5 mm | 100 ms | 1000 ms no mejora |
| Asentamiento del cambio de línea | 1000 ms | Sin artefacto detectable |
| Tiempo por punto | 0,43–0,57 s | 5 a 20 promedios |
| Deriva de PVA recién montada | hasta 4,3 µm/min | Decae en horas |
| Deriva de PVA asentada | < 1 µm/min | Misma pieza, 2 h después |
| Hinchamiento del PVA | 0,18 µm/min | Lámina de 3 mm |

---

*Figuras pendientes: panel de la subpestaña Calibration; gráfica de foco con la parábola; resultado de planitud con los dos ángulos; gráficas del test de estabilidad. Dibujo de los convenios de ejes (remite al capítulo 2).*
