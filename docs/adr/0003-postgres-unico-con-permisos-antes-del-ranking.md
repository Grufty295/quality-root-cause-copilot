# ADR 0003 — Postgres con pgvector para todo; permisos en SQL antes del ranking

**Estado:** Aceptada

## Contexto
Documentos, vectores, permisos, versiones y auditoría deben ser coherentes entre sí y respetar el alcance por planta y línea.

## Decisión
Un solo Postgres 16 con pgvector. La búsqueda híbrida (texto en español + vector, fusión RRF k=60) consulta solo
`visible_fragments(usuario)`, que filtra permisos, y aplica `as_of` y tipos de documento **antes** de ordenar. Los embeddings
(`intfloat/multilingual-e5-large`, 1024 dims) se calculan en local.

## Alternativas descartadas
- **Qdrant / Redis aparte:** duplica permisos y complica la consistencia.
- **Filtrar después del ranking:** un fragmento ajeno compite por el top-k y puede aparecer en trazas.
- **API de embeddings:** los documentos confidenciales saldrían de la planta al indexarse.

## Consecuencias
- (+) `test_permission_case_per_01`, `test_other_plant_sees_nothing`, `test_as_of_excludes_future_documents`.
- (−) Escala vertical; para un volumen mayor habría que medir el índice vectorial (no medido).
- (−) La búsqueda directa trae el 8D precedente en el top-5 en 0.50 de los episodios y casi nunca su D4; la expansión por enlace lo compensa (ADR 0004).

## Evidencia
`db/migrations/sql/0001_initial.sql` (`visible_fragments`), `app/retrieval/`, `tests/retrieval/test_retrieval_db.py`.
