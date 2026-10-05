# Tarea: Fase 5 — Barrido en línea, referencias en agua y guardado

Lee antes `scanner_tab_spec.md` (secciones 3, 4, 5.1 y 5.6) y las tareas de las fases 3 y 4. Entorno de adquisición de 32 bits según `CLAUDE.md`; se desarrolla y prueba primero con el SeDaq sintético.

Reutiliza el **secuenciador** de la fase 2 y el **seguimiento del eco frontal** de la fase 3. No escribas un bucle nuevo.

**Cambio respecto al reparto original de fases:** el guardado entra aquí, no en la fase 6. El formato admite las dos dimensiones y un barrido en línea es el caso de una sola fila, así que conviene estrenarlo con la geometría sencilla. La fase 6 solo añadirá la segunda dimensión.

## 1. Barrido en línea
- Eje: lateral o Z, a elegir.
- Rango: inicio y fin, absolutos o relativos al centro, más el paso.
- Espera tras cada movimiento y número de promedios, configurables.
- **Tiempo estimado antes de empezar**, bien visible, y aviso si supera media hora.
- Pausa, continuar y parar. Al parar, se ofrece guardar lo adquirido.
- Se guardan **los dos canales** en cada punto, junto con la posición real leída del escáner, no la pedida.

### Asentamiento y promedios: no heredes los del foco
Los valores de la fase 3 (5000 ms y 100 promedios) se midieron con pasos de 1 mm. Un barrido usa pasos mucho menores, que excitan mucho menos la mecánica, y además tiene cientos o miles de puntos: a 5 s por punto, un barrido de 200 puntos son 20 minutos solo de espera.

Deja los dos como parámetros propios del barrido, independientes de los del foco, con valores por defecto más bajos (por ejemplo 500 ms y 20 promedios) marcados como **pendientes de caracterizar en función del paso**. Que el tiempo estimado se actualice al cambiarlos, para que la compensación entre calidad y duración sea visible.

### Mapa en vivo
Se dibuja punto a punto, con la magnitud elegida por el usuario:
- amplitud máxima de la envolvente en la ventana,
- tiempo de vuelo del eco frontal,
- energía en la ventana.

Estructúralo para poder añadir más magnitudes sin tocar el barrido.

## 2. Referencias en agua (opcional)
Casilla «Tomar referencias en agua al inicio y al final», con la ganancia de referencia por canal y el número de promedios de la referencia como parámetros.

Flujo, tal como describe la spec 5.6:
1. Al pulsar Inicio, la posición actual se guarda como **punto de inicio**.
2. Si no hay PT100, se avisa: la temperatura se guardará como no disponible.
3. Mensaje: saca la pieza del eje con los controles manuales y pulsa Continuar. Durante este paso solo está activo el movimiento manual, y el programa **registra el orden de los ejes** que se mueven.
4. Al continuar: se aplica la ganancia de referencia, **volviendo a fijar Gain2 después de cualquier cambio de Gain1** por el fallo conocido del pulser, se toma un A-scan promediado de los dos canales y se muestra. Botones OK, Repetir y Cancelar.
5. Al aceptar: la posición actual se guarda como **posición de referencia**, se restaura la ganancia del barrido y se vuelve al punto de inicio con **un movimiento por eje, en orden inverso** al registrado. Después empieza el barrido.
6. Al terminar, se va a la posición de referencia en el orden registrado, se toma la referencia final y se vuelve al punto de inicio en orden inverso.
7. Si el barrido se para a mitad, se pregunta si se toma la referencia final.

Cada referencia guarda señales de los dos canales, ganancias, posición, hora y temperatura.

## 3. Temperatura
- **No se lee en cada punto.** Se lee al empezar, al terminar y en cada referencia. En la fase 6 se añadirá al acabar cada línea.
- Una sola instancia de `Arduino` abierta durante la secuencia y cerrada al final. El patrón actual de crear y cerrar por lectura cuesta ~2 s cada vez.
- Cada valor se guarda con su marca de tiempo y el índice del punto en que se tomó.
- Sin PT100: NaN y aviso al empezar. **Nunca abrir el diálogo manual de temperatura durante un barrido**: es modal y bloquearía la secuencia.

## 4. Guardado
Carpeta por barrido, siguiendo la convención de ECOS:

```
PVA_10_PG_5_A_C005_SCAN_20261002_091500/
  meta.json    specimen, protocol, equipment (parámetros del pulser), bloque scanner_session,
               parámetros del barrido, operator y comentario. schema_version: "scan-32-1.0"
  scan.npz     señales por canal (N_línea × N_punto × N_muestras, con N_línea = 1 aquí),
               coordenadas reales de cada punto, temperaturas con marca de tiempo e índice,
               y las referencias en agua si se tomaron
```

- **Función nueva**, por ejemplo `save_scan_raw_32`: `save_experiment_raw_32` valida que haya exactamente tres señales 1D de igual longitud y no admite un cubo. Reutiliza su esquema de metadatos, no su firma.
- Sin `results.json`: los resultados se calculan después, en el análisis.
- **Guardado automático en `../database`** con el nombre de la convención y `SCAN` como tipo, para que `analysis/ecos_loader.py` pueda catalogarlo. Botón «Guardar en otra carpeta…» como alternativa.
- El nombre se construye a partir del descriptor de muestra de la pestaña Acquisition. El método actual tiene `"PVA"` y `"US"` incrustados en un f-string: generalízalo o escribe un constructor nuevo, sin romper el nombrado existente.
- **`operator` está fijo como «Sebas»** en `BD_Experimentos_PVA.py`. En la función nueva debe ser un campo editable, con ese valor como defecto.

## 5. Detalles heredados
- c_w de los PT100, con el mecanismo compartido.
- Mensajes diferenciados de ventana estrecha y de seguimiento perdido.
- Bloqueo durante la secuencia y STOP siempre activo; al parar no se mueve.
- Volcado de depuración, como en foco y planitud.
- El eco puede perderse si el haz se sale de la pieza: marcar esos puntos y seguir, no abortar.

## Verificación (simulador)
1. Barrido en línea completo en los dos ejes, con el mapa dibujándose punto a punto y la ventana sin congelarse.
2. Pausa, continuar y parar; al parar se ofrece guardar lo adquirido.
3. Con referencias activadas, el flujo completo: el orden de ejes se registra y la vuelta se hace en orden inverso; la ganancia se restaura; las dos referencias quedan guardadas.
4. El archivo guardado se vuelve a leer y contiene lo que se midió: señales, coordenadas reales, temperaturas y referencias, con las dimensiones correctas.
5. Sin PT100, NaN y aviso, sin ningún diálogo modal.
6. El tiempo estimado coincide razonablemente con el real.
7. Todos los tests del proyecto siguen pasando.

## No hacer
- Barrido en superficie (fase 6).
- Cálculo de resultados a partir del barrido: eso es análisis.
- Sintaxis posterior a Python 3.9 ni API de pyqtgraph posterior a 0.11.

## Commits propuestos
- `feat(database): save_scan_raw_32 for scan data`
- `feat(scanner): line scan with live map and water references (phase 5)`
