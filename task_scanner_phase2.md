# Tarea: Fase 2 — integración del escáner en `ecos_gui.py`

Lee antes `scanner_tab_spec.md` (secciones 3 y 4) y `analysis_ecos_gui_integration.md`, que es el análisis del que sale esta tarea. Las referencias `archivo:línea` de abajo vienen de ese informe: **compruébalas antes de editar**, porque el archivo puede haberse movido.

Esta fase **no implementa foco, planitud ni barridos**. Deja montada la estructura y el secuenciador, con una secuencia de prueba que valide el diseño.

## Entorno
- Desarrollo y prueba en el `.venv` de **64 bits**, que tiene scipy. `ecos_gui.py` cae a `_DemoSeDaq` sin hardware, así que la GUI entera arranca.
- **La restricción «sin scipy» queda anulada.** No portes `Envelope` ni `MakeWindow` a numpy: la máquina de adquisición tiene scipy. Reutiliza los estimadores de ECOS tal cual.
- Comentarios y nombres en inglés; textos de la GUI en el idioma que ya use `ecos_gui.py`.

## 1. Arreglos previos (commit aparte, antes de integrar nada)

### 1.1 `_acquire_ch_avg` puede no terminar nunca
`ecos_gui.py:1111-1126`: el bucle no cuenta las capturas que salen todo ceros y reintenta sin límite. Con el hardware desconectado o en fallo, cuelga la sesión sin aviso. Añade un máximo de intentos (por ejemplo, `4 × avg_n`); al superarlo, lanza una excepción con un mensaje claro. El llamador actual debe seguir comportándose igual en el caso normal.

### 1.2 Choque de nombres `Scanner`
Existen `tools/Scanner.py` (driver antiguo, API distinta) y `hardware/scanner/Scanner.py`. `ecos_gui.py` hace `sys.path.insert(0, _TOOLS_DIR)` y `scanner_panel.py` inserta `hardware/scanner/`, así que **el orden decide cuál gana**, con un fallo silencioso si alguna vez se invierte.

Resuélvelo con una importación explícita que no dependa del `sys.path`: convierte `hardware/scanner/` en paquete (`__init__.py`) e importa por ruta de paquete, o carga el módulo por su ruta de archivo con `importlib.util`. `scanner_panel.py` debe seguir funcionando en solitario. **No renombres `tools/Scanner.py`**, que está fuera del alcance de esta tarea.

### 1.3 `RecLen` es estado global
`SetRecLen` (`tools/SeDaq.py:72-75`) fija la ventana para todas las adquisiciones posteriores. Si una secuencia lo cambia, debe guardarlo y restaurarlo al terminar, también si falla. Escribe un pequeño gestor de contexto y úsalo en el secuenciador.

## 2. Pestañas (spec sección 4)
- `_build_left_panel` (`ecos_gui.py:355`): envuelve `self._plot_zoom` como página «A-scan» de un `QTabWidget` nuevo y añade una segunda página «Escáner», de momento vacía, donde irán la curva de foco, las líneas de planitud y el mapa del barrido. **`self._plot_ov` (el overview) no se toca**: ya es la gráfica pequeña siempre visible que pide la spec.
- `_build_right_panel` (`ecos_gui.py:453`): envuelve el `QScrollArea` actual como página «Adquisición» y añade `ScannerPanel` como página «Escáner».
- **Ningún `_build_block_*` cambia**, ni la lógica de curvas, región o cursor.
- Método para llevar la gráfica grande a la pestaña «Escáner» al lanzar una herramienta.

## 3. `ScannerPanel` embebido
- Instánciarlo desde `EcosGUI.__init__` y cablear sus señales igual que hace hoy en solitario.
- `ScannerPanel` no debe crear su propio `QApplication` ni asumir que es ventana de nivel superior. Si hace falta, separa el arranque autónomo (`if __name__ == '__main__'`) del widget.
- El botón de depuración del ciclo de tensión sigue apareciendo solo en modo simulador.
- Al cerrar `EcosGUI`, el worker del escáner se detiene y el puerto se cierra limpiamente.

## 4. Secuenciador genérico (lo nuevo de esta fase)

Dirigido por eventos, en el hilo de la GUI, tal como describe la spec sección 3. **No un bucle ni un hilo aparte.**

- Entrada: lista de posiciones, tiempo de asentamiento (ms), número de promedios y una función de medida por punto que recibe las señales promediadas y devuelve un escalar o una tupla.
- Ciclo por punto: pedir el movimiento al worker → al recibir `moved`, `QTimer.singleShot(asentamiento)` → adquirir en el hilo de la GUI → calcular la medida → emitir `point_done(i, coords, medida)` → siguiente punto.
- Al empezar: `self._timer.stop()`. Al terminar, al pausar o al parar: `self._timer.start(...)`. Siempre en un `finally`, para que un fallo no deje el refresco apagado.
- Pausa, continuar y parar, comprobados entre puntos. El STOP del escáner también aborta la secuencia.
- Emite progreso (`i`, `n`) y tiempo restante estimado.
- Mientras corre, bloquea las acciones incompatibles: adquisición manual, cambio de ganancia y modo de movimiento libre.
- Un único punto donde se comprueba si se puede lanzar una secuencia (`is_free_movement_active()` y los avisos de conexión de la fase 1).

### Temperatura durante una secuencia
- Una sola instancia de `Arduino` abierta al empezar y cerrada al terminar; nada de crear y cerrar por lectura (`ecos_gui.py:1040`).
- Lecturas: al empezar, al terminar y en los puntos que pida quien lance la secuencia (en un barrido de superficie, al acabar cada línea).
- Si no hay Arduino, NaN y aviso al empezar. **Nunca abrir `_ask_manual_temperature` durante una secuencia**: es modal y la bloquearía.

### Secuencia de prueba (solo para validar, no es una herramienta)
Añade en la pestaña «Escáner» un botón de depuración, visible solo en modo simulador, que recorra N puntos equiespaciados en el eje lateral, adquiera en cada uno, calcule la amplitud máxima y la dibuje en la gráfica grande. Sirve para comprobar el ciclo completo antes de implementar el foco.

## 5. No hacer
- Foco, planitud y barridos (fases 3 a 6).
- La función de guardado de barridos (fase 6).
- Portar nada a numpy.
- Cambiar la API de `Scanner`.
- Renombrar `tools/Scanner.py`.

## Verificación
1. `python acquisition/ecos_gui.py` en el `.venv` de 64 bits, sin hardware: arranca con `_DemoSeDaq`, se ven las dos pestañas a cada lado y todo lo que había antes sigue funcionando.
2. La pestaña «Escáner» conecta con el simulador y el movimiento manual funciona igual que en solitario.
3. `python acquisition/scanner_panel.py --sim` sigue funcionando por separado.
4. Secuencia de prueba de 10 puntos: la ventana no se congela, el progreso avanza, la gráfica se actualiza punto a punto, Pausa y Parar responden y, al terminar, el refresco en vivo se reanuda.
5. Parar a mitad y comprobar que el refresco vuelve. Provocar un fallo a mitad (desconectar el simulador) y comprobar que también vuelve.
6. `python -m unittest hardware/scanner/test_sim_scanner.py` sigue pasando.
7. Comprobar que `from Scanner import Scanner` carga el driver correcto con `tools/` en el `sys.path`.

## Commits propuestos
- `fix(ecos-gui): bound _acquire_ch_avg retries; explicit Scanner import; RecLen guard`
- `feat(ecos-gui): tabbed layout with embedded ScannerPanel`
- `feat(scanner): event-driven sequencer with shared SeDaq access`
