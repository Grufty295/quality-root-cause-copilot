-- 0009: detalle de defect_event y maintenance_order para cargar el dataset real.
--
-- defect_event
--   * occurred_at es la fecha de FABRICACION (a medianoche UTC: el dato es diario).
--     detected_on es cuando la planta se entero. Difieren hasta 10 dias en los
--     defectos que llegan por cliente o laboratorio. El corte "as_of" del agente
--     debe usar detected_on: con la fecha de fabricacion vería defectos que en
--     ese momento nadie conocia.
--   * source_id (evento_id del CSV) hace idempotente la carga. NULL para filas
--     capturadas a mano; UNIQUE admite varios NULL.
--   * Las columnas de trazabilidad (aplicador, maquina de corte, terminal, lote,
--     cable) son texto sin FK: no hay catalogo de equipos ni de terminales cargado.
--     defect_event sigue SIN causa: el agente debe inferirla, no leerla.
--
-- maintenance_order
--   * status es el estado reportado; completed_at solo existe si esta completada.
--   * cycles_at_event: ciclos acumulados del aplicador al ejecutar la orden.

ALTER TABLE defect_event
    ADD COLUMN source_id            text,
    ADD COLUMN detected_on          date,
    ADD COLUMN detection_point      text,
    ADD COLUMN applicator_id        text,
    ADD COLUMN cutting_machine_id   text,
    ADD COLUMN terminal_part_number text,
    ADD COLUMN terminal_lot         text,
    ADD COLUMN cable_part_number    text;

UPDATE defect_event SET detected_on = (occurred_at AT TIME ZONE 'UTC')::date;

ALTER TABLE defect_event
    ALTER COLUMN detected_on SET NOT NULL,
    ADD CONSTRAINT defect_event_source_uk UNIQUE (source_id),
    ADD CONSTRAINT defect_event_detected_after_made
        CHECK (detected_on >= (occurred_at AT TIME ZONE 'UTC')::date);

-- Consultas del agente: ventana por fabricacion con corte por deteccion.
CREATE INDEX defect_event_detected_idx ON defect_event (plant_id, line_id, detected_on);
CREATE INDEX defect_event_applicator_idx
    ON defect_event (plant_id, line_id, applicator_id, occurred_at)
    WHERE applicator_id IS NOT NULL;

ALTER TABLE maintenance_order
    ADD COLUMN status             text,
    ADD COLUMN reschedule_reason  text,
    ADD COLUMN cycles_at_event    integer;

UPDATE maintenance_order
   SET status = CASE WHEN completed_at IS NOT NULL THEN 'completada' ELSE 'pendiente' END;

ALTER TABLE maintenance_order
    ALTER COLUMN status SET NOT NULL,
    ADD CONSTRAINT maintenance_order_status_ck
        CHECK (status IN ('completada', 'reprogramada', 'pendiente')),
    ADD CONSTRAINT maintenance_order_done_ck
        CHECK ((status = 'completada') = (completed_at IS NOT NULL)),
    ADD CONSTRAINT maintenance_order_cycles_ck
        CHECK (cycles_at_event IS NULL OR cycles_at_event >= 0);

CREATE INDEX maintenance_order_equipment_idx ON maintenance_order (plant_id, line_id, equipment, due_date);
