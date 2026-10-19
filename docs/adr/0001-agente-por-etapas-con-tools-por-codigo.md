# ADR 0001 — Un agente por etapas en LangGraph; las tools las llama el código

**Estado:** Aceptada

## Contexto
D2 y D4 necesitan evidencia de varias fuentes (casos, controles, datos operativos) y deben ser reproducibles y baratos de evaluar.

## Decisión
Un grafo de LangGraph con etapas fijas: `guard_input → gather → d2 → d4_small → (d4_large)`. `gather` es código puro: decide
qué tools llamar, con un presupuesto de 17 llamadas. El LLM solo redacta y cita sobre un libro de evidencia con ids estables
(`F#`, `T#`, `NCR`). `d4_large` es un reintento con retroalimentación sobre el mismo modelo.

## Alternativas descartadas
- **Multiagente / tools elegidas por el LLM:** más costo, más superficie de ataque y comportamiento no reproducible.
- **Un solo prompt sin etapas:** no permite revisar el contexto ni reintentar solo D4.

## Consecuencias
- (+) En `dev-v6`, `gather` (SQL, búsquedas y embedding de la consulta) toma ≈ 3 s de 87 s de pared por corrida; el resto es espera del modelo. Optimizar herramientas no mueve la latencia.
- (+) Una inyección no puede cambiar qué herramientas se ejecutan (ADV-05, `test_adv_05_the_agent_has_no_tool_that_can_send_or_write_anything`).
- (−) El agente no explora: si la consulta no trae la evidencia, no hay una segunda ronda de búsqueda.
- (−) D4 depende de D2 en el grafo; no se pueden generar en paralelo sin cambiar el contrato.

## Evidencia
`app/agent/graph.py`, `app/agent/tools.py`; eval `dev-v6`: causa esperada en el top-3 en 36/36 corridas.
