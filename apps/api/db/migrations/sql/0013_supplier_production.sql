-- 0013: catalogo de proveedores y produccion.
--
-- supplier: catalogo global (como customer y part). `supplies` son los numeros de parte
-- que suministra; la carga verifica que cada lote sea de una parte que su proveedor
-- suministra. material_lot deja de guardar el nombre y referencia al proveedor.
-- Los lotes cargados con 0012 conservan su proveedor: se crea desde ellos y el
-- siguiente seed completa categoria y partes.
--
-- production: unidades terminadas (arneses) por dia, turno, linea y numero de parte
-- de cliente (cada numero de parte es una variante). Es el denominador de las tasas de
-- defecto: defect_event.quantity cuenta piezas fabricadas ese dia, y la tasa se calcula
-- por fecha de fabricacion. Se conoce el mismo dia; el corte as_of filtra por produced_on.

CREATE TABLE supplier (
    id        text PRIMARY KEY,
    name      text NOT NULL UNIQUE,
    category  text,
    supplies  text[] NOT NULL DEFAULT '{}'
);

INSERT INTO supplier (id, name, supplies)
SELECT supplier_id, min(supplier_name), array_agg(DISTINCT part_number ORDER BY part_number)
FROM material_lot GROUP BY supplier_id;

ALTER TABLE material_lot
    ADD FOREIGN KEY (supplier_id) REFERENCES supplier (id),
    DROP COLUMN supplier_name;

CREATE TABLE production (
    plant_id     text NOT NULL,
    produced_on  date NOT NULL,
    shift        smallint NOT NULL CHECK (shift BETWEEN 1 AND 3),
    line_id      text NOT NULL,
    part_id      text NOT NULL REFERENCES part (id),
    units        integer NOT NULL CHECK (units > 0),
    PRIMARY KEY (plant_id, produced_on, shift, line_id, part_id),
    FOREIGN KEY (plant_id, line_id) REFERENCES line (plant_id, id)
);
CREATE INDEX production_line_idx ON production (plant_id, line_id, produced_on);
