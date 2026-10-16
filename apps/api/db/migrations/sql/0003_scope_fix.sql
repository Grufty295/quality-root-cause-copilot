-- =====================================================================
-- 0003_scope_fix.sql: semantica correcta del alcance a nivel planta
--
-- Bug en 0001: user_can_access(usuario, planta, NULL) devolvia true si el
-- usuario tenia CUALQUIER linea de esa planta. Una tool que pidiera
-- "defectos de toda la planta" le mostraba L1 a un ingeniero que solo
-- tiene L2.
--
-- Regla nueva:
--   * p_line con valor: acceso si tiene esa linea o toda la planta.
--   * p_line NULL (consulta de toda la planta): acceso solo si su alcance
--     es la planta completa (user_scope.line_id IS NULL).
--
-- visible_fragments() no cambia: un documento de planta (line_id NULL,
-- p. ej. un SOP general) si debe ser visible para un usuario de una linea.
-- La diferencia es entre "leer un documento de la planta" y "consultar los
-- datos de todas las lineas".
-- =====================================================================

CREATE OR REPLACE FUNCTION user_can_access(p_user uuid, p_plant text, p_line text)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM user_scope s
        WHERE s.user_id = p_user
          AND s.plant_id = p_plant
          AND (s.line_id IS NULL OR s.line_id = p_line)
    )
$$;

-- Lineas que el usuario puede consultar en una planta. Las tools filtran con
-- line_id = ANY(user_allowed_lines(...)) en vez de confiar en el parametro
-- que propone el LLM.
CREATE FUNCTION user_allowed_lines(p_user uuid, p_plant text)
RETURNS SETOF text LANGUAGE sql STABLE AS $$
    SELECT l.id
    FROM line l
    WHERE l.plant_id = p_plant
      AND EXISTS (
            SELECT 1 FROM user_scope s
            WHERE s.user_id = p_user
              AND s.plant_id = p_plant
              AND (s.line_id IS NULL OR s.line_id = l.id)
      )
    ORDER BY l.id
$$;
