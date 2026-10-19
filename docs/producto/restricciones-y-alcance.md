# Restricciones del contexto y límites de los requisitos

Sistema para una planta manufacturera en México (arneses, Ciudad Juárez). Este documento dice qué restricciones reales
moldean los requisitos y dónde se recorta a propósito. **Las celdas marcadas SUPUESTO no son medidas: son el escenario
sobre el que se dimensionan las pruebas. Se confirman o se corrigen; los umbrales de abajo dependen de ellas.**

## 1. Escenario de dimensionamiento

| Variable | Valor | Estado | Por qué importa |
|---|---|---|---|
| Sitios | 1 planta | SUPUESTO | Sin multi-región ni réplica; el canary entre instancias no aplica |
| Usuarios | Dataset: 2 ingenieros de calidad, 1 gerente, 1 auditor, 1 inspector por línea. Escenario de escala: 5 ingenieros | HECHO (dataset) / SUPUESTO (escala) | Solo los ingenieros ejecutan el agente |
| Volumen | Dataset: 80 NCR en 183 días en 2 líneas = **0.44 por día**. Escenario de escala ×10 (≈ 4–5 por día) | HECHO (dataset) / SUPUESTO (×10) | Define la carga y el costo mensual |
| Concurrencia | Ley de Little: λ·W = (5 corridas/día ÷ 28 800 s de turno) × 130 s ≈ 0.02 corridas simultáneas en promedio. El caso de diseño es una ráfaga: los 5 ingenieros pulsan "analizar" a la vez | DERIVADO | La prueba de carga se ancla en la ráfaga (5), no en el promedio |
| Turnos | 3 turnos, planta continua de lunes a sábado | SUPUESTO | Ventana de mantenimiento: cambio de turno o domingo |
| Equipo de TI | Sin equipo de plataforma dedicado; un servidor con Docker Compose | SUPUESTO | Nada que exija operar Kubernetes, un secret manager gestionado o un clúster |
| Salida a internet | Restringida por TI; la API externa puede no estar disponible | SUPUESTO | La degradación sin modelo es un requisito, no un extra |
| Modelo local | Hoy simulado con OpenRouter | HECHO | La garantía "lo confidencial no sale" no se cumple en el entorno de pruebas |

## 2. Restricciones reales y qué requisito producen

| Restricción | Requisito resultante | Límite aceptado | Evidencia |
|---|---|---|---|
| Acuerdos con el OEM y requisitos específicos del cliente: su información no sale de la planta | Router por nivel; confidencial solo a modelo local; restricción también en la base. **Supuesto de diseño: caso estricto** (no sale de la planta); el caso "proveedor aprobado" está documentado como alternativa en el ADR 0012 y no construido | El modelo local real no está desplegado; el eval corre simulado | ADR 0002, `audit_log` CHECK, T-modelo de amenazas |
| Datos personales de operadores (LFPDPPP; verificar el texto vigente con quien corresponda) | Seudonimización antes de cualquier modelo; auditoría sin contenido | La purga de `pseudonym_map` no está implementada; un nombre sin rol ni etiqueta no se detecta | `pii.py`, modelo de amenazas |
| Trazabilidad de registros de calidad (IATF 16949) | Versiones inmutables, auditoría solo-inserción con cadena de hash, aprobación por rol | Sin ancla externa de la cabeza de la cadena | ADR 0005, 0006 |
| El 8D es un trabajo de horas, no una pantalla interactiva | El análisis es asíncrono; **la latencia no es un SLO de experiencia**, es de capacidad | p95 medido ~130 s solo D4; `/analyze` completo sin medir | Eval dev-v6 |
| La herramienta no está en la ruta crítica de producción | Si cae, se trabaja como hoy (hoja y Excel). SLO de disponibilidad modesto, solo en turnos | No se persigue 99.9 %: el costo de las nueves no se justifica aquí | Sección 4 |
| Presupuesto de un proyecto pequeño | Costo por corrida visible y con tope | ≈ US$0.007 por corrida; sin cuota por usuario todavía | FinOps (pendiente) |
| Un solo servidor | Despliegue en ventana, humo posterior y retroceso por tag de imagen | **No hay canary ni rollback automático**; el retroceso es manual con criterio escrito | Runbook |
| Documentos y vocabulario en español de planta | Embeddings multilingües, golden set en español | Solo datos sintéticos; sin corpus real | `data/` |

## 3. Fuera de alcance, con razón

- Cerrar un 8D sin ingeniero: el sistema propone, una persona aprueba.
- Integración con MES, ERP o QMS reales: sin acceso y sin necesidad para demostrar el flujo.
- Alta disponibilidad multi-nodo y autoscaling horizontal: con 5 usuarios concurrentes sería ingeniería sin demanda.
  La prueba de carga mide el punto de saturación de **una** instancia y lo compara con la demanda esperada.
- Fotos, planos y video.

## 4. Cómo cada límite se vuelve una verificación

| Límite | Verificación | Umbral propuesto (SUPUESTO hasta confirmar) |
|---|---|---|
| Capacidad | Locust/k6 sobre `/analyze` con modelo simulado de latencia fija y con el real | Sostener 3× la ráfaga de diseño (15 corridas simultáneas) sin errores; reportar el punto donde se satura |
| Latencia | p95 de `/analyze` completo | ≤ 180 s; sobre eso, el análisis pasa a segundo plano con estado visible |
| Disponibilidad | Chequeo de `/health` en horario de turnos | ≥ 99 % semanal en turnos |
| Calidad | Gates sobre el reporte congelado | Los de `app.evalkit.gates`; sin dato no se aprueba |
| Costo | Costo por corrida en p50/p95 y total mensual | p95 ≤ US$0.02 por corrida; alerta al 80 % del tope mensual |
| Degradación | Con el proveedor caído, la API devuelve el libro de evidencia sin borrador | Prueba automatizada: `sin_borrador`, nunca error 500 |

## 5. Lo que es deuda, no restricción

Para no usar el contexto como excusa: la falta de límite de tasa, de secret manager, de purga de `pseudonym_map`, de
fallback de modelo y de una corrida de los 10 adversariales con el modelo real no vienen de la planta. Son trabajo
pendiente y están en el modelo de amenazas y en el PRD con ese nombre.
