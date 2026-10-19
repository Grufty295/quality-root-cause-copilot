# Agente D2 / D4 (grafo)

`POST /ncrs/{id}/analyze` (solo rol **ingeniero**) genera borradores de D2 y D4 para una NCR.

## Flujo

`guard_input → gather → d2 → d4_small → (d4_large si se descartó alguna causa) → fin`

- **guard_input**: si la descripción de la NCR trae instrucciones dirigidas al agente, no se genera nada.
- **gather**: el grafo llama las tools de forma determinista (no las elige el LLM) con un presupuesto de 14 llamadas (D4 usa 12):
  `get_defect_summary`, `get_maintenance_history`, `get_applicator_wear`, `get_crimp_measurements`, `get_change_log`, `get_material_lots`, `search_similar_cases`, `search_controls`. Los fragmentos con
  inyección se ponen en cuarentena y las salidas de tools se clasifican por nivel.
- **d2 / d4**: D2 solo recibe los conteos de defectos por estación y turno (el mantenimiento y el desgaste son evidencia causal de D4).
  Salida estructurada, verificada por guardrails. D4 propone 3 causas de ocurrencia (RC-xx del AMEF) y
  1 de no detección (ND-xx del SOP-QA-011). Primero el modelo pequeño; si el guardrail descarta alguna causa, se
  reintenta con el grande.

## Guardrails de salida (`app/agent/guardrails`)

Una causa se descarta, con motivo visible en `descartes`, si: su código no está en el catálogo, no cita ningún
fragmento existente, ningún fragmento citado menciona el código, culpa a una persona o declara el caso cerrado.
`respaldo` (`caso` | `solo_catalogo`) lo calcula el guardrail, no el modelo.

## Abstención: candidato causal frente a evidencia insuficiente

Una causa del catálogo no es la causa raíz del incidente por existir en el AMEF. D4 (`prompts` `d4-v2`) separa:

- `estado`: `candidato_respaldado` o `evidencia_insuficiente`. El modelo lo declara; el guardrail **baja**
  `candidato_respaldado` a `evidencia_insuficiente` (con `estado_motivo`) si la primera causa solo cita su propia fila
  del catálogo y ningún dato del caso (`T#`) ni caso parecido. Nunca sube un estado: abstenerse siempre se respeta.
  Con `evidencia_insuficiente` las 3 causas siguen ahí, como lista de verificación en orden, no como conclusión.
- Por causa, además de la evidencia a favor y la pregunta de confirmación: `evidencia_contradictoria` (hechos con
  fuentes que la debilitan; se verifican igual que la evidencia), `refutaria` (qué resultado la descartaría) y
  `dato_faltante` (qué no está en las fuentes y haría falta).
- Los borradores anteriores (sin `estado`) se leen como `candidato_respaldado`; los campos nuevos son opcionales.

La causa validada sigue siendo la del ingeniero: el agente propone hipótesis con su evidencia y sus huecos.

## Corridas (`analysis_run`) e idempotencia

Cada `POST /analyze` es una corrida con id = `trace_id` (32 hex), el mismo de `audit_log`, `section_version` y la traza
de Langfuse. Se abre antes del grafo y se cierra con estado (`completada`, `parcial`, `sin_borrador`, `fallida`;
`abandonada` si quedó en curso más de 15 min), tiempos por nodo, costo y tokens (sumados de `audit_log`) y el
manifiesto (`app/agent/manifest.py`: prompt, índice, hash del catálogo, modelos, proveedor fijado, cuantización,
razonamiento, top-k, decodificación y `GIT_SHA`; `config_id` es el hash de todo menos la revisión de código).

- `Idempotency-Key` (8–200 caracteres): la misma clave sobre la misma NCR devuelve la corrida ya hecha
  (`replayed: true`) sin llamar al modelo. Si la primera sigue en curso, 409.
- Sin clave: a lo más una corrida en curso por NCR (índice único parcial); la segunda recibe 409 en vez de duplicar
  gasto. Una corrida cerrada no se modifica ni se borra (trigger).
- La respuesta de `/analyze` trae `run_id`, `status`, `duration_ms`, `stage_ms`, `usage` (llamadas, tokens, costo
  estimado y reportado) y `config_id`. `GET /ncrs/{id}/runs` lista las corridas para todo rol con alcance.

## Callbacks (`app/agent/observe.py`)

El grafo emite a un `AgentObserver` sin contenido (ids, conteos, tiempos y códigos de evento):

- **Hooks de LangGraph**: `NodeCallbacks` es un callback handler de LangChain pasado en `config["callbacks"]`;
  LangGraph avisa inicio y fin de cada nodo (`metadata["langgraph_node"]`) y de ahí salen `stage_ms` y los spans.
  Ignora `inputs`/`outputs`, donde viaja el estado con fragmentos.
- **Eventos de dominio**: herramienta rechazada, cuarentena, escalamiento, `estado_insuficiente`, cada llamada al LLM
  (modelo, destino, nivel, tokens) y los fragmentos que trajo cada búsqueda, en orden.

Observadores: `RecordingObserver` (lo usa el servicio para `analysis_run` y el eval, que además guarda el texto citado
para el juez), `LangfuseObserver` (`TRACE_EXPORTER=langfuse`, grupo `observabilidad`) y cualquiera que se sume.
Un observador que falla no detiene el análisis.

No se usa el `CallbackHandler` de Langfuse para LangChain: mandaría el estado completo (NCR, fragmentos
confidenciales) a un servicio fuera del gateway y del `audit_log`. `LangfuseObserver` manda lo mismo que ya guarda la
auditoría y, sin `LANGFUSE_HOST`, se niega a arrancar (el SDK usa cloud.langfuse.com por defecto).

## Persistencia

- El agente solo genera si no hay borrador o la última versión es un `rechazo`; una `aprobacion` es final.
- Se escribe fuera del grafo, en una transacción que verifica que nadie cambió las versiones mientras el modelo
  trabajaba (409 si cambiaron). Ninguna llamada al LLM sostiene un lock de base de datos.
- Fuentes citadas: `F#` (fragmentos, tabla `citation`), `T#` (tools) y `NCR` (en `indice_fuentes` del contenido).

## Confidencialidad

El nivel de cada llamada es el más alto entre NCR, fragmentos y salidas de tools. Confidencial → solo local (con
pseudonimización de PII); interno/público → puede ir a la API, redactado. Como el corpus de 8D es mayormente
confidencial, D4 casi siempre corre local.

## Probar con modelos reales

`python -m app.agent.run_case NCR-2026-0079` (dentro del contenedor `api`, tras el seed con embeddings reales) crea
el NCR desde `ncr.csv` y corre el agente con `as_of` = fecha del NCR, porque la API no expone el corte. Imprime las
secciones, el ruteo de cada llamada (destino, modelo, nivel, redacción), tokens, costo y, aparte, la causa
preliminar de la planta, que **no** se le da al agente. Las variables `LLM_*` están en `.env.example`.

Para que el replay no vea el resultado:

- el NCR nuevo toma como fecha de reporte la del caso, no la del día en que corre la prueba;
- la recuperación excluye el documento del propio NCR (`exclude_sources`). Tiene la misma fecha que el corte, así
  que `as_of` no lo filtra, y sin la exclusión el agente lo citaba como "caso previo" de sí mismo.

`--out caso.json` guarda en `traces/caso.json` del repo. Usa una ruta relativa: en Git Bash de Windows, una absoluta
como `/tmp/...` se convierte en `C:/...` antes de llegar al contenedor.

Con OpenRouter para ambos destinos, el "local" se marca `LLM_LOCAL__SIMULATED=true` y queda así en `audit_log`.
Es válido solo con datos ficticios. Para que la prueba diga algo del despliegue real, el modelo "local" debe ser
del tipo que correrá en planta (pesos abiertos), no un modelo de frontera.

## Expansión por enlace (encendida en producción)

`AgentDeps.expand_case_links`: del top de `search_cases` sigue el enlace al 8D (el recuperado o el que cita una NCR) y
agrega su sección D4. Existe porque la consulta describe el síntoma y nunca recupera la sección con la causa. Está
encendida en producción (variante `con_enlaces`, [ADR 0004](adr/0004-expansion-por-enlace-en-produccion.md)); la
comparación contra `sin_enlaces` se corre con `make eval-agent` y está en `evaluacion.md`.

## Rechazo con motivo

`POST .../reject` acepta `reason` opcional: `causa_incorrecta`, `evidencia_insuficiente`, `cita_irrelevante`,
`contexto_incompleto`, `redaccion`, `error_tecnico` (CHECK en `section_version.feedback_reason`, solo en rechazos).
El motivo entra al prompt de regeneración y permite contar qué parte del sistema falla sin leer texto libre. La UI
todavía no lo pide.

## Pendiente conocido

`validate_content` de ediciones; que la UI pida el motivo del rechazo y muestre `estado`, evidencia contradictoria y
corridas. Los datos operativos ya se cargan: ver `datos-operativos.md`.
