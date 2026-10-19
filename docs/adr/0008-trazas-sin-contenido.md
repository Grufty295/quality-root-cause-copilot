# ADR 0008 — Langfuse recibe solo metadatos, no el estado del grafo

**Estado:** Aceptada

## Contexto
Los nodos del grafo manejan fragmentos confidenciales. Exportarlos a una herramienta de observabilidad crearía una segunda frontera de confidencialidad fuera del gateway.

## Decisión
Un observador propio (`AgentObserver`) recibe identificadores, conteos, tiempos y códigos de evento, nunca texto. No se usa el `CallbackHandler` de Langfuse para LangChain porque envía
`inputs` y `outputs` de cada nodo. Langfuse (self-hosted en la VPC) recibe lo mismo que ya guarda `audit_log`. Un observador que falla no rompe el análisis.

## Alternativas descartadas
- **Trazar prompts completos:** facilita depurar, pero es otra copia de datos confidenciales.
- **Sin trazas:** no hay forma de atribuir latencia ni costo por etapa.

## Consecuencias
- (+) Latencia y tokens por etapa y por llamada sin exponer contenido.
- (−) Depurar una mala respuesta exige reproducir la corrida con `run_case` o `make llm-diagnose CASO=EV-01`.
- (+) La traza lleva `user_id` (id interno), `session_id` (la NCR), versión del prompt, etiquetas de catálogo y scores
  deterministas por corrida (escalamiento, violaciones, errores del modelo, cuarentenas). Ninguno es texto.
- (+) El costo por request y por feature sale de `audit_log` (`docs/operacion/observabilidad.md`), que no depende de Langfuse.
- (−) Pendientes: dashboards y alertas sobre las trazas. No hay alertas; la alternativa es una consulta programada.

## Evidencia
`app/agent/observe.py`, `tests/agent/test_observe.py`, `tests/agent/test_observe_langfuse_trace.py`; traza real revisada en `docs/operacion/observabilidad.md`.
