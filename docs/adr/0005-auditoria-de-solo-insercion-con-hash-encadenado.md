# ADR 0005 — Auditoría de solo inserción con hash encadenado y sin contenido

**Estado:** Aceptada

## Contexto
Hay que poder demostrar qué se envió, adónde, con qué modelo y a qué costo, sin que el registro se vuelva otra fuga.

## Decisión
`audit_log` guarda nivel, destino, proveedor, modelo, ids de fragmentos, tokens, costo estimado, latencia y tags; **nunca contenido**. Triggers
impiden `UPDATE`, `DELETE` y `TRUNCATE`; otro trigger encadena el hash de cada fila con el anterior. `audit_verify()` devuelve una fila por cada
registro roto y el hash de la cabeza. Un `CHECK` prohíbe `confidencial` + `api`.

## Alternativas descartadas
- **Guardar prompts y respuestas:** útil para depurar, pero duplica los datos confidenciales.
- **Solo logs de aplicación:** no son verificables.

## Consecuencias
- (+) `make audit` detecta una alteración de una fila o de su orden.
- (−) Protege contra alteraciones accidentales y de un usuario sin privilegios. Un administrador de la base puede reescribir toda la cadena: no hay ancla externa del hash de la cabeza.
- (−) El usuario de la aplicación es uno solo (`app`); no hay rol de base de solo inserción separado.

## Evidencia
`0001_initial.sql` (triggers `audit_log_chain`, `audit_log_immutable`, `audit_log_no_truncate`), `tests/agent/llm/test_audit_db.py`.
