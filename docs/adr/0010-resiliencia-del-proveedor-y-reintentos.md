# ADR 0010 — Reintentos acotados con backoff; sin fallback de modelo (decisión abierta)

**Estado:** Propuesta (el análisis de peor caso es de lectura de código; falta medirlo con 429 sostenido)

## Contexto
Los proveedores externos devuelven 429 y 5xx. Los prompts de D4 son largos. Con DeepSeek el p50 de una corrida fue 85 s; con Qwen 3.6 27B (`dev-qwen27`) fue 209 s, p95 378 s, y una sola llamada a D4 tarda ≈ 100 s. Esa latencia choca con el timeout por defecto.

## Estado actual
- El cliente reintenta 408, 409, 425, 429, 500, 502, 503 y 504 con backoff, respetando `Retry-After` con un tope (`openai_compat.py`).
- Tras agotar los reintentos lanza un error de proveedor que se audita; el análisis falla sin escribir un borrador parcial.
- La salida estructurada inválida se reintenta con la retroalimentación (`max_attempts`). `d4_large` reintenta con el mismo modelo.
- `Idempotency-Key` en `/analyze` devuelve la corrida ya hecha sin llamar al modelo.

## Peor caso que se puede alcanzar hoy (de la configuración por defecto)

Los tres mecanismos se **multiplican**, no se suman:

| Capa | Tope | Dónde |
|---|---|---|
| Intentos HTTP por llamada | 4 (`max_retries=3` más el primero) | `openai_compat.py`, `config.py` |
| Intentos de salida estructurada por etapa | 3 (`max_attempts`) | `structured.py`, `gateway.py` |
| Etapas con modelo | D2, D4 pequeño y, si `d4_retry`, D4 grande | `graph.py` |

Cota superior teórica: 3 etapas × 3 × 4 = **36 peticiones HTTP por corrida**, cada una con hasta `timeout_s`. No se
alcanza en la práctica, pero nada en el código lo impide, y **un timeout cuenta como reintento** (`httpx.TimeoutException`
está en la ruta de reintento). Con un proveedor lento, cada llamada puede gastar hasta 4 × `timeout_s` antes de fallar, y
el proveedor puede facturar las que sí llegaron a procesarse.

Observado con Qwen en `dev-qwen27`: 1.8 llamadas por corrida y 3 truncamientos por `max_tokens=8192` reintentados dentro
de la misma llamada. No hay medición de 429 sostenido (hipótesis H3 de `prueba-de-carga.md`).

**Timeout por defecto: 60 s (`LLM_*__TIMEOUT_S`).** Una llamada a D4 con Qwen tarda ≈ 100 s, así que con el valor por
defecto cada llamada agotaría el tiempo y se reintentaría. Los workflows y la prueba de carga fijan 180 y 300 s. **Lo
que corre en cada despliegue es el valor efectivo, no el por defecto**: hay que verificarlo con `make llm-diagnose` y
bajar el riesgo cambiando el por defecto a un valor coherente con el modelo candidato.

## Decisión propuesta
1. **Presupuesto único de reintentos por corrida** (p. ej. un máximo de peticiones HTTP por corrida, compartido por todas las etapas), en lugar de topes independientes que se multiplican. El valor se fija después de medir H3; no se adopta uno a ojo. **No implementado.**
2. **Fallback de modelo solo dentro del mismo nivel de confidencialidad.** Para una NCR confidencial, el único fallback permitido es otro modelo local; nunca la API. Para contexto interno puede usarse otro modelo de la API.
3. **Timeout por destino coherente con la latencia real.** El por defecto (60 s) es menor que las llamadas observadas con Qwen (≈ 100 s) y que algunas con DeepSeek (56–73 s). Pasar el por defecto a un valor de ese orden y verificar el efectivo con `make llm-diagnose`.
4. **Un timeout no debe reintentarse a ciegas.** Reintentar una llamada que ya consumió 100 s de GPU duplica el costo y el tiempo; el reintento por timeout conviene limitarlo a 1 y reportarlo como métrica propia.

## Consecuencias
- (+) El comportamiento ante un 429 sostenido quedaría definido y probado.
- (−) Sin fallback, la caída del proveedor local detiene el análisis de lo confidencial. Es una decisión explícita: preferible a enviarlo fuera.

## Evidencia pendiente
- Prueba de carga con el punto de saturación (en curso, `prueba-de-carga.md`).
- Simulación de 429 sostenido (H3): `STUB_ERROR_RATE=0.5 STUB_ERROR_STATUS=429` en el stub; medir peticiones por corrida y latencia, y con eso fijar el tope del punto 1.
- Cuántas corridas de `dev-qwen27` habrían fallado con un `timeout_s` de 60 s (no se ha medido).
