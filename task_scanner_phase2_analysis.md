# Tarea: Fase 2 — análisis previo a la integración en `ecos_gui.py`

**Esta tarea NO modifica código.** Es un análisis del estado actual de `ecos_gui.py`, cuyo resultado se entrega como informe. La integración se especificará después, con ese informe delante.

Lee antes `scanner_tab_spec.md`, secciones 3 y 4.

## Contexto
`acquisition/scanner_panel.py` es un QWidget autónomo, ya probado en hardware (fase 1). La fase 2 lo incorpora a `ecos_gui.py` como pestaña, junto a los controles de adquisición existentes. El punto delicado es que la GUI refresca la señal en vivo desde el SeDaq mientras el escáner debe poder adquirir en cada punto de una secuencia: **nunca puede haber dos accesos simultáneos al SeDaq**.

## Qué hay que averiguar

### 1. Estructura de `ecos_gui.py`
- Clases y widget principal, cómo se construye la ventana y qué disposición tiene (las columnas y zonas que describe la sección 4 de la spec).
- Si ya usa `QTabWidget` en algún sitio, y dónde encajaría la pestaña del escáner con el menor cambio posible.
- Cómo se gestionan las gráficas (grande y pequeña) y si es viable alternar el contenido de la grande sin reescribir su lógica.

### 2. Acceso al SeDaq — lo más importante
- Qué objeto representa el SeDaq, dónde se crea y cómo se comparte.
- Función o funciones concretas de adquisición: firma, parámetros (ventana de muestras, canal, promedios) y qué devuelven.
- Cómo funciona el refresco en vivo: temporizador (`QTimer`), hilo, bucle, frecuencia y si adquiere en el hilo de la GUI o en otro.
- **Si ya existe algún mecanismo de exclusión** (lock, bandera, pausa del temporizador) y cómo se usa.
- Si la adquisición es bloqueante y cuánto tarda aproximadamente, si se puede deducir del código.

### 3. Temperatura (PT100)
- Cómo se lee el Arduino, dónde está fijado el puerto y con qué frecuencia se consulta.
- Si la lectura se puede invocar puntualmente desde otro punto del código, para registrar la temperatura en cada punto de un barrido.

### 4. Pulser y ganancias
- Cómo se fijan ganancia y voltaje, y dónde está el manejo del fallo por el que `SetGain1` resetea `Gain2`.
- Si hay una función para leer la ganancia actual (necesaria para guardarla y restaurarla en las referencias en agua).

### 5. Estimadores de señal
- Qué funciones existen ya para el tiempo de vuelo y la envolvente, dónde están y qué dependencias tienen.
- **Cuáles usan scipy**, dado que el entorno de 32 bits no lo tiene (spec, sección 3). Indicar cuáles habría que portar a numpy y con qué dificultad.

### 6. Guardado
- Cómo se construyen ahora los nombres de archivo y los metadatos (`BD_Experimentos_PVA.py`).
- Qué habría que añadir para el formato de barrido propuesto en la sección 5.6 de la spec, y si el formato propuesto encaja o conviene otro.

## Entrega
Un informe en `analysis_ecos_gui_integration.md` con:
- Un apartado por cada punto anterior, con referencias a archivo y línea.
- **Riesgos y puntos de conflicto** detectados, sobre todo en el acceso compartido al SeDaq.
- **Dos o tres opciones de integración**, con sus ventajas e inconvenientes: por ejemplo, pausar el refresco durante las secuencias frente a servir el refresco desde las propias adquisiciones de la secuencia.
- Una recomendación razonada, indicando qué partes de `ecos_gui.py` habría que tocar y cuánto.
- Lo que no se pueda determinar leyendo el código, señalado explícitamente como duda, sin rellenarlo con suposiciones.

No escribas código de integración ni modifiques ningún archivo existente.
