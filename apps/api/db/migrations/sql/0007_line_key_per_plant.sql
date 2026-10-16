-- 0007: la llave de line es (plant_id, id), no id solo.
--
-- Dos plantas reales repiten nombres de linea ("L1"). Con id como llave unica
-- global la segunda planta tenia que inventar nombres (L1B) y los datos de una
-- planta podian chocar con los de otra.
--
-- Todas las FK a line ya eran compuestas (plant_id, line_id) -> line (plant_id, id),
-- asi que ninguna depende de line_pkey y los datos existentes siguen validos:
-- si id era unico, (plant_id, id) tambien.
--
-- line_plant_uk se conserva: las FK compuestas estan ligadas a ese indice y
-- quitarlo exigiria recrearlas. Queda redundante con la nueva llave primaria.

ALTER TABLE line DROP CONSTRAINT line_pkey;
ALTER TABLE line ADD PRIMARY KEY (plant_id, id);
