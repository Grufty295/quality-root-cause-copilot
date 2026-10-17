# Fase 0 — Mapa técnico del análisis D2/D4

**Resultado:** el flujo real está mapeado sobre el árbol de trabajo, no solamente sobre el commit. D4 ejecuta 13 herramientas deterministas y hasta 14 con expansión por enlace; esta expansión está **activada en el runtime**. La consulta de recuperación concatena descripción y parte, normaliza espacios y corta a 600 caracteres. El guardrail comprueba referencias y presencia de códigos, pero no demuestra respaldo semántico.

**Validez de resultados anteriores:** no se ha establecido que una serie histórica concreta sea inválida. No se abrieron resultados guardados ni registros de evaluación. Los números del PRD y de comentarios del código son afirmaciones documentales, **no métricas verificadas en esta auditoría**. Sí se comprobaron divergencias del PRD y riesgos de comparabilidad descritos más abajo.

## 1. Alcance y procedencia

- Auditoría estática de fase 0; no es un cambio SDD. Único entregable: `audit/00-mapa.md`.
- Fecha de la sesión: 17 de octubre de 2026. Raíz verificada: `quality-root-cause-copilot`; HEAD: `8431e64629be4d3f9acb250d5ec67bc06e102e51`.
- La evidencia representa archivos **con modificaciones preexistentes**, cuya autoría no se atribuye a esta auditoría. Las referencias `archivo:línea` corresponden a ese árbol de trabajo.
- No se ejecutaron agentes, modelos, embeddings, pruebas, validadores generales, generadores, ingesta ni consultas de base. No se instalaron dependencias ni se cambió el entorno.
- No se abrieron payloads de E9/E10, EV-13..20, archivos de resultados ni directorios de datos. No se leyeron `.env`, secretos o valores del entorno.
- CodeGraph se intentó una vez con `projectPath` explícito y la consulta solicitada. Respondió que no existe índice. Se utilizaron lecturas y búsquedas acotadas como alternativa; no se inicializó índice. La ausencia conocida de `.codegraph/` no es un incidente.
- Skill cargada mediante ruta inyectada: `C:/Users/sebas/.config/opencode/skills/cognitive-doc-design/SKILL.md`. Registro consultado: `.atl/skill-registry.md`. No se generó HTML ni se delegó trabajo.

### Estado preexistente registrado

`git status --short` mostró modificaciones en `Makefile`; agente `graph.py`, `manifest.py`, `observe.py`, `routes.py`, `runtime.py`, `tools.py`; evalkit `agent.py`, `retrieval.py`; recuperación `models.py`, `repository.py`; `apps/api/tests/retrieval/test_retrieval_db.py`; frontend `globals.css`, `layout.tsx`, `page.tsx`, `next.config.ts`; y `docs/evaluacion.md`.

También había archivos/directorios sin seguimiento: `.vscode/`, dos pruebas nuevas (`test_audit_route_db.py`, `test_observe_metrics.py`) y componentes, utilidades, login y NCRs del frontend. No se inspeccionaron ni modificaron sus contenidos para este mapa. El estado inicial no equivale al contenido de HEAD.

## 2. Flujo real: petición → salida

```text
POST /ncrs/{id}/analyze [disciplinas opcionales, Idempotency-Key]
  │ sesión del servidor + rol ingeniero
  ▼
AnalysisService
  ├─ replay autorizado: devuelve corrida previa, sin LLM
  ├─ lectura corta: NCR visible, versiones previas, catálogo visible/as_of
  ├─ decide pendientes: nueva o rechazada; no sobrescribe pendiente/aprobada
  └─ abre analysis_run y libera conexión de lectura
       ▼
guard_input(descripción NCR)
  ├─ patrón de injection → bloquea todas las disciplinas → fin
  └─ sin patrón
       ▼
gather [hilo síncrono, conexión SQL solo durante recolección]
  ├─ D2: defectos por estación y turno
  ├─ D4: añade semana/aplicador/parte/lote, mantenimiento/desgaste/
  │      crimpado/cambios/lotes
  ├─ D4: build_query → search_cases(5) + search_controls(6)
  │        └─ runtime: hasta 2 enlaces de 8D → sección D4 (hasta 12 fragmentos)
  ├─ SQL filtra visibilidad/fecha/tipo/exclusión antes de ranking
  ├─ Python deduplica fragmentos y pone injection recuperada en cuarentena
  └─ añade catálogo completo visible al EvidenceBook (F#, T#)
       ▼
d2, si se solicitó
  NCR + T(estación, turno) + revisión previa/feedback
  → gateway + JSON Schema → validación JSON → guardrail D2
  → hasta 2 rondas semántico-estructurales externas
       ▼
d4_small, si se solicitó
  NCR + todos los T# + F# recuperados + catálogo abreviado + D2/revisión
  → gateway + JSON Schema → validación JSON → guardrail D4
  ├─ sin violaciones → fin [incluye abstención sin violaciones]
  └─ violaciones/error LLM → d4_large
       misma evidencia + nota de violaciones, no nueva búsqueda
       → conserva contenido según número de RC válidas → fin
       ▼
AnalysisService: nueva transacción + bloqueo NCR + comparación de versiones
  ├─ hubo cambio concurrente → conflicto, sin escribir borradores
  └─ persiste section_version + citation(F#) + estado NCR
       ▼
cierra analysis_run [estado, tiempos, uso, manifiesto/config_id]
       ▼
AnalyzeOut: secciones, blocked/skipped, eventos, llamadas, uso, trace_id
       ▼
revisión humana posterior; el agente no aprueba ni cierra el 8D
```

**Evidencia:** `apps/api/app/agent/routes.py:108–123`; `service.py:79–158,282–359`; `graph.py:179–204,242–518`. La conexión de lectura de `gather` termina antes de D2/D4 (`graph.py:259–294`); no se observó una conexión de esa recolección mantenida durante la generación. Redacción y auditoría abren transacciones propias cuando corresponde.

El endpoint público no admite `as_of` ni `exclude_sources`; esos parámetros pertenecen al servicio y a replays/evaluación (`routes.py:35–39,120–122`; `service.py:84–88`). El eval del agente solicita **solo D4** (`evalkit/agent.py:104–105`): eso explica que una serie de ese harness no tenga llamadas D2, sin suponer un fallo de instrumentación.

## 3. Consulta y recuperación

### 3.1 Composición exacta de `build_query`

```python
QUERY_CHARS = 600
return " ".join(f"{description} {part_number or ''}".split())[:QUERY_CHARS]
```

Fuente: `apps/api/app/agent/graph.py:68,93–96`.

1. Usa la **descripción completa original**, un espacio y la parte, o cadena vacía.
2. `split()` elimina extremos y colapsa cualquier secuencia de espacios, tabulaciones y saltos; `join` deja espacios simples.
3. Corta los primeros 600 caracteres de la cadena ya normalizada. No son tokens ni bytes; no conserva límites de palabra/código.
4. La parte se agrega al final: una descripción larga puede eliminarla completa o parcialmente. Tampoco hay deduplicación si ya estaba en la descripción.
5. No agrega cliente, planta, línea, turno, fechas, defecto estructurado, códigos RC/ND, D2, feedback ni resultados de tools.
6. La misma cadena alimenta **ambas búsquedas** (`graph.py:364–372`) y el eval de recuperación (`evalkit/retrieval.py:173`). El prompt de generación, en cambio, conserva la descripción completa (`prompts.py:62–72`): truncar la búsqueda no trunca el caso enviado al generador.

`SearchQuery` exige longitud 3–2000, `top_k` 1–20 y vuelve a normalizar espacios (`retrieval/models.py:45–70`). No existe reformulación por LLM. La validación de `SearchQuery` puede lanzar errores distintos de `ToolError`; el bloque del grafo captura únicamente este último (`graph.py:370–377`).

### 3.2 Ranking y filtros SQL frente a Python

| Lugar | Operación real | Límites importantes |
|---|---|---|
| SQL, antes de ranking | `visible_fragments(user.id)`; fecha documental `<= as_of` o fecha nula; tipos permitidos; exclusión por `source_key` | Visibilidad es alcance del usuario, no filtro adicional por la línea de la NCR. Los documentos sin fecha pasan el corte. |
| SQL, rama léxica | Español sin códigos; `plainto_tsquery` convertido de AND a OR; códigos normalizados sin guiones y con prefijo `:*` | Coincidencia de códigos por **prefijo**, no igualdad estricta. No es filtro duro por número de parte. |
| SQL, rama semántica | Coseno pgvector; exige mismo `embedding_model` | No hay umbral mínimo de similitud ni reranker semántico posterior. |
| SQL, fusión | RRF `k=60`, 50 candidatos por rama como mínimo; suma de pesos/rangos; desempate por UUID | Producción `hybrid`: pesos 1:1, sin tope por documento. Variantes experimentales: peso vectorial 2 o un fragmento por documento. |
| Python, antes del SQL | Embedding de consulta salvo modo `text`; prefijo `query: ` | Cada búsqueda llama `embed_query`; no hay caché compartida explícita entre cases y controls. Embedding local, no llamada generativa. |
| Python, después de recuperación | Expansión opcional, deduplicación por UUID, detector de injection sobre título+cuerpo, `EvidenceBook` | Cuarentena ocurre después del top-k: no se repone un fragmento descartado. La expansión se decide con hits originales, antes de su cuarentena. |

Fuentes: `retrieval/repository.py:26–148,151–197`; `codes.py:24–63`; `service.py:32–47`; `embedder.py:85–110`; `graph.py:379–414`. Los filtros SQL se aplican también a la expansión por sección.

`search_cases`: NCR y 8D, top-5; `search_controls`: AMEF, plan de control, instrucciones y SOP, top-6. No incluye automáticamente normas, especificaciones ni requisitos de cliente (`tools.py:132–138,679–725`). Los fragmentos pueden pertenecer a varios documentos o repetirse dentro del mismo documento; el modo de producción no impone diversidad documental.

### 3.3 Expansión y catálogo fuera del ranking

- `linked_8d` usa el propio `source_key` de un hit 8D o extrae referencias mediante `\b8D-\d{4}-\d{3}\b` de una NCR. Conserva orden de aparición y unicidad; máximo 2 enlaces por defecto (`graph.py:71–90,164`).
- La herramienta enlazada consulta únicamente sección `D4`, hasta 12 fragmentos en total; no hace otra búsqueda vectorial (`tools.py:708–725`).
- `AgentDeps.expand_case_links` tiene default `False`, pero **`build_deps` lo fija a `True`** (`graph.py:158–166`; `runtime.py:50–59`). El eval sobrescribe el flag por variante: `base=False`, `enlace=True`, `enlace_ctl=True` más controles `hybrid_wdoc` (`evalkit/agent.py:46–50,93`).
- El catálogo se carga separadamente de `visible_fragments`: secciones RC/ND de documentos AMEF/SOP con corte temporal; no depende del top-k. `complete` solo exige al menos una entrada de cada familia, no 20 RC y 8 ND (`catalog.py:49–82`). Si hay varias revisiones para un código, conserva la primera por orden de sección/UUID, no la más reciente por fecha.

## 4. Herramientas deterministas y datos que llegan al prompt

El modelo **no decide ni invoca tools**. Son llamadas Python de solo lectura programadas por el grafo, secuenciales dentro de `gather`. Sea `fin = min(fecha de creación de NCR, as_of o date.max)`; la herramienta además limita el corte a hoy. `inicio = fin − 30 días`. Los intervalos por fecha incluyen ambos extremos: ese intervalo puede abarcar 31 fechas naturales, no necesariamente 30.

Hay dos relojes distintos: la ventana de fabricación usa ese `fin`, pero `_limit()` usa `as_of`/hoy para conocimiento de detecciones y estados. Sin `as_of`, analizar hoy una NCR antigua puede incorporar conocimiento posterior a su fecha original. La recuperación documental tampoco queda cortada por creación de NCR si `as_of` es nulo; esto no debe confundirse con el replay fechado del eval (`tools.py:203–212,746–748`; `retrieval/repository.py:43`).

### 4.1 Inventario de llamadas de negocio

| Orden / ID normal¹ | Llamada y parámetros del grafo | Datos entregados | D2 | D4 |
|---|---|---|:---:|:---:|
| 1 / T1 | `defect_summary(planta,línea,inicio,fin, estacion)` | Conteos por estación, porcentajes, producción/tasas, avisos de detección tardía | Sí | Sí |
| 2 / T2 | Igual, `turno` | Conteos por turno y denominador de producción por turno | Sí | Sí |
| 3 / T3 | Igual, `semana` | Tendencia semanal de defectos y producción | No | Sí |
| 4 / T4 | Igual, `aplicador` | Defectos por aplicador; no tiene denominador propio | No | Sí |
| 5 / T5 | Igual, `parte` | Defectos por parte, producción asociada | No | Sí |
| 6 / T6 | Igual, `lote_terminal` | Defectos por lote; cobertura de eventos que tienen lote | No | Sí |
| 7 / T7 | `maintenance_history(planta,línea,fin−120d,fin)` | Hasta 25 órdenes recientes, equipo, vencimiento/ejecución, estado, ciclos, motivo y notas | No | Sí |
| 8 / T8 | `applicator_wear(planta,línea,on=fin)` | Ciclos desde último servicio, umbral/ratio PM, PM pendientes y faltantes de días | No | Sí |
| 9 / T9 | `crimp_summary(planta,línea,fin−60d,fin)` | Altura/tracción por equipo-terminal-cable, posición normalizada, margen, NOK, remedición/muestra | No | Sí |
| 10 / T10 | `change_log(planta,línea,fin−90d,fin)` | Hasta 25 cambios, equipo/parte/variante, revisiones, descripción, actualizaciones y rol aprobador | No | Sí |
| 11 / T11 | `material_lots(planta,línea,inicio,fin)` | Hasta 25 lotes consumidos, proveedor, inspección/resultado, ventana/estado conocidos | No | Sí |
| 12 | `search_cases(build_query,top_k=5)` | Hasta 5 fragmentos NCR/8D | No | Sí |
| 13 | `search_controls(build_query,top_k=6)` | Hasta 6 fragmentos de controles | No | Sí |
| 14, condicional | `linked_case_causes(hasta 2 8D,limit=12)` | Hasta 12 fragmentos D4 enlazados | No | Sí |

¹ Los IDs T# se asignan solo a salidas incorporadas: si una herramienta falla, los posteriores se desplazan. `search_*` producen F#, no T#. El catálogo también produce/reutiliza F#.

Fuentes: `graph.py:296–414`; `tools.py:180–297,336–675,679–725`. D2 solo necesita 2 llamadas; D4 o D2+D4 necesitan 13, hasta 14 con enlace. El presupuesto del grafo es **15**, aunque el default autónomo de `ToolBudget` es 8 (`graph.py:158`; `tools.py:145–155`). Cada llamada consume presupuesto antes de validar; una rechazada se registra y continúa. No hay recarga de presupuesto por cambio de modelo. El conteo de tools **no es el conteo de consultas SQL**: permisos y producción agregan consultas internas, y catálogo/términos/versiones también se leen fuera de ese presupuesto.

### 4.2 Qué filtran realmente las tools

- **Permisos:** Python solicita `user_allowed_lines` y rechaza si la línea no está permitida; las consultas de datos filtran planta/línea con parámetros enlazados. No es un permiso elegido por el modelo (`tools.py:750–760`; `db/migrations/sql/0003_scope_fix.sql:33–45`).
- **Defectos:** SQL limita fabricación y `detected_on <= corte`; no filtra por parte de la NCR, familia de defecto ni turno, porque el grafo no pasa esos filtros. D2/D4 ven **todos los defectos de la línea** en el rango. Hasta 40 grupos; tiempo: últimos grupos y luego inversión cronológica; otras dimensiones: mayor cantidad. Producción calcula denominadores por turno/fecha/semana/parte o total de línea (`tools.py:195–334`).
- **Mantenimiento:** SQL selecciona por vencimiento o ejecución dentro del rango. Python oculta una ejecución posterior al corte y cambia estado a pendiente; motivo/notas siguen incorporándose, hasta 160 caracteres cada uno. No se observa fecha de conocimiento independiente para esos textos (`tools.py:352–404`).
- **Desgaste:** SQL usa servicios completados hasta referencia, suma ciclos posteriores y consulta PM no completadas al corte; Python calcula ratio, orden descendente y advertencias. No hay límite de equipos en la salida (`tools.py:101–129,406–481`).
- **Crimpado:** SQL agrega por equipo y combinación de partes; sin filtro de equipo en el grafo, **no se incorpora tendencia semanal**, aunque la herramienta la ofrece al recibir `equipment`. No hay límite global de grupos en esta salida (`tools.py:76–99,620–675`).
- **Cambios:** SQL por planta, pertenencia de línea al array y fecha; Python limita descripción a 400 caracteres. El grafo no filtra equipo/parte (`tools.py:498–537,806–821`).
- **Lotes:** SQL por planta, recepción conocida y solapamiento de consumo; **no por línea** ni parte en esta llamada. `line_id` solo comprueba autorización. Python oculta fin/estado cuando el consumo termina después del corte; los datos pueden ser de consumo compartido entre líneas (`tools.py:548–602,824–833`).

### 4.3 Composición completa de D2 y D4

| Bloque | D2 | D4 pequeño y grande | Tratamiento |
|---|---|---|---|
| Instrucción de sistema | D2 5W2H + reglas comunes | 3 RC distintas + 1 ND, evidencia, contradicciones, refutación, faltantes y abstención | `prompts.py:21–59` |
| JSON Schema | `D2Draft` | `D4Draft` | Añadido como **otro mensaje system**, antes de los mensajes de etapa; no es únicamente `response_format` (`llm/structured.py:39–47,71`). |
| NCR | Código, línea, turno, parte, cliente, fecha de reporte, descripción completa | Igual | HTML escape; `<caso id="NCR">`. No agrega planta explícita (`prompts.py:62–72`). |
| T# | Solo defectos estación/turno | Todas las salidas de datos disponibles | Texto completo de tool, sin recorte global; encabezado, nivel e ID entre etiquetas (`graph.py:423–438,462–470`; `evidence.py:46–50,106–127`). |
| F# recuperados | Ninguno | Casos, controles y enlaces sobrevivientes | Body limitado a 1400 caracteres por fragmento; header separado, escape HTML. |
| Catálogo | No | Todas las entradas visibles RC/ND | Cada descripción normalizada y cortada a **260 caracteres**; ID citable. No se vuelve a imprimir en `<fuentes>` el ID que se lista como catálogo (`prompts.py:102–115,181–184`). |
| D2 vigente | No | Nuevo D2 si existe; si no, prior no rechazado | Solo texto de siete campos cuando se puede validar; fallback JSON sin índice (`graph.py:458–459,709–711`; `prompts.py:105–108,187–197`). |
| Regeneración humana | Borrador rechazado, feedback y motivo | Igual, para D4 | Se elimina `indice_fuentes`, no se remapean referencias antiguas a los IDs del nuevo libro (`prompts.py:154–178`). |
| Corrección de esquema | Respuesta anterior + errores de validación | Igual | Hasta 3 intentos internos; errores hasta 1500 caracteres (`llm/structured.py:75–113`). |
| Corrección de guardrail | Respuesta anterior completa + violaciones | No dentro del mismo tier | D2 tiene una segunda ronda; D4 grande recibe nota de violaciones, no la respuesta pequeña completa (`graph.py:477–488,624–635`). |

El contenido de herramientas se clasifica por reglas en cada `gather`; el nivel de fragmentos proviene del índice. Catálogo y herramientas no pasan por la misma cuarentena de injection que los hits recuperados. El feedback y las versiones previas se escapan, pero no se incorporan explícitamente a la agregación de niveles/PII de `_ctx` (`graph.py:352–359,397–414,637–667`). Esto delimita la cobertura de la política; no demuestra una fuga ejecutada.

### 4.4 Tamaños aproximados: estimación, no medición de tokens

**Método:** se contaron caracteres de cadenas estáticas mediante AST, sin importar la aplicación. Solo esos caracteres fueron medidos. Para orientar lectura se usa la heurística **3–5 caracteres por token**: `ceil(caracteres/5)` a `ceil(caracteres/3)`. No es tokenización del modelo; español, códigos, JSON, escape HTML y marcadores pueden variar mucho. Ningún número siguiente es uso real del proveedor.

| Componente | Tamaño verificable / aproximación de tokens |
|---|---|
| Sistema D2, reglas incluidas | **1284 caracteres contados** → aproximadamente **257–428 tokens** |
| Sistema D4, reglas incluidas | **2401 caracteres contados** → aproximadamente **481–801 tokens** |
| Consulta de recuperación | Hasta 600 caracteres normalizados → aproximadamente **120–200 tokens**, más `query: ` para embedding; no es por sí sola un bloque adicional del prompt generativo |
| Un fragmento ordinario | Presupuesto de chunk nominal 550 caracteres → aproximadamente **110–184 tokens** de cuerpo; no es límite duro para filas atómicas o unidades largas (`chunker.py:219–237,270–282`) |
| Un F# renderizado | Hasta 1400 caracteres de cuerpo → aproximadamente **280–467 tokens** de cuerpo, más header/etiquetas y expansión de escape |
| Casos + controles | Hasta 11 F# → aproximadamente **1210–2024 tokens** de cuerpo si cada uno mide 550 caracteres; hasta **3080–5137** si cada cuerpo llega a 1400; no son tamaños observados |
| Enlaces | Hasta 12 F# adicionales → aproximadamente **1320–2200 tokens** de cuerpo a 550 caracteres cada uno; hasta **3360–5600** a 1400 |
| Catálogo | Hasta 260 caracteres por entrada → aproximadamente **52–87 tokens** por descripción, más ID/etiquetas; con el catálogo nominal del PRD (20 RC + 8 ND), hasta **1456–2427 tokens** de descripciones; cantidad real en DB no medida |
| Cada T de defectos (T1–T6) | `H + Σ longitud(fila) + avisos`, hasta 40 filas. Ejemplo **hipotético**: 10 filas de 80 caracteres + 200 de encabezado/avisos = 1000 caracteres → **200–334 tokens por tool** |
| Mantenimiento (T7) | Hasta 25 filas; motivo+notas hasta 320 caracteres por fila, además de metadatos. Solo esos dos campos al máximo suman 8000 caracteres → **1600–2667 tokens**, sin contar metadatos; no es un tamaño total observado |
| Desgaste (T8) | Sin límite global de equipos. Ejemplo **hipotético**: 5 filas de 250 caracteres + 200 de encabezado = 1450 → **290–484 tokens** |
| Crimpado (T9) | Sin límite global de combinaciones. Ejemplo **hipotético**: 5 filas de 400 caracteres + 300 de leyenda = 2300 → **460–767 tokens**; el grafo no pide la serie semanal |
| Cambios (T10) | Hasta 25 filas; descripción hasta 400 caracteres por fila. Solo descripciones al máximo: 10000 caracteres → **2000–3334 tokens**, más metadatos |
| Lotes (T11) | Hasta 25 filas; sin límite global de caracteres de cada fila en el renderer. Ejemplo **hipotético**: 10 filas de 220 caracteres + 200 de encabezado = 2400 → **480–800 tokens** |
| NCR, D2 previo, feedback, borrador previo | Variables; contar texto final escapado. No se midieron con casos reales ni se infirió su tamaño a partir de resultados guardados |
| Schema y overhead del protocolo | Presentes; tamaño **no medido**. La introspección aislada del schema se bloqueó con `PydanticUserError`; no se aplicó workaround ni se importó el runtime |

**No hay un total de entrada verificado.** D2 = schema + sistema + NCR + dos tools + revisión + protocolo. D4 = schema + sistema + NCR + once tools + F# + catálogo + D2 opcional + revisión + protocolo; el grande añade nota. A esto se suma historial en reintentos. No hay presupuesto global de entrada por tokens, selección dinámica por tamaño ni resumen de tools (`evidence.py:94,120,141–143`). El límite de 8192 es de **salida**, no de contexto de entrada.

## 5. Decisiones de guardrails y cascada

### 5.1 Controles antes y después del modelo

| Control | Decisión real | Lo que no acredita |
|---|---|---|
| Injection de NCR | Regex sobre descripción; bloquea todo el grafo | No es detector exhaustivo ni inspecciona todos los campos del caso |
| Injection de recuperación | Regex sobre título+cuerpo; cuarentena individual | No evalúa semánticamente ataques ni repone top-k |
| Esquema | Tipos, longitudes y cardinalidad; D4 exige 3 RC distintas y 1 ND con forma correcta | La forma de RC/ND no prueba pertenencia al catálogo; eso ocurre después |
| Guardrail D2 | IDs existentes/NCR, PII/culpa y cierre | No verifica que un número o frase esté respaldado por el texto citado; valida contra el libro completo, no contra el subconjunto efectivamente entregado a D2 |
| Guardrail D4 | Código en catálogo; fuentes existentes; al menos un F# positivo; algún F# positivo contiene código normalizado; PII/culpa/cierre en textos de la causa | Presencia de código no implica respaldo causal. Un T# válido no prueba que el hecho interprete sus cifras correctamente |
| Contradicciones | IDs existentes y controles textuales de seguridad | No hay prueba determinista de contradicción semántica ni obligación de citar un fragmento para cada contradicción |
| Abstención | Solo degrada `candidato_respaldado` cuando la principal no tiene soporte de caso según reglas | No escala al grande por abstención sola. Una cita de cualquier herramienta cuenta como señal de soporte, sin medir pertinencia |

Fuentes: `guardrails/injection.py:17–86`; `schemas.py:32–98`; `guardrails/output.py:97–188,201–275`.

### 5.2 Reintentos: tres niveles diferentes

1. **Transporte HTTP:** reintenta timeouts/errores de transporte y HTTP 408/409/425/429/500/502/503/504. Default `max_retries=3` ⇒ hasta 4 intentos HTTP por llamada lógica; configuración permite otros valores. Backoff con jitter o Retry-After acotado (`llm/config.py:63–64`; `openai_compat.py:34–37,67–103,121–125`). Una respuesta 200 malformada produce `LLMResponseError`, no ese mismo bucle de reintento HTTP.
2. **JSON/Pydantic:** hasta **3 generaciones** por invocación estructurada. Agrega respuesta fallida y errores al historial. Cada generación lógica que llega al gateway tiene registro de auditoría; intentos HTTP internos no generan cada uno una fila (`llm/structured.py:61–101`; `gateway.py:144–167,224–239`).
3. **Guardrail/grafo:** D2 hasta 2 rondas; D4 1 pequeña y, si hay violaciones, 1 grande. El grande reusa evidencia, agrega explicación de violaciones y no recibe nueva recolección (`graph.py:416–518,522–635`).

Sin fallos de transporte y en la ruta máxima: hasta **6 generaciones D2 + 6 D4 = 12**; con defaults HTTP, límite teórico de **48 intentos HTTP** para ese patrón. Es una cota combinatoria del código, no un gasto observado; errores pueden cortar antes. Solo D4: hasta 6 generaciones/24 intentos HTTP bajo esos defaults. No son 13/14 tools adicionales por cada reintento.

**Selección final D4:** el guardrail puede devolver contenido parcial con una sola RC válida y ND nula. La pequeña escala ante cualquier lista de violaciones, incluso `LLMError` convertido en violación; no solo ante descarte de RC. Se retiene la propuesta con **más RC válidas** y, en empate, gana la nueva. No se compara número de ND válidas, severidad, pertinencia ni estado de abstención (`graph.py:489–518`; `guardrails/output.py:138–176`). `d4_max_rounds` aparece en dependencias/manifiesto, pero la ruta usa `rounds=1` por tier: no controla esas rondas.

**Riesgo de atribución comprobable por lectura:** `state['models']['D4']` se reemplaza en cada llamada estructurada exitosa antes de decidir si se conserva el contenido anterior (`graph.py:591,615,498–503`). Si el grande genera una respuesta estructurada pero pierde por cantidad de RC, puede conservarse contenido pequeño y persistirse la etiqueta del último modelo grande (`service.py:346`). No se afirma que esto haya ocurrido en una serie previa.

## 6. Fronteras: ingesta, gateway, citas y auditoría

### Ingesta y embeddings

- Generador: produce CSV/corpus y evals separados; `main` elimina y vuelve a crear salidas (`data/generator/generate.py:108–168`). **No se ejecutó**.
- Validator: carga CSV y verdad completa a nivel de módulo, después los casos completos. Ejecutarlo/importarlo no preserva el sellado exigido (`data/generator/validate.py:43–51,125–126`). Se leyeron solo utilidades genéricas y rangos seguros; se omitieron comprobaciones específicas de escenarios.
- CLI de ingesta rechaza rutas con componente `evals`, pero el servicio reutilizable no impone ese veto por sí mismo (`ingest/__main__.py:29–31`; `service.py:80–89`). No se inspeccionó contenido del corpus para probar ausencia de contaminación.
- Front matter inválido/sin nivel ⇒ confidencial; PII ausente ⇒ verdadera. El cuerpo no reclasifica el documento (`ingest/frontmatter.py:108–135`). Chunker elimina D1 y “Reportado por”, divide por estructura y filas, con presupuesto nominal de 550 caracteres (`retrieval/chunker.py:25–27,76–105,137–151`).
- Ingesta conserva IDs si hash/chunker/modelo coinciden; bloquea reindexar documentos ya citados. `max_chars` no integra la condición de idempotencia (`ingest/service.py:104–126`).
- Default de código para embeddings: `intfloat/multilingual-e5-large`, 1024 dimensiones, prefijos `passage: ` y `query: `; carga diferida local con fastembed (`retrieval/embedder.py:29–43,77–110`). Es default estático, no verificación del proceso desplegado.

### Gateway y confidencialidad

1. `_ctx` reúne nivel de NCR y tools de la etapa, niveles e IDs de fragmentos y PII; sin clasificación se trata como confidencial (`graph.py:637–667`; `llm/schemas.py:136–165`).
2. Router: confidencial ⇒ local; público/interno ⇒ API si configurada, si no local. D2 pequeño; D4 pequeño/grande por override de etapa (`llm/router.py:23–62`).
3. API: redactor de clientes/partes no públicos y PII, después inspector de términos confidenciales. Local con PII: redacción limitada a PII. El local simulado **no se convierte en API a efectos de estas reglas** (`gateway.py:183–214`; `redactor.py:92–101,179–201`).
4. Redactor mantiene seudónimos reversibles por NCR; restaura salida antes de validar/guardar. PII depende de heurísticas; nombre sin rol puede no detectarse. Inspector solo busca términos de catálogo configurados, no toda información sensible ni PII general (`redactor.py:13–21,105–159,205–218`; `inspector.py:28–63`).
5. Runtime construye redactor/inspector con catálogo de ese momento; no se recargan automáticamente (`runtime.py:30–49`). Feedback, versión anterior y D2 heredado no tienen niveles/PII independientes en `_ctx`: no se ha acreditado cobertura completa de todo texto que compone el prompt.
6. Cliente envía `temperature=0`, `max_tokens=8192` para generación estructurada y `extra_body` configurable; `json_mode` nativo es condicional. Los tokens de razonamiento cuentan dentro de salida cuando el proveedor los informa (`gateway.py:151–166`; `openai_compat.py:107–119,149–166`).

**Modelos/razonamiento efectivos:** no verificados. El código exige modelos por destino y permite `extra_body` para proveedor/razonamiento; no fija nombres de modelo generativo ni effort en esos defaults (`llm/config.py:38–75`). El PRD declara Qwen3.8-27B para local simulado y Haiku/Sonnet 5.5 para API, y describe `effort: low` histórico (`PRD:141–144,250`). Se registran como **declaraciones del PRD**, no configuración actual confirmada. No se imprimieron valores del entorno ni manifiestos almacenados. Configuración estática verificable: temperatura 0, tope 8192, tres intentos de esquema; el razonamiento efectivo y proveedor atendiendo solicitudes quedan pendientes de medición autorizada.

### Citas y soporte

- `EvidenceBook` define F#, T# y NCR. El cuerpo de F# se corta a 1400 caracteres; tool no tiene ese corte. Referencias guardadas incluyen metadatos, **no snapshot del cuerpo completo** (`evidence.py:23,46–66,94,106–153`).
- `citation` persiste únicamente enlaces a UUID de fragmento. Citas T# y NCR quedan en JSON de la sección; no son filas `citation` (`service.py:363–396`). Inmutabilidad/reindexado protegido contribuyen a trazabilidad, pero no prueban la interpretación semántica.
- **Dedupe catálogo:** si una fila de catálogo ya llegó como hit de controles, `add_fragment` devuelve el objeto anterior sin actualizar `catalog_code` (`evidence.py:86–88`). Luego `_verify_cause` puede clasificarla como respaldo `caso` porque `catalog_code` sigue nulo (`guardrails/output.py:272–275`). Por tanto, “respaldo de caso”/abstención no deben interpretarse como prueba semántica ni como clasificación infalible. Hallazgo estático, no frecuencia medida.
- Las descripciones de catálogo se cortan a 260 caracteres para el modelo mientras el guardrail conserva hasta 1400; además D2 valida contra el libro completo aunque solo vio dos tools. Existencia en el libro y visibilidad efectiva en el prompt no son idénticas garantías.

### Auditoría y observabilidad

- Gateway registra metadata sin contenido, incluso bloqueos/errores gestionados, en transacción propia; si esa escritura falla, no devuelve resultado (`gateway.py:188–239,273–353`; `llm/audit.py:29–70`). Una excepción al restaurar o al decidir ruta no atraviesa todos esos bloques de registro: no equivale a garantía universal de una fila para cualquier excepción posible.
- SQL tiene CHECK contra `confidencial + api`, triggers de cadena SHA-256, rechazo de update/delete/truncate y `audit_verify()` (`db/migrations/sql/0001_initial.sql:415–535`). Ese CHECK impide **registrar** combinación inválida; no es una barrera de red retroactiva. No se verificó instalación de migraciones ni cadena real.
- `analysis_run`, `section_version` y `audit_log` comparten trace_id; cierre de corrida atrapa su propio error y no necesariamente impide devolución del resultado (`service.py:218–278`). La garantía fuerte de auditoría por llamada y la tolerancia al fallo de cierre de corrida son distintas.
- `RecordingObserver(keep_evidence=True)` puede mantener texto y el eval lo guarda para juez; no es el mismo contrato que Langfuse. Langfuse omite input/output, exporta IDs, tiempos, tokens y ciertos detalles de eventos, y exige host explícito (`observe.py:255–271,277–421`). “Sin contenido” no significa “sin metadatos sensibles”.
- `LLM_DEBUG_HTTP` habilita impresión de cuerpo de error del proveedor y conserva request fallido completo en memoria; puede exponer contenido fuera del audit log. No se comprobó si está activo (`openai_compat.py:26–32,87–92,180–189`).

## 7. Evaluación: qué mide el código, sin ejecutar casos

| Módulo | Contrato comprobado por lectura | Precaución para interpretar resultados |
|---|---|---|
| `evalkit/agent.py:71–206` | Crea NCR, ajusta fecha a as_of, genera solo D4, registra auditoría/evidencia y score | Ejecutarlo escribe DB/resultados y llama proveedores; no se usó |
| `agent.py:305–325,390–489` | Separa infraestructura inválida de bloqueo de política y fallo de esquema; excluye inválidas de tasas; macro por caso/episodio | No se infiere `invalid_rate` histórico sin registros. `classify_run` retorna ok si ya hay contenido generado, aun si hubo error previo recuperado |
| `agent.py:797–806,890–900` | Retoma por caso/variante/repetición y reemplaza inválidas | La clave de reanudación no incluye config_id; cambiar configuración con mismo nombre puede mezclar series. `paired` no excluye inválidas como `aggregate` (`agent.py:521–539`) |
| `agent.py:971–1012` | Preflight llama cliente directo sin gateway/auditoría, solo texto mínimo | Excepción explícita a “todo pasa por gateway”; no ejecutado |
| `retrieval.py:160–214,399–401` | Misma query y permisos; pide 10 hits para medir @5/@10; **carga casos y verdad completos antes de filtrar dev** | No es comando seguro para el sellado de esta auditoría; @10 no representa los 6 controles que recibe el agente |
| `scoring.py:41–115` | Pass = RC esperada primera + ND aceptable; cuenta citas por documento | Abstenerse con códigos correctos también pasa; semántica de evidencia no forma parte de pass. `rc_top3` significa presencia en lista; depende del límite 3 del esquema |
| `gates.py:60–90,116–145` | Inválidas/seguridad bloqueantes, baseline 0.59, causa nueva, controles @10; sin dato no pasa | Juez semántico sin calibración no cuenta; no se ejecutaron gates porque leen reportes existentes |
| `baseline.py:144–159` | TF-IDF con historia y casos completos, copia RC/ND del 8D de NCR más similar | Sin opción de carga dev segura; no se ejecutó ni se verificaron sus cifras documentadas |

**Manifiesto y reproducibilidad:** incluye prompt/index version, hash de descripciones de catálogo, flags, top-k, decodificación, destinos y extra_body. `config_id` excluye revisión de código; esta viene de `GIT_SHA`, no de detectar el árbol sucio. Índice = versión de chunker + nombre de embedding, no hash del contenido completo ni del estado DB (`manifest.py:25–42,65–98`; `retrieval/service.py:27–30`). No cubre timeout/max_retries, todas las constantes de recuperación/chunking o todo cambio de implementación. Igual `config_id` **no basta** para acreditar igualdad del código/índice ni comparabilidad experimental sin procedencia adicional.

## 8. Divergencias comprobadas frente al PRD

Referencia abreviada **PRD**: `docs/PRD — Agente de Causa Raíz 8D (16 oct 2026).md`. No se validaron sus tablas de mediciones, despliegue o estado de pruebas.

| Tema | PRD | Árbol de trabajo auditado | Lectura de la divergencia |
|---|---|---|---|
| Baseline y gate | 55% y umbral ≥0.55 (`PRD:38,61,214`) | Gate 0.59 y comentario de baseline dev 7/12 (`evalkit/gates.py:67–69`) | PRD mezcla referencia general con la partición dev; el número actual del gate difiere. No se recalculó baseline |
| Presupuesto de tools | 14 y D4 usa 12 (`PRD:132`) | 15; D4 usa 13, hasta 14 con enlace (`graph.py:158,306–342,366–384`) | Inventario aumentado: incluye corte de lote terminal |
| Enlace desactivado | Flag apagado y decisión pendiente (`PRD:301,317`) | Runtime `True` (`runtime.py:59`) | Producción por código corresponde al enlace, no a `base`; justificación numérica en comentario no revalidada |
| `finish_reason` pendiente | No se guarda; tarea futura (`PRD:272,321`) | Parseo, auditoría, observer y eval lo recogen (`openai_compat.py:155`; `gateway.py:301–303`; `observe.py:344–369`; `evalkit/agent.py:159–163`) | La carencia documental ya no coincide con el código; no se garantiza que resultados viejos lo tengan |
| Tres RC + una ND | Contrato de salida (`PRD:95`) | Schema lo exige al modelo, pero contenido persistido admite RC parciales/ND nula (`guardrails/output.py:138–175`; `schemas.py:131–139`) | Distinguir borrador solicitado de salida depurada |
| Conexión durante LLM | Deuda conocida (`PRD:333`) | Lectura/gather termina antes de generar y escritura abre después (`service.py:102–133`; `graph.py:259–294`) | Esa deuda no se demuestra en la ruta normal mapeada |
| Todo LLM por gateway | Afirmación arquitectónica (`PRD:121,139`) | Preflight directo sin datos del caso (`evalkit/agent.py:971–994`) | Excepción de diagnóstico explícita, no generación de NCR |
| D2 ausente en auditoría | Pregunta abierta (`PRD:355`) | Harness solicita solo D4 (`evalkit/agent.py:104–105`) | Explicación suficiente para ese harness; no prueba qué comandos originaron todas las llamadas históricas |

## 9. Evidencia, comandos y limitaciones

### Leído versus ejecutado

**Leído:** runtime obligatorio del agente (`graph`, `tools`, `runtime`, `manifest`, `observe`); todos los `.py` de recuperación; evalkit `agent` (lógica operativa/agregación/reanudación/CLI), `retrieval`, `scoring`, `gates`, `baseline`; `generate.py`; utilidades y comprobaciones documentales genéricas de `validate.py`; prompts reales en **`agent/prompts.py`** (no existe carpeta `agent/prompts/`); PRD; rutas/servicio/esquemas/catálogo/evidencia; guardrails; configuración/router/gateway/cliente/inspector/audit/factory/DTOs; clasificador/redactor; ingesta; servicio/modelos NCR; SQL acotado de alcance y auditoría. No se leyeron escenarios específicos de generadores auxiliares ni fixtures/pruebas/resultados.

**Comandos ejecutados, deterministas y sin aplicación:**

```text
git rev-parse --show-toplevel
git rev-parse HEAD
git status --short
python: ast.parse de generate.py, validate.py, evalkit/agent.py y retrieval.py;
        impresión solo de nombres, tipos y rangos de nodos superiores
python: extracción por rangos seguros de validate.py (125–126, 140–157)
python: evaluación restringida de Constant/Name/JoinedStr de prompts.py;
        len de sistemas D2/D4 + conversión heurística caracteres/tokens
python: construcción aislada desde AST de clases de schema, sin app imports;
        bloqueada con PydanticUserError, sin modificación ni reintento de entorno
python: SHA-256 de archivos de código explícitos (tabla siguiente)
```

Además: herramientas read/glob/grep sobre rutas de código/documentación indicadas; un intento CodeGraph fallido por ausencia de índice; memoria Engram de hallazgos sin casos ni payloads. Las lecturas AST son análisis de fuente, **no ejecución/importación** de generadores o evalkit. Los rangos de comprobaciones por escenario de `validate.py:65–124,127–138` no se mostraron ni analizaron por contenido; solo se identificaron sus límites estructurales para evitarlos.

### Huellas del árbol leído

| Ruta, bajo raíz | SHA-256 |
|---|---|
| `apps/api/app/agent/graph.py` | `22476b5ce9d025de3fae2c50f2c47fac60754d655f3646688e754b19d31662af` |
| `apps/api/app/agent/tools.py` | `031c33a31bb26243eb822a826318d0c743477d60c9ce99ef8fa1449afcf0805a` |
| `apps/api/app/agent/prompts.py` | `7b933c62820bdd34c2b0ede51fcc45f31795d72ac0955677bc0d787128471de5` |
| `apps/api/app/agent/evidence.py` | `16df7f032f455fde107ffdda5365dbc2e84524323b1c251ec3524b5e7695aac5` |
| `apps/api/app/agent/runtime.py` | `08805c839e432051b5b06e8e958347071ba2dd0229728907f594f23e3a16fefa` |
| `apps/api/app/agent/manifest.py` | `bf566cb86b68848861407827ca9a2345b38fd6e0ac768b68668e1d7ab83930b5` |
| `apps/api/app/retrieval/repository.py` | `f029971db1fe69cb6dc5a94c4a50a601ddbad5fc2668979a3cf87f877df72d0c` |
| `apps/api/app/evalkit/agent.py` | `fad6bbb78522955faaaf508a38cff6de5ecd495bc9122097d4697ad5609ac9ca` |
| `apps/api/app/evalkit/retrieval.py` | `677eececc27bb9eaa295b407877cd78b543af6887dce660d730acbd83afa7137` |

### No medido / no acreditado

- Tokens de entrada/salida reales, tokens de razonamiento, tiempos por tool/etapa, coste, frecuencia de escalamiento y fallos de cualquier serie.
- Modelo/proveedor/quantización/effort del proceso efectivo; estado desplegado de API/observabilidad y migraciones instaladas.
- Tamaño real de catálogo, fragmentos/índice, contenido de corpus, datasets y reportes; limpieza o contaminación histórica de esos conjuntos.
- Calidad semántica de citas, exactitud de cifras generadas, falsos positivos/negativos de injection o redacción y tasa de abstención.
- Pertenencia causal de un lote/cambio/8D a un incidente concreto. Se mapearon filtros y reglas, no se ejecutó un caso.

## 10. Comprobación de cobertura y salida de fase

- [x] Diagrama textual real desde HTTP/NCR hasta salida/persistencia/revisión.
- [x] `build_query`: composición, normalización, truncamiento y pérdida posible de parte.
- [x] Inventario completo de tools, ventanas, presupuestos y fuentes D2/D4.
- [x] Tamaños aproximados etiquetados como heurística; conteos estáticos separados de tokens no medidos.
- [x] Filtros SQL/Python, expansión, catálogo y cuarentena identificados.
- [x] Guardrails, abstención, reintentos HTTP/JSON/grafo y selección final explicados.
- [x] Gateway/redactor/inspector/citas/auditoría/observadores e ingesta delimitados.
- [x] Configuración segura de código descrita; modelos y razonamiento efectivos no se inventan.
- [x] Divergencias PRD con referencias archivo:línea y procedencia del árbol sucio.
- [x] Partición sellada, resultados guardados y datos sin acceso; sin llamadas LLM/embedding, pruebas, regeneración ni cambios de código/configuración/prompts.
- [x] Solo fase 0; no implementación ni propuestas de fase 2. Sin commits.

**Validación final del entregable:** se comprobó existencia y lectura UTF-8 del archivo, presencia de términos/secciones requeridas, igualdad de huellas de `graph.py`, `tools.py`, `runtime.py` y `retrieval/repository.py` respecto de las tomadas durante la lectura, y estado Git con la misma lista preexistente más `audit/`. Esta comprobación no ejecuta pruebas ni abre datos/resultados.

**Siguiente paso recomendado:** entregar este mapa al responsable de la auditoría para la fase 1 autorizada, manteniendo el sellado y la separación entre evidencia estática y mediciones. Cualquier implementación queda fuera de este entregable y requiere la aprobación prevista tras las propuestas.
