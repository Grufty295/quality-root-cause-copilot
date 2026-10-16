-- 0011: mediciones de crimpado (altura y fuerza de tracción) por aplicador y turno.
--
-- Una fila por aplicador, dia, turno y combinacion terminal/cable. Los limites van
-- en la fila (la especificacion puede cambiar de revision). height_ok y pull_ok se
-- calculan, no se capturan: la carga verifica ademas que coincidan con los
-- resultados del CSV, asi un dato incoherente no entra.
--
-- Valen desde measured_on (la medicion se conoce el mismo dia); el corte as_of del
-- agente filtra por esa fecha.

CREATE TABLE crimp_measurement (
    plant_id              text NOT NULL,
    equipment_id          text NOT NULL,
    measured_on           date NOT NULL,
    shift                 smallint NOT NULL CHECK (shift BETWEEN 1 AND 3),
    terminal_part_number  text NOT NULL,
    cable_part_number     text NOT NULL,
    line_id               text NOT NULL,
    press_id              text NOT NULL,
    height_mm             numeric(6,3) NOT NULL CHECK (height_mm > 0),
    height_lsl            numeric(6,3) NOT NULL,
    height_usl            numeric(6,3) NOT NULL,
    pull_n                numeric(7,1) NOT NULL CHECK (pull_n >= 0),
    pull_min_n            numeric(7,1) NOT NULL CHECK (pull_min_n > 0),
    action                text,
    height_ok             boolean GENERATED ALWAYS AS (height_mm BETWEEN height_lsl AND height_usl) STORED,
    pull_ok               boolean GENERATED ALWAYS AS (pull_n >= pull_min_n) STORED,
    PRIMARY KEY (plant_id, equipment_id, measured_on, shift, terminal_part_number, cable_part_number),
    CHECK (height_lsl < height_usl),
    FOREIGN KEY (plant_id, equipment_id) REFERENCES equipment (plant_id, id),
    FOREIGN KEY (plant_id, press_id) REFERENCES equipment (plant_id, id),
    FOREIGN KEY (plant_id, line_id) REFERENCES line (plant_id, id)
);
CREATE INDEX crimp_measurement_line_idx ON crimp_measurement (plant_id, line_id, measured_on);
