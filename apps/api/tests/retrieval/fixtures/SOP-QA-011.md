---
doc_id: SOP-QA-011
tipo: SOP
titulo: Manejo de no conformidades y solución de problemas 8D
revision: E
fecha: 2026-01-12
lineas: [L1, L2]
clientes: []
confidencialidad: interno
contiene_pii: false
---

# SOP-QA-011 — Manejo de no conformidades y 8D

**Responsable:** gerente de calidad. **Referencias:** AMEF-ARN-PD-001, CP-ARN-PD-001.

## 1. Apertura de NCR

1. Quien detecta el defecto registra la NCR con línea, turno, estación, número de parte, código de defecto, cantidad y descripción.
2. Calidad define la contención inmediata y la disposición del material (retrabajo, desecho, uso con desviación).

## 2. Criterios para abrir un 8D

Se abre 8D cuando ocurre cualquiera de estas condiciones:

- Reclamo de cliente.
- Defecto repetido: 3 o más NCRs del mismo código de defecto en la misma línea en 30 días.
- Defecto de severidad 8 o mayor según el AMEF.

## 3. Contenido del 8D

| Disciplina | Requisito mínimo |
|---|---|
| D2 | Descripción con 5W2H y tabla Es / No es, con cantidades y fechas |
| D3 | Contención con cantidades y verificación de efectividad |
| D4 | Causa de ocurrencia y causa de no detección, ambas verificadas con datos. La causa de ocurrencia referencia la fila del AMEF (RC-xx). La causa de no detección se clasifica con el catálogo de la sección 4 |
| D5–D6 | Acciones permanentes con evidencia de implementación |
| D7 | Actualización de AMEF, plan de control e instrucciones; despliegue horizontal a líneas y productos similares |
| D8 | Cierre con criterio de salida definido |

**Prohibido:** declarar "error del operador" como causa raíz. Cuando intervenga una persona, el análisis debe explicar qué permitió el error en el sistema (método, instrucción, capacitación, diseño a prueba de error).

## 4. Catálogo de categorías de no detección

| Código | Categoría |
|---|---|
| ND-01 | Frecuencia o método de medición en proceso insuficiente para detectar una deriva gradual; sin reglas de tendencia |
| ND-02 | Inspección de recibo sin medición (aceptación por certificado) |
| ND-03 | Verificación en estación solo visual; sin prueba física de asentamiento o retención |
| ND-04 | Verificación de primer artículo contra referencia o revisión incorrecta |
| ND-05 | Cambio de ingeniería no reflejado en el control de detección (programa de prueba o criterio de inspección) |
| ND-06 | No existe control de detección para el modo de falla |
| ND-07 | La prueba eléctrica estática no detecta el modo de falla (intermitencia o crimpado débil) |
| ND-08 | Control de detección existente pero no ejecutado conforme a la instrucción |

## 5. Tiempos de respuesta internos

- Contención: 24 horas desde la apertura.
- D4 verificado: 10 días hábiles.
- Cierre: 60 días naturales, salvo acuerdo con el cliente.
