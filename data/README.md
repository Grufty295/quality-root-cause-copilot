# Datos sintéticos del Agente 8D

Planta ficticia: **Cablenova México, planta Juárez**. Arneses de puerta delantera, 2 líneas (L1, L2), 3 turnos, producción de lunes a sábado del 1 de abril al 30 de septiembre de 2026. Todos los nombres de clientes, proveedores, personas y números de parte son inventados; los valores numéricos son supuestos de modelado.

## Regenerar y validar

```bash
python data/generator/generate.py      # semilla 42, reproducible
python data/generator/validate.py      # comprueba firmas, casos de evaluación y clasificación
```

Solo usa la biblioteca estándar de Python 3.10+.

## Qué hay y quién lo usa

| Carpeta | Contenido | Lo usa |
|---|---|---|
| `seed/corpus/documentos/` | 15 documentos: AMEF (catálogo de causas RC-01 a RC-20), plan de control, 7 instrucciones de trabajo, 4 SOPs (incluye catálogo de no detección ND-01 a ND-08), especificación de crimpado y CSR del cliente | Índice RAG |
| `seed/corpus/ncr/` | 80 NCRs históricas | Índice RAG |
| `seed/corpus/8d/` | 6 reportes 8D cerrados | Índice RAG |
| `seed/estructurados/` | CSVs de producción, defectos, crimpado, ciclos, mantenimiento, lotes, cambios y catálogos | Tools del agente |
| `../evals/` | Casos de evaluación, documentos adversariales y verdad de fondo | Solo la suite de evals; **nunca se indexa** |

Cada documento del corpus tiene front matter con `doc_id`, `tipo`, `fecha`, `lineas`, `clientes`, `confidencialidad` y `contiene_pii`. La ingesta debe copiar esos campos a cada fragmento.

## Reglas que la implementación debe respetar

- **Confidencialidad:** un documento es `confidencial` si menciona a Norvane Motors, un número de parte `A7-DRH-…` o el programa Halcón. El validador lo comprueba. El clasificador del router debe aplicar la misma regla al texto de entrada y a los resultados de las tools (que también contienen números de parte de Norvane).
- **Permisos:** un documento es visible para un usuario si sus `lineas` se intersecan con las del usuario (`usuarios_demo.csv`).
- **PII:** las NCRs y los 8D incluyen nombres y números de empleado ficticios (campo "Reportado por", equipos D1). Se seudonimizan siempre.
- **`as_of`:** los casos de evaluación traen una fecha. Las tools filtran por `fecha_deteccion <= as_of` (defectos) o `fecha <= as_of` (resto), y la recuperación excluye documentos con `fecha` posterior. Sin esto el agente vería el futuro (por ejemplo, la corrección de una receta).
- **Fecha de defecto:** `fecha_fabricacion` viene de la trazabilidad de la etiqueta; `fecha_deteccion` es cuando se encontró (los reclamos de cliente llegan 3 a 10 días después).

## Tablas y tools

| Tool | Tablas | Campos clave |
|---|---|---|
| `get_defect_summary` | `eventos_defecto.csv`, `produccion.csv` | Agrupar por `aplicador_id`, `lote_terminal`, `estacion_origen`, `turno`, `variante`, `numero_parte_cable`, `linea`; tasa por unidades producidas |
| `get_crimp_measurements` | `mediciones_crimpado.csv` | 1 lectura de altura y 1 de tracción por aplicador y turno; `resultado_*` y `accion` muestran re-mediciones aceptadas |
| `get_maintenance_history` | `mantenimiento.csv`, `ciclos_aplicador.csv`, `catalogo_equipos.csv` | Ciclos desde el último PM completado contra `umbral_pm_ciclos`; OTs reprogramadas con motivo |
| `get_change_log` | `cambios.csv` | Recetas, ECN (con `tablero_actualizado` y `programa_prueba_actualizado`), cambios de mano de obra y herramienta |
| `get_material_lots` | `lotes_material.csv` | Lote, proveedor, tipo de inspección de recibo y ventana de consumo |

`ncr.csv` es la misma información que `corpus/ncr/` en forma tabular, para la UI.

## Escenarios (resumen)

La verdad de fondo completa está en `evals/episodios_verdad.json`.

| Episodio | Causa | Cuándo | 8D en el corpus | Firma |
|---|---|---|---|---|
| H1 | RC-01 desgaste de APL-L1-02 | abril | 8D-2026-011 | Un aplicador, tres turnos, altura sube, ciclos sobre el umbral |
| H2 | RC-02 lote de TRM-A-1064 | junio | 8D-2026-019 | Un lote, ambas líneas, crimpado normal |
| H3 | RC-04 receta de corte en CUT-L1-01 | julio | 8D-2026-024 | Un cable (WIR-050), salto tras cambio de receta |
| E6 | RC-01 desgaste de APL-L2-01 | septiembre | No (recurrente de 8D-2026-011) | Igual que H1, en L2 |
| E7 | RC-02 lote de TRM-B-2150 | septiembre | No (recurrente de 8D-2026-019) | Igual que H2, otra terminal |
| E8 | RC-03 inserción en INS-L1-02 T3 | agosto | No (causa nueva) | Una estación y un turno, desde ingreso de personal |
| E9 | RC-04 receta de corte en CUT-L2-01 | agosto | No (recurrente de 8D-2026-024) | Igual que H3, en L2 |
| E10 | RC-05 ECN-2026-031 no implementado | agosto-septiembre | No (causa nueva) | Solo variante Alta, ambas líneas, reclamos de cliente |
| N1-N3 | RC-14, RC-12, RC-15 | mayo, junio, agosto | 8D-2026-013, -021, -027 | Ruido con causas fuera de los 5 escenarios |

Las recurrencias son intencionales: cada 8D histórico deja una acción de despliegue horizontal pendiente o mal acotada en su D7, y el episodio de evaluación ocurre por ese hueco.

## Evals

| Archivo | Casos | Qué mide |
|---|---|---|
| `casos_calidad.jsonl` | 20 (4 por episodio E6-E10) | Causa de ocurrencia (código exacto), no detección (código o alternas aceptables), recurrencia y 8D citado, nivel mínimo de confidencialidad |
| `casos_adversariales.jsonl` | 10 | Inyección en la NCR y en documentos, exfiltración, acción no permitida, confidencial oculto, PII |
| `casos_permisos.jsonl` | 6 | Filtro por línea en búsqueda, análisis fuera de alcance, auditor sin aprobación, quien redacta no aprueba |
| `documentos_adversariales/` | 2 | Se inyectan en la recuperación solo durante los casos ADV-06 y ADV-07 |

EV-01 es el caso de la demo.

## Supuestos de modelado

- La altura de crimpado de familia A deriva 0.010 mm por cada 100,000 ciclos sobre 300,000 desde el último PM; la tracción baja en proporción. Las lecturas individuales casi siempre siguen dentro de especificación (supuesto alineado con USCAR-21: altura en rango no garantiza un crimpado conforme).
- Un aplicador de familia A acumula unos 19,000 ciclos por día; el PM cada 2 semanas lo mantiene por debajo de 250,000.
- Tasas de defecto base por línea-turno en `generator/config.py`.
