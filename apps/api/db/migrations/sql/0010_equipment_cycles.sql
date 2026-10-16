-- 0010: catalogo de equipos y ciclos diarios de los aplicadores.
--
-- La llave de equipment es (plant_id, id): "APL-L1-01" existe en cada planta.
-- pm_threshold_cycles es el umbral de mantenimiento preventivo, solo para
-- aplicadores. Los ciclos se reinician con cada servicio completado; ver
-- docs/datos-operativos.md para la regla de calculo.
--
-- defect_event.applicator_id y maintenance_order.equipment siguen siendo texto
-- sin FK: la carga los valida contra este catalogo, y asi las pruebas y las
-- capturas a mano no dependen de que el catalogo exista.

CREATE TABLE equipment (
    plant_id              text NOT NULL REFERENCES plant(id),
    id                    text NOT NULL,
    line_id               text NOT NULL,
    kind                  text NOT NULL,
    terminal_family       text,
    terminal_part_number  text,
    housed_in             text,
    pm_threshold_cycles   integer CHECK (pm_threshold_cycles IS NULL OR pm_threshold_cycles > 0),
    PRIMARY KEY (plant_id, id),
    FOREIGN KEY (plant_id, line_id) REFERENCES line (plant_id, id)
);
CREATE INDEX equipment_line_idx ON equipment (plant_id, line_id);

CREATE TABLE applicator_cycles (
    plant_id      text NOT NULL,
    equipment_id  text NOT NULL,
    day           date NOT NULL,
    cycles        integer NOT NULL CHECK (cycles >= 0),
    PRIMARY KEY (plant_id, equipment_id, day),
    FOREIGN KEY (plant_id, equipment_id) REFERENCES equipment (plant_id, id)
);
