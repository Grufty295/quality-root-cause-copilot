-- 0008: por que una NCR quedo en cierto nivel.
--
-- Guarda los *tipos* de hallazgo del clasificador ('cliente:confidencial',
-- 'parte_desconocida', 'pii:persona', ...), nunca el valor encontrado. Sirve para
-- mostrar en la traza por que se eligio el modelo y para auditar el clasificador.
--
-- NULL en las NCR anteriores: no se clasificaron con estas reglas.

ALTER TABLE ncr ADD COLUMN classification_reasons text[];
