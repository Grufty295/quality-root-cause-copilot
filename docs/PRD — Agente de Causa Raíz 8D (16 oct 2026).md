# PRD — Agente de Causa Raíz 8D

Oct 16, 2026 · @Sebastián

## Resumen ejecutivo

El agente ya produce D2 y D4 con un modelo real: la primera serie de evaluación está corriendo y las 4 corridas terminadas pasan. Lo que falta es completar la serie (72 corridas) y tener los primeros números de calidad contra la línea base trivial de 55%.

El agente redacta borradores de D2 (5W2H) y D4 (3 causas de ocurrencia del AMEF + 1 de no detección del SOP-QA-011) para una planta ficticia de arneses en Ciudad Juárez (Cablenova Juárez, JRZ1). Un humano aprueba; el agente nunca cierra un 8D. El diferenciador es el router de confidencialidad: lo confidencial solo va a un modelo local.

Desde el PRD anterior se sumaron abstención con criterios, trazabilidad por corrida con idempotencia, juez semántico (DeepEval y Ragas) que pasa por el mismo gateway, gates de evaluación y Langfuse self-hosted en una VPC propia.

| Área | Estado | Dato clave |
| --- | --- | --- |
| Dataset sintético | Hecho | 101 documentos, 20 casos de evaluación, 10 adversariales, 6 de permisos; `validate.py` sin fallas |
| Ingesta e índice | Hecho | Chunker `struct-v1`, e5-large (1024 dims), 256 fragmentos |
| Router, redacción y auditoría | Hecho | Hash encadenado y `audit_verify()` |
| Agente D2/D4 | Hecho | Cascada pequeño → grande; abstención nueva |
| Revisión humana | Hecho en API | Rechazo con motivo tipificado; la UI aún no lo pide |
| Trazabilidad de corridas | Hecho | `analysis_run`, `Idempotency-Key`, manifiesto con `config_id` |
| Eval de recuperación | Línea base | Precedente en top-5: 0.50; sección D4 en top-10: 0.00 |
| Eval del agente | En curso | 4 de 4 corridas terminadas pasan; 72 en total, concurrencia 3 |
| Eval semántico | Construido, sin correr | Juez sin calibrar: no decide nada todavía |
| Langfuse | Desplegado en VPC | La API aún no exporta trazas (timeout al enviar) |
| Pruebas | Verde | 604 pasan, 2 se saltan |
| UI web | Sin cambios | No muestra abstención, corridas ni motivo de rechazo |

## Problema y contexto

Las causas raíz se repiten porque el conocimiento de casos anteriores vive en 8D dispersos, y cada D4 nuevo empieza casi de cero. Usar una IA pública para acelerarlo expone datos del cliente, así que el agente ataca la parte más lenta (D4) sin sacar lo confidencial de la planta.

El caso es una planta ficticia de arneses eléctricos: Cablenova Juárez, planta JRZ1, con las líneas L1 y L2. Los defectos típicos son de crimpado, terminales y ensamble, con datos operativos de mantenimiento, desgaste de aplicadores, mediciones, cambios y lotes de material.

Todos los datos son sintéticos y generados con semilla fija. Ningún dato real de una planta entra al proyecto, y esa es la razón por la que hoy se permite usar OpenRouter en los dos destinos de modelo.

## Objetivos, no-objetivos y criterios de éxito

El PoC tiene éxito si el agente supera la línea base trivial (55%) sin ningún borrador inseguro, y si aporta en los casos de causa nueva, donde la línea base acierta 0 de 8.

**Objetivos**

- Proponer causas de ocurrencia y no detección verificables, citadas con evidencia del caso.
- Reutilizar el conocimiento de 8D anteriores sin inventar recurrencias.
- Decir "la evidencia no alcanza" cuando sea cierto, en lugar de forzar una causa.
- Mantener lo confidencial dentro de la planta, con auditoría verificable.

**No-objetivos**

- Cerrar un 8D o aprobar secciones sin un humano.
- D3 y D5–D8; integración con MES, ERP o QMS reales; fotos y planos.
- Despliegue productivo: el PoC corre en Docker Compose.

**Criterios de éxito (gates provisionales)**

Los umbrales se fijaron sin una corrida válida del agente. Se ajustan una sola vez, con la primera serie dev válida, y no se vuelven a mover para que una versión pase.

| Gate | Métrica | Umbral | Bloquea |
| --- | --- | --- | --- |
| Salida segura | Borradores que culpan a personas o cierran el 8D | 0 | Sí |
| Medición válida | Corridas inválidas | 0% | Sí |
| Línea base | pass@1 | ≥ 0.55 | Sí |
| Causa nueva | RC top-1 en causa nueva | ≥ 0.25 | Sí |
| Sin 8D ajeno | Causa principal apoyada en un 8D de otra causa (causa nueva) | ≤ 0.25 | Sí |
| Recuperación del precedente | `cases` híbrida, precedente en top-5 | ≥ 0.50 | Sí |
| Recuperación de controles | `controls` híbrida, hit@10 | ≥ 0.90 | Sí |
| Consistencia | pass^k | ≥ 0.50 | No |
| Abstención indebida | Se abstiene teniendo con qué responder | ≤ 0.20 | No |
| Costo | Costo estimado por análisis D4 | ≤ $0.10 | No |
| Latencia | p95 por análisis | ≤ 180 s | No |
| Citas respaldadas | Juez de citas (solo calibrado) | ≥ 0.80 | No |

Un gate sin dato no pasa. El de latencia ya se ve en riesgo: las primeras corridas tardaron de 233 a 652 s.

## Usuarios y roles

Hay cuatro roles y quien redacta no aprueba: el ingeniero corre el agente y edita, el gerente aprueba, y esa regla la impone un trigger de la base aunque el código fallara.

| Rol | Qué hace en el sistema | Dónde se aplica |
| --- | --- | --- |
| Inspector | Está en piso: abre NCRs y lee los borradores de su alcance sin editarlos, para avisar al ingeniero si algo no cuadra | API (`OPEN_ROLES`) |
| Ingeniero de calidad | Abre NCRs, es el único que corre el agente, edita y rechaza secciones | API + trigger `section_version_rules` |
| Gerente de calidad | Aprueba secciones que no abrió ni editó, y puede rechazarlas | Trigger + `review.py` (`based_on_version`) |
| Auditor | Solo lectura: borradores, corridas, citas y log de auditoría | API |

El alcance es por planta y línea (L1, L2) y se aplica en tres lugares: la API, las tools del agente y la búsqueda (`visible_fragments`, antes del ranking).

La sesión es opaca, guardada en la base, con cookie httpOnly. Keycloak no es obligatorio en el PoC.

## Alcance funcional

`POST /ncrs/{id}/analyze` genera D2 y D4 como borradores; ninguno vale hasta que el gerente lo aprueba, y una aprobación es final.

**D2 (5W2H)**: se arma con conteos de defectos por estación y turno. Mantenimiento y desgaste son evidencia causal de D4, no de D2.

**D4**: 3 causas de ocurrencia ordenadas (códigos RC del AMEF) y 1 de no detección (código ND del SOP-QA-011). Cada causa lleva:

| Campo | Qué contiene |
| --- | --- |
| `evidencia` | Fragmentos o salidas de tools que la respaldan, citados |
| `evidencia_contradictoria` | Hasta 3 hallazgos que van en contra |
| `refutaria` | Qué dato la descartaría |
| `dato_faltante` | Qué falta para confirmarla |
| `respaldo` | `caso` o `solo_catalogo`; lo calcula el guardrail, no el modelo |

No hay porcentajes de confianza: la confianza que reporta un LLM no está calibrada.

**Abstención**: el D4 declara `estado` = `candidato_respaldado` o `evidencia_insuficiente`, con `estado_motivo`. Si el modelo dice que está respaldada pero su causa principal solo cita el catálogo, el guardrail la baja a `evidencia_insuficiente`. Nunca la sube.

**Revisión humana**

1. El agente solo genera si no hay borrador o si el último fue rechazado.
2. El ingeniero edita; el gerente aprueba o rechaza.
3. Un rechazo lleva retroalimentación (mínimo 10 caracteres) y un motivo opcional: `causa_incorrecta`, `evidencia_insuficiente`, `cita_irrelevante`, `contexto_incompleto`, `redaccion` o `error_tecnico`.
4. Al regenerar, el prompt recibe el borrador anterior, la retroalimentación y el motivo.
5. Si alguien cambió las versiones mientras el modelo trabajaba, la escritura devuelve 409.

**Fuera de alcance hoy**: la UI no pide el motivo del rechazo, ni muestra el estado de abstención, la evidencia contradictoria o las corridas. La API ya los expone.

## Arquitectura

El agente es un grafo por etapas en el que el código llama a las tools y el modelo solo redacta y cita; toda llamada a un modelo pasa por un gateway único que decide el destino según el nivel de confidencialidad.

&#91;embedded content: análisis de una NCR · 5 etapas, gateway y destinos\]

El gateway decide el destino por el nivel más alto de la llamada: lo confidencial solo va al modelo local y cada llamada queda en `audit_log`. Langfuse recibe tiempos y eventos, nunca texto.

**Stack**: Next.js en el frontend; FastAPI, LangGraph y SQLAlchemy en la API; Postgres 16 con pgvector; e5-large local (fastembed) para embeddings; clientes OpenAI-compatibles configurados por variables `LLM_*`. Todo corre en Docker Compose.

**Grafo del agente**

1. **guard\_input**: si la descripción de la NCR trae instrucciones al agente, no genera nada.
2. **gather**: tools deterministas con presupuesto de 14 llamadas (D4 usa 12). Fragmentos con inyección van a cuarentena; cada salida se clasifica por nivel.
3. **d2**: redacta el 5W2H.
4. **d4\_small → d4\_large**: el modelo pequeño propone; si el guardrail descarta una causa, reintenta el grande con la retroalimentación.
5. **Persistencia fuera del grafo**: versión de sección, citas y cierre de la corrida.

**Recuperación híbrida**: texto completo en español + códigos normalizados + pgvector, fusión RRF (k=60, 50 candidatos por rama). Permisos, corte `as_of`, tipo de documento y `exclude_sources` se filtran antes del ranking.

**Gateway de modelos** (`ModelGateway`): router → redacción → inspector → cliente → restauración → auditoría. Si la auditoría no se escribe, el resultado no se devuelve.

| Destino | Modelo hoy | Vía |
| --- | --- | --- |
| Local (simulado) | Qwen3.8-27B, pequeño y grande | OpenRouter; atendido por DeepInfra (BF16) en las pruebas |
| API | Claude Haiku 5.5 y Claude Sonnet 5.5 | OpenRouter; atendido por Azure en el preflight |

La etapa `EVAL` (el juez semántico) usa el tier grande y pasa por el mismo gateway, así que obedece el router y queda auditada.

## Confidencialidad, seguridad y guardrails

El nivel más alto presente en una llamada (NCR, fragmentos y salidas de tools) decide el destino, y lo confidencial nunca va a la API: un `CHECK` en la base prohibe `confidencial` + `api` aunque el código fallara.

| Nivel | Destino | Tratamiento antes de enviar |
| --- | --- | --- |
| Confidencial | Solo local | Seudónimos reversibles de PII, también hacia el local |
| Interno o público | Local o API | Hacia la API: redacción de clientes, partes y PII + inspector del payload |

**Mecanismos**

- **Redactor** (`RuleRedactor`): reglas y catálogo de entidades; el mismo valor recibe el mismo marcador en todo el payload.
- **Inspector** (`CatalogInspector`): si queda un identificador confidencial en el payload ya redactado, bloquea la llamada y lo audita.
- **Auditoría**: `audit_log` solo de inserción, con hash encadenado y `audit_verify()`. Guarda nivel, destino, modelo, fragmentos, tokens, costo, latencia y tags; nunca contenido.
- **Local verificado**: el destino local debe ser un host privado. Para desarrollar con OpenRouter se marca como simulado, exige un permiso explícito y queda etiquetado en la auditoría.

**Guardrails de salida** (descartan la causa con motivo visible): código fuera del catálogo, cita a un fragmento inexistente, fragmentos que no mencionan el código, culpa a una persona o declara cerrado el caso. La evidencia contradictoria pasa por las mismas revisiones.

**Fuera del gateway, nada sale**

- El juez semántico usa adaptadores propios sobre el gateway, no el cliente por defecto de DeepEval o Ragas (que mandaría fragmentos a la API sin router ni auditoría).
- La telemetría de DeepEval, Ragas y Langfuse está apagada.
- El exportador a Langfuse no manda entradas ni salidas, solo metadatos que ya guarda la auditoría. Se niega a arrancar sin `LANGFUSE_HOST`, porque el SDK enviaría a la nube de Langfuse por defecto.

Con OpenRouter en los dos destinos, la garantía "lo confidencial no sale de la planta" no se cumple en las pruebas. Solo es aceptable porque los datos son ficticios.

## Trazabilidad y observabilidad

Cada análisis queda registrado como una corrida con su estado, sus tiempos, su costo y la configuración exacta que lo produjo; Langfuse es una vista adicional, no la fuente de verdad.

**Corridas (`analysis_run`, migración 0014)**

- El `id` de la corrida es el `trace_id` que comparten la auditoría y Langfuse.
- Estado: `en_curso`, `completada`, `parcial`, `sin_borrador`, `fallida` o `abandonada`. Un trigger impide cerrar una corrida dos veces.
- Una sola corrida activa por NCR. Una corrida sin cerrar por más de 15 minutos se marca abandonada.
- `Idempotency-Key` en `/analyze`: repetir la petición con la misma llave devuelve la corrida ya hecha sin volver a llamar al modelo.
- `GET /ncrs/{id}/runs` lista las corridas de una NCR.

**Manifiesto por corrida**: versión del prompt (`d2-v1+d4-v2`), versión del índice, hash del catálogo, parámetros del agente y de recuperación, decodificación, modelos, proveedor, razonamiento y precios. De todo eso sale un `config_id`. El commit (`GIT_SHA`) se guarda aparte y no cambia el `config_id`.

**Auditoría por llamada**: `audit_log` con tokens, costo estimado y reportado por el proveedor, latencia y tags (`stage`, `tier`, `destination`, `reasoning_tokens`, `http_attempts`, `outcome`, redacciones por tipo).

**Callbacks del agente**: los tiempos por etapa salen de los hooks nativos de LangGraph (`NodeCallbacks`). El agente emite además eventos propios: llamadas al modelo, fragmentos recuperados, cuarentenas, escalamientos y abstención.

| Observador | Para qué | Lleva contenido |
| --- | --- | --- |
| `RecordingObserver` | Evaluación: tiempos, eventos y evidencia para el juez | Solo si se pide (`keep_evidence`) |
| `LangfuseObserver` | Una traza por análisis, con etapas, eventos y llamadas | Nunca |

**Langfuse self-hosted**: desplegado el 16 de octubre en una VPC propia con Dokploy (compose "raw"). Usa Postgres, ClickHouse y Redis internos, y Cloudflare R2 para los eventos. La subida de media y la exportación por lotes están apagadas. La API todavía no exporta: el SDK reporta timeout al enviar spans, y el contenedor apunta al default local (`http://langfuse-web:3000`) porque `LANGFUSE_HOST` no está en `.env` o la API no se recreó.

## Evaluación

La evaluación tiene tres capas: recuperación (con línea base), agente (corriendo ahora) y semántica (construida, sin calibrar). `evalkit` es la fuente de verdad; DeepEval y Ragas solo aportan métricas de juez.

**Dataset** (`data/generator/generate.py`, semilla fija; `validate.py` sin fallas)

| Conjunto | Contenido | Uso |
| --- | --- | --- |
| Corpus | 80 NCR históricas, 6 8D cerrados, 15 documentos de control (AMEF RC-01..RC-20, SOP-QA-011 ND-01..ND-08); 101 documentos | Índice RAG |
| Datos operativos | Defectos, mantenimiento, ciclos de aplicador, crimpado, cambios, lotes | Tools del agente |
| Casos de evaluación | 20 (EV-01..EV-20), 5 episodios × 4: E6, E7, E9 recurrentes; E8, E10 de causa nueva | Calidad del agente; nunca se indexan |
| Adversariales y permisos | 10 y 6 | Guardrails, router y filtro de alcance |

**Partición**: dev = E6, E7, E8; test = E9, E10, sellada. Solo se ajusta sobre dev; test se abre una vez, con la configuración decidida.

**Línea base trivial**: copiar la causa de la NCR más parecida (TF-IDF) que tenga 8D acierta 11 de 20 (55%): 11 de 12 recurrentes y 0 de 8 de causa nueva.

**Recuperación** (`make eval-retrieval`, partición dev, promedio por episodio)

| Búsqueda | Métrica | Texto | Vector | Híbrida |
| --- | --- | --- | --- | --- |
| `cases` | 8D precedente en top-5 | 0.25 | 0.75 | 0.50 |
| `cases` | Precedente vía la NCR que lo cita, top-5 | 0.75 | 1.00 | 0.88 |
| `cases` | Sección D4 del precedente en top-10 | 0.00 | 0.00 | 0.00 |
| `controls` | Documento de control de la RC en top-10 | 0.58 | 0.92 | 0.92 |

La búsqueda encuentra el 8D precedente en la mitad de los episodios recurrentes, pero nunca su D4: la consulta describe el síntoma y se parece más a D2. La variante `enlace` (D4 de hasta 2 8D a un salto) intenta resolverlo, a riesgo de traer 8D ajenos.

**Agente** (`make eval-agent`): 12 casos dev × 2 variantes (`base`, `enlace`) × 3 repeticiones = 72 corridas. Sin juez LLM: todo sale de códigos y citas.

- pass, pass@1 y pass^k; RC top-1 y top-3 y ND, separados para recurrentes y causa nueva.
- Top-1 que cita el 8D precedente o uno ajeno.
- Abstención: si se abstuvo, si fue indebida y, cuando el caso lo trae etiquetado, si fue correcta.
- Desglose por tipo de caso, episodio, línea, defecto y nivel.
- Inválidas aparte (no entran a las tasas y se repiten al retomar); costo, tokens y p50/p95 desde la auditoría.

**Semántica** (`make eval-semantic`): cuatro métricas de juez, con un tope de llamadas por experimento.

| Métrica | Framework | Qué mide |
| --- | --- | --- |
| Citas respaldadas | DeepEval (métrica propia) | Si cada hecho citado está respaldado por sus fuentes |
| Relevancia causal | DeepEval (GEval) | Si la causa se conecta con este incidente y no solo con el catálogo |
| Faithfulness | Ragas | Fidelidad de la causa principal a su contexto |
| Precisión del contexto | Ragas | Si lo recuperado sirve para la causa esperada |

**Calibración del juez**: `make eval-labels N=40` exporta hechos sin el veredicto del juez y un ingeniero los etiqueta. El juez cuenta para un gate solo con al menos 30 etiquetas y kappa de Cohen ≥ 0.6. Si dos revisores etiquetan, su acuerdo es el techo de lo que se le pide al juez.

## Rendimiento y costo

El costo no es problema; el tiempo sí. Una llamada de D4 tarda en promedio 130 s porque genera unos 5,700 tokens, y la mitad son razonamiento. No hubo reintentos.

Mediciones del 16 de octubre sobre las llamadas de D4 en el `audit_log` (34 llamadas, Qwen3.8-27B vía DeepInfra, `reasoning.effort: low`):

| Medida | Valor |
| --- | --- |
| Tokens de salida por llamada (promedio) | 5,697 |
| De ellos, razonamiento | 2,942 (52%) |
| Tokens de entrada por llamada | 11,500 a 15,000 |
| Latencia por llamada (promedio) | 130 s |
| Velocidad de generación | 28 a 76 tokens/s, variable entre llamadas |
| Llamadas con reintento HTTP | 0 |
| Costo por llamada | $0.0013 a $0.0038 |
| Duración por corrida completa | 233 a 652 s (4 corridas) |
| Costo por corrida completa | $0.0038 a $0.0133 (4 corridas) |

**Lectura**

- El timeout no es la causa: ninguna llamada se reintentó. Las llamadas de más de 180 s fueron generación continua.
- El JSON del D4 no está inflado: el contenido real ronda 2,750 tokens. Los campos de abstención no explican el tiempo.
- El tiempo de pared de la serie se redujo con concurrencia (`--concurrency`, 3 por defecto): de unas 8 horas a unas 2.5 estimadas. No cambia la calidad.

**Regla**: nada se recorta por comodidad. Un campo o un nivel de razonamiento se quita solo si el eval muestra que no cambia RC top-1/top-3, ND, citas ni faithfulness.

**Riesgo de calidad abierto**: el tope es `max_tokens = 8192` y ya hubo salidas de 7,183 tokens. Si una respuesta llega al tope, el JSON se corta y la corrida se pierde. Hoy no se puede saber si ya pasó, porque `finish_reason` no se guarda en la auditoría.

## Registro de decisiones

Las decisiones de arquitectura del PRD original siguen vigentes; las filas de abajo son las que pesan hoy, con las de esta semana primero.

| Decisión | Elección | Descartado | Por qué |
| --- | --- | --- | --- |
| Recortes de salida | Solo con evidencia del eval | Recortar el esquema o el razonamiento para ganar tiempo | La calidad manda; el tiempo se resuelve con concurrencia |
| Velocidad de la serie | Concurrencia 3 en el harness | Bajar el timeout; reducir repeticiones | Baja el tiempo de pared sin tocar la medición |
| Langfuse | Self-hosted en VPC (Dokploy) con R2 | Nube de Langfuse; MinIO en el VPS | Los metadatos de la planta no salen a un tercero; R2 evita operar el almacenamiento |
| Exportador de trazas | Observador propio sin contenido | Handler de LangChain de Langfuse | El handler manda el estado completo de cada nodo, con NCR y fragmentos |
| Juez semántico | DeepEval y Ragas a través del gateway | Su cliente OpenAI por defecto | El default saltaría el router y la auditoría |
| Fuente de verdad del eval | `evalkit` (códigos, citas, qrels) | Frameworks como fuente principal | Verificable y barato; el juez solo complementa |
| Uso del juez | Solo cuenta calibrado (≥ 30 etiquetas, kappa ≥ 0.6) | Usarlo de inmediato | Un juez sin medir no es evidencia |
| Abstención | `estado` del D4; el guardrail solo baja, nunca sube | Forzar siempre 3 causas | Mejor decir "no alcanza" que inventar una recurrencia |
| Rechazo | Motivo tipificado + texto libre | Solo texto libre | Permite medir por qué se rechaza y alimentar el prompt |
| Corridas | `analysis_run` con `Idempotency-Key` y manifiesto | Solo `section_version` | Reproducir y comparar exige la configuración exacta |
| Gates | Umbrales provisionales, ajustados una sola vez | Ajustarlos en cada versión | Moverlos para que algo pase invalida la comparación |
| Imagen Docker | `uv sync --no-install-project` en los dos pasos | Instalar el proyecto | El código corre desde `/app`; el build fallaba buscando `src/api` |
| Orquestación | Un agente por etapas; tools llamadas por el código | Multiagente; tools elegidas por el LLM | Reproducible y con menos superficie de evaluación |
| Salida de D4 | 3 RC del AMEF + 1 ND, sin porcentajes | Causas libres; confianza numérica | Códigos verificables; la confianza de un LLM no está calibrada |
| Base de datos | Postgres con pgvector para todo | Qdrant, Redis | Datos, vectores, permisos y auditoría en un solo lugar |
| Embeddings | e5-large local | API de embeddings | Los documentos confidenciales no salen ni al indexarse |
| Permisos en RAG | Filtro en SQL antes del ranking | Filtrar después | Un fragmento fuera de alcance nunca compite ni aparece en trazas |
| Replay | `as_of` + `created_at` del caso + `exclude_sources` | Fecha de hoy | Sin esto el agente ve el futuro o se cita a sí mismo |
| Partición | dev E6–E8, test E9–E10 sellada | Medir todo junto | Evita sobreajustar a los casos que deciden |
| Corridas fallidas | Inválidas: fuera de las tasas, se repiten | Contarlas como 0% | Un error de configuración no mide al modelo |
| Modelo "local" de prueba | Qwen3.8-27B | Modelo de frontera | Debe ser lo que cabría en un servidor de planta con 1 GPU de 24 GB |
| Expansión por enlace | Detrás de un flag, apagada | Encenderla ya | Trae el precedente pero también 8D ajenos; lo decide el eval |

## Estado actual y siguientes pasos

Lo siguiente es terminar la serie dev y correr los gates; todo lo demás depende de tener la primera tabla de pass@1 con un modelo real.

**Hecho esta semana**

- Eval del agente desbloqueado: `llm-diagnose CASO=EV-01` corrió sin rechazos HTTP y generó D4 (RC-01, RC-04, RC-07) en 4 llamadas.
- Abstención, `analysis_run`, idempotencia, motivo de rechazo, callbacks, observador de Langfuse, juez semántico, calibración y gates.
- Concurrencia en el harness del eval y aviso de progreso en el diagnóstico.
- Corrección del Dockerfile (`--no-install-project`).
- Langfuse desplegado en la VPC con R2.

**Siguientes pasos**

1. **Terminar la serie dev** (`make eval-agent`, 72 corridas) y correr `make eval-gates`. Salida: primera tabla con pass@1, pass^k, causa nueva, 8D ajeno y abstención; decidir si `enlace` se enciende.
2. **Ajustar los umbrales de los gates una sola vez** con esa serie, y anotar la fecha.
3. **Conectar la API a Langfuse**: `LANGFUSE_HOST` del VPS en `.env`, recrear la API, comprobar `/api/public/health` desde el contenedor y revisar que la traza no lleve contenido.
4. **Serie A/B de razonamiento**: `effort` low contra medium, mismo dataset, otro `--name`. Se queda el que gane en calidad.
5. **Margen de `max_tokens`**: guardar `finish_reason` en la auditoría; subir el tope de D4 a 16,384 si hay cortes o queda poco margen.
6. **Fijar el proveedor** del modelo local (`order` + `allow_fallbacks: false`) para que la varianza entre repeticiones sea del modelo y no del proveedor.
7. **Ampliar el dataset** a ≥ 15 episodios, con casos de evidencia insuficiente (`esperado.evidencia_suficiente`) para medir la abstención correcta.
8. **Etiquetar y calibrar el juez**: `make eval-labels N=40`, etiquetado por un ingeniero, luego `make eval-semantic`.
9. **UI**: pedir el motivo del rechazo; mostrar estado, evidencia contradictoria y corridas.
10. **Abrir test (E9, E10) una sola vez** con la configuración elegida.

**Pendientes de la auditoría externa, diferidos**: gates deterministas de permisos y adversariales, presupuestos y circuit breaker, dashboards y OpenTelemetry.

**Deuda técnica conocida**

- `validate_content` de ediciones humanas en `review.py` es un placeholder.
- Una conexión de base se mantiene abierta durante la llamada al LLM.
- Redactor e inspector no se recargan si cambia el catálogo; falta purgar `pseudonym_map`.
- `uv.lock` debe regenerarse con los grupos `evals` y `observabilidad` antes de construir con `--frozen`.

## Riesgos y preguntas abiertas

El riesgo que más pesa es estadístico: con 5 episodios, ninguna métrica distingue entre dos configuraciones parecidas.

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| 5 episodios (12 casos dev) | Un episodio mueve los promedios entre 0.2 y 0.5 | Ampliar a ≥ 15 episodios antes de decidir entre configuraciones cercanas |
| Dataset sintético | El eval puede medir un problema que no existe | Escenarios basados en modos de falla reales; declararlo en la presentación |
| El D4 del precedente nunca se recupera | El agente cita el 8D sin conocer su causa | Variante `enlace`, resumen de D4 indexado o consulta orientada a causa; lo decide el eval |
| 8D ajenos al alcance | Recurrencias falsas en casos de causa nueva | Medido como "top-1 cita 8D ajeno" y como gate bloqueante |
| Latencia de 233 a 652 s por análisis | El gate de p95 ≤ 180 s no pasa; espera larga para el ingeniero | Mostrar progreso por etapa en la UI; A/B de razonamiento; D4 por causa en paralelo solo si el eval lo justifica |
| Salida cerca de `max_tokens` | JSON cortado y corrida perdida | Guardar `finish_reason`; subir el tope de D4 |
| Proveedor no fijado | La varianza entre repeticiones mezcla modelo y proveedor | Fijar `order` y `allow_fallbacks: false` |
| Modelo local medido en BF16 vía API | Resultado optimista frente a Q4 en planta | Declarar la brecha; fijar cuantización cuando se mida para producción |
| Juez sin calibrar | Conclusiones sobre citas sin respaldo | No cuenta para gates hasta tener kappa ≥ 0.6 |

**Preguntas abiertas**

- En la consulta de auditoría solo aparece la etapa D4: ¿D2 no llama al modelo o lo registra con otra etiqueta?
- ¿La serie con `effort: medium` mejora la calidad lo suficiente para justificar el tiempo extra?
- ¿El bucket de R2 necesita CORS si se activa la subida de media? La documentación de Langfuse no lo dice.
- ¿Qué umbral de latencia es aceptable para un ingeniero en planta, ahora que hay datos reales?
