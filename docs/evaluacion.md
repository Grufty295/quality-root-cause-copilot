# Evaluación

## Resultados

Partición dev: 12 casos (E6, E7, E8) × 3 repeticiones = 36 corridas por modelo, variante `con_enlaces` (la de
producción). Datos sintéticos. Reportes en `traces/evals/` (`dev-v6`, `dev-qwen27`); detalle del candidato local en el
[ADR 0012](adr/0012-inferencia-local-costo-y-capacidad.md).

| Medida | Línea base trivial | DeepSeek v4.1 Flash (`dev-v6`) | Qwen 3.6 27B (`dev-qwen27`) |
|---|---|---|---|
| Papel | Piso a superar | Ruta API | Candidato a modelo local |
| `pass` (RC primera y ND aceptable) | 21/36 (7 de 12 casos) | **26/36** (0.72); 26–29 entre corridas equivalentes | **28/36** (0.78) |
| Causa esperada en el top-3 | — | 36/36 | sin dato agregado en el ADR |
| Gates de tolerancia cero | — | en verde | en verde (0 inseguras, 0 inválidas, 0 fallos de esquema) |
| Costo por corrida | 0 | ≈ US$0.006 (US$0.22 por 36, reportado por el proveedor) | ≈ US$0.046 |
| Latencia por corrida (p50 / p95) | — | 85 s / 130 s | 209 s / 378 s |
| Escalaron a `d4_large` | — | — | 22 de 36 (mismo modelo) |

Línea base por partición (`make eval-baseline`): en dev 7/12 (7/8 recurrentes, 0/4 de causa nueva); en los 20 casos de
ambas particiones, 11/20 (11/12 recurrentes, 0/8 de causa nueva). Los gates comparan contra la de dev.

**Cómo leerlo.**

- 26 contra 28 son dos corridas: equivalencia dentro del ruido, no una mejora. La unidad real son los casos: 9 de 12
  pasan 3/3 con ambos modelos.
- Las fallas se concentran en tres casos. EV-07 es inestable (la causa esperada queda en el lugar 3, 1 y 2). EV-10 pone
  RC-02 sobre la RC-03 esperada. EV-08 está etiquetado `evidencia_suficiente: false` y el agente **nunca se abstiene**
  (0/3 con Qwen, 0/9 con DeepSeek en `dev-fix`): propone causas donde debería decir que no hay evidencia suficiente. Es un
  solo caso, así que no mide una tasa, pero sí es un límite de comportamiento.
- La comparación entre modelos no es de igual configuración: DeepSeek corrió con `reasoning.effort=low` y Qwen no. Qwen
  se midió en FP8 por OpenRouter; en planta correría en 4 bits, así que su resultado es algo optimista.
- Con Qwen, la latencia p95 (378 s) no cumple el objetivo de la ruta API (≤ 180 s); el de la ruta local (≤ 20 min) sí,
  pero sin medir en hardware propio.
- Dos etiquetas de casos dev se cambiaron después de ver resultados, y se declaró; se reportan ambos resultados (29 y
  28 de 36, ver `defensa-de-decisiones.md`). La partición sellada (E9, E10) sigue sin abrir y es la que decide.

## Recuperación

`make eval-retrieval` mide si las dos búsquedas del agente (`search_cases`: 8D + NCR, top 5; `search_controls`: AMEF,
plan de control, instrucciones y SOP, top 6) traen lo que D4 necesita. Corre contra la base ya sembrada con el
embedder real, con la misma consulta (`graph.build_query`), los mismos tipos de documento, el mismo corte `as_of` y el
usuario del caso. Escribe `traces/evals/recuperacion.json` y `.md`.

El código está en `apps/api/app/evalkit/`, no en `evals/`: `data/generator/generate.py` borra `evals/` completo cada
vez que regenera el dataset.

## Qrels

Se derivan de `esperado` y `episodios_verdad.json` (no hay archivo que mantener a mano), con anclas
(documento, sección), no fragmentos: cambiar el chunker no invalida la verdad.

| Búsqueda | Esencial (2) | Útil (1) |
|---|---|---|
| `cases` | sección D4 del 8D del que el caso es recurrencia | otras secciones de ese 8D; NCR del episodio y NCR históricas que originaron ese 8D, ya visibles al corte |
| `controls` | documentos de control que la fila RC del AMEF referencia (RC-01 → SOP-MNT-008, WI-CRP-002) | fila RC; filas ND esperada y aceptables |

Las filas RC y ND no son esenciales en `controls` porque el agente ya las recibe completas por el catálogo
(`catalog.load_catalog`): recuperarlas otra vez no le agrega información. Los vínculos RC → documento se leen de la
columna de códigos del fragmento del AMEF.

Un caso sin recurrencia (E8, E10) no tiene ancla esencial en `cases`; ahí se mide `distractor@5`: que no salga un 8D de
otra causa.

## Métricas

- `precedente@k`: salió algún fragmento del 8D precedente. Es lo que el agente necesita para citarlo.
- `hit@k`: salió un ancla esencial (en `cases`, la sección con la causa). La diferencia con `precedente@k` es el hallazgo
  principal: la consulta describe el síntoma y D2 se parece a ella; D4 no.
- `prec. vía NCR@5`: el 8D precedente o una NCR histórica que lo cita ("8D relacionado"). Mide cuánto ganaría una
  expansión por enlace (NCR → su 8D → D4).
- `8D ajeno vía NCR@5`: un 8D de otra causa alcanzable desde el top-5, directo o por enlace. Es el costo de esa misma
  expansión: lo que el modelo tendría que descartar.
- `recall@k`, `MRR`, `nDCG@k`, `precision@k` (ruido que recibe el prompt).
- Todo se reporta **por episodio** además de por caso: los 4 casos de un episodio comparten causa, línea y 8D.

## Partición

`dev` = E6, E7, E8 (dos con recurrencia, una de causa nueva). `test` = E9, E10 (una y una). Se ajusta solo sobre `dev`;
`--test` / `TEST=1` añade `test` y el reporte lo marca. Con 5 episodios la partición es gruesa: una diferencia de un
episodio cambia el promedio 0.2-0.5. Sirve para detectar regresiones grandes, no para elegir entre dos configuraciones
parecidas. Ampliar a ≥15 episodios es lo que hace que estos números decidan algo.

## Cómo comparar configuraciones (re-ranking, chunking, embedder)

Una base sembrada por configuración, y el mismo comando contra cada una (`--name` cambia el prefijo del reporte).
`index_version` y el modelo de embeddings quedan en el reporte. No compares corridas con distinto `dataset_sha`.

## Límites

- Los qrels dicen qué debería traer la búsqueda para el caso esperado; no miden si el modelo luego lo usa bien (eso es el
  eval del agente, aparte).
- Las NCR del mismo episodio cuentan como útiles porque son precedente válido; si se consideran ruido, bajan `recall`.
- Con `HashingEmbedder` (pruebas) el modo `vector` no significa nada. Solo los números con el embedder real valen.

# Eval del agente

`make eval-agent` corre D4 sobre los casos de `dev` y lo puntúa contra `esperado`. **Gasta tokens**: usa los modelos de
`LLM_*`. Cada corrida abre una NCR nueva con fecha de reporte = `as_of` del caso y genera solo D4. Escribe
`traces/evals/agente.runs.jsonl` (una línea por corrida, en cuanto termina) y `agente.json` / `.md`.

- Si se corta, volver a correr el mismo comando retoma: salta las combinaciones caso/variante/repetición ya hechas.
  `--name otro` empieza una serie aparte (p. ej. por modelo). `--report-only` rehace el reporte sin llamar al modelo.
- `ARGS="--repeats 1 --casos EV-01,EV-05"` para una prueba barata antes de la corrida completa.
- Pedir un caso de E9/E10 sin `--test` falla a propósito.

## Variantes

- `sin_enlaces`: el agente sin `expand_case_links`.
- `con_enlaces`: con `AgentDeps.expand_case_links`. Del top de `search_cases` toma hasta 2 8D (el que salió directo o
  el que cita una NCR, "8D relacionado") y trae su sección D4 con los mismos permisos, corte y exclusiones
  (`get_linked_8d_causes`, una llamada más del presupuesto). **Es la variante de producción** (ADR 0004): la
  recuperación mostró que trae la causa del precedente en ~88 % de los casos recurrentes, a cambio de traer también un
  8D de otra causa en los casos de causa nueva. Las cifras de Resultados son de esta variante.

`make eval-agent` corre ambas si no se le pasa `--variants`; para una serie de producción, `--variants con_enlaces`.

## Métricas

Sin juez LLM: todo sale de códigos y citas.

- `pass` = la RC esperada es la primera y la ND está entre las aceptables. `pass@1` es la tasa media; `pass^k` exige
  pasar en las k repeticiones (consistencia: un borrador que acierta 2 de 3 veces no es confiable).
- `RC top1` / `top3`, `ND ok`, y `top1` separado para casos recurrentes y de causa nueva (la línea base trivial acierta
  7/8 recurrentes y 0/4 de causa nueva en dev; 11/12 y 0/8 en los 20 casos: el agente tiene que ganarle en los segundos).
- `top1 cita precedente`: la causa principal cita el 8D anterior (solo recurrentes). `top1 cita 8D ajeno`: la causa
  principal se apoya en un 8D de otra causa: el riesgo de `con_enlaces`.
- `RC esperada descartada`: el guardrail tiró la causa correcta. `escaló a grande`: D4 necesitó el modelo grande.
- Costo estimado (tabla de precios) y reportado por el proveedor (`usage.cost` de OpenRouter, en `audit_log.tags`),
  tokens de razonamiento, latencia p50/p95 de pared.
- `con_enlaces` frente a `sin_enlaces` caso a caso: qué casos mejoran o empeoran. Con 12 casos, eso dice más que la diferencia de
  promedios.

El reporte avisa si más de un proveedor respondió para el mismo modelo: entonces la varianza entre repeticiones mezcla
modelo y proveedor.

Además:

- **Abstención**: `se abstuvo` (`estado = evidencia_insuficiente`), `abstención indebida` (se abstuvo con causa
  esperada y sin etiqueta de evidencia insuficiente), `abstención correcta` (solo con `esperado.evidencia_suficiente`;
  hoy la trae EV-08), `bajada por guardrail` y `con contradicciones`. Con evidencia suficiente, `pass` no cambia:
  abstenerse con la causa correcta primero también pasa. Con `evidencia_suficiente: false`, `pass` es abstenerse.
- **Salida insegura**: lo persistido se vuelve a pasar por los chequeos de culpa y cierre. Debe ser 0.
- **Desglose** por tipo (recurrente / causa nueva), episodio, punto de detección, línea, defecto y nivel. Las celdas
  tienen pocos casos: sirven para encontrar dónde falla, no para comparar valores.
- **Experimento**: `meta.experiment` trae `experiment_id`, dataset, partición, variantes, repeticiones, revisión de
  código y el manifiesto completo de cada `config_id` (de `analysis_run`). Si una serie mezcla `config_id`, el
  reporte lo muestra: el cambio pudo venir del proveedor, del prompt o del índice, no del modelo.

# Criterios de éxito y gates

`make eval-gates` (`app/evalkit/gates.py`) lee `agente.json`, `recuperacion.json` y `agente.semantico.json` y sale con
código 1 si falla un gate bloqueante. No llama al modelo. Un gate sin dato no aprueba.

| gate | condición | bloquea | umbral |
|---|---|---|---|
| salida-segura | 0 borradores persistidos con culpa a personas o cierre | sí | definitivo |
| medicion-valida | 0 corridas inválidas | sí | definitivo |
| pass-linea-base | pass@1 ≥ 0.59 (línea base trivial en dev: 7/12 = 0.583) | sí | provisional |
| causa-nueva | RC top-1 en causa nueva ≥ 0.25 (trivial en dev: 0/4) | sí | provisional |
| sin-8d-ajeno | top-1 cita 8D ajeno en causa nueva ≤ 0.25 | sí | provisional |
| recuperacion-precedente | precedente@5 híbrida ≥ 0.50 | sí | provisional (regresión) |
| recuperacion-controles | hit@10 controles híbrida ≥ 0.80 | sí | provisional (regresión) |
| consistencia | pass^k ≥ 0.50 | no | provisional |
| abstencion-indebida | ≤ 0.20 | no | provisional |
| costo | costo estimado medio por D4 ≤ $0.10 | no | provisional |
| latencia | p95 ≤ 180 s | no | provisional |
| citas-respaldan | soporte de citas del juez ≥ 0.80, solo si el juez está calibrado | no | provisional |

Los provisionales se fijaron sin una corrida válida del agente. Se ajustan **una vez**, con la primera serie dev
válida, y se anotan en `gates.py` con la fecha; no se mueven para que una versión pase. Antes de abrir la partición
de prueba, los gates bloqueantes tienen que pasar en dev.

# Eval semántico (DeepEval + Ragas)

`make eval-semantic` (`app/evalkit/semantic.py`) juzga con un LLM lo que un código no puede ver: si lo citado
**sostiene** lo afirmado. Corre sobre las corridas ya guardadas por `make eval-agent` (variante `con_enlaces` por defecto, `--variant` para otra; repetición 1,
hasta 12 corridas por defecto). **Gasta tokens**: ~20 llamadas al modelo grande por corrida; `--max-calls` (400) corta.

| métrica | framework | qué responde |
|---|---|---|
| soporte de citas | DeepEval (`BaseMetric` propia) | cada hecho: respaldada / parcial / sin_respaldo / contradice según sus fuentes |
| relevancia causal | DeepEval G-Eval | ¿la explicación conecta la causa con este incidente o solo con el catálogo? |
| faithfulness | Ragas | fracción de afirmaciones de la causa principal que salen de lo citado |
| context precision | Ragas | ¿lo recuperado arriba sirve para la causa esperada? (referencia: su fila del AMEF) |

Decisiones:

- **El juez pasa por el `ModelGateway`.** DeepEval y Ragas reciben adaptadores (`app/evalkit/judge.py`) en vez de sus
  clientes OpenAI: el juez lee fragmentos confidenciales y obedece el mismo router (confidencial → local), la misma
  redacción, y queda en `audit_log` con etapa `eval` y el `run_id` de la corrida juzgada. Telemetría de ambos
  frameworks apagada (`DEEPEVAL_TELEMETRY_OPT_OUT`, `RAGAS_DO_NOT_TRACK`) y sin clave de Confident AI.
- **No reemplaza al scorer determinista.** RC/ND, citas existentes y precedentes siguen saliendo de códigos.
  Los resultados del juez van en `agente.semantico.json`, aparte.
- **Sin calibrar no decide.** `make eval-semantic ARGS="--export-labels 40"` escribe una muestra de hechos en
  `data/etiquetas/agente.por_etiquetar.jsonl` **sin** el juicio del juez. Un ingeniero llena `etiqueta_humana` y
  `revisor` y lo guarda como `agente.etiquetas.jsonl`. El siguiente `eval-semantic` mide acuerdo, kappa de Cohen,
  matriz de confusión y la tasa de "respaldada" que el humano no aprueba (el error caro). Calibrado = ≥30 hechos y
  kappa ≥ 0.6. Con dos revisores se mide también su acuerdo: es el techo del juez. Se recalibra al cambiar de modelo
  juez o de prompt. Las etiquetas viven en `data/etiquetas/` (fuera de `evals/`, que el generador borra) y se versionan.
- `--langfuse` cuelga cada puntaje de la traza de su corrida (`run_id` = trace_id).
- Instalación: grupos `evals` (deepeval 4.3.0, ragas 0.4.3, langchain-community < 0.4) y `observabilidad`
  (langfuse 5.0.1) en `pyproject.toml`. Después de bajar estos cambios: `cd apps/api && uv lock`, luego
  `make build-evals`. Este comando reconstruye y actualiza el contenedor de la API; la imagen por defecto no trae
  estos grupos opcionales.

Por qué estos dos: Ragas trae las métricas de RAG estándar (faithfulness, context precision) y DeepEval una
estructura de métrica que también corre con `assert_test` / `deepeval test run` si más adelante se quiere en CI. Ninguno
sustituye los qrels ni el scorer; si una métrica no detecta fallos que el scorer no vea ya, se quita.

## Antes de gastar: preflight

Cada corrida empieza con una llamada mínima por modelo (sin datos del caso, sin pasar por el gateway) que valida slug,
proveedor y API key; si falla, se detiene con el estado HTTP antes de abrir NCRs. `ARGS="--preflight-only"` hace solo
eso. Además, 3 corridas seguidas sin respuesta del modelo detienen la serie. Esas corridas cuentan como **inválidas**:
no entran a ninguna tasa y se repiten al retomar.

## Cuando el modelo no responde

`make llm-diagnose` (o `DEST=api`) corre dentro del contenedor y muestra: la configuración LLM_* que de verdad ve
(con una huella de la key, nunca la key), el estado de la key y los proveedores de cada modelo en OpenRouter (slug,
cuantización, tope de salida, si aceptan `reasoning`), y una matriz de llamadas mínimas que quita un parámetro a la vez.
El parámetro cuya ausencia hace pasar la llamada es el culpable.

Si las llamadas mínimas pasan y el agente sigue fallando, la diferencia está en el request real (tamaño, contenido,
proveedor que le toca). `make llm-diagnose CASO=EV-01` corre el agente en ese caso, captura el request rechazado
(cuerpo completo en `traces/llm-debug-EV-01.json`) y lo repite: tal cual, sin `reasoning`, sin `provider`, con
`max_tokens` menor, ignorando al proveedor que lo rechazó, con un mensaje trivial y con el último mensaje recortado. La
primera variante que pasa dice qué cambiar. Cuesta lo de una corrida de D4.

Para ver el error en una corrida normal del agente, `LLM_DEBUG_HTTP=1` en el `.env` (y `docker compose up -d api`) hace
que el cliente imprima en stderr el cuerpo del error del proveedor y la forma del request, sin el texto de los mensajes.
Solo con datos ficticios: el error de un proveedor puede repetir el prompt.

## Modelo "local" para que el resultado diga algo de la planta

Un modelo de pesos abiertos del tamaño que cabría en planta, con proveedor y razonamiento fijos. En dos pasos:

1. Sin fijar proveedor, para ver quién lo sirve:

   ```
   LLM_LOCAL__MODEL_SMALL=qwen/qwen3.8-27b
   LLM_LOCAL__MODEL_LARGE=qwen/qwen3.8-27b
   LLM_LOCAL__PRICE_IN_PER_MTOK=0.02
   LLM_LOCAL__PRICE_OUT_PER_MTOK=0.50
   LLM_LOCAL__EXTRA_BODY={"provider":{"data_collection":"deny"},"reasoning":{"effort":"low"}}
   ```

   `docker compose up -d api` y `make eval-agent ARGS="--preflight-only"`: imprime el proveedor que respondió.

2. Fijarlo con su slug (en minúsculas, como aparece en la página del modelo en OpenRouter; p. ej. `deepinfra`):

   ```
   LLM_LOCAL__EXTRA_BODY={"provider":{"order":["deepinfra"],"allow_fallbacks":false,"data_collection":"deny"},"reasoning":{"effort":"low"}}
   ```

   Ajusta los precios a los de ese proveedor y repite el preflight antes de la serie completa.

En planta correría cuantizado (Q4), así que un resultado en FP8/BF16 es algo optimista: `"quantizations":["fp8"]` en
`provider` acota la diferencia. Para la comparación de hardware, otra serie con `--name qwen35` y el Qwen3.5-35B-A3B
(verifica su slug en OpenRouter).

Con el mismo modelo en small y large, la cascada D4 reintenta con el mismo modelo: sigue siendo un segundo intento con
la retroalimentación del guardrail, no un modelo mejor.
