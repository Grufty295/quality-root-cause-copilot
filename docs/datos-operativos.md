# Datos operativos: defectos, mantenimiento, equipos y ciclos

`python -m app.seed` carga, además de catálogos y corpus, dos CSV de `data/seed/estructurados/`:

| CSV | Tabla | Filas (dataset actual) |
|---|---|---|
| `eventos_defecto.csv` | `defect_event` | 2 128 (2 644 piezas) |
| `mantenimiento.csv` | `maintenance_order` | 91 |
| `catalogo_equipos.csv` | `equipment` | 26 (8 aplicadores con umbral de PM) |
| `ciclos_aplicador.csv` | `applicator_cycles` | 1 464 días (8 aplicadores × 183) |
| `mediciones_crimpado.csv` | `crimp_measurement` | 3 768 (8 NOK de altura, 15 de tracción) |
| `cambios.csv` | `change_log` | 19 |
| `catalogo_proveedores.csv` | `supplier` | 2 |
| `lotes_material.csv` | `material_lot` | 31 (2.8 M piezas de TRM-A-1064) |
| `produccion.csv` | `production` | 2 826 (157 días × 3 turnos × 2 líneas × 3 partes; 376 mil unidades) |

Si un archivo no existe se omite y el reporte lo dice; no es error. `--dry-run` los valida sin tocar la base.

## Reglas de la carga

- **Todo o nada.** Se lee y valida todo antes de abrir la transacción, y la escritura es una sola transacción
  junto con los catálogos. Los errores salen juntos (hasta 10 filas, con número de fila e id) y el comando termina con código 2.
- **Validación cruzada**: turno `T1..T3`, línea de la planta, defecto en el catálogo, parte de cliente conocida,
  el cliente coincide con el de la parte, la estación pertenece a la línea, se detecta en o después de la fabricación,
  una orden completada trae `fecha_ejecucion` (y solo ella).
- **Idempotente y con el CSV como fuente de verdad.** Upsert por `evento_id` (`defect_event.source_id`) y por
  `ot_id`. Lo que cargó antes y ya no está en el CSV se **borra de esa planta** (el reporte cuenta los obsoletos).
  No se tocan los eventos sin `source_id` (capturados a mano) ni los de otras plantas. Un CSV vacío es error:
  borraría la tabla.

## Dos fechas por evento

- `occurred_at`: **fabricación** (medianoche UTC; el dato es diario).
- `detected_on`: **cuándo lo supo la planta**. Difiere hasta 10 días en los defectos que llegan por `CLIENTE`
  o `LAB` (312 de 2 128).

Las tools del agente filtran por `detected_on <= as_of`. Con la fecha de fabricación un análisis hecho el 25 de
septiembre vería defectos que la planta conoció después (en el dataset, 32 piezas de L1 entre agosto y septiembre).

## Equipos y ciclos

- `equipment` tiene llave `(plant_id, id)`: `APL-L1-01` existe en cada planta. `applicator_cycles` referencia al equipo
  con FK; los ciclos se reemplazan completos para la planta en cada carga. Con el catálogo presente, los aplicadores y
  máquinas de eventos y órdenes se validan contra él (existen, son aplicadores y son de la línea que dicen).
  `ciclos_aplicador.csv` sin el catálogo es error.
- **Regla de ciclos**: los ciclos de un aplicador se reinician con cada servicio completado (preventivo o correctivo).
  *Ciclos desde el último servicio* = suma de los días posteriores a ese servicio hasta la fecha. Reproduce los 71
  `ciclos_al_evento` del dataset (hay una prueba que lo verifica); la única excepción es el correctivo OT-2026-0020,
  que no cuenta los ciclos de su propio día (unos 18 000, 3.5 %).
- La tool `get_applicator_wear` entrega esa cifra contra `umbral_pm_ciclos`, las PM sin ejecutar posteriores al último
  servicio y los huecos o el fin de los datos. Un servicio completado después del corte no cuenta.

Lo que muestra en los datos: `APL-L1-02` llegó al 30 de abril con 485 mil ciclos (194 % del umbral) y tres PM
reprogramadas; `APL-L2-01` estaba al 164 % el 10 de septiembre con dos PM sin ejecutar.

## Mediciones de crimpado

- Una fila por aplicador, día, turno y combinación terminal / cable. Se reemplazan completas para la planta en cada
  carga. Requiere el catálogo de equipos. Se valida que la prensa sea la que aloja al aplicador, que el terminal sea
  el que crimpa ese aplicador, que los límites sean coherentes y que `OK`/`NOK` corresponda a los valores.
  `height_ok` y `pull_ok` son columnas generadas por la base, no se confía en las del CSV.
- La tool `get_crimp_measurements` resume por aplicador la **posición de la altura en su banda** (0 = límite inferior,
  1 = superior) y el **margen de tracción** sobre el mínimo, y con un equipo concreto agrega la tendencia semanal.
  Así se ve una deriva semanas antes de la primera pieza NOK y sirve para familias con bandas distintas.
- El texto libre de `accion` no se cita: solo se cuenta cuántas NOK se re-midieron sobre la misma pieza y cuántas se
  repitieron con nueva muestra (no son excluyentes).
- Lo que muestra en los datos: `APL-L2-01` sube de 0.53 a 1.00 de posición entre agosto y fines de septiembre
  (tracción de +23 % a −3 %); la deriva se nota desde el 5–8 de septiembre y la primera NOK es del 22 (unas dos semanas después). De las 18
  mediciones NOK, ninguna detuvo la producción: todas se re-midieron o repitieron y se continuó.

## Bitácora de cambios y lotes de material

- **Cambios**: un cambio puede tocar varias líneas y equipos (`"L1, L2"`, `"BRD-L1, BRD-L2"`), por eso son arreglos
  sin FK; la carga los valida contra el catálogo (el equipo existe y es de una línea que el cambio declara).
  `tablero_actualizado` y `programa_prueba_actualizado` conservan el texto de la planta: **"No" y vacío son cosas
  distintas** (no se actualizó vs. no aplica), y la tool no inventa un "No" donde no hay dato. El tipo debe ser uno de
  los cinco conocidos; uno nuevo es error a propósito, para que un typo no cree una categoría.
- **Proveedores**: `catalogo_proveedores.csv` es un catálogo global (como clientes y partes): se actualiza, no se borra,
  porque los lotes lo referencian por FK. `lotes_material.csv` sin él es error. Cada lote debe tener un proveedor del
  catálogo, con el mismo nombre, que suministre esa parte.
- **Lotes**: los consumen ambas líneas, así que no tienen línea. Cada lote debe ser de un terminal que algún aplicador
  del catálogo crimpa.
- **Trazabilidad cruzada**: con los dos archivos presentes, cada evento con lote debe existir en `lotes_material.csv`,
  ser de la misma parte y haberse fabricado dentro de la ventana de consumo del lote. Los 1 063 eventos con lote del
  dataset lo cumplen. No hay FK: es una validación de la carga, para no atar el orden ni el reemplazo de los CSV.
- Las dos tablas se reemplazan completas para la planta en cada carga.
- Tools: `get_change_log` (cambios que tocan la línea, del más antiguo al más reciente) y `get_material_lots` (lotes
  cuya ventana de consumo traslapa el rango). Con `as_of`, un lote cuyo consumo termina después del corte aparece "en
  consumo", sin fecha de fin ni estado final: ese estado todavía no se conoce.
- Dato a vigilar: `LT-A-2606-07` se recibió el 2026-06-17 y su tipo de inspección ya cita `SCAR-2026-007`, cuyo
  consumo detenido (`LT-A-2605-06`) es del 19. Si el SCAR se abrió antes del paro es coherente; si no, es una fuga de
  información posterior en el dato de origen.

## Producción y tasas de defecto

- Una fila por día, turno, línea y número de parte de cliente (cada número de parte es una variante). Se valida que la
  parte exista, que el cliente corresponda, que una parte no aparezca con dos variantes y que no haya filas repetidas.
  Se reemplaza completa para la planta en cada carga.
- **Cruce con eventos**: cada defecto necesita producción ese día, turno, línea y parte, y las piezas defectuosas no
  pueden exceder lo producido. Los 2 128 eventos del dataset lo cumplen (la peor celda es 9.2 %).
- `get_defect_summary` agrega **tasa por mil de unidades**. El denominador depende de la agrupación: por turno, día,
  semana y parte usa la producción de ese grupo; por estación, familia y punto de detección, la de toda la línea (lo
  dice el texto); por aplicador y lote no hay denominador y no se inventa. Sin producción en el rango lo dice.
- Nueva agrupación **por parte** (`parte`): es la forma de ver una variante (E10 solo aparece ahí: en el rango del
  17 de agosto al 13 de septiembre la variante Alta tiene 9.5 por mil en L1 contra 5.8 y 6.2 de las otras).
  Es solo de D4: trae partes de clientes confidenciales y mandaría un D2 interno a local.
- **Sesgo de rezago**: los defectos que detecta el cliente o el laboratorio llegan hasta 10 días después de fabricar, así
  que la tasa de los últimos 10 días antes del corte está subestimada. La tool lo avisa cuando el rango termina en esa
  ventana. Cuidado al redactar avisos: una frase como «reclamos de cliente» activa un marcador del clasificador y manda
  el D2 a local aunque el dato sea interno.

## Qué no se carga todavía

Todos los CSV de `estructurados/` con datos operativos están cargados. Quedan fuera `ncr.csv` (es la misma información
que el corpus de NCR, en forma tabular, para la UI) y `usuarios_demo.csv` (se usa para el roster de demo). Los lotes y números de parte de terminal de
`defect_event` son texto sin FK hasta que existan esos catálogos. `defect_event` no trae causa, a propósito.
