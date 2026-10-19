# Documentación

## Producto y diseño
| Documento | Para qué |
|---|---|
| [producto/restricciones-y-alcance.md](producto/restricciones-y-alcance.md) | Restricciones de la planta, alcance y qué no se persigue |
| [adr/](adr/README.md) | Decisiones de arquitectura con alternativas y consecuencias (0001 a 0012) |
| [arquitectura/c4.md](arquitectura/c4.md) | Contexto, contenedores, componentes y flujo de datos |
| [arquitectura/diagramas.md](arquitectura/diagramas.md) | Grafo del agente, estados de corrida, despliegue, observabilidad, CI y prueba de carga |

## Seguridad
| Documento | Para qué |
|---|---|
| [seguridad/modelo-de-amenazas.md](seguridad/modelo-de-amenazas.md) | Fronteras de confianza, amenazas, OWASP LLM Top 10 y brechas abiertas |
| [seguridad/promptfoo.md](seguridad/promptfoo.md) | Controles de inyección y de salida: qué cubren, resultados y límites |
| [matriz-roles.md](matriz-roles.md) | Roles, permisos y separación de funciones |
| [redactor.md](redactor.md) | Redactor y seudonimizador del destino `api` |
| [evaluacion-pii-textos-reales.md](evaluacion-pii-textos-reales.md) | Cómo evaluar la detección de PII con textos que no escribió el mismo equipo |

## Operación
| Documento | Para qué |
|---|---|
| [operacion/runbook.md](operacion/runbook.md) | Arranque, verificaciones, incidentes, rotación de llaves y evals |
| [operacion/observabilidad.md](operacion/observabilidad.md) | Trazas, scores, costo por análisis, dashboard (captura: `operacion/langfuse-dashboard-slo.png`) y alertas |
| [operacion/prueba-de-carga.md](operacion/prueba-de-carga.md) | Hipótesis, resultados y límites de la prueba de carga |
| [operacion/ci.md](operacion/ci.md) | Las tres capas de CI y qué bloquea cada una |
| [operacion/probar-ci.md](operacion/probar-ci.md) | Plan paso a paso para probar el CI, incluidas roturas deliberadas |

## Evaluación y referencia técnica
| Documento | Para qué |
|---|---|
| [evaluacion.md](evaluacion.md) | Métricas, partición, gates y reglas del eval |
| [agente.md](agente.md) | El grafo D2/D4, sus etapas y sus guardrails |
| [datos-operativos.md](datos-operativos.md) | Datos de defectos, mantenimiento, equipos y ciclos que carga la semilla |

Las cifras de calidad, costo y latencia provienen de `dev-v6` (36 corridas, datos sintéticos). Los huecos conocidos están
en cada documento, en la sección de brechas o consecuencias.
