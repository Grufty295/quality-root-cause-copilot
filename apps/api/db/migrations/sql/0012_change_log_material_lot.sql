-- 0012: bitacora de cambios y lotes de material.
--
-- change_log: un cambio de proceso, receta, herramienta, plantilla, mano de obra o ECN.
-- Un cambio puede tocar varias lineas y varios equipos (p. ej. un ECN en ambas lineas),
-- por eso son arreglos y no FK; la carga los valida contra el catalogo de equipos.
-- board_updated y test_program_updated conservan el texto de la planta ("Si", "No",
-- "No (plantillas en fabricacion)"): la diferencia entre "No" y vacio es informacion.
--
-- material_lot: lote de terminal recibido, con su inspeccion de recibo y la ventana en
-- que se consumio. Un lote lo consumen ambas lineas, por eso no tiene line_id.
-- supplier_* se guardan tal cual vienen: aun no hay tabla de proveedores.
-- defect_event.terminal_lot sigue siendo texto: la carga valida que exista y coincida,
-- sin FK, para no atar el orden ni el reemplazo de los dos CSV.
--
-- Ambas tablas se conocen desde su fecha (changed_on, received_on); el corte as_of del
-- agente filtra por ellas. El estado final de un lote (status) y su ultimo dia de consumo
-- no se conocen antes de consumed_to.

CREATE TABLE change_log (
    plant_id             text NOT NULL REFERENCES plant (id),
    id                   text NOT NULL,
    changed_on           date NOT NULL,
    kind                 text NOT NULL,
    equipment_ids        text[] NOT NULL DEFAULT '{}',
    part_number          text,
    variant              text,
    line_ids             text[] NOT NULL CHECK (cardinality(line_ids) > 0),
    previous_revision    text,
    new_revision         text,
    description          text NOT NULL,
    board_updated        text,
    test_program_updated text,
    approved_by_role     text NOT NULL,
    PRIMARY KEY (plant_id, id),
    CHECK ((previous_revision IS NULL) = (new_revision IS NULL))
);
CREATE INDEX change_log_date_idx ON change_log (plant_id, changed_on);

CREATE TABLE material_lot (
    plant_id          text NOT NULL REFERENCES plant (id),
    id                text NOT NULL,
    part_number       text NOT NULL,
    family            text NOT NULL,
    supplier_id       text NOT NULL,
    supplier_name     text NOT NULL,
    received_on       date NOT NULL,
    quantity          integer NOT NULL CHECK (quantity > 0),
    inspection_type   text NOT NULL,
    inspection_result text NOT NULL,
    consumed_from     date NOT NULL,
    consumed_to       date NOT NULL,
    status            text NOT NULL,
    PRIMARY KEY (plant_id, id),
    CHECK (received_on <= consumed_from AND consumed_from <= consumed_to)
);
CREATE INDEX material_lot_window_idx ON material_lot (plant_id, part_number, consumed_from);
