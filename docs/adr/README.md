# Registro de decisiones de arquitectura (ADR)

Formato breve: contexto, decisión, alternativas, consecuencias y evidencia. Las cifras provienen de `dev-v6` (36 corridas, datos sintéticos).

| ADR | Decisión | Estado |
|---|---|---|
| [0001](0001-agente-por-etapas-con-tools-por-codigo.md) | Un agente por etapas en LangGraph; las tools las llama el código | Aceptada |
| [0002](0002-gateway-unico-con-router-de-confidencialidad.md) | Gateway único de modelos con router de confidencialidad | Aceptada |
| [0003](0003-postgres-unico-con-permisos-antes-del-ranking.md) | Postgres con pgvector para todo; permisos en SQL antes del ranking | Aceptada |
| [0004](0004-expansion-por-enlace-en-produccion.md) | Expansión por enlace NCR → 8D → D4 encendida en producción | Aceptada |
| [0005](0005-auditoria-de-solo-insercion-con-hash-encadenado.md) | Auditoría de solo inserción con hash encadenado y sin contenido | Aceptada |
| [0006](0006-roles-y-separacion-de-funciones.md) | Cuatro roles; quien redacta no aprueba | Aceptada |
| [0007](0007-salida-cerrada-con-guardrail-determinista.md) | Salida de D4 con catálogo cerrado y guardrail determinista, sin confianza numérica | Aceptada |
| [0008](0008-trazas-sin-contenido.md) | Langfuse recibe solo metadatos, no el estado del grafo | Aceptada |
| [0009](0009-evaluacion-con-particion-sellada.md) | Evaluación con partición sellada, promedio por episodio y gates | Aceptada |
| [0010](0010-resiliencia-del-proveedor-y-reintentos.md) | Reintentos: peor caso multiplicativo, timeout coherente con Qwen, sin fallback de modelo | Propuesta |
| [0011](0011-secretos-y-despliegue.md) | Secretos en .env y despliegue con Docker Compose (alcance de PoC) | Aceptada para el PoC; deuda declarada |
| [0012](0012-inferencia-local-costo-y-capacidad.md) | Inferencia local: costo fijo de cumplimiento, Qwen 3.6 27B como candidato, SLO p95 ≤ 20 min | Propuesta |
