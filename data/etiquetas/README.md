# Etiquetas humanas para calibrar el juez

Aquí viven las etiquetas que los ingenieros de calidad ponen a mano para medir al juez LLM del eval semántico
(`apps/api/app/evalkit/calibration.py`). Están fuera de `evals/` porque `data/generator/generate.py` borra esa carpeta
al regenerar el dataset; esto es trabajo humano y se versiona.

1. `make eval-labels N=40` escribe `agente.por_etiquetar.jsonl`: hechos al azar del D4 con el texto de sus fuentes,
   sin el juicio del juez.
2. Por cada línea, llenar `etiqueta_humana` con una de `respaldada`, `parcial`, `sin_respaldo`, `contradice`, y
   `revisor` con un identificador (iniciales). `nota` es opcional.
3. Guardar como `agente.etiquetas.jsonl`. Si dos personas etiquetan los mismos hechos, una línea por revisor.
4. `make eval-semantic` empareja por `id` y reporta acuerdo y kappa en `agente.semantico.md`.

Criterio de lectura de las etiquetas:

- `respaldada`: las fuentes dicen lo que el hecho afirma (cifras, fechas, equipos coinciden).
- `parcial`: una parte sí, otra no aparece o está exagerada.
- `sin_respaldo`: las fuentes no hablan de eso, o solo mencionan el código sin el hecho.
- `contradice`: las fuentes dicen lo contrario.

Los datos son ficticios. Con datos reales, estas muestras contendrían texto confidencial y no se versionarían aquí.
