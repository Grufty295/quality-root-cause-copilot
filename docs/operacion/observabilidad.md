# Observabilidad: qué se ve, dónde y qué falta

Dos fuentes que se corresponden por `trace_id` (el id de la corrida, 32 hex):

- **Langfuse** (VPC): la traza de cada análisis, para ver dónde se fue el tiempo y los tokens. **Sin texto**: ids, conteos,
  tiempos y códigos de evento (ADR 0008).
- **`audit_log` en Postgres**: una fila por llamada al modelo, solo-inserción con hash encadenado, con tokens, costo,
  latencia y tags. Es la fuente de verdad del costo y no depende de que Langfuse esté arriba.

## Qué muestra una traza real

La traza `a7a1ffe2…` (análisis de D4, 18 oct 2026, Qwen 3.6 27B) tiene 28 observaciones:

| Tramo | Duración | Qué dice |
|---|---|---|
| `guard_input` | 0.00 s | El guardrail de entrada no vio inyección |
| `gather` (13 tools, 3 búsquedas) | 0.34 s | Etapa de datos: SQL y búsqueda híbrida, sin LLM |
| `d4_small` | 103 s | Primera llamada al modelo (13,900 → 6,777 tokens, US$0.026) |
| evento `violaciones` + `escala_al_modelo_grande` | | El guardrail de salida rechazó el borrador |
| `d4_large` | 94 s | Segunda llamada, mismo modelo (13,959 → 7,163, US$0.027) |
| **Total** | **198 s** | **US$0.0535** · 27,859 tokens de entrada, 13,940 de salida |

Lo que esta traza permite afirmar, con evidencia y no de memoria:
- El tiempo está en el modelo (197 de 198 s); los datos son 0.34 s. Optimizar la recuperación no cambia nada.
- Esta corrida costó el doble por el escalamiento: una segunda llamada completa al mismo modelo.
- En el humo anterior `gather` tardó 34 s. Aquí 0.34 s: era un arranque en frío del modelo de embeddings.

Correcciones al exportador a partir de esa misma traza (hechas, falta reconstruir la imagen para verlas):
1. Las `generation` salían con **duración 0** porque se creaban al terminar la llamada. Ahora se abren antes y cuelgan de su
   etapa, así la latencia por llamada es la real.
2. La traza no tenía usuario, sesión, etiquetas ni versión. Ahora lleva `user_id` (id interno, no nombre), `session_id` = la
   NCR, `version` = versión del prompt y etiquetas `nivel:`, `planta:`, `linea:`, `disciplina:`.
3. Scores en línea por corrida (deterministas, sin juez de LLM): `escalo_a_modelo_grande`, `violaciones_guardrail`,
   `errores_llm`, `fragmentos_en_cuarentena`, `disciplinas_bloqueadas`.

   Verificado con la traza `c9a9eccd…` (19 oct 2026): las correcciones 1 y 2 se vieron en Langfuse; los scores **no llegaron**.
   Causa: el SDK 5 los manda en un arreglo a `POST /api/public/scores` y el Langfuse self-hosted 3.162 solo acepta un
   objeto (400 `expected object, received array`); el SDK lo registra en un hilo de fondo y descarta el score. Ahora el
   observador manda cada score como objeto con `id` determinista (`<traza>-<nombre>`), y un rechazo se registra como
   advertencia. Lección: las pruebas con un cliente falso no lo habrían visto; hay una prueba contra un servidor HTTP
   que acepta objeto y rechaza arreglo (`tests/agent/test_observe_langfuse_trace.py`).

   Con la traza posterior se confirmó que los 5 scores llegan, que la generación `llm:D4` trae su metadata (`destino`,
   `nivel`, `tier`, `intentos`, `latencia_ms`, `razonamiento_tokens`, `salida_visible_tokens`, `finish_reason`) y que el
   JSON exportado desde la interfaz **no** incluye la metadata por observación (solo la de la traza): no es un fallo del
   exportador. Los scores se crean al primer uso; no hay nada que dar de alta en Langfuse (las *score configs* son
   opcionales y solo validan rangos).

Qué **no** miden esos scores: no dicen si la causa propuesta es correcta (eso es el eval con respuesta esperada). Miden
cuánto trabajo de contención hizo el sistema. Una subida sostenida del escalamiento o de las violaciones es la señal de
deriva que se puede vigilar en producción sin etiquetas.

El entorno (`dev`) viene de `ENTORNO` (`LANGFUSE_TRACING_ENVIRONMENT` en el SDK); la versión del código, de `GIT_SHA`
como `LANGFUSE_RELEASE`.

## Costo por request y por feature (Postgres)

Las consultas se probaron contra el esquema; con la base vacía devuelven cero filas.

```sql
-- Costo y latencia por análisis (trace_id), últimos 30 días
SELECT trace_id,
       min(created_at)           AS inicio,
       count(*)                  AS llamadas,
       sum(tokens_in)            AS tokens_in,
       sum(tokens_out)           AS tokens_out,
       round(sum(cost_usd), 4)   AS costo_usd,
       sum(latency_ms) / 1000    AS segundos_de_modelo
FROM audit_log
WHERE trace_id IS NOT NULL AND stage IN ('D2', 'D4') AND created_at > now() - interval '30 days'
GROUP BY trace_id
ORDER BY inicio DESC;
```

```sql
-- p50 y p95 del costo y de la espera de modelo por análisis, y costo total, por feature y destino
WITH por_analisis AS (
  SELECT trace_id,
         tags ->> 'feature'  AS feature,
         destination::text   AS destino,
         sum(cost_usd)       AS costo,
         sum(latency_ms)     AS ms
  FROM audit_log
  WHERE trace_id IS NOT NULL AND stage IN ('D2', 'D4') AND created_at > now() - interval '30 days'
  GROUP BY trace_id, tags ->> 'feature', destination
)
SELECT feature, destino, count(*) AS analisis,
       round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY costo)::numeric, 4) AS costo_p50,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY costo)::numeric, 4) AS costo_p95,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY ms)::numeric / 1000, 0) AS espera_modelo_p95_s,
       round(sum(costo), 2) AS costo_total
FROM por_analisis
GROUP BY feature, destino;
```

Con destino `local` el costo del proveedor es el del modelo simulado; con hardware propio el costo es fijo y se imputa
(ADR 0012), no sale de esta consulta.

## Dashboards y alertas: qué hay y qué falta

- **Dashboard en Langfuse (creado el 19 oct 2026, 9 widgets):** latencia p50 y p95 de trazas, latencia p95 filtrada por
  nombre de traza (en el tiempo), costo p95 por traza, costo total por etiqueta, promedio y suma de scores numéricos
  (en el tiempo) y tokens por modelo. Lectura del día de la captura, sobre las corridas dev del 18 y 19 oct:

  | Widget | Valor | Contra el umbral |
  |---|---|---|
  | Latencia p50 de trazas | 104.5 s (el widget muestra `104.549K`; Langfuse reporta ms, coherente con la traza de 198 s) | — |
  | Latencia p95 de trazas | 306.4 s | SLO de la ruta local ≤ 1,200 s (ADR 0012): dentro. SLO por API ≤ 180 s del runbook: **fuera**, ya reconocido en el ADR |
  | Costo p95 por traza | US$0.059 | Umbral propuesto US$0.10: dentro |
  | Promedio del score de escalamiento | 0.357 | Umbral propuesto 60 %: dentro (coincide con el 33–40 % medido) |

  Captura del dashboard: `docs/operacion/langfuse-dashboard-slo.png`.

  **Qué no dicen esos números:**
  1. Son pocas trazas de desarrollo, no tráfico: un p95 de pocas decenas de puntos es una estimación débil.
  2. Mezclan modelos (las corridas con DeepSeek y con Qwen comparten el dashboard), así que el p95 **no** es el de la ruta
     local sola. Para afirmar el SLO de ADR 0012 hay que filtrar por modelo o por etiqueta de destino.
  3. Los dos primeros widgets de latencia no filtran por nombre de traza; el tercero sí (`analisis_8d`).
  4. El widget de tokens por modelo salió sin valor visible en la captura: no lo cito hasta verlo con datos.
  5. Los scores miden trabajo de contención, no si la causa propuesta es correcta (ver arriba).
  El SLO de análisis fallidos no sale de Langfuse (solo hay traza si el análisis se emitió); es `analysis_run` en Postgres.
- **Alertas: no hay ninguna.** No asumo que Langfuse las traiga. La alternativa mínima y honesta es una consulta
  programada sobre `audit_log` (la de arriba con un umbral) que avise por correo o chat. Umbrales propuestos, pendientes de
  confirmar con tu escenario: costo p95 por análisis > US$0.10 (≈ 3 × lo medido con Qwen), tasa de escalamiento > 60 %
  (medida: 33–40 %), análisis fallidos > 5 % en un día.
- **Evals en línea:** los scores de arriba son lo que existe. Un juez de LLM sobre muestras de producción no existe y no
  se promete.
