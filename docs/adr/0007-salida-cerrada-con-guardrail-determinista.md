# ADR 0007 — Salida de D4 con catálogo cerrado y guardrail determinista, sin confianza numérica

**Estado:** Aceptada

## Contexto
Una causa raíz inventada o sin respaldo es peor que no dar una. La confianza que declara un LLM no está calibrada.

## Decisión
D4 devuelve 3 causas de ocurrencia (RC-xx del AMEF) y 1 de no detección (ND-xx del SOP-QA-011), cada una con evidencia citada. Un guardrail determinista descarta, con motivo visible, la causa
cuyo código no está en el catálogo, que no cita un fragmento existente, cuyos fragmentos no mencionan el código, que culpa a una persona o que declara el caso cerrado. El respaldo
(`caso` o `solo_catalogo`) lo calcula el guardrail. Si la primera causa no tiene respaldo en el caso, el estado baja a `evidencia_insuficiente`. Cada hecho tiene un tope de 500 caracteres.

## Alternativas descartadas
- **LLM-as-judge:** la misma familia de modelos puede favorecer al agente y exige su propia calibración.
- **Causas libres y porcentajes de confianza:** no verificables.

## Consecuencias
- (+) Salida estructurada y verificable; un documento completo no cabe en un hecho (ADV-04).
- (−) La abstención no se activa en la práctica: 0 de 36 corridas en `dev-v6`. El criterio de respaldo casi siempre se cumple aunque la evidencia no distinga dos causas.
- (−) La calidad causal no se mide con el guardrail: acierta RC top-1 en 0.75 (dev), con fallos sistemáticos RC-02 ↔ RC-03.

## Evidencia
`app/agent/guardrails/output.py`, `schemas.py`, `tests/agent/graph/test_guardrails.py`.
