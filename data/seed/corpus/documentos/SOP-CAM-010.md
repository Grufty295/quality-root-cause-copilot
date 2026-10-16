---
doc_id: SOP-CAM-010
tipo: SOP
titulo: Control de cambios de ingeniería (ECN)
revision: C
fecha: 2025-10-13
lineas: [L1, L2]
clientes: []
confidencialidad: interno
contiene_pii: false
---

# SOP-CAM-010 — Control de cambios de ingeniería

**Responsable:** ingeniería de producto. **Referencias:** WI-BRD-005, WI-TST-006, AMEF-ARN-PD-001 (RC-05, RC-14).

## 1. Alcance

Cambios de dibujo, lista de materiales o ruteo solicitados por el cliente o por ingeniería interna.

## 2. Flujo

1. Ingeniería de producto recibe el cambio del cliente y emite el ECN con número, variante afectada y fecha efectiva.
2. Ingeniería de manufactura actualiza plantillas de tablero y ayudas visuales antes de la fecha efectiva.
3. Planeación define el punto de corte (último lote con revisión anterior).
4. Calidad actualiza el plan de control y el AMEF si aplica.
5. Ingeniería de pruebas actualiza el programa de prueba eléctrica, si aplica.
6. Ingeniería de producto cierra el ECN cuando recibe la confirmación de los pasos 2 a 5.

## 3. Registro

Cada ECN se registra en el log de cambios con fecha efectiva y el estado de implementación por área.

## 4. Responsabilidades

| Actividad | Responsable |
|---|---|
| Emisión del ECN | Ingeniería de producto |
| Plantillas y ayudas visuales | Ingeniería de manufactura |
| Programa de prueba | Ingeniería de pruebas |
| Plan de control y AMEF | Ingeniería de calidad |
| Liberación a producción en fecha efectiva | Planeación |
