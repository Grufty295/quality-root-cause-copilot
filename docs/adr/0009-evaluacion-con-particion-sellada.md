# ADR 0009 — Evaluación con partición sellada, promedio por episodio y gates

**Estado:** Aceptada

## Contexto
El dataset es sintético y pequeño: 12 casos dev en 3 episodios. Los 4 casos de un episodio no son independientes.

## Decisión
Dev = E6–E8; test = E9–E10, sellada: se abre una sola vez con `--test` y la configuración congelada. Las tasas se promedian por caso y luego por episodio. El juez es determinista (códigos y citas). Hay una línea base trivial
(copiar la causa de la NCR más parecida: 11/20) que el agente debe superar. `make eval-gates` lee los reportes y sale con código 1 si falla un gate bloqueante; un gate sin dato no aprueba.

## Alternativas descartadas
- **Medir todo junto:** se sobreajusta a los casos que deciden.
- **Iterar sobre dev hasta subir el pass rate:** con ruido de ±1.5 casos no distingue mejoras.

## Consecuencias
- (+) Se reportan ambos conteos cuando una etiqueta cambió después de ver resultados (29/36 y 28/36).
- (−) Una sola corrida de test: no hay estimación del ruido fuera de muestra.
- (−) Los gates aún no corren en CI.

## Evidencia
`docs/evaluacion.md`, `app/evalkit/gates.py`, `app/evalkit/agent.py`.
