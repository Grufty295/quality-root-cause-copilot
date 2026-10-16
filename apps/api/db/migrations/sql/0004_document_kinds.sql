-- =====================================================================
-- 0004_document_kinds.sql: tipos de documento que el corpus ya trae
--
-- El generador produce PLAN_CONTROL, ESPECIFICACION y CSR, que 0001 no tenia.
-- Mapearlos a 'norma' perdia informacion: un CSR es un requisito del cliente
-- (y confidencial), no una norma publica. El tipo original queda ademas en
-- document.metadata->>'tipo'.
--
-- ADD VALUE no se puede usar en la misma transaccion en que se agrega; aqui
-- solo se agrega.
-- =====================================================================

ALTER TYPE document_kind ADD VALUE IF NOT EXISTS 'plan_control';
ALTER TYPE document_kind ADD VALUE IF NOT EXISTS 'especificacion';
ALTER TYPE document_kind ADD VALUE IF NOT EXISTS 'requisito_cliente';
