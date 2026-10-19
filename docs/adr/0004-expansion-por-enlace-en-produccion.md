# ADR 0004 — Expansión por enlace NCR → 8D → D4 encendida en producción

**Estado:** Aceptada

## Contexto
La consulta describe el síntoma y se parece a D2 de un 8D, no a su D4: la sección causal del precedente casi no aparece en el top-10 de la búsqueda directa.

## Decisión
`expand_case_links=True` en producción (variante `con_enlaces`): del top de `search_cases` se toman hasta 2 8D, directos o citados por una NCR, y se
trae su D4 con los mismos permisos, corte `as_of` y exclusiones (`get_linked_8d_causes`, una llamada más del presupuesto).

## Alternativas descartadas
- **Cambiar pesos de RRF, un fragmento por documento, multi-query:** probados y retirados; la diferencia fue de un episodio sobre tres y no movió la causa top-3.
- **Reconstruir el índice:** sin una medición que apunte al chunking, no se justifica.

## Consecuencias
- (+) Cobertura del precedente vía NCR de 0.50 a 0.88 en la partición dev.
- (−) Trae también un 8D de otra causa en los casos de causa nueva (`top1 cita 8D ajeno` = 0.06 en `dev-v6`).
- (−) Con 12 casos dev, las diferencias de 1–2 casos son ruido (rango observado 26–29 de 36).

## Evidencia
`docs/evaluacion.md`, `app/evalkit/retrieval.py`, reporte `dev-v6.md`.
