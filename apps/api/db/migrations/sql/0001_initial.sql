-- =====================================================================
-- 0001_initial.sql: esquema inicial del Agente 8D (MVP)
--
-- Bloques:
--   1. Extensiones y tipos
--   2. Catalogos (planta, linea, cliente, parte, familia, causa AMEF)
--   3. Usuarios simulados y alcance (RBAC por planta y linea)
--   4. Corpus: documentos y fragmentos (nivel, PII, planta, linea, vector)
--   5. Datos operativos para las tools (defectos, mantenimiento)
--   6. NCR, versiones de secciones D2-D4 y citas
--   7. Mapeo de pseudonimos
--   8. Log de auditoria de solo insercion con hash encadenado
--   9. Recuperacion con permisos
--
-- Convenciones: catalogos con PK de texto legible ('JRZ1', 'L1'); entidades
-- con UUID. Alembic lo ejecuta crudo con el driver (sin parametros), asi que
-- los '%' de format() y RAISE no se interpretan como placeholders.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Extensiones y tipos
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;

-- El orden de declaracion define el orden del enum:
-- publico < interno < confidencial. Por eso max()/GREATEST() devuelven
-- "el nivel mas alto presente en el contexto", que es lo que decide el router.
CREATE TYPE confidentiality_level AS ENUM ('publico', 'interno', 'confidencial');

CREATE TYPE user_role AS ENUM ('ingeniero', 'gerente', 'auditor');

CREATE TYPE document_kind AS ENUM ('8d', 'amef', 'sop', 'instruccion', 'norma', 'ncr');

CREATE TYPE eightd_discipline AS ENUM ('D2', 'D3', 'D4');

-- No existe estado "cerrada": D5-D8 estan fuera del MVP y el agente
-- nunca cierra un 8D. Si no hay estado, no hay forma de asignarlo.
CREATE TYPE ncr_status AS ENUM ('abierta', 'en_analisis', 'pendiente_aprobacion', 'aprobada');

-- agente: borrador generado por el modelo (autor NULL)
-- edicion: cambio del ingeniero
-- aprobacion: version final, la registra alguien distinto a quien redacto
-- rechazo: vuelve al agente con retroalimentacion
CREATE TYPE section_version_kind AS ENUM ('agente', 'edicion', 'aprobacion', 'rechazo');

CREATE TYPE llm_destination AS ENUM ('local', 'api');

-- ---------------------------------------------------------------------
-- 2. Catalogos
-- ---------------------------------------------------------------------
CREATE TABLE plant (
    id          text PRIMARY KEY,
    name        text NOT NULL
);

CREATE TABLE line (
    id          text PRIMARY KEY,
    plant_id    text NOT NULL REFERENCES plant(id),
    name        text NOT NULL
);
CREATE INDEX line_plant_idx ON line (plant_id);
-- Permite FKs compuestas (plant_id, line_id) para garantizar que la linea
-- pertenece a la planta declarada en cada fila.
ALTER TABLE line ADD CONSTRAINT line_plant_uk UNIQUE (plant_id, id);

CREATE TABLE customer (
    id                  text PRIMARY KEY,
    name                text NOT NULL,
    -- Si es true, cualquier mencion del cliente o de sus partes eleva el
    -- caso a 'confidencial' (regla determinista del clasificador).
    is_confidential     boolean NOT NULL DEFAULT true
);

CREATE TABLE part (
    id                  text PRIMARY KEY,
    part_number         text NOT NULL UNIQUE,
    customer_id         text NOT NULL REFERENCES customer(id),
    description         text
);

CREATE TABLE defect_family (
    id          text PRIMARY KEY,
    name        text NOT NULL
);

-- Codigos de causa del AMEF. Los evals califican por coincidencia exacta
-- de este codigo.
CREATE TABLE cause_code (
    id                  text PRIMARY KEY,
    defect_family_id    text NOT NULL REFERENCES defect_family(id),
    -- 'ocurrencia' o 'no_deteccion' (el MVP pide 3 de ocurrencia + 1 de no deteccion)
    cause_type          text NOT NULL CHECK (cause_type IN ('ocurrencia', 'no_deteccion')),
    description         text NOT NULL
);

-- ---------------------------------------------------------------------
-- 3. Usuarios simulados y alcance
-- ---------------------------------------------------------------------
CREATE TABLE app_user (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username        text NOT NULL UNIQUE,
    display_name    text NOT NULL,
    role            user_role NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Un usuario puede tener varios alcances.
-- line_id NULL = todas las lineas de esa planta.
CREATE TABLE user_scope (
    user_id     uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    plant_id    text NOT NULL REFERENCES plant(id),
    line_id     text,
    FOREIGN KEY (plant_id, line_id) REFERENCES line (plant_id, id)
);
CREATE UNIQUE INDEX user_scope_uk ON user_scope (user_id, plant_id, coalesce(line_id, ''));

-- ---------------------------------------------------------------------
-- 4. Corpus: documentos y fragmentos
-- ---------------------------------------------------------------------
CREATE TABLE document (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Clave estable del generador (p. ej. '8D-2025-031'): hace la ingesta idempotente.
    source_key      text NOT NULL UNIQUE,
    kind            document_kind NOT NULL,
    title           text NOT NULL,
    -- plant_id NULL = documento global (normas, guias publicas)
    plant_id        text REFERENCES plant(id),
    -- line_id NULL = documento de toda la planta (SOP general, AMEF de planta)
    line_id         text,
    level           confidentiality_level NOT NULL,
    contains_pii    boolean NOT NULL DEFAULT false,
    defect_family_id text REFERENCES defect_family(id),
    doc_date        date,
    -- Si el documento nace de un 8D aprobado en el sistema (RF-16)
    ncr_id          uuid,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (plant_id, line_id) REFERENCES line (plant_id, id),
    CHECK (line_id IS NULL OR plant_id IS NOT NULL)
);

CREATE TABLE fragment (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    ordinal         integer NOT NULL,
    -- Unidad estructural: 'D2', 'D4', fila del AMEF, paso de la instruccion...
    section         text NOT NULL,
    content         text NOT NULL,
    -- Codigos exactos (numeros de parte, codigos de causa, IDs de aplicador).
    -- Se indexan con la configuracion 'simple' para que el stemming en espanol
    -- no los altere.
    codes           text NOT NULL DEFAULT '',

    -- Metadatos desnormalizados para filtrar dentro de la consulta. Los fija
    -- el trigger fragment_inherit a partir del documento: no se confia en
    -- lo que mande la ingesta.
    plant_id        text,
    line_id         text,
    level           confidentiality_level NOT NULL,
    contains_pii    boolean NOT NULL DEFAULT false,
    defect_family_id text,
    doc_date        date,

    -- Debe coincidir con EMBEDDING_DIM. Cambiar de modelo exige reindexar.
    embedding       vector(384),
    embedding_model text,

    tsv             tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('simple'::regconfig, codes), 'A')
                     || setweight(to_tsvector('spanish'::regconfig, content), 'B')
                    ) STORED,
    created_at      timestamptz NOT NULL DEFAULT now(),

    UNIQUE (document_id, ordinal),
    CHECK ((embedding IS NULL) = (embedding_model IS NULL))
);

CREATE INDEX fragment_tsv_idx    ON fragment USING gin (tsv);
CREATE INDEX fragment_scope_idx  ON fragment (plant_id, line_id);
CREATE INDEX fragment_doc_idx    ON fragment (document_id);
-- Sin indice vectorial a proposito: con pocos miles de fragmentos, la busqueda
-- exacta tarda milisegundos y es determinista (los evals son reproducibles).
-- Un indice HNSW es aproximado y, combinado con el filtro de permisos, puede
-- devolver menos de k resultados. Activarlo solo si el corpus crece:
-- CREATE INDEX fragment_embedding_hnsw ON fragment USING hnsw (embedding vector_cosine_ops);

-- Herencia de metadatos: un fragmento nunca tiene un nivel menor que su
-- documento ni otra planta/linea.
CREATE FUNCTION fragment_inherit() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    d document;
BEGIN
    SELECT * INTO d FROM document WHERE id = NEW.document_id;
    NEW.plant_id         := d.plant_id;
    NEW.line_id          := d.line_id;
    NEW.level            := GREATEST(d.level, NEW.level);
    NEW.contains_pii     := d.contains_pii OR NEW.contains_pii;
    NEW.defect_family_id := coalesce(NEW.defect_family_id, d.defect_family_id);
    NEW.doc_date         := d.doc_date;
    RETURN NEW;
END $$;

CREATE TRIGGER fragment_inherit
    BEFORE INSERT OR UPDATE ON fragment
    FOR EACH ROW EXECUTE FUNCTION fragment_inherit();

-- Si cambia el documento, sus fragmentos se re-sincronizan.
CREATE FUNCTION document_propagate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Un UPDATE vacio dispara fragment_inherit, que vuelve a copiar todo.
    -- Si el documento baja de nivel, el fragmento conserva el mayor (fallo seguro).
    UPDATE fragment SET document_id = document_id WHERE document_id = NEW.id;
    RETURN NEW;
END $$;

CREATE TRIGGER document_propagate
    AFTER UPDATE OF plant_id, line_id, level, contains_pii, doc_date ON document
    FOR EACH ROW EXECUTE FUNCTION document_propagate();

-- ---------------------------------------------------------------------
-- 5. Datos operativos para las tools (solo lectura para el agente)
-- ---------------------------------------------------------------------
-- IMPORTANTE: defect_event NO lleva cause_code. Si el registro de defectos
-- trae la causa, el agente "encuentra" la respuesta leyendo una columna y
-- los evals miden eso, no el razonamiento.
CREATE TABLE defect_event (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at         timestamptz NOT NULL,
    plant_id            text NOT NULL REFERENCES plant(id),
    line_id             text NOT NULL,
    shift               smallint NOT NULL CHECK (shift BETWEEN 1 AND 3),
    part_id             text REFERENCES part(id),
    defect_family_id    text NOT NULL REFERENCES defect_family(id),
    station             text,
    quantity            integer NOT NULL DEFAULT 1 CHECK (quantity > 0),
    notes               text,
    FOREIGN KEY (plant_id, line_id) REFERENCES line (plant_id, id)
);
CREATE INDEX defect_event_query_idx ON defect_event (plant_id, line_id, occurred_at);

CREATE TABLE maintenance_order (
    id                  text PRIMARY KEY,
    plant_id            text NOT NULL REFERENCES plant(id),
    line_id             text NOT NULL,
    equipment           text NOT NULL,
    order_type          text NOT NULL CHECK (order_type IN ('preventivo', 'correctivo')),
    due_date            date,
    completed_at        timestamptz,
    notes               text,
    FOREIGN KEY (plant_id, line_id) REFERENCES line (plant_id, id)
);
CREATE INDEX maintenance_order_query_idx ON maintenance_order (plant_id, line_id, due_date);

-- ---------------------------------------------------------------------
-- 6. NCR, versiones de secciones y citas
-- ---------------------------------------------------------------------
CREATE TABLE ncr (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,
    plant_id        text NOT NULL REFERENCES plant(id),
    line_id         text NOT NULL,
    shift           smallint NOT NULL CHECK (shift BETWEEN 1 AND 3),
    part_id         text REFERENCES part(id),
    customer_id     text REFERENCES customer(id),
    description     text NOT NULL,
    -- Lo fija el clasificador al registrar. NULL = aun sin clasificar,
    -- y el router debe tratarlo como 'confidencial' (fallo seguro).
    detected_level  confidentiality_level,
    contains_pii    boolean,
    status          ncr_status NOT NULL DEFAULT 'abierta',
    opened_by       uuid NOT NULL REFERENCES app_user(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (plant_id, line_id) REFERENCES line (plant_id, id)
);
CREATE INDEX ncr_scope_idx ON ncr (plant_id, line_id);

ALTER TABLE document
    ADD CONSTRAINT document_ncr_fk FOREIGN KEY (ncr_id) REFERENCES ncr(id);

-- Historial de cada seccion: cada fila es inmutable; una correccion es una
-- version nueva.
CREATE TABLE section_version (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ncr_id          uuid NOT NULL REFERENCES ncr(id),
    discipline      eightd_discipline NOT NULL,
    version_no      integer NOT NULL,
    kind            section_version_kind NOT NULL,
    -- Contenido validado por el esquema Pydantic de la disciplina
    content         jsonb,
    feedback        text,
    author_id       uuid REFERENCES app_user(id),
    -- Reproducibilidad: que modelo, prompt e indice produjeron el borrador
    model           text,
    prompt_version  text,
    index_version   text,
    trace_id        text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (ncr_id, discipline, version_no),
    -- El agente no tiene autor humano y siempre declara su modelo;
    -- cualquier otra version tiene autor humano.
    CHECK ((kind = 'agente') = (author_id IS NULL)),
    CHECK (kind <> 'agente' OR (model IS NOT NULL AND content IS NOT NULL)),
    CHECK (kind <> 'rechazo' OR feedback IS NOT NULL),
    CHECK (kind = 'rechazo' OR content IS NOT NULL)
);

-- Reglas de autoria:
--   * 'edicion' solo la hace un ingeniero con alcance en la planta/linea.
--   * 'aprobacion' solo la hace un gerente con alcance, que no abrio la NCR
--     ni edito esa seccion (quien redacta no aprueba).
CREATE FUNCTION user_can_access(p_user uuid, p_plant text, p_line text)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM user_scope s
        WHERE s.user_id = p_user
          AND s.plant_id = p_plant
          AND (s.line_id IS NULL OR p_line IS NULL OR s.line_id = p_line)
    )
$$;

CREATE FUNCTION section_version_rules() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    n       ncr;
    r       user_role;
BEGIN
    SELECT * INTO n FROM ncr WHERE id = NEW.ncr_id;

    IF NEW.author_id IS NOT NULL THEN
        SELECT role INTO r FROM app_user WHERE id = NEW.author_id;
        IF NOT user_can_access(NEW.author_id, n.plant_id, n.line_id) THEN
            RAISE EXCEPTION 'El usuario no tiene alcance sobre la planta/linea de la NCR'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;

    IF NEW.kind = 'edicion' AND r <> 'ingeniero' THEN
        RAISE EXCEPTION 'Solo un ingeniero puede editar una seccion'
            USING ERRCODE = 'insufficient_privilege';
    END IF;

    IF NEW.kind = 'aprobacion' THEN
        IF r <> 'gerente' THEN
            RAISE EXCEPTION 'Solo un gerente puede aprobar'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.author_id = n.opened_by OR EXISTS (
            SELECT 1 FROM section_version v
            WHERE v.ncr_id = NEW.ncr_id
              AND v.discipline = NEW.discipline
              AND v.kind = 'edicion'
              AND v.author_id = NEW.author_id
        ) THEN
            RAISE EXCEPTION 'Quien redacta o edita una seccion no puede aprobarla'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;

    RETURN NEW;
END $$;

CREATE TRIGGER section_version_rules
    BEFORE INSERT ON section_version
    FOR EACH ROW EXECUTE FUNCTION section_version_rules();

-- Que fragmentos respaldan cada afirmacion. La FK impide citar IDs inventados;
-- el guardrail de la API verifica ademas que el fragmento fue recuperado en
-- ese turno y que el usuario podia verlo.
CREATE TABLE citation (
    section_version_id  uuid NOT NULL REFERENCES section_version(id),
    -- Ruta dentro del JSON de la seccion: 'causas[0]', 'no_deteccion', 'd2.where'
    claim_ref           text NOT NULL,
    fragment_id         uuid NOT NULL REFERENCES fragment(id),
    PRIMARY KEY (section_version_id, claim_ref, fragment_id)
);
CREATE INDEX citation_fragment_idx ON citation (fragment_id);

-- Historial inmutable: versiones y citas no se modifican ni se borran.
CREATE FUNCTION forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'La tabla % es de solo insercion', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER section_version_immutable
    BEFORE UPDATE OR DELETE ON section_version
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER citation_immutable
    BEFORE UPDATE OR DELETE ON citation
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- ---------------------------------------------------------------------
-- 7. Mapeo de pseudonimos
-- ---------------------------------------------------------------------
-- Contiene datos en claro: nunca se envia a un modelo ni a las trazas.
-- Retencion: mientras la NCR este abierta + 90 dias (expires_at).
CREATE TABLE pseudonym_map (
    ncr_id          uuid NOT NULL REFERENCES ncr(id),
    placeholder     text NOT NULL,          -- '[CLIENTE_1]', 'Operador A'
    real_value      text NOT NULL,
    entity_type     text NOT NULL,          -- 'cliente', 'parte', 'persona', 'nomina'
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz,
    PRIMARY KEY (ncr_id, placeholder),
    UNIQUE (ncr_id, entity_type, real_value)
);

-- ---------------------------------------------------------------------
-- 8. Log de auditoria: solo insercion, hash encadenado
-- ---------------------------------------------------------------------
-- Nunca guarda contenido: solo IDs, niveles, modelo y metricas.
CREATE TABLE audit_log (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
    user_id             uuid REFERENCES app_user(id),
    ncr_id              uuid REFERENCES ncr(id),
    stage               text NOT NULL,                   -- 'clasificacion', 'D2', 'D4', ...
    detected_level      confidentiality_level NOT NULL,
    destination         llm_destination NOT NULL,
    provider            text NOT NULL,                   -- 'mock', 'openrouter', 'ollama'
    model               text NOT NULL,
    fragment_ids        uuid[] NOT NULL DEFAULT '{}',
    redaction_applied   boolean NOT NULL,
    pseudonymized       boolean NOT NULL,
    tokens_in           integer,
    tokens_out          integer,
    cost_usd            numeric(12, 6),
    latency_ms          integer,
    trace_id            text,
    -- Tags de FinOps (planta, linea, feature, entorno)
    tags                jsonb NOT NULL DEFAULT '{}'::jsonb,
    prev_hash           bytea NOT NULL,
    hash                bytea NOT NULL,
    -- Invariante del router en la propia base: un contexto confidencial
    -- jamas se registra con destino 'api'. Si el codigo lo intenta, falla.
    CHECK (NOT (detected_level = 'confidencial' AND destination = 'api'))
);
CREATE INDEX audit_log_ncr_idx ON audit_log (ncr_id);

-- Serializacion canonica de una fila. Una sola funcion para el trigger y para
-- la verificacion, asi ambas calculan exactamente lo mismo.
-- created_at se serializa como microsegundos epoch: el texto de un timestamptz
-- depende de la zona horaria de la sesion y romperia la verificacion.
CREATE FUNCTION audit_row_hash(a audit_log) RETURNS bytea
LANGUAGE sql IMMUTABLE AS $$
    SELECT sha256(
        a.prev_hash || convert_to(
            jsonb_build_object(
                'id',                a.id,
                'created_at_us',     (extract(epoch FROM a.created_at) * 1000000)::bigint,
                'user_id',           a.user_id,
                'ncr_id',            a.ncr_id,
                'stage',             a.stage,
                'detected_level',    a.detected_level,
                'destination',       a.destination,
                'provider',          a.provider,
                'model',             a.model,
                'fragment_ids',      a.fragment_ids,
                'redaction_applied', a.redaction_applied,
                'pseudonymized',     a.pseudonymized,
                'tokens_in',         a.tokens_in,
                'tokens_out',        a.tokens_out,
                'cost_usd',          a.cost_usd::text,
                'latency_ms',        a.latency_ms,
                'trace_id',          a.trace_id,
                'tags',              a.tags
            )::text,
            'UTF8'
        )
    )
$$;

CREATE FUNCTION audit_log_chain() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Serializa las inserciones: dos transacciones concurrentes leerian el
    -- mismo prev_hash y la cadena se bifurcaria.
    PERFORM pg_advisory_xact_lock(hashtext('audit_log_chain'));

    SELECT hash INTO NEW.prev_hash FROM audit_log ORDER BY id DESC LIMIT 1;
    NEW.prev_hash := coalesce(NEW.prev_hash, '\x00'::bytea);  -- registro genesis
    NEW.hash      := audit_row_hash(NEW);
    RETURN NEW;
END $$;

CREATE TRIGGER audit_log_chain
    BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_chain();

CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

CREATE FUNCTION forbid_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'La tabla % no se puede truncar', TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_truncate();

-- Verificacion de la cadena. Devuelve una fila por cada registro roto
-- (vacio = cadena integra) y, al final, el hash de la cabeza.
--   SELECT * FROM audit_verify();
CREATE FUNCTION audit_verify()
RETURNS TABLE (id bigint, problem text, head_hash text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    a        audit_log;
    expected bytea := '\x00'::bytea;
    n        bigint := 0;
BEGIN
    FOR a IN SELECT * FROM audit_log ORDER BY audit_log.id LOOP
        n := n + 1;
        IF a.prev_hash <> expected THEN
            id := a.id; problem := 'prev_hash no coincide con el registro anterior'; head_hash := NULL;
            RETURN NEXT;
        END IF;
        IF a.hash <> audit_row_hash(a) THEN
            id := a.id; problem := 'el contenido no coincide con su hash'; head_hash := NULL;
            RETURN NEXT;
        END IF;
        expected := a.hash;
    END LOOP;
    id := NULL;
    problem := format('registros verificados: %s', n);
    head_hash := encode(expected, 'hex');
    RETURN NEXT;
END $$;

-- ---------------------------------------------------------------------
-- 9. Recuperacion con permisos
-- ---------------------------------------------------------------------
-- Unica puerta de entrada al corpus para el RAG: la busqueda hibrida debe
-- consultar esta funcion, no la tabla fragment. El filtro ocurre antes del
-- ranking, asi que un fragmento fuera de alcance nunca compite por el top-k.
--
-- Visibilidad:
--   * documento global (plant_id NULL): visible para todos
--   * documento de planta (line_id NULL): visible con alcance en esa planta
--   * documento de linea: visible con alcance en la planta y esa linea
--     (o en toda la planta)
CREATE FUNCTION visible_fragments(p_user uuid)
RETURNS SETOF fragment
LANGUAGE sql STABLE AS $$
    SELECT f.*
    FROM fragment f
    WHERE f.plant_id IS NULL
       OR EXISTS (
            SELECT 1 FROM user_scope s
            WHERE s.user_id = p_user
              AND s.plant_id = f.plant_id
              AND (s.line_id IS NULL OR f.line_id IS NULL OR s.line_id = f.line_id)
       )
$$;
