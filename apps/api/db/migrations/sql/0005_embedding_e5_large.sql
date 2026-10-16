-- =====================================================================
-- 0005_embedding_e5_large.sql: fragment.embedding pasa de vector(384) a vector(1024)
--
-- Modelo anterior: paraphrase-multilingual-MiniLM-L12-v2 (384 dims, 128 tokens).
-- Nuevo: intfloat/multilingual-e5-large (1024 dims, 512 tokens).
--
-- pgvector no convierte vectores entre dimensiones, así que los embeddings
-- existentes se anulan. embedding y embedding_model van juntos: lo exige la
-- CHECK de fragment. Después hay que reindexar con `python -m app.ingest`.
-- Mientras tanto la búsqueda vectorial no devuelve nada; la de texto completo
-- sigue funcionando.
--
-- Si un documento tiene citas, la ingesta se niega a reindexarlo (ver
-- ingest/service.py). Esos fragmentos quedan sin vector hasta que alguien
-- decida; no se borran en silencio.
-- =====================================================================

UPDATE fragment SET embedding = NULL, embedding_model = NULL;

ALTER TABLE fragment ALTER COLUMN embedding TYPE vector(1024) USING NULL::vector(1024);
