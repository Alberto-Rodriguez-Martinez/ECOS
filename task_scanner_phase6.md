# Tarea: Fase 6 — Barrido en superficie

Lee antes `scanner_tab_spec.md` (secciones 3, 4, 5.1 y 5.6) y `task_scanner_phase5.md`. Entorno de adquisición de 32 bits según `CLAUDE.md`; se desarrolla y prueba primero con el SeDaq sintético.

Reutiliza el **secuenciador** de la fase 2, el **seguimiento del eco frontal** de la fase 3 y el **barrido en línea** de la fase 5. No escribas un bucle nuevo ni un detector de ecos nuevo.

La interfaz ya está hecha: la casilla «Superficie» activa los campos del segundo eje y la elección de recorrido, el plan genera las líneas de los dos recorridos y el tiempo estimado las cuenta. Lo que falta es la adquisición, más tres cosas nuevas que salen de las medidas del 5 de octubre.

---

## 0. Qué se midió el 5/10, porque cambia esta fase

Cuatro resultados sobre el equipo real, todos sobre la misma línea de 21 puntos con paso de 0,5 mm:

1. **El ruido sigue 1/√N y es electrónico, no vibración.** Con 20 promedios, 0,93–0,99 µm de temblor punto a punto. El asentamiento de 1000 ms no mejora al de 100. Confirmado por dos métodos independientes: comparando seis barridos consecutivos y midiendo un punto fijo durante veintiún minutos.
2. **El temblor lo manda la relación señal-ruido del eco, no un suelo fijo del sistema.** Con un reflector de acero y la ganancia a 0 dB sale **0,41 µm**; con el PVA, **0,99 µm**. Es decir, el foco y la ganancia pesan más que duplicar los promedios, y **el ruido no será uniforme a lo largo del mapa**: en una línea de 10 mm la amplitud variaba 10 dB.
3. **La muestra de PVA deriva −4,34 µm/min, a tirones**, con episodios de −9 µm/min alternando con pausas y saltos aislados de 5 a 7 µm: 97,5 µm en veintiún minutos. Con un reflector de acero en el mismo montaje la deriva es de +0,32 µm/min sin un solo salto, así que **es la muestra, no el escáner**. La hipótesis en pie es que la lámina de 3 mm se arquea bajo su propio peso.
4. **El espesor medido entre los ecos 1 y 2 es inmune a esa deriva**, porque el movimiento afecta igual a los dos ecos y se cancela en la diferencia. Residuo de 0,20 µm frente a 2,4 µm de la posición de la cara: **es la magnitud más fiable del sistema**, y es la que alimenta la caracterización del material.

De ahí salen las secciones 2 y 3, que son lo realmente nuevo de esta fase.

---

## 1. Adquisición línea a línea

- Quita el rechazo que hoy impide empezar con «Superficie» marcada.
- **Recorrido en zigzag por defecto**, unidireccional como opción.
- **Asentamiento propio del cambio de línea**, independiente del asentamiento entre puntos. Los 100 ms están validados para pasos de 0,5 mm o menores; un cambio de línea es un salto de decenas de milímetros y excita la mecánica mucho más. Valor por defecto 1000 ms, **marcado en el código como no caracterizado**, y editable. Es otro argumento a favor del zigzag, que no tiene retorno largo.
- Orden de ejes fijo y documentado, para que el barrido sea reproducible.
- Se guarda la **posición real leída del escáner** en cada punto, no la pedida, igual que en la fase 5.
- Pausa, continuar y parar. Al parar se ofrece guardar lo adquirido: las líneas completas más la línea parcial, marcada como tal.

## 2. Espesor por punto

Lo nuevo más importante. En cada punto, además de lo que ya mide el barrido en línea:

- **Tiempo entre el eco 1 y el eco 2 por correlación cruzada**, los dos dentro de la ventana Smin–Smax, y el espesor correspondiente.
- **Guarda el coeficiente de correlación de cada punto** como indicador de calidad. Donde el eco se deforme, que es donde la cara está más inclinada, el coeficiente baja y avisa de que ese punto es menos fiable.
- **Si el segundo eco no cabe en la ventana**, avisa **antes de empezar** y deja la magnitud deshabilitada. No des un número malo: más vale no ofrecer el espesor que ofrecer uno medido contra lo que haya en el borde de la ventana.
- Por lo dicho en el punto 0.4, **el espesor es la magnitud por defecto del mapa en vivo**.

El espesor definitivo se calcula en el análisis, a partir de las señales guardadas. Lo de aquí es para el mapa en vivo y para los metadatos, igual que la amplitud y el tiempo de vuelo.

## 3. Punto testigo

Opcional, **activado por defecto**, porque sin él la topografía de la cara de cualquier muestra blanda no vale.

- Un **punto fijo**, elegido por el usuario o el primero del barrido, al que se vuelve cada N líneas, con N configurable y 1 por defecto.
- En cada visita se mide igual que en un punto normal y se guarda con su marca de tiempo y el índice de línea.
- **No corrijas nada en el archivo guardado.** La adquisición guarda datos crudos más la serie del testigo; la corrección de deriva es cosa del análisis. El mapa en vivo sí puede mostrarla corregida, indicándolo.
- **Marca las líneas en las que el testigo salte** más de un umbral configurable respecto de la interpolación entre visitas. La deriva medida es a tirones, así que un salto entre dos visitas no se puede reconstruir y esa línea queda en duda.
- La corrección de deriva **nunca se aplica al espesor**, que no la necesita y a la que la empeoraría. Solo a la posición de la cara.
- El tiempo estimado debe contar las visitas al testigo y sus movimientos.

## 4. Mapa en vivo en dos dimensiones

- Magnitudes seleccionables: **espesor** (por defecto), tiempo de vuelo de la cara, amplitud y energía. Mantén la estructura de la fase 5, que ya permite añadir magnitudes sin tocar el barrido.
- Se dibuja **línea a línea**, no al final.
- Barra de color con unidades, y escala que se pueda fijar o dejar automática.
- **pyqtgraph 0.11**: `ImageItem` y nada de API posterior; colores como tuplas RGB.
- Conviene poder ver el mapa de amplitud junto al de espesor, porque la amplitud es el indicador de dónde fiarse.

## 5. Temperatura

- **Al acabar cada línea**, además del inicio, el final y las referencias. El secuenciador ya lo prevé.
- Cada valor con su marca de tiempo y el índice de línea.
- Sin PT100, NaN y aviso al empezar, sin ningún diálogo modal.
- **Deja constancia en los metadatos de que el PT100 está en el fondo de la vasija y no en el camino del haz.** Medimos el 5/10 que 0,07 K en la capa límite alrededor de una pieza recién metida valen 5 µm de tiempo de vuelo, así que esa sonda sirve para seguir la tendencia pero no da la temperatura del agua que atraviesa el haz. Es una limitación del montaje, no un fallo del programa, pero tiene que quedar escrita en cada archivo.

## 6. Guardado

El formato de la fase 5 ya admite las dos dimensiones; aquí `N_línea > 1`. Añade:

- la **serie del punto testigo**, con posición, tiempo de vuelo, amplitud, marca de tiempo e índice de línea;
- el **coeficiente de correlación del espesor** por punto;
- las **temperaturas por línea**, con el índice de línea;
- los parámetros nuevos: recorrido, asentamiento del cambio de línea, periodo del testigo.

Sube `schema_version` y documenta el cambio en la sección 5.6 de la spec.

## 7. Tiempo estimado

Debe contar las líneas, los cambios de línea con su propio asentamiento y las visitas al testigo. Como referencia medida el 5/10, sin referencias en agua: **0,43 s por punto con 5 promedios y 0,57 s con 20**, de los cuales unos 0,28 s son movimiento y proceso, 9,5 ms cada A-scan y el resto el asentamiento. Mantén el aviso cuando supere media hora.

---

## Verificación (simulador)

1. Barrido en superficie completo en los dos recorridos, con el mapa dibujándose línea a línea y la ventana sin congelarse.
2. El archivo guardado se vuelve a leer y tiene las dimensiones correctas, con `N_línea` igual al número de líneas y las coordenadas reales de cada punto.
3. Con el segundo eco dentro de la ventana, el espesor recuperado coincide con el del simulador; con el segundo eco fuera, avisa antes de empezar y no ofrece la magnitud.
4. Con una deriva impuesta en el simulador, el testigo la recoge y la serie guardada permite reconstruirla. Comprueba también que el espesor **no** se ve afectado por esa deriva.
5. Con un salto brusco impuesto entre dos visitas del testigo, la línea correspondiente queda marcada.
6. Pausa, continuar y parar a mitad de una línea; al parar se ofrece guardar y la línea parcial queda marcada.
7. Una temperatura por línea, con su índice, y el aviso sin PT100.
8. El tiempo estimado coincide razonablemente con el real, incluidas las visitas al testigo.
9. Todos los tests del proyecto siguen pasando.

## No hacer

- Calcular resultados definitivos a partir del barrido: eso es análisis.
- Aplicar la corrección de deriva a los datos guardados.
- Cambiar el estimador de tiempo de vuelo del barrido a correlación cruzada: sobre datos reales mejora solo un 10 % (0,99 frente a 1,09 µm) y es una tarea aparte.
- Sintaxis posterior a Python 3.9 ni API de pyqtgraph posterior a 0.11.

## Commits propuestos

- `feat(scanner): per-point thickness from front and back echoes`
- `feat(scanner): drift monitor point`
- `feat(scanner): surface scan with 2D live map (phase 6)`
