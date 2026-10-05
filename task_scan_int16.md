# Tarea: guardar las señales de barrido como enteros

Cambio en el formato de guardado de la fase 5, **antes de que existan barridos reales**. No hace falta compatibilidad hacia atrás, pero déjalo dicho en `scanner_tab_spec.md`.

## Motivo
El SeDaq entrega cuentas enteras; la conversión a flotante la hace `_raw_to_float`, restando el punto medio del cuantizador. Guardar en `float32` ocupa el doble sin añadir información: el convertidor es de 10 bits y cabe de sobra en 16. Guardar las cuentas en crudo es además más fiel al origen, porque no se convierte nada al escribir.

Orden de magnitud para la fase 6: un barrido de 50×50 puntos con ventanas de 6000 muestras y dos canales son unos 120 MB en `float32` y 60 MB en entero de 16 bits.

## 1. Resolución real del convertidor: aclararla primero
`_update_plots` y `_acquire_ch_avg` tienen **1024 fijo** como punto medio del cuantizador, y `BITS_OPTIONS` (8, 10 y 12 bits) está declarado en `ecos_gui.py` pero no se usa en ningún sitio.

Antes de tocar el guardado, determina si la resolución se puede leer del equipo o de la configuración. Si no se puede:
- mantén el valor actual,
- documenta el supuesto en el código y en la spec,
- y hazlo **parámetro**, no constante incrustada, para que quede en los metadatos de cada archivo.

Esto pasa a importar porque a partir de ahora la conversión queda escrita en cada barrido.

## 2. Guardado
- `save_scan_raw_32` escribe las señales como **enteros de 16 bits**, con las cuentas tal como las entrega el SeDaq, **sin convertir a flotante** al escribir.
- A los metadatos se añaden los parámetros de conversión: punto medio del cuantizador, número de bits y ganancia por canal.
- Comprueba que la compresión del `.npz` sigue activa: con enteros comprime mejor que con flotantes.

## 3. Lectura
- `load_scan_raw_32` devuelve **flotantes**, aplicando la conversión con los parámetros del propio archivo, de modo que quien la use no note el cambio.
- La reconstrucción debe ser exacta: el flotante leído es idéntico al que habría devuelto la conversión en el momento de medir.

## 4. Versión del esquema
Sube `schema_version`. En la spec, sección 5.6, deja constancia de que las señales se guardan en enteros con los parámetros de conversión en los metadatos, y de por qué.

## Verificación
1. Guardar un barrido simulado y volver a leerlo: las señales coinciden **exactamente** con las medidas, no de forma aproximada.
2. El archivo ocupa aproximadamente la mitad que con `float32`. Indica las dos cifras.
3. Los metadatos contienen punto medio, bits y ganancia por canal.
4. Con ganancias distintas en los dos canales, la conversión de cada uno usa la suya.
5. Todos los tests del proyecto siguen pasando.

## Commit propuesto
`feat(database): store scan signals as int16 with conversion metadata`
