---
doc_id: WI-CRP-002
tipo: INSTRUCCION_TRABAJO
titulo: Crimpado de terminales — operación y verificaciones
revision: D
fecha: 2025-11-03
lineas: [L1, L2]
clientes: []
confidencialidad: interno
contiene_pii: false
---

# WI-CRP-002 — Crimpado de terminales

**Estaciones:** prensas PRS-L1-01, PRS-L1-02, PRS-L2-01, PRS-L2-02. **Referencias:** SPEC-CRP-001, CP-ARN-PD-001, AMEF-ARN-PD-001 (RC-01, RC-06, RC-07, RC-20).

## 1. Objetivo

Crimpar terminales al conductor cumpliendo altura de crimpado y fuerza de tracción.

## 2. Equipo

- Prensa de crimpado con aplicador identificado (APL-Lx-01 a APL-Lx-04).
- Aplicadores 01 y 02: familia de terminal A (TRM-A-1064). Aplicadores 03 y 04: familia B (TRM-B-2150).
- Micrómetro de crimpado con calibración vigente.
- Probador de tracción.

## 3. Operación

1. Verificar que el aplicador montado corresponda al terminal de la orden.
2. Insertar el cable desforrado hasta el tope del aplicador.
3. Accionar la prensa con un solo ciclo.
4. Revisar visualmente el crimpado: hebras dentro del barril, aislamiento dentro de su barril, sin rebaba visible.

## 4. Verificaciones del operador

| Verificación | Frecuencia | Criterio |
|---|---|---|
| Altura de crimpado | Al inicio de turno y después de cada cambio de aplicador | Dentro de los límites de SPEC-CRP-001 |
| Fuerza de tracción | 1 pieza por turno por aplicador | Mayor o igual al mínimo de SPEC-CRP-001 |

Registrar cada lectura en la hoja de verificación de crimpado con fecha, turno y aplicador.

## 5. Reacción ante no conformidad

- Altura fuera de límites: re-medir la misma pieza. Si la segunda lectura está dentro de límites, continuar. Si persiste fuera, detener la prensa y avisar a mantenimiento.
- Tracción bajo el mínimo: repetir la prueba con una nueva muestra. Si la segunda muestra cumple, continuar. Si falla, detener la prensa, contener la producción desde la última verificación conforme y avisar a calidad.

## 6. Notas

- Las hojas de verificación llenas se entregan al líder de línea al final del turno y se archivan semanalmente en calidad.
- El mantenimiento preventivo de aplicadores se rige por SOP-MNT-008.

## Historial

| Rev | Fecha | Cambio |
|---|---|---|
| C | 2025-02-14 | Se separan los aplicadores por familia de terminal |
| D | 2025-11-03 | Se agrega re-medición antes de detener la prensa |
