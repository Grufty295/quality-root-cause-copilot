---
doc_id: WI-TST-006
tipo: INSTRUCCION_TRABAJO
titulo: Prueba eléctrica de arneses
revision: F
fecha: 2025-12-01
lineas: [L1, L2]
clientes: []
confidencialidad: interno
contiene_pii: false
---

# WI-TST-006 — Prueba eléctrica

**Estaciones:** TST-L1, TST-L2. **Referencias:** CP-ARN-PD-001, AMEF-ARN-PD-001 (RC-19).

## 1. Objetivo

Verificar al 100% la continuidad, la ausencia de circuitos abiertos y cruzados, y el mapa de pines de cada arnés.

## 2. Preparación

1. Seleccionar el programa de prueba de la variante en el probador.
2. Verificar el adaptador (*fixture*) con el arnés patrón al inicio del turno.
3. Confirmar en pantalla la revisión del programa de prueba.

## 3. Secuencia

1. Conectar todos los conectores del arnés al adaptador.
2. Ejecutar el programa.
3. Si el resultado es "Pasa", colocar la etiqueta de prueba y enviar a inspección final.
4. Si es "Falla", imprimir el reporte, identificar el circuito y enviar a retrabajo autorizado.

## 4. Alcance de la prueba

- Detecta: circuitos abiertos, circuitos cruzados, terminal en cavidad equivocada según el programa cargado, resistencia por encima del umbral del programa.
- La prueba se ejecuta con el arnés en reposo.

## 5. Control del programa de prueba

- Los programas de prueba los administra ingeniería de pruebas.
- Cada programa tiene una revisión visible en pantalla. Ingeniería de pruebas actualiza el programa cuando recibe la notificación del cambio de ingeniería correspondiente.
