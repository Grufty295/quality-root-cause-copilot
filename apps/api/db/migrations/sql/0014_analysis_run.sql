-- 0014: corridas del agente (estado, idempotencia, manifiesto) y motivo tipificado de rechazo.
--
-- analysis_run: una fila por POST /ncrs/{id}/analyze. `id` es el trace_id de la corrida, el
-- mismo que llevan audit_log, section_version y la traza de Langfuse: desde un borrador se
-- llega a cuanto costo, cuanto tardo cada etapa y con que configuracion se genero.
--
-- Idempotencia: el cliente puede mandar Idempotency-Key; la misma clave sobre la misma NCR
-- devuelve la corrida ya hecha en vez de llamar otra vez al modelo. Concurrencia: a lo mas
-- una corrida `en_curso` por NCR (indice unico parcial). Una corrida que quedo en curso por
-- una caida se marca `abandonada` cuando otra la encuentra vieja.
--
-- No guarda contenido: tiempos, conteos, codigos de evento, costos y la configuracion.

CREATE TYPE analysis_run_status AS ENUM (
    'en_curso',      -- el grafo esta trabajando
    'completada',    -- todas las disciplinas pedidas tienen borrador nuevo
    'parcial',       -- alguna si y alguna bloqueada por un guardrail o el modelo
    'sin_borrador',  -- ninguna: guardrails, injection en la NCR o el modelo no respondio
    'fallida',       -- excepcion (p. ej. 409 al escribir, base caida)
    'abandonada'     -- quedo en curso y nadie la cerro (caida del proceso)
);

CREATE TABLE analysis_run (
    id               text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    ncr_id           uuid NOT NULL REFERENCES ncr(id),
    requested_by     uuid NOT NULL REFERENCES app_user(id),
    idempotency_key  text CHECK (length(idempotency_key) BETWEEN 8 AND 200),
    disciplines      text[] NOT NULL,
    status           analysis_run_status NOT NULL DEFAULT 'en_curso',
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    duration_ms      integer CHECK (duration_ms >= 0),
    stage_ms         jsonb NOT NULL DEFAULT '{}',
    outcome          jsonb NOT NULL DEFAULT '{}',
    manifest         jsonb NOT NULL DEFAULT '{}',
    CHECK ((status = 'en_curso') = (finished_at IS NULL))
);
CREATE UNIQUE INDEX analysis_run_idempotency ON analysis_run (ncr_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX analysis_run_one_active ON analysis_run (ncr_id)
    WHERE status = 'en_curso';
CREATE INDEX analysis_run_ncr_idx ON analysis_run (ncr_id, started_at DESC);

-- Una corrida terminada no cambia: solo se cierra una vez (en_curso -> estado final).
CREATE FUNCTION analysis_run_close_once() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'en_curso' THEN
        RAISE EXCEPTION 'analysis_run % ya esta cerrada (%)', OLD.id, OLD.status
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.id <> OLD.id OR NEW.ncr_id <> OLD.ncr_id OR NEW.requested_by <> OLD.requested_by
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.started_at <> OLD.started_at THEN
        RAISE EXCEPTION 'analysis_run: solo cambian estado, tiempos, resultado y manifiesto'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER analysis_run_close_once BEFORE UPDATE ON analysis_run
    FOR EACH ROW EXECUTE FUNCTION analysis_run_close_once();
CREATE TRIGGER analysis_run_no_delete BEFORE DELETE ON analysis_run
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- Motivo tipificado del rechazo. La retroalimentacion libre sigue siendo obligatoria; el motivo
-- dice que parte del sistema mejorar (recuperacion, generacion, producto) sin leer el texto.
ALTER TABLE section_version
    ADD COLUMN feedback_reason text,
    ADD CONSTRAINT section_version_feedback_reason_valid CHECK (feedback_reason IN (
        'causa_incorrecta',      -- la hipotesis principal no es la causa
        'evidencia_insuficiente',-- la causa puede ser, pero lo citado no la sostiene
        'cita_irrelevante',      -- cita fuentes que no hablan del caso
        'contexto_incompleto',   -- falto un dato que el sistema tenia o debia tener
        'redaccion',             -- contenido correcto, mal expresado
        'error_tecnico'          -- formato roto, campos vacios, codigos raros
    )),
    ADD CONSTRAINT section_version_feedback_reason_on_reject CHECK (
        feedback_reason IS NULL OR kind = 'rechazo'
    );
