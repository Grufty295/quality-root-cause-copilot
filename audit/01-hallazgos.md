# Fase 1 — Hallazgos verificables antes de optimizar D2/D4

## Primero: el instrumento no acredita «causa respaldada»

**RIESGO-01 — Interpretar exactitud de etiquetas como causa respaldada excede el contrato de `pass`.** Severidad **alta**; impacto esperado **alto** sobre interpretación de calidad; confianza **alta**; **leído y ejecutado previamente con entradas sintéticas**. No es un bug de implementación: la documentación inicial de `apps/api/app/evalkit/scoring.py:3–22` define expresamente exactitud RC/ND e incluye el caso de abstención con códigos correctos. `:77–115` implementa ese contrato: `pass = rank == 1 and nd in acceptable_nd`, sin condicionar a estado, suficiencia, citas ni respaldo semántico. La sonda histórica ilustró ese alcance:

```text
SCORING {"pass": true, "abstained": true, "abstention_correct": true}
UNSUPPORTED {"pass": true, "abstention_correct": false}
```

La segunda entrada declara un candidato respaldado pese a que la etiqueta pide abstención y no aporta evidencia; `pass` sigue midiendo correctamente exactitud de códigos, no esa propiedad adicional. **El riesgo es de interpretación; no demuestra uso indebido por el usuario ni invalidez histórica.** Los registros dev examinados no contienen abstenciones; no se ha recalificado su evidencia semántica. Un futuro `strict_success` sería un endpoint nuevo y versionado, no una reparación del contrato legado. `rc_top3` también significa «presente en la lista», sin cortar en tres (`scoring.py:98`); el esquema actual sí limita la lista a tres.

**BUG-02 — `paired` y `aggregate` comparan poblaciones distintas.** Severidad **alta**; impacto esperado **alto** en decisiones experimentales cuando hay inválidas o repeticiones desbalanceadas; confianza **alta**; **leído y ejecutado sintético**. `evalkit/agent.py:399` excluye inválidas; `:529–539` no las excluye ni agrupa por episodio o empareja repetición/configuración. Con base = [acierto, timeout inválido] y enlace = [acierto, acierto], mismo caso sintético:

```text
DENOMINATORS {"aggregate": [["base", 1.0, 0.5], ["enlace", 1.0, 0.0]],
 "paired": {"a": "base", "b": "enlace", "mejora": ["SYNTH-001"], "empeora": [], "igual": []}}
```

El empate de tasas válidas se presenta como mejora pareada. No se afirma que este mecanismo haya afectado los archivos dev inspeccionados: no presentan un campo `error` con valor, aunque eso por sí solo no sustituye `classify_run`.

## 1. Alcance y resultado ejecutivo

- **No implementar todavía.** Hay fallos deterministas reproducidos en clasificación del respaldo, selección final, atribución y cobertura de confidencialidad. Añadir una medida de respaldo distinta de la exactitud de etiquetas requiere decisión explícita posterior; no se redefine ni se declara defectuoso el contrato de `pass` legado.
- Único archivo creado: `audit/01-hallazgos.md`. Se conserva `audit/00-mapa.md`, SHA-256 `2ce9f4cfbfa17f079516000688d4d8b413a98509ba608678cb0f8b08f6fa90c4`.
- HEAD comprobado: `8431e64629be4d3f9acb250d5ec67bc06e102e51`. Las líneas citadas corresponden al **árbol sucio preexistente**, no necesariamente a HEAD. Las huellas de graph/tools/manifest/repository/evalkit-agent coinciden con fase 0.
- Skill leída primero: `C:/Users/sebas/.config/opencode/skills/cognitive-doc-design/SKILL.md`. Se leyó después el mapa completo. No se delegó, no se inició SDD ni CodeGraph: se respetó el fallo de índice documentado y se usaron lecturas acotadas.
- **Ejecutado ahora:** SQL `BEGIN READ ONLY … ROLLBACK`, chunker/frontmatter puros, puntuación/guardrails puros y expresiones AST aisladas con objetos sintéticos. No se construyó un runtime, grafo operativo, gateway, cliente HTTP ni embedder.
- **Leído ahora:** fuente genérica; 15 documentos estáticos; exclusivamente los 8D históricos `8D-2026-011` y `8D-2026-019`; EV-01..12; dos archivos cuyo nombre empieza por `dev-` y cuyas filas se validaron antes de leer su payload.
- **No examinado ni ejecutado:** payloads/verdad de E9/E10, EV-13..20, resultados test o mixtos, verdad JSON completa, generadores/validator importados, suites amplias, LLM/proveedores, ingesta, regeneración, instalaciones, cambios del entorno o llamadas externas. Se listaron nombres de archivos de resultados, no su contenido, salvo los dos dev expresamente indicados.

### Evidencia cuantitativa disponible

| Medición | Resultado | Alcance exacto |
|---|---|---|
| Chunks documentales reales | 15 documentos, 93 chunks; min 90, p50 392, p90 539, p95 547, media 378,11, máx. 662 caracteres | SQL del índice y ejecución local del chunker coinciden en distribución; no es toda la DB |
| Sobre presupuesto nominal | 4/93 >550; 0/93 >1400 | No demuestra truncamiento de embeddings; no son tokens |
| Filas de catálogo | 20 RC + 8 ND, 28 códigos únicos, todos presentes en su chunk | Documentos estáticos; 20/28 cuerpos exceden los 260 caracteres del catálogo renderizado |
| D4 históricos permitidos | 5 chunks en -011 y 3 en -019; todos repiten documento y encabezado causal | 8 fragmentos; no son nuevos resultados de recuperación |
| Recuperación léxica dev/documental | RC esperada top-6: 6/12; presente en candidatos top-50: 12/12 | Solo controles de la lista blanca documental; no híbrido ni vector; ancla RC, no qrels completas |
| ND canónica en esa prueba | top-6: 0/12; top-50: 1/12; cualquier coincidencia léxica: 6/12 | No mide ND alternativas aceptables; catálogo completo entra al prompt por otra vía |
| Contraejemplos | Cinco mecanismos de fase 0 reproducidos, además de dos límites del scoring | Entradas sintéticas, no frecuencia en producción |

## 2. A — Recuperación y chunking

### RIESGO-03 — Fragmentos identificables no siempre equivalen a explicación autocontenida

Severidad **media**; impacto esperado **medio**; confianza **alta** en estructura, **media** en efecto sobre inferencia; **leído + ejecutado documental**.

`retrieval/chunker.py:76–105,219–237,243–282` conserva filas RC/ND atómicas y separa D4 por subsección. En los D4 permitidos se midieron longitudes **[471,478,153,466,383]** y **[335,348,234]**. Todos repiten el documento y «Causa de ocurrencia … RC» o «Causa de no detección … ND». No hay pérdida del código en esos encabezados.

Sin embargo, el quinto «porqué» de -011 queda solo en 153 caracteres y necesita el razonamiento anterior; la verificación de -019 conserva RC-02 pero ya no repite terminal/lote. Son unidades citables con identidad, no necesariamente unidades causales autosuficientes. Una oración sintética de 2000 caracteres produjo **un chunk de 2019**: 550 es presupuesto de agrupación, no tope duro. No se justifica aumentar tamaños por intuición ni declarar roto el chunker por sus cuatro filas largas.

### RIESGO-04 — La consulta de síntomas y la fusión pueden ocultar el discriminador

Severidad **media**; impacto esperado **alto** para priorización de evidencia; confianza **alta** en medición léxica, **media** en extrapolación; **leído + ejecutado dev/documental**.

`agent/graph.py:93–96,364–372` solo usa descripción + parte, colapsa espacios y corta a 600 caracteres. No utiliza los discriminadores ya recolectados por tools. El número de parte al final puede desaparecer con descripciones largas. La NCR completa sí llega al generador.

Se reprodujeron OR léxico español, códigos normalizados/prefijo, desempate UUID, permiso, tipo y fecha de `retrieval/repository.py:39–67`, restringiendo además candidatos a los 15 documentos estáticos. Las posiciones siguientes son **medidas**, no propuestas:

| Caso / episodio | Rango RC canónica | Rango ND canónica |
|---|---:|---:|
| EV-01 / E6 | 17 | sin coincidencia |
| EV-02 / E6 | 13 | 51 |
| EV-03 / E6 | 36 | sin coincidencia |
| EV-04 / E6 | 33 | sin coincidencia |
| EV-05 / E7 | 8 | sin coincidencia |
| EV-06 / E7 | 3 | 53 |
| EV-07 / E7 | 5 | sin coincidencia |
| EV-08 / E7 | 4 | sin coincidencia |
| EV-09 / E8 | 1 | 55 |
| EV-10 / E8 | 9 | 58 |
| EV-11 / E8 | 3 | 50 |
| EV-12 / E8 | 5 | 61 |

Esto separa **candidatura** de **ranking**: RC existe en los primeros 50 en los doce casos, pero seis quedan fuera de top-6; para ND, parte del problema precede al ranking porque seis ni siquiera coinciden léxicamente. No es Recall@6 de todas las fuentes relevantes. Tampoco implica que el generador carezca de esos códigos: recibe todo el catálogo.

Una segunda sonda con consultas causales manuales, **informadas por la etiqueta y no generadas automáticamente desde tools**, dio rangos RC/ND: **E6 1/18; E7 1/10; E8 1/13**. Las consultas fueron respectivamente desgaste/ciclos/deriva, lanza/proveedor/lote/certificado e inserción/TPA/empuje-jalón. Es una sonda de sensibilidad léxica con información privilegiada, **no una mejora del agente ni un benchmark independiente**.

El híbrido usa 50 candidatos por rama, RRF k=60 y pesos 1:1, no un reranker (`repository.py:26–31,69–106`). Un fragmento en ambas ramas puede superar al primero vectorial presente solo en una; top-k fusionado **no es** top-k vectorial. No se midieron hit@k, Recall, MRR o nDCG vectoriales/híbridos. La DB sí estaba disponible; el bloqueo fue demostrar carga local de embeddings sin descarga: caché default `/tmp/fastembed_cache` ausente y `/tmp` vacío en API; una comprobación de `/root/.cache/fastembed` recibió `PermissionError`. No se cambió usuario, entorno ni se buscó un bypass. No se excluye una caché configurada en otra ruta; no se inspeccionaron valores del entorno para resolverlo.

### RIESGO-05 — Metadatos disponibles no equivalen a filtros de aplicabilidad causal

Severidad **media**; impacto esperado **alto**; confianza **alta**; **SQL y fuente leídos**, medición limitada a documentos permitidos.

En AMEF/SOP se verificaron metadatos de revisión, líneas [L1,L2], fecha, clientes y versión/hash. Sus 36 chunks tienen planta/fecha, pero `line_id` y `defect_family_id` nulos. En estos documentos, línea nula representa ámbito de planta, no necesariamente un dato perdido (`ingest/service.py:162–174`). SearchHit ofrece documento/sección/fecha/planta/línea/confidencialidad, no terminal, aplicador, proveedor o lote estructurados (`retrieval/models.py:73–93`).

SQL filtra permisos, fecha, tipos y exclusiones **antes** del ranking; no filtra por parte/terminal/defecto de la NCR (`repository.py:39–45`). Un usuario autorizado a L1/L2 puede recibir un precedente de otra línea: esto es necesario para E6 y no constituye por sí mismo fuga de permisos. La coincidencia de códigos es por prefijo, no un filtro duro de parte. Documentos sin fecha pasan `as_of`. Producción no limita fragmentos por documento; una página puede ocupar varias posiciones. Cuarentena se aplica después del top-k sin reposición (`graph.py:391–414`). No se ha medido la tasa de distractores adversariales ni falsos positivos de cuarentena.

### OPORTUNIDAD-06 — Verificar aplicabilidad E6/E7 antes de promover el precedente

Severidad **media**; impacto esperado **alto**; confianza **alta** en señales necesarias, **no verificada** la ganancia.

EV-01..04/E6 requieren distinguir desgaste de aplicador familia A en L2 de lote/inserción. -011 es de otro aplicador y línea: transfiere mecanismo, no prueba identidad del equipo. EV-05..08/E7 requieren diferenciar lanza de terminal/lote del proveedor de inserción deficiente y desgaste; -019 corresponde a otra terminal/lote. EV-07 comparte intermitencia/L2/septiembre con E6: esos atributos no bastan para causalidad. Las señales de lote, ciclos y crimpado importan más que la similitud narrativa. No se ha demostrado con esta sonda que un enlace concreto correcto/incorrecto haya sido recuperado para cada caso.

**Prefijos y normalización verificados:** `retrieval/embedder.py:77–89` añade `passage: ` y `query: ` explícitamente; `_check` solo revisa dimensión y no normaliza. En DB, la norma media de vectores fue **27,424495** (AMEF) y **28,511254** (SOP), con modelo guardado `intfloat/multilingual-e5-large`: no son unitarios. Se utiliza distancia **coseno** `<=>`; por ello no se concluye un fallo de similitud por falta de norma unitaria. No se verificaron tokens realmente consumidos, truncamiento ONNX ni normalización efectiva de consultas nuevas.

## 3. B — Agente, guardrails y presentación

### BUG-07 — Dedupe convierte catálogo en supuesto respaldo de caso

Severidad **alta**; impacto esperado **alto** sobre abstención/soporte; confianza **alta**; **reproducido con EvidenceBook y guardrail reales, entradas sintéticas**.

`evidence.py:86–88` devuelve el fragmento existente sin incorporar `catalog_code`; `guardrails/output.py:272–275` interpreta catálogo nulo como fuente ajena al catálogo. Sin cambiar el contenido de las cuatro fuentes sintéticas:

```text
CATALOG_DEDUPE [
 {"retrieved_first": false, "estado": "evidencia_insuficiente", "respaldo": "solo_catalogo", "violations": []},
 {"retrieved_first": true, "estado": "candidato_respaldado", "respaldo": "caso", "violations": []}]
```

El control negativo es catálogo incorporado directamente; el positivo reproduce el orden recuperación→catálogo del runtime. No se midió cuántas corridas archivadas sufren el efecto.

### BUG-08 — La selección final puede perder ND válida

Severidad **alta**; impacto esperado **alto** sobre D4 íntegro; confianza **alta**; **expresión exacta AST ejecutada con objetos inertes**.

`graph.py:498–503` solo compara cantidad de RC; en empate gana la propuesta nueva. La sonda con pequeña=3 RC + ND válida y grande=3 RC + ND nula conservó **grande, ND=null**. Ni ND, estado, semántica ni severidad del descarte participan en la selección. El resultado parcial es legal en `schemas.py:131–139`; no es un fallo de Pydantic. No se midió incidencia histórica.

### BUG-09 — Etiqueta del modelo y contenido seleccionado pueden divergir

Severidad **media**; impacto esperado **alto** para trazabilidad/comparación por modelo; confianza **alta**; **expresiones AST reproducidas**.

`graph.py:591` actualiza el modelo antes del guardrail/selección. Con pequeña=3 RC y grande=2 RC, quedó **contenido pequeño** y etiqueta **SYNTH-LARGE**. `service.py:340–354` persiste esa etiqueta. Las llamadas individuales siguen trazables; el campo del borrador no garantiza autoría del contenido retenido. Esto es distinto de que dos tiers usen el mismo nombre de modelo en ciertos archivos dev.

### RIESGO-10 — Anclaje y orden de presentación no se resuelven con más texto

Severidad **media**; impacto esperado **alto**; confianza **alta** en orden, **media** en efecto; **leído**, sin experimento LLM.

Orden real D4: schema-system → sistema D4 → NCR → D2 opcional → fuentes → catálogo RC → catálogo ND → revisión → instrucción final (`llm/structured.py:71`; `prompts.py:102–119`). En fuentes: tools, casos, controles y D4 enlazados por el orden de inserción; las filas listadas como catálogo no se imprimen otra vez allí (`graph.py:296–414,460–465`). Los enlaces siguen orden de hits, máximo dos, no una prueba causal (`graph.py:74–90`). Se calculan antes de cuarentena. El catálogo queda después de precedentes y antes de feedback; el cuerpo de cada entrada se reduce a 260 caracteres. Se midieron **20 entradas >260**: no puede suponerse que controles/detección completos de cada fila sean visibles al modelo.

Las instrucciones piden exactamente tres RC aun cuando no haya evidencia para preferirlas; a la vez ordenan no inventar y permiten abstención (`prompts.py:45–57`). No es contradicción lógica absoluta: son tres hipótesis, pero sí presión de formato hacia un ranking sin información suficiente. El schema repite cardinalidad; las reglas comunes repiten citas/no invención. No hay medición que atribuya errores a esa redundancia. La revisión conserva IDs antiguos sin remapearlos (`prompts.py:154–178`), por lo que F1 anterior puede referirse ahora a otra fuente.

### RIESGO-11 — Existencia de cita no demuestra respaldo semántico

Severidad **alta**; impacto esperado **alto**; confianza **alta**; **leído + contraejemplo de catálogo**.

El guardrail acepta un F# con el código, fuentes existentes y texto que no activa culpa/cierre; una T# positiva cuenta como apoyo de caso aunque sea irrelevante (`guardrails/output.py:179–188,218–275`). No contrasta cantidades, dirección de tendencia, pertenencia de lote ni consistencia RC→ND. D2 valida contra el libro completo aunque solo recibe estación/turno (`graph.py:416–438`; `output.py:97–109`). La revisión semántica humana sigue siendo necesaria; no se ejecutó juez LLM.

### OPORTUNIDAD-12 — Presupuesto y razonamiento: medir por etapa, no asumir determinismo

Severidad **media**; impacto esperado **medio/alto** en coste y latencia; confianza **alta** en código/registros, **no verificada** la ganancia.

- Sistemas D2/D4: 1284/2401 caracteres medidos en fase 0. Ahora schema JSON = **895/1773** y mensaje completo de schema = **1023/1901** caracteres. No hay tokenizador del modelo demostrado ni total de prompt actual: **no convertir estos caracteres en tokens medidos**.
- Hay tokens históricos reales reportados en los registros dev (§5), pero `input_tokens` suma generaciones/reintentos; no equivale a una sola entrada ni a tokens únicos. Tools sin presupuesto global y salida máxima 8192 son límites distintos.
- D2 usa tier pequeño (`llm/router.py:23–28`) y no tiene configuración propia de effort en el request; `DestinationSettings.extra_body` es por destino y se mezcla en el cuerpo HTTP (`config.py:74–78`; `openai_compat.py:107–119`). Se permite transmitir una opción de razonamiento si el proveedor la admite; no se verificó soporte efectivo ni valor desplegado. No se propone una sintaxis externa no comprobada.
- `temperature=0` **ya está** en `gateway.py:151–155`. No elimina por contrato diferencias de backend, cuantización, scheduling o razonamiento. Los tiers de los dos archivos dev inspeccionados usan el mismo identificador; eso no prueba pesos, backend o muestreo idénticos ni la configuración actual.
- Voting de tres ejecuciones multiplicaría aproximadamente por tres llamadas/tokens de la política elegida, más adjudicación; compartir recuperación solo ahorraría esa recolección. Como orientación aritmética de registros, ctl costó 0,2293408824 USD/36 ≈0,00637 USD por corrida; tres serían ≈0,01911 USD antes de adjudicar, **no un presupuesto garantizado ni una ganancia medida**. Votos correlacionados y códigos correctos sin evidencia no resuelven RIESGO-01, BUG-07 ni RIESGO-11.

### RIESGO-13 — `finish_reason` existe, pero no controla el tratamiento del corte

Severidad **media**; impacto esperado **alto** en reintentos/coste; confianza **alta**; **fuente y archivo dev**.

Se parsea `finish_reason`, se audita y se resume `length` (`openai_compat.py:149–166`; `gateway.py:299–308`; `evalkit/agent.py:159–163,435–437`). No está pendiente implementarlo. `structured.py:75–95` intenta parsear y reintenta errores sin ramificar por `finish_reason`; JSON válido con `length` puede aceptarse, JSON roto recibe corrección genérica. No hay política específica para presupuesto agotado ni razonamiento excesivo. En `dev-ds` se observaron tres `length`, en `dev-ctl` cero; no se infiere que correspondan a las tres truncaciones de cualquier otra serie citada por el usuario.

## 4. C — Tools, discriminadores y relojes

### RIESGO-14 — Señales existen, pero sus cortes no están alineados con la hipótesis

Severidad **media**; impacto esperado **alto**; confianza **alta** en interfaces, **media** en suficiencia de cada caso; **leído**, sin ejecución sobre datos estructurados mixtos.

| Discriminador | Disponible | Límite que importa |
|---|---|---|
| Lote/terminal/proveedor | Resumen por lote y cobertura; lotes con parte/proveedor/inspección/ventana | Lotes se filtran por planta, no por línea; el grafo no pasa parte. No hay denominador de producción por lote |
| Aplicador/ciclos/PM | Desgaste con familia, terminal, prensa, servicio, umbral y PM pendiente | Agrupación de defectos por aplicador no tiene denominador propio; correlación no es causalidad |
| Turno/estación | Conteos y producción por turno; estación con tasa sobre producción de línea | No hay corte conjunto estación×turno; detectar «una estación y un turno» no demuestra que ambas concentraciones correspondan a los mismos eventos |
| Crimpado | Altura normalizada, margen, NOK, re-medición | La tendencia semanal solo se añade con `equipment`; el grafo no lo pasa y recibe agregados de 60 días |
| Fechas/cambios | Cambios con equipo, fecha, revisión, variante e implementación | Ventana de 90 días, no necesariamente inicio real del síntoma; no filtro de parte/equipo en grafo |
| Población afectada | Parte, semana y producción | Defectos de toda la línea/familias; la NCR no restringe esos datos a su propio defecto |

Fuentes: `tools.py:180–334,336–404,406–481,483–602,604–675`; `graph.py:296–342`. Los límites 40 grupos/25 filas sí anuncian truncamiento por filas; **no es silencioso** en esas tablas. Sí se recortan motivo/notas a 160+160 caracteres y descripción de cambios a 400 sin marcador de texto recortado (`tools.py:395–398,815`). Desgaste/crimpado carecen de límite global de grupos. El intervalo `fin−30` a `fin` incluye 31 fechas. No se cuantificó el volumen de registros omitidos.

Las fechas narrativas de fabricación —por ejemplo, 14–19 de septiembre en EV-01— no ajustan esas ventanas programadas: la descripción permanece como texto y `graph.py:305–341` calcula rangos a partir de `end`, no de un intervalo extraído del relato. No se observó resolución específica de expresiones relativas («hace dos semanas») en la ruta examinada. Fecha del reporte y fecha causal del cambio no deben confundirse.

### RIESGO-15 — Replay requiere separar fecha del evento, del reporte y del conocimiento

Severidad **alta**; impacto esperado **alto** sobre evaluación; confianza **alta** en mecanismo, **no verificada** su ocurrencia histórica.

`tools.py:203–212,737–748` separa fabricación de detección, pero sin `as_of` el conocimiento llega hasta hoy. Mantenimiento oculta fecha/estado/ciclos futuros, **no** notas/motivos futuros (`:387–398`). Lotes oculta fin/estado, no versiona el resultado de inspección (`:824–833`). No existe una fecha independiente de conocimiento de esos textos en las interfaces leídas. La fuga es posible si se actualizan posteriormente; no se demostró una fila contaminada.

`SearchQuery.exclude_sources` permite evitar citar la propia NCR (`retrieval/models.py:59–62`), pero runtime no puede deducir por sí solo toda relación documental futura. `as_of` no excluye un documento del mismo día. El harness crea otra NCR con fecha de reporte = as_of y solicita solo D4 (`evalkit/agent.py:78–105`); no debe confundirse con un replay universal del histórico. Una evidencia temporalmente posterior no se vuelve admisible por estar presente hoy.

**Conversión dev verificada por lectura:** EV-05 declara L1,L2, pero `ncr_draft` conserva solo la primera línea; turno vacío se transforma a 1 (`agent.py:57–68`). Esto explica un límite del insumo, no valida la firma multilateral de E7. Las señales contrafactuales entre líneas requieren evidencia autorizada adicional; no se ejecutaron agregaciones amplias que pudieran alcanzar escenarios sellados.

## 5. Registros dev permitidos: qué se observó realmente

Se autorizaron por nombre `dev-ctl.runs.jsonl` y `dev-ds.runs.jsonl`; antes de deserializar cada fila se exigieron **EV-01..12 + E6/E7/E8 + split=dev** en su prefijo. El parser falla antes del resto de la fila si no se cumple. No se abrieron `agente.*`, `diag-*`, `humo-*`, resultados de recuperación, test ni informes JSON/MD. Las observaciones siguientes son **lectura y agregación actual de ejecuciones pasadas**, no una nueva ejecución del agente ni validación semántica.

| Archivo / variante | Corridas; casos/episodios | Etiquetas `pass` | Escaladas | Llamadas auditadas; `length` | p50 pared ms | Mediana input tokens por llamada estructurada* |
|---|---|---:|---:|---|---:|---:|
| dev-ds / base | 36; 12/3 | 24/36 | 18/36 | 60; 2 | 84915 | 11680,5 |
| dev-ds / enlace | 36; 12/3 | 26/36 | 15/36 | 54; 1 | 70376,5 | 12484 |
| dev-ctl / enlace_ctl | 36; 12/3 | 25/36 | 20/36 | 59; 0 | 113114,5 | 12501,5 |

*`calls[].input_tokens` acumula intentos internos de schema, según el código actual; no necesariamente una petición HTTP. Cada caso tiene tres repeticiones en cada variante. No se recalculó contenido contra un nuevo criterio de evidencia.

`dev-ctl`: config_id **27fc7f09c26cf15b**, 59 finish=`stop`, 0 campos `error` con valor, 0 abstenciones. `dev-ds`: configs **c2cb6bd385485fb1**, **ce5237b3eb111505**, 111 `stop` + 3 `length`, 0 campos `error` con valor, 0 abstenciones. En ambos archivos los nombres guardados para tiers **small y large son `deepseek/deepseek-v4.1-flash`**. Es comprobación de etiquetas históricas, no demostración de identidad de proveedores/pesos o configuración desplegada actual.

| Archivo / variante | Tokens entrada / salida / razonamiento, sumas | Coste reportado USD, suma | Tiempo LLM / pared, sumas ms |
|---|---|---:|---|
| dev-ds / base | 714863 / 378637 / 245583 | 0,2156175952 | 2969148 / 3078972 |
| dev-ds / enlace | 680682 / 367518 / 239636 | 0,21358456 | 2884349 / 2993398 |
| dev-ctl / enlace_ctl | 747657 / 403360 / 261508 | 0,2293408824 | 3725347 / 3865503 |

En ctl, razón de sumas reasoning/salida ≈64,83%; LLM/pared ≈96,37%. No es igual a «tiempo de espera» ni a media por corrida de esas razones. No se separaron cola, prefilling, generación y razonamiento por reloj. La afirmación general «90% espera» no queda verificada por este cálculo.

**Razones reales de descarte final persistido:** ctl tiene una RC-03 y una ND-03 por «Ninguna fuente citada menciona [código]»; ds tiene ND-03, RC-13 y RC-18 por ese mismo motivo, y una RC-01 por «Ninguna fuente citada es un fragmento recuperado». Son **2 y 4 descartes finales**, no todos los descartes transitorios ni las razones de cada escalamiento: un reintento exitoso puede eliminarlos de la salida final. No se atribuye toda escalada a estas seis entradas.

Las cifras baseline dev .583/test .50, intervalos enlace .72–.78, «ruido ±.06», test agotado y diagnósticos históricos por caso siguen siendo **contexto no verificado en sus series originales**. Aquí se observan etiquetas dev 24/36,26/36,25/36, no se ratifica ni invalida el resto ni se consulta test. En la selección actual EV-08 tiene etiqueta RC-02/E7; cualquier afirmación previa sobre RC-03 para EV-08 necesita identificar archivo/versión, sin inferir su significado de memoria.

## 6. D — Validez del dev y episodios nuevos solo sobre papel

### RIESGO-16 — Doce casos no son doce experimentos independientes

Severidad **alta**; impacto esperado **alto** en incertidumbre y selección; confianza **alta**; **dev leído y agrupación de registros ejecutada**.

`evals/casos_calidad.jsonl:1–12`: cuatro formulaciones/fechas de cada E6, E7 y E8. Solo hay **tres episodios**; los 108 registros dev de §5 no son 108 incidentes independientes. `agent.py:361–387` ya calcula macro por episodio; esto no convierte repeticiones en nuevas unidades ni salva una selección post-hoc de variantes. El código llama exploratoria a enlace_ctl (`:44–49`).

| Episodio | RC→ND permitida en dev | Suficiencia y riesgo de atajo |
|---|---|---|
| E6 / EV-01..04 | RC-01→ND-01, alternativa ND-07 | Síntoma compatible con varias causas; EV-04 temprano requiere ciclos/tendencia. Las notas del eval contienen la explicación: no deben entrar al modelo |
| E7 / EV-05..08 | RC-02→ND-02 | Lanza/lote/proveedor deben distinguirse de inserción. EV-07 solapa síntomas de E6; EV-08 temprano puede ser débil. Primera línea sola reduce evidencia entre líneas |
| E8 / EV-09..12 | RC-03→ND-03, alternativa ND-07 | EV-09/11 explicitan TPA; EV-12 menciona instrucción de jalón y contiene cebo de culpa: fácil atajo textual. EV-10 necesita cambio/estación/turno, no solo parecido con un 8D |

Las etiquetas y notas no llegan por `ncr_draft`, que selecciona campos de NCR (`agent.py:57–68`). Los códigos RC/ND del catálogo son vocabulario permitido, no fuga de la etiqueta por sí mismos. El acoplamiento entre redacción sintética de NCR, catálogo y explicación causal puede facilitar atajos; no se probó contaminación de entrenamiento ni filtración de verdad en prompts. La suficiencia de **tools al as_of exacto de cada caso** sigue sin demostrarse: no se leyeron eventos/verdad de fondo mezclados para completarla.

### OPORTUNIDAD-17 — Nueve incidentes dev independientes, aún sin generar

Severidad **media**; impacto esperado **alto** en diagnóstico; confianza **media** hasta construir/verificar datos; **diseño, no medición**.

Reservar **E101..E109 / EV-101..EV-118**, fuera de los rangos existentes. Dos casos por episodio: observación principal y control/ablación, contados como un solo cluster. Compartir clase causal RC o mecanismo general con otro episodio es admisible; no reutilizar el mismo evento subyacente, lote, par equipo–ventana, filas latentes ni otra realización del mismo incidente bajo nombres nuevos. No derivar datos o frases de escenarios sellados. Construcción por una persona/proceso distinto del que evalúa; verdad fijada antes del texto de la NCR; revisión ciega de suficiencia y de independencia de los datos. Son requisitos de diseño, no independencia ya demostrada. No se crean archivos ni se cambian casos actuales.

| Episodio / casos reservados | Resultado esperado principal → control | Evidencia discriminante y control negativo |
|---|---|---|
| E101 / EV-101,102 | RC-01/ND-01 → abstención | Nuevo aplicador con desgaste medido y tendencia previa; control elimina contador y tendencia, mantiene intermitencia. Otros lotes/equipos normales |
| E102 / EV-103,104 | RC-02/ND-02 → abstención | Nuevo lote con medición de lanza y retención frente a lote previo; control retira asignación de lote a eventos. Crimpado normal en ambos |
| E103 / EV-105,106 | RC-03/ND-03 → abstención | Nuevo puesto con WI visual y comparación física empuje-jalón; control no observa asentamiento ni resultado físico. Lanza y crimpado conformes |
| E104 / EV-107,108 | RC-01/ND-07 → misma RC/ND | Otra planta/equipo, fallo dinámico demostrado y prueba estática pasa; control cambia cliente/parte/turno sin tocar mecanismo. Prueba de invariancia, no nueva muestra independiente |
| E105 / EV-109,110 | RC-02/ND-08 → misma RC, ND-02 | Mismo incidente sintético con lanza defectuosa; principal tiene instrucción dimensional exigida pero no ejecutada, control documental la sustituye por aceptación por certificado. Distinguir ejecución de diseño de control |
| E106 / EV-111,112 | RC-03/ND-08 → misma RC, ND-03 | Nuevo puesto: método correcto vigente pero verificación omitida demostrada; control cambia a método solo visual. Instrucción y ejecución tienen fechas de vigencia anteriores al defecto |
| E107 / EV-113,114 | abstención → RC-02/ND-02 | Síntoma compartido, herramientas sin discriminadores; control añade laboratorio trazable a lote nuevo. No permitir que semejanza histórica resuelva la primera |
| E108 / EV-115,116 | RC-03/ND-03 → misma RC/ND | Precedente muy parecido de desgaste pero datos actuales confirman inserción; control retira el precedente distractor. Verificar resistencia al anclaje, no contar dos éxitos independientes |
| E109 / EV-117,118 | abstención → abstención | Fuentes contradictorias, lotes sin trazabilidad y nota correctiva posterior al as_of; control retira esa nota futura y añade dato no discriminante. Ningún código preferido debe pasar como causa verificada |

RC-01/02/03 se sustentan en filas AMEF inspeccionadas; ND-01/02/03/07/08 en `data/static_docs/SOP-QA-011.md:47–54`. Las combinaciones nuevas son hipótesis del diseño: no existe mapeo determinista universal RC→ND. Por ejemplo, proveedor defectuoso con control dimensional requerido pero omitido justifica ND-08 solo con evidencia de ejecución; el código de RC solo no decide la ND.

### RIESGO-18 — El validador y el cargador actuales no preservan el sellado

Severidad **alta**; impacto esperado **alto** para gobernanza experimental; confianza **alta**; **fuente genérica leída, no importada**.

`data/generator/validate.py:43–51` carga CSVs y toda la verdad al importar; `evalkit/retrieval.py:206–214` deserializa casos y verdad completos antes del filtro dev. **No se ejecutaron**. No se afirma «0 fallos de validación» para los episodios existentes o propuestos.

Una validación futura autorizada necesita selección de IDs/partición **antes de cargar payload y verdad**, comprobación cerrada de IDs dev y de documentos/filas autorizados, invariantes de fechas/cantidad/clasificación, y salida que declare exactamente lo inspeccionado. Debe trabajar sobre material dev separado o un lector realmente acotado; no necesita abrir, modificar ni regenerar heldout. Eso es requisito para la fase siguiente, no parche realizado.

### OPORTUNIDAD-19 — Predefinir efecto útil e incertidumbre por incidente

Severidad **media**; impacto esperado **alto**; confianza **media**; **plan no ejecutado**.

Antes de comparar: definir un éxito estricto separado de `pass` legado: RC principal y ND admisible **más** evidencia pertinente y estado adecuado; abstención correcta cuenta separadamente, no como RC acertada. Registrar seguridad, inválidas, cortes, cobertura y coste con sus denominadores. Comparar variantes sobre los mismos incidentes, cortes y repeticiones válidas emparejadas, sin reemplazar errores de infraestructura selectivamente por variante.

Predefinición sugerida para decisión: **+0,10 absoluto** en éxito estricto macro por episodio como mejora útil; ninguna regresión de seguridad, caída >0,05 de abstención correcta o ND correcta impide promover. Son umbrales de decisión propuestos, no significancia encontrada. Evaluar tres repeticiones por caso para consistencia condicional; resumir variación dentro del incidente, sin tratarlas como n independiente. Para incertidumbre, remuestrear **episodios completos** y diferencias pareadas, preservando controles/repeticiones; informar intervalo y tamaño efectivo. Con nueve episodios el intervalo puede seguir siendo amplio: si incluye pérdida relevante, resultado inconcluso y recopilar nuevos incidentes independientes. No adoptar «±0,06» sin estimador, procedencia y clusters suficientes. El dev actual n=3 sirve para diagnóstico, no para certificar un margen estrecho ni reutilizar test agotado.

## 7. E — Ingeniería, seguridad y reconstrucción

### BUG-20 — Feedback puede elevar sensibilidad sin elevar el contexto de routing

Severidad **alta**; impacto esperado **alto** si API está habilitada y otras barreras no cubren el texto; confianza **alta** en omisión, **no verificada** fuga de red.

Sonda determinista: feedback sintético con marcador de especificación de cliente/parte desconocida aparece en el prompt; el clasificador real lo clasifica confidencial; construcción pura AST de `_ctx` devuelve **interno y pii=false**. `graph.py:637–667` solo agrega NCR/tools/fragmentos, no feedback/previo/D2 heredado; `prompts.py:154–173` sí incorpora feedback.

```text
FEEDBACK {"present_in_prompt": true, "classified_if_inspected": "confidencial",
 "ctx_level": "interno", "ctx_pii": false}
```

No se llamó al router operativo ni al gateway. El redactor/inspector aún pueden bloquear identificadores conocidos antes de API (`gateway.py:185–214`); el inspector solo busca términos de catálogo (`llm/inspector.py:35–55`), no sustituye clasificación general. Por tanto, no se declara una exfiltración ejecutada ni protección completa por el solo hecho de existir inspector.

### BUG-21 — Igualdad de manifiesto y reanudación no garantizan experimento equivalente

Severidad **alta**; impacto esperado **alto** sobre reproducibilidad; confianza **alta**; **manifest reproducido + reanudación leída**.

Con mismos objetos inertes salvo `timeout_s:60→600` y `max_retries:3→8`, `build_manifest` dio **config_id idéntico**. `manifest.py:45–61,72–98` no incluye esos campos ni revisión dentro del hash; `code_revision` depende de GIT_SHA, no del árbol sucio. `retrieval/service.py:27–30` identifica índice por versión de chunker+modelo, no contenido. Ingesta no invalida por `max_chars` (`ingest/service.py:107–117`). `_load_runs` deduplica únicamente caso/variante/rep (`evalkit/agent.py:797–805`): puede mezclar configuraciones bajo el mismo nombre. No se demostró mezcla dentro de las dos series leídas.

### RIESGO-22 — Idempotencia protege gasto concurrente, pero TTL y deadline divergen

Severidad **media**; impacto esperado **alto** bajo fallos lentos; confianza **alta** en mecanismo, **no ejecutado** ensayo concurrente.

`service.py:95–108,162–216` hace replay autorizado; SQL declara índices únicos por NCR+clave y una activa por NCR (`0014_analysis_run.sql:38–41`). Después de generar, `_write` bloquea NCR y compara versiones antes de guardar (`service.py:328–338`). No se mantuvo la conexión de gather durante inferencia según la ruta leída en fase 0. Son controles positivos, no problemas que deban reinventarse.

Pero `runs.py:25–27,103–110` abandona una corrida a los **15 minutos** sin heartbeat. El cliente tiene timeout por request configurable hasta 600 s, retries hasta ocho, y reintentos adicionales de schema/tier (`llm/config.py:63–64`; `openai_compat.py:67–103`; `structured.py:61–101`). Incluso cotas combinatorias con defaults pueden superar quince minutos; no se observa deadline global. Un trabajo vivo lento puede clasificarse abandonado, permitir otro trabajo y luego perder su cierre por condición `status='en_curso'` (`runs.py:153–157`). El chequeo de versiones protege escritura, no evita el gasto ya consumido. Replay tampoco vincula clave al hash de disciplinas/entrada: la misma clave devuelve la corrida previa, no una nueva petición distinta.

### RIESGO-23 — Auditoría encadenada no equivale a reconstrucción exacta del prompt

Severidad **media**; impacto esperado **alto** en explicación posterior; confianza **alta** en fuente, **no verificada** integridad de la cadena real.

La migración serializa inserciones con advisory lock, calcula SHA-256 y prohíbe mutaciones/truncate (`0001_initial.sql:447–535`). El CHECK confidencial+API impide registrar tal combinación, no deshace un envío. Gateway audita bloqueos/errores gestionados y éxitos, con finish/modelo reportado/proveedor e intentos (`gateway.py:188–239,273–343`); excepciones de routing/restauración no están todas envueltas en ese mismo contrato. El cierre de `analysis_run` puede fallar y retornar uso vacío (`service.py:265–277`). No se consultaron audit_log/analysis_run ni `audit_verify()`, que recorrería registros potencialmente mixtos.

Trace_id une corrida, llamada y sección; fuentes F# guardan UUID/metadatos y filas citation. T#/NCR quedan en JSON, sin snapshot del resultado de datos (`evidence.py:52–66,145–153`; `service.py:363–395`). Con DB mutable, versión/hash incompletos y posible BUG-09, esos IDs no reconstruyen de forma exacta todos los textos/historiales/reintentos. Los archivos dev con evidence-for-judge tienen otro contrato de retención y no sustituyen garantías de producción. `LLM_DEBUG_HTTP` puede guardar request fallido en memoria/imprimir cuerpo de error (`openai_compat.py:87–92,180–189`); no se verificó activación ni se imprimió configuración sensible.

## 8. Reproducción segura y salidas

Las ejecuciones históricas de esta fase se realizaron desde la raíz; no se repitieron durante la corrección documental. Las recetas P2/P3/P4 revisadas abajo son **NUEVAS, NO EJECUTADAS** y no originaron los stdout conservados. `-B` evita pyc; no autoriza instalaciones ni cambios del entorno. No importar runtime, generadores, validator ni CLI eval inseguro. La especificación SQL corregida usa parámetros psycopg y presupone una conexión aislada ya autorizada: no proporciona credenciales ni una orden Docker validada. Ninguna receta autoriza leer datos o ejecutar servicios ahora.

### P1 — Selección dev antes de materializar payload

Este prefijo fue utilizado en las sondas de consultas y en la lectura de casos. La lectura termina tras doce filas, sin solicitar la siguiente. Primer intento de impresión con `ensure_ascii=False` falló por consola cp1252/Ω en EV-02; se corrigió solo la serialización de stdout a ASCII, no el entorno ni los datos.

```bash
python - <<'PY'
from pathlib import Path
import re,json
with Path('evals/casos_calidad.jsonl').open(encoding='utf-8') as f:
 for i in range(1,13):
  prefix=''
  while not (m:=re.search(r'"caso_id"\s*:\s*"([^\"]+)"',prefix)):
   c=f.read(1);assert c and c!='\n';prefix+=c;assert len(prefix)<150
  assert m[1]==f'EV-{i:02d}'
  row=json.loads(prefix+f.readline());assert row['episodio'] in {'E6','E7','E8'}
  print(json.dumps(row,ensure_ascii=True))
print('SAFE_STOP after EV-12; no next line / no truth loaded')
PY
```

Salida resumida real: **EV-01..04/E6, EV-05..08/E7, EV-09..12/E8; SAFE_STOP after EV-12; no next line / no truth loaded**. No es una carga segura de verdad por episodio; esa verdad no se abrió.

### P2 — Chunker real, solo documentos y dos históricos permitidos

**Corrección de procedencia:** el comando histórico formó una lista dinámica con `glob('*.md')` y comprobó solo `len == 15`; eso no era una allowlist fija ni garantiza seguridad ante sustituciones futuras. La distribución publicada se conserva como observación histórica de aquel alcance, no como certificación de cualquier corpus actual. En esta revisión se listaron primero los nombres y después se calcularon únicamente los hashes de estos quince archivos autorizados; no se ejecutó chunking ni se volvió a medir calidad.

Lista fija de `data/static_docs/`; SHA-256 de bytes observados en esta revisión documental, no prueba de todo el índice DB ni del corpus operacional:

| Archivo permitido | SHA-256 |
|---|---|
| `AMEF-ARN-PD-001.md` | `b652c9711a2685856e1aacd5b70768817a7d3f9d7647811114cf7657e585b66a` |
| `CP-ARN-PD-001.md` | `4ed82e81ee8f47359a8dfbb7e5f173249868d0ca512a37cbac9ac53bdb50ced4` |
| `CSR-NV-001.md` | `18fc5065f3c4eb3cad8d33c46fc1b4471499287f6ef6377a48bd0e20ce282f2d` |
| `SOP-CAM-010.md` | `5de291745c63284da8f1e0b794f016b46575514e3eeb87125a60261f1f4acc93` |
| `SOP-MNT-008.md` | `a9641d4f704c495faab4a7156fefc92b0ac0c1b1ceb250829341180500fda038` |
| `SOP-QA-011.md` | `928ce4e64a1e300d7775908e98552da983cf43bdc552b4e4bd4c3814c388122f` |
| `SOP-REC-009.md` | `07e9d5fca1da00e44d0271ba5cb659852b55bc60a691abb3023b04345fa04c87` |
| `SPEC-CRP-001.md` | `2fa9664ce6c72a59ef1eb6ba702b02141c4c7c343b5ca96cb4726090e79f13a1` |
| `WI-BRD-005.md` | `a72cc18a7d10d5a0c2d31f6a65b9127e45d68475ba975ecf11dcaaf2828902b0` |
| `WI-CRP-002.md` | `b09c5049882cc1dfdc65e18db00e32516b47d8af35e04d90b9d4dbc804576f1b` |
| `WI-CRP-003.md` | `6a37f951c7ad597a4de63fa249ad73987ad20f72b8d6d19fde5009befa301ae1` |
| `WI-CUT-001.md` | `7201492501c8af6b35ad333242832fbb515a66ff4d2419a999a2b20602575aab` |
| `WI-INF-007.md` | `86f026e5fba5b14fd9d4df51651f1d6e6bc9f332205cd6b32ea544c885df12c8` |
| `WI-INS-004.md` | `07dae40d0fb297ee764c118c15dbea141354d47342a46a9f1a6b905d2cbb3a04` |
| `WI-TST-006.md` | `597fa7b9eddb5a7106fc8e1722663e70fbea400b67f2be54a6d490ba7ec14018` |

**Receta revisada NUEVA / NO EJECUTADA:** compara el conjunto exacto de entradas antes de leer cuerpos, rechaza enlaces y comprueba los hashes fijados arriba. Una diferencia bloquea la receta; no actualizar automáticamente la lista o sus hashes para hacerla pasar. Los dos históricos siguen identificados de forma literal; no se hashearon ni releyeron en esta revisión.

```bash
apps/api/.venv/Scripts/python.exe -B - <<'PY'
import sys,json,statistics,math,re,hashlib
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
from app.ingest.frontmatter import parse_document
from app.retrieval.chunker import chunk_markdown
from app.retrieval.models import DocumentKind
allc=[];cat=[]
EXPECTED=set(('AMEF-ARN-PD-001.md CP-ARN-PD-001.md CSR-NV-001.md SOP-CAM-010.md '
 'SOP-MNT-008.md SOP-QA-011.md SOP-REC-009.md SPEC-CRP-001.md WI-BRD-005.md '
 'WI-CRP-002.md WI-CRP-003.md WI-CUT-001.md WI-INF-007.md WI-INS-004.md WI-TST-006.md').split())
root=Path('data/static_docs');assert not root.is_symlink() and not root.is_junction()
assert {p.name for p in root.iterdir()}==EXPECTED
files=[root/n for n in sorted(EXPECTED)]
assert all(p.is_file() and not p.is_symlink() and not p.is_junction() for p in files)
pins=dict(re.findall(r'^\| `([^`]+\.md)` \| `([0-9a-f]{64})` \|$',
 Path('audit/01-hallazgos.md').read_text(encoding='utf-8'),re.M))
assert set(pins)==EXPECTED
for p in files:
 raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==pins[p.name]
 d=parse_document(raw.decode('utf-8'))
 cs=chunk_markdown(source_key=d.source_key,title=d.title,kind=d.kind,body=d.body)
 allc+=cs;cat +=[(d.source_key,c.section,c.content) for c in cs if c.section.startswith(('RC-','ND-'))]
ns=sorted(len(c.content) for c in allc)
print('DOC_CHUNKER',len(files),len(ns),min(ns),ns[math.ceil(.5*len(ns))-1],
 ns[math.ceil(.9*len(ns))-1],ns[math.ceil(.95*len(ns))-1],max(ns),round(statistics.mean(ns),2),
 sum(n>550 for n in ns),len(cat),len(set(s for _,s,_ in cat)),
 all(s in t for _,s,t in cat),sum(len(t)>260 for _,s,t in cat))
for key in ['8D-2026-011','8D-2026-019']:
 paths=list(Path('data/seed/corpus/8d').glob(key+'.md'));assert len(paths)==1
 d=parse_document(paths[0].read_text(encoding='utf-8'))
 cs=[c for c in chunk_markdown(source_key=d.source_key,title=d.title,kind=d.kind,body=d.body) if c.section=='D4']
 print('HIST_D4',key,[len(c.content) for c in cs],all(c.content.startswith(key+' ') for c in cs),
  all('Causa' in c.content.split('\n')[0] for c in cs))
long=chunk_markdown(source_key='SYNTH-DOC',title='Synthetic',kind=DocumentKind.SOP,body='## Prueba\n'+'x'*2000)
print('LONG_UNIT',len(long),max(len(c.content) for c in long))
PY
```

Salida histórica conservada, resumida sin contenido: **15;93;90;392;539;547;662;378.11;4;28;28;true;20**, históricos **-011 [471,478,153,466,383] true/true; -019 [335,348,234] true/true**, **LONG_UNIT 1 2019**. Procede del comando original con lista dinámica y conteo, no de la receta fijada y no ejecutada que se muestra ahora. Esta corrección no agrega observaciones sobre los históricos.

### P3 — Consulta SQL dev/documental: separar candidatura de ranking

**Corrección R1-001 de la receta, no de la aplicación:** la sonda exploratoria histórica interpoló valores con escape manual de comillas y obtuvo los stdout conservados abajo. No se presenta ese patrón como consulta recomendada ni como prueba de un exploit del endpoint. Se retira su comando ejecutable; la sustitución siguiente es una **especificación parametrizada NUEVA / NO EJECUTADA**, no el origen de las mediciones. No se abrió DB durante esta revisión.

Contrato futuro: el lector mínimo aprobado en P01 de fase 2 entrega `cases` exclusivamente dev, `uid` autorizado y una conexión **psycopg** aislada, ya en transacción de solo lectura con rollback al finalizar. Antes de leer documentos se verifica el conjunto literal de quince nombres y hashes de P2; `STATIC_DOC_KEYS` son sus stems exactos. Una diferencia bloquea la consulta. No se indica cómo obtener credenciales ni se afirma haber probado sintaxis Docker/conexión. Los identificadores de esquema/tabla/columna son literales; todos los valores, incluidas listas, usuario, fecha y etiquetas usadas solo al puntuar, se enlazan mediante `%s`:

```python
# ESPECIFICACION NUEVA / NO EJECUTADA; no es un programa de conexión o carga.
SQL = """
WITH vis AS MATERIALIZED (
 SELECT f.id,f.section,f.tsv,d.source_key
 FROM visible_fragments(%s::uuid) f JOIN document d ON d.id=f.document_id
 WHERE d.source_key = ANY(%s::text[])
   AND d.kind = ANY(%s::document_kind[])
   AND (f.doc_date IS NULL OR f.doc_date <= %s::date)
), query AS (
 SELECT coalesce(nullif(replace(plainto_tsquery('spanish',%s)::text,'&','|'),''),'')::tsquery
   || coalesce(to_tsquery('simple',%s),''::tsquery) tsq
), ranked AS (
 SELECT v.*,row_number() OVER(ORDER BY ts_rank_cd(v.tsv,query.tsq) DESC,v.id) r
 FROM vis v,query WHERE v.tsv @@ query.tsq
)
SELECT %s caso,%s ep,count(*) matched,
 min(r) FILTER(WHERE source_key='AMEF-ARN-PD-001' AND section=%s) rc_rank,
 min(r) FILTER(WHERE source_key='SOP-QA-011' AND section=%s) nd_rank,
 string_agg(source_key||'#'||section,',' ORDER BY r) FILTER(WHERE r<=6) top6
FROM ranked
"""
STATIC_DOC_KEYS = (
 'AMEF-ARN-PD-001','CP-ARN-PD-001','CSR-NV-001','SOP-CAM-010','SOP-MNT-008',
 'SOP-QA-011','SOP-REC-009','SPEC-CRP-001','WI-BRD-005','WI-CRP-002','WI-CRP-003',
 'WI-CUT-001','WI-INF-007','WI-INS-004','WI-TST-006')
assert {c['caso_id'] for c in cases} == {f'EV-{i:02d}' for i in range(1,13)}
assert len(cases)==12 and all(c['episodio'] in {'E6','E7','E8'} for c in cases)
for c in cases:
 query=' '.join((c['ncr']['descripcion']+' '+c['ncr'].get('numero_parte','')).split())[:600]
 assert 'RC-' not in query and 'ND-' not in query
 params=(str(uid),list(STATIC_DOC_KEYS),['amef','sop','instruccion','plan_control'],
  c['as_of'],strip_codes(query),codes_tsquery(query),c['caso_id'],c['episodio'],
  c['esperado']['causa_ocurrencia'],c['esperado']['causa_no_deteccion'])
 result=conn.execute(SQL,params).fetchone()  # conn: psycopg; sin interpolación de valores
```

Valores históricos exactos conocidos: usuario `u-ingcal-1` resuelto entonces a UUID `fbd86adc-dbe5-4153-a9f4-04d5515dacb5`; EV-01..12; los quince keys anteriores; kinds amef/sop/instruccion/plan_control; `as_of`, descripción+parte y etiquetas canónicas de cada caso dev. No se vuelven a cargar esos payloads para documentarlos. El UUID de otra DB exige resolución autorizada, no asumir que coincide.

Stdout **histórico de la sonda original con escape manual**, `caso|episodio|matched|rc_rank|nd_rank` (top6 omitido aquí por espacio). La especificación parametrizada aún no tiene stdout:

```text
EV-01|E6|66|17|     EV-02|E6|58|13|51   EV-03|E6|54|36|    EV-04|E6|55|33|
EV-05|E7|44|8|      EV-06|E7|64|3|53    EV-07|E7|53|5|     EV-08|E7|62|4|
EV-09|E8|60|1|55    EV-10|E8|62|9|58    EV-11|E8|54|3|50   EV-12|E8|65|5|61
```

El SQL histórico emitió NOTICE sobre la consulta vacía alternativa `''::tsquery`; no hubo error (exit 0, ROLLBACK). Sus keys procedieron de lista dinámica y conteo 15, no de una validación fija de nombres/hashes. La restricción documental de aquella sonda no acredita un origen operacional seguro. La receta futura conserva permisos y añade selección fija; necesita revisión y autorización antes de ejecutarse.

La distribución DB histórica se obtuvo con los keys dinámicos escapados de la sonda original, `fragment JOIN document` y `WHERE d.source_key IN (...)`, agregando `length(f.content)`, `percentile_disc(.5/.9/.95)`, conteos >550/>1400. Normalización se midió solo para AMEF/SOP con `avg(vector_norm(f.embedding))`, agrupado por source_key y embedding_model; no se consultaron vectores de escenarios. Salida conservada sin nueva ejecución: **93 chunks, 15 docs, 90/392/539/547/662, 378.11,4,0**; normas medias **27.424495/28.511254**.

### P4 — Lectura segura de registros dev y agregados reproducibles

**Receta consolidada NUEVA / NO EJECUTADA.** La versión anterior omitía fórmulas de varias columnas publicadas. Se recuperan del contexto de los dos comandos originales, sin releer resultados: los números de §5 siguen siendo stdout histórico, no resultados de esta consolidación. La selección de prefijos y el dedupe conservan el contrato original; no se ejecuta este bloque durante la revisión.

```bash
python - <<'PY'
from pathlib import Path
import re,json,collections,statistics
allowed={f'EV-{i:02d}' for i in range(1,13)}
for name in ['dev-ctl.runs.jsonl','dev-ds.runs.jsonl']:
 p=Path('traces/evals')/name;assert p.name.startswith('dev-');rows=[]
 with p.open(encoding='utf-8') as f:
  while True:
   c=f.read(1)
   if not c:break
   if c.isspace():continue
   assert c=='{';prefix=c
   while not (m:=re.search(r'^\{\s*"caso_id"\s*:\s*"(EV-\d+)"\s*,\s*"episodio"\s*:\s*"(E\d+)"\s*,\s*"split"\s*:\s*"([^"\n]+)"',prefix)):
    c=f.read(1);assert c and c!='\n';prefix+=c;assert len(prefix)<180
   assert m[1] in allowed and m[2] in {'E6','E7','E8'} and m[3]=='dev','STOP BEFORE PAYLOAD'
   rows.append(json.loads(prefix+f.readline()))
 rs=list({(r['caso_id'],r['variant'],r['rep']):r for r in rows}.values())
 tiers=collections.defaultdict(set);discard=collections.Counter();code_disc=collections.Counter();finish=collections.Counter()
 for r in rs:
  for c in r.get('calls',[]):tiers[c.get('tier','?')].add(c.get('model','?'))
  finish.update(r.get('finish_reasons') or [])
  for d in (r.get('content') or {}).get('descartes') or []:
   discard[d.get('motivo','')]+=1;code_disc[d.get('codigo','?')]+=1
 print(json.dumps({'file':name,'lines':len(rows),'latest':len(rs),
  'cases':len({r['caso_id'] for r in rs}),'episodes':sorted({r['episodio'] for r in rs}),
  'config_ids':sorted({r.get('config_id') or '(missing)' for r in rs}),
  'errors':sum(bool(r.get('error')) for r in rs),
  'abstained':sum(bool(r['score'].get('abstained')) for r in rs),
  'pass_and_abstained':sum(bool(r['score'].get('pass')) and bool(r['score'].get('abstained')) for r in rs),
  'missing_finish_reasons':sum('finish_reasons' not in r for r in rs),
  'models_by_tier':{k:sorted(v) for k,v in tiers.items()},'finish':dict(finish),
  'discard_reasons':dict(discard),'discard_codes':dict(code_disc)},ensure_ascii=True))
 for v in sorted({r['variant'] for r in rs}):
  rr=[r for r in rs if r['variant']==v]
  cs=[c for r in rr for c in r.get('calls',[])]
  # En los outputs originales la clave resuelta fue input_tokens, no tokens_in.
  input_key='input_tokens' if cs and 'input_tokens' in cs[0] else 'tokens_in'
  llm_sum=sum(r.get('llm_ms') or 0 for r in rr)
  wall_sum=sum(r.get('wall_ms') or 0 for r in rr)
  out_sum=sum(r.get('tokens_out') or 0 for r in rr)
  reasoning_sum=sum(r.get('reasoning_tokens') or 0 for r in rr)
  print(json.dumps({'variant':v,'runs':len(rr),
   'cases':len({r['caso_id'] for r in rr}),'episodes':len({r['episodio'] for r in rr}),
   'per_case_reps':sorted(set(collections.Counter(r['caso_id'] for r in rr).values())),
   'config_ids':sorted({r.get('config_id') or '(missing)' for r in rr}),
   'pass_labels':sum(bool(r['score'].get('pass')) for r in rr),
   'errors':sum(bool(r.get('error')) for r in rr),
   'abstained':sum(bool(r['score'].get('abstained')) for r in rr),
   'escalated':sum(any(c.get('tier')=='large' for c in r.get('calls',[])) for r in rr),
   'audit_calls':sum(r.get('llm_calls',0) for r in rr),
   'finish_length':sum((r.get('finish_reasons') or []).count('length') for r in rr),
   'wall_ms_p50':statistics.median(r['wall_ms'] for r in rr),
   'structured_call_input_key':input_key,
   'structured_call_input_p50':statistics.median(c[input_key] for c in cs) if cs and input_key in cs[0] else None,
   'input_tokens_total':sum(r.get('tokens_in',0) for r in rr),
   'output_tokens_total':out_sum,'reasoning_tokens_total':reasoning_sum,
   'llm_ms_sum':llm_sum,'wall_ms_sum':wall_sum,
   'llm_wall_ratio':llm_sum/wall_sum if wall_sum else None,
   'reasoning_output_ratio':reasoning_sum/out_sum if out_sum else None,
   'cost_reported_sum':sum(r.get('cost_reported_usd') or 0 for r in rr),
   'missing_reported_cost':sum(r.get('cost_reported_usd') is None for r in rr)},ensure_ascii=True))
PY
```

Procedencia de fórmulas: `config_ids`, errores/abstenciones, códigos/motivos de descartes y tiers se imprimieron por archivo en el primer comando histórico; `sum(r['llm_calls'])`, `calls[].input_tokens`, sumas de tiempos/tokens/costes y conteos por variante, en el segundo. Las dos razones de §5 se calcularon aritméticamente a partir de esas sumas; los campos explícitos `llm_wall_ratio` y `reasoning_output_ratio` se agregan aquí **por primera vez y no se han ejecutado**; sus porcentajes se expresan como `round(100 * razón, 2)`. `audit_calls` suma filas auditadas reportadas, no `len(calls)` ni intentos HTTP; la mediana usa llamadas estructuradas y sus reintentos internos. `errors` solo cuenta `bool(error)`, no clasifica inválidas; ausencia de costo no equivale a costo cero y se publica aparte. Los valores y sus límites se conservan en §5 sin reclamar una nueva tasa semántica o una reproducción realizada por este bloque.

### P5 — Recetas de contraejemplos y procedencia de ejecución

Todos se ejecutaron con `apps/api/.venv/Scripts/python.exe -B - <<'PY'`, `sys.path.insert(0, str(Path('apps/api').resolve()))`, sin importar runtime ni evalkit-agent/retrieval. Las funciones de agregación de `agent.py` se extrajeron mediante `ast.parse`, seleccionando únicamente `_mean,_rate,paired,classify_run,_error_classes,is_invalid,aggregate,_pass_hat_k,_pct,_tool_means` y constantes de clasificación; se compilaron en diccionario local con `defaultdict,statistics,typing`, no como módulo operativo.

Receta mínima de la sonda histórica de RIESGO-01, que ilustra el contrato de exactitud sin demostrar un bug del scoring:

```python
from app.evalkit.scoring import score_d4
expected={'causa_ocurrencia':'RC-01','causa_no_deteccion':'ND-01','evidencia_suficiente':False}
content={'estado':'evidencia_insuficiente','causas_ocurrencia':[{'codigo':'RC-01','evidencia':[]}],
         'causa_no_deteccion':{'codigo':'ND-01'}}
s=score_d4(content,expected)
print({k:s[k] for k in ['pass','abstained','abstention_correct']})
content['estado']='candidato_respaldado';s=score_d4(content,expected)
print({k:s[k] for k in ['pass','abstention_correct']})
```

Para BUG-07 se instanciaron cuatro `CatalogEntry` sintéticas RC-01/02/03/ND-01 con UUID(int=1..4), nivel interno y descripciones `código + ' descripcion de catalogo'`. En cada libro se llamó `add_fragment` con esos mismos datos y `catalog_code=código`; en la variante adversarial primero se llamó `add_fragment` sin catalog_code. Un `D4Draft` idéntico en ambas variantes citó F1/F2/F3/F4, estado candidato_respaldado, textos neutrales válidos. Se ejecutó `verify_d4`; salida exacta en BUG-07. No hubo datos dev ni catálogo real en este contraejemplo.

Para BUG-08/09 se compiló únicamente el `ast.If` de `graph.py:499` y el `ast.Assign` de `:591`, con `SimpleNamespace` para propuestas/respuesta y un diccionario de estado. Salidas reales **SELECTION_TIE {kept:large,nd:null}**, **ATTRIBUTION {kept:small,label:SYNTH-LARGE}**. No se ejecutó `_generate`, el grafo ni una llamada de agente.

Para BUG-20 se aisló por AST solo el cuerpo constructor de contexto `_ctx`, convertido en función local sin `self`, con NCR interna sin PII y evidencia vacía. Feedback sintético: `Revisar especificacion del cliente y parte Z9-ABC-9999-X.`. Se compararon `_revision_parts(None,feedback)` y `RuleClassifier([]).classify(feedback)` con ese contexto. Salida exacta en BUG-20. Un primer import intentó obtener RuleClassifier del paquete raíz y falló; se usó su módulo real `app.confidentiality.classifier`, sin modificar archivos/dependencias.

Para BUG-21 se llamó `build_manifest` sobre `SimpleNamespace` sin BaseSettings ni lectura de `.env`, con destino localhost sintético, modelos same/same, extra_body vacío, índice synthetic y catálogo sintético; solo se cambiaron timeout/retries. Salida real **MANIFEST_EQ True**. Para schema se invocaron `model_json_schema()` y `schema_instruction()` con D2Draft/D4Draft; no se envió un mensaje.

Comando autocontenido de los contraejemplos principales (mismas entradas y expresiones que en la ejecución; sin resultados de evaluación como entrada):

```bash
apps/api/.venv/Scripts/python.exe -B - <<'PY'
import sys,json,ast,types,statistics
from pathlib import Path
from collections import defaultdict
from typing import Any,Mapping,Sequence,Iterable
from uuid import UUID
sys.path.insert(0,str(Path('apps/api').resolve()))
from app.evalkit.scoring import score_d4
from app.agent.evidence import EvidenceBook
from app.agent.catalog import CatalogEntry,CauseCatalog
from app.agent.schemas import Causa,D4Draft
from app.agent.guardrails.output import verify_d4
from app.confidentiality import ConfidentialityLevel as L
expected={'causa_ocurrencia':'RC-01','causa_no_deteccion':'ND-01','evidencia_suficiente':False}
content={'estado':'evidencia_insuficiente','causas_ocurrencia':[{'codigo':'RC-01','evidencia':[]}],
 'causa_no_deteccion':{'codigo':'ND-01'}}
s=score_d4(content,expected);print('SCORING',{k:s[k] for k in ['pass','abstained','abstention_correct']})
content['estado']='candidato_respaldado';s=score_d4(content,expected)
print('UNSUPPORTED',{k:s[k] for k in ['pass','abstention_correct']})
p=Path('apps/api/app/evalkit/agent.py');tree=ast.parse(p.read_text(encoding='utf-8'))
names={'_mean','_rate','paired','classify_run','_error_classes','is_invalid','aggregate','_pass_hat_k','_pct','_tool_means'}
nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.Assign,ast.AnnAssign)) and
 (isinstance(n,ast.FunctionDef) and n.name in names or isinstance(n,(ast.Assign,ast.AnnAssign)) and
 any(isinstance(x,ast.Name) and x.id in {'_INFRA_ERRORS','_POLICY_ERRORS','_NO_ANSWER'} for x in ast.walk(n)))]
g={'defaultdict':defaultdict,'statistics':statistics,'Any':Any,'Mapping':Mapping,'Sequence':Sequence,'Iterable':Iterable}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(p),'exec'),g)
def row(var,ok,err=None):
 return {'variant':var,'split':'dev','episodio':'SYNTH','caso_id':'SYNTH-001',
  'score':{'generated':ok,'pass':ok,'recurrent':False},'error':err,'calls':[],
  'cost_est_usd':0,'cost_reported_usd':None,'wall_ms':0,'providers':[],'models':[],
  'tokens_in':0,'tokens_out':0,'reasoning_tokens':0}
rows=[row('base',True),row('base',False,'TimeoutError'),row('enlace',True),row('enlace',True)]
print('DENOMINATORS',{'aggregate':[(x['variant'],x['pass@1'],x['invalid_rate'])
 for x in g['aggregate'](rows) if x['split']=='dev'],'paired':g['paired'](rows)})
codes=['RC-01','RC-02','RC-03','ND-01']
entries={c:CatalogEntry(c,c+' descripcion de catalogo',UUID(int=i+1),L.INTERNO,False) for i,c in enumerate(codes)}
cat=CauseCatalog({c:entries[c] for c in codes[:3]},{'ND-01':entries['ND-01']})
def run(retrieved_first):
 b=EvidenceBook()
 for c,e in entries.items():
  kw=dict(fragment_id=e.fragment_id,document='SYNTH-CATALOG',section=c,title='Catalogo',
   content=e.description,level=L.INTERNO,contains_pii=False)
  if retrieved_first:b.add_fragment(**kw)
  b.add_fragment(**kw,catalog_code=c)
 def cause(c,i):return Causa(codigo=c,explicacion='Hipotesis sistemica por verificar con nuevos datos',
  evidencia=[{'texto':'La fila describe una hipotesis de catalogo','fuentes':['F'+str(i)]}],
  pregunta_confirmacion='Que dato independiente permitiria confirmarla?')
 draft=D4Draft(estado='candidato_respaldado',causas_ocurrencia=[cause(c,i+1) for i,c in enumerate(codes[:3])],
  causa_no_deteccion=cause('ND-01',4))
 out,vs,_=verify_d4(draft,b,cat)
 return {'retrieved_first':retrieved_first,'estado':out.estado,'respaldo':out.causas_ocurrencia[0].respaldo,
  'violations':[v.code for v in vs]}
print('CATALOG_DEDUPE',[run(False),run(True)])
tree=ast.parse(Path('apps/api/app/agent/graph.py').read_text(encoding='utf-8'))
nodes=[n for n in ast.walk(tree) if isinstance(n,ast.If) and n.lineno==499];assert len(nodes)==1
small=types.SimpleNamespace(causas_ocurrencia=[1,2,3],causa_no_deteccion='ND-01',estado='candidato_respaldado')
large=types.SimpleNamespace(causas_ocurrencia=[1,2,3],causa_no_deteccion=None,estado='evidencia_insuficiente')
env={'best':small,'content':large};exec(compile(ast.Module(body=nodes,type_ignores=[]),'selection','exec'),env)
print('SELECTION_TIE',{'kept':'large' if env['best'] is large else 'small','nd':env['best'].causa_no_deteccion})
large.causas_ocurrencia=[1,2];env={'best':small,'content':large}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'selection','exec'),env)
state={'models':{}};modelnode=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and n.lineno==591)
exec(compile(ast.Module(body=[modelnode],type_ignores=[]),'attribution','exec'),
 {'state':state,'label':'D4','res':types.SimpleNamespace(decision=types.SimpleNamespace(model='SYNTH-LARGE'))})
print('ATTRIBUTION',{'kept':'small' if env['best'] is small else 'large','label':state['models']['D4']})
from app.agent.manifest import build_manifest
D=types.SimpleNamespace(provider_label='synthetic',base_url=types.SimpleNamespace(host='localhost'),model_small='same',
 model_large='same',simulated=False,json_mode=False,extra_body={},price_in_per_mtok=0,price_out_per_mtok=0,
 timeout_s=60,max_retries=3)
deps=types.SimpleNamespace(gateway=types.SimpleNamespace(settings=types.SimpleNamespace(local=D,api=None)),
 tool_budget=15,d4_max_rounds=2,expand_case_links=True,max_linked_8d=2,controls_mode='hybrid')
a=build_manifest(deps,index_version='synthetic',catalog=cat);D.timeout_s=600;D.max_retries=8
b=build_manifest(deps,index_version='synthetic',catalog=cat);print('MANIFEST_EQ',a['config_id']==b['config_id'])
PY
```

La variante de stdout ejecutada usó `json.dumps` y no repr para los mismos diccionarios; los valores históricos están transcritos en RIESGO-01 y BUG-02/07/08/09/21. RIESGO-01 ilustra un endpoint definido, no un defecto implementado. Las referencias de línea AST requieren las huellas de fuente registradas; si cambian, revisar la selección, no ampliar la ejecución al módulo entero.

### Inventario de bloqueos y límites pendientes

| Pendiente | Bloqueo concreto / decisión de seguridad |
|---|---|
| Vector/híbrido, distractores semánticos, recall completo | No carga local de e5 demostrada sin descarga; no se inició modelo. SQL léxico documental no los sustituye |
| Suficiencia por tools, evolución temporal de cada dev | No hay lista de filas autorizadas por episodio independiente de verdad mezclada; no se ejecutaron tools amplias sobre líneas/fechas compartidas |
| Tokens/contexto D2 efectivos | Registros leídos son D4; sin tokenizador/nombre efectivo actual demostrado, no se informa total D2 ni reasoning D2 |
| Efecto causal de orden, chunks, enlaces, voting | Requiere ensayos nuevos autorizados; solo hay fuente, sondas léxicas y registros dev archivados |
| Integridad de cadena y concurrencia real | No se leyó audit_log mixto ni se realizaron escrituras/fallos concurrentes; migraciones no equivalen a prueba operativa |
| Validación de nuevos episodios | Son diseños; validador actual carga heldout. Ningún resultado «0 errores» |
| Baselines/test y afirmaciones históricas restantes | Fuera de evidencia verificada; no abrir test para resolverlas |

## 9. Cierre y siguiente decisión

- [x] A: tamaños reales documentales, contexto D4/atomicidad, metadatos, prefijos/norma, síntomas vs consultas causales manuales y separación candidatura/ranking; vector/híbrido explícitamente pendiente.
- [x] B: orden/anclaje, redundancia/tensión de formato, presupuesto de caracteres/tokens archivados, D2/razonamiento, cortes, descartes finales, tiers, RC→ND, temperatura/voting.
- [x] C: discriminadores, ventanas/límites/truncamiento, replay/futuro/autorreferencia; sospechas de dedupe, selección ND, atribución, manifiesto y feedback reproducidas con controles sintéticos.
- [x] D: EV-01..12/E6..8, suficiencia limitada/leakage, tres clusters, nueve episodios nuevos en papel, validación sellada bloqueada y umbral/incertidumbre predefinidos como propuesta.
- [x] E: retries/timeouts, idempotencia/concurrencia, auditoría, fronteras de confidencialidad y reconstrucción.
- [x] Sin agentes/LLM/proveedores, test, regeneración, instalaciones, código/configuración modificados ni commits. Sin documento de propuestas de fase 2.

**Siguiente recomendación:** revisar primero el alcance interpretativo de RIESGO-01 y BUG-02, además de los contraejemplos BUG-07/08/09/20/21. Un endpoint nuevo de respaldo no redefine el legado; los tests sintéticos de seguridad/instrumentación/selección pueden aprobarse por separado sin dataset ni Docker. La medición operacional sí requiere lector/origen dev autorizados; el plan de fase 2 no implica aprobación de implementación.

**Comprobación histórica del entregable original:** lectura UTF-8 correcta, 23 identificadores consecutivos 01–23, sintaxis Python válida entonces de los cinco bloques bash con stdin y siete huellas inalteradas. No se traslada esa validación a las recetas revisadas ni se repitieron mediciones durante la corrección.

**Corrección documental de revisión:** se mantiene toda métrica observada; se reclasifica RIESGO-01 según el contrato explícito, se distinguen comandos históricos de recetas nuevas no ejecutadas y se sustituye la receta SQL interpolada por especificación con binds. Solo se añadieron nombres/hashes de los quince documentos ya autorizados como procedencia acotada, no como certificación del corpus real. No se aprobaron cambios de implementación ni se abrieron datos/resultados adicionales.
