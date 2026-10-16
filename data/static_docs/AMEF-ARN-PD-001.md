---
doc_id: AMEF-ARN-PD-001
tipo: AMEF
titulo: AMEF de proceso — Familia de arneses de puerta delantera
revision: F
fecha: 2026-03-15
lineas: [L1, L2]
clientes: []
confidencialidad: interno
contiene_pii: false
---

# AMEF de proceso (PFMEA) — Familia de arneses de puerta delantera

**Planta:** Cablenova México, planta Juárez
**Alcance:** corte y desforre, crimpado, inserción y TPA, ensamble en tablero, prueba eléctrica, inspección final y empaque de las variantes Base, Media y Alta, líneas L1 y L2.
**Equipo:** Ingeniería de calidad, ingeniería de proceso, mantenimiento, producción.
**Nota:** los valores de Severidad (S), Ocurrencia (O), Detección (D) y la Prioridad de Acción (AP) son ilustrativos. La AP se asigna conforme a la tabla AIAG-VDA aplicable; esta copia no reproduce dicha tabla.

Cada fila tiene un código de causa (RC-xx). El procedimiento SOP-QA-011 exige que el D4 de todo 8D referencie la fila del AMEF que corresponde a la causa de ocurrencia, o que se agregue una fila nueva.

## Cadenas de falla

| Código | Paso de proceso | Función | Modo de falla | Efecto | Causa | Control de prevención | Control de detección | S | O | D | AP |
|---|---|---|---|---|---|---|---|---|---|---|---|
| RC-01 | Crimpado | Unir terminal y conductor conforme a altura de crimpado y fuerza de tracción | Altura de crimpado con deriva hacia el límite superior; fuerza de tracción baja | Alta resistencia, falso contacto intermitente en vehículo | Desgaste de punzón y yunque del aplicador por operar más ciclos de los establecidos sin mantenimiento preventivo | PM de aplicador cada 250,000 ciclos o 4 semanas (SOP-MNT-008) | Altura de crimpado al inicio de turno y tras cambio de aplicador; tracción 1 por turno (WI-CRP-002) | 8 | 3 | 5 | H |
| RC-02 | Inserción (material) | Retener la terminal en la cavidad con la lanza primaria | Terminal se retrae o sale del conector (*back-out*) | Circuito abierto o intermitente en vehículo | Terminal con lanza de retención deformada desde el proceso de estampado del proveedor | Certificado de calidad del proveedor; proveedor categoría A | Inspección de recibo por certificado (SOP-REC-009); prueba de jalón en inspección final por muestreo | 8 | 2 | 6 | H |
| RC-03 | Inserción y TPA | Asentar la terminal y enganchar la retención secundaria (TPA) | Terminal no asentada; TPA en posición de preensamble | Circuito abierto, intermitencia o *back-out* en cliente | Método de inserción sin verificación de empuje-jalón; TPA verificada solo visualmente | Instrucción de trabajo WI-INS-004; inducción de operadores | Verificación visual de TPA; prueba eléctrica de continuidad | 8 | 3 | 6 | H |
| RC-04 | Corte y desforre | Exponer el conductor a la longitud especificada | Longitud de desforre menor a especificación; aislamiento atrapado en barril conductor | Alta resistencia, circuito abierto | Receta de corte cargada con parámetros de una revisión obsoleta de la hoja de parámetros | Control de recetas en controlador de máquina; WI-CUT-001 | Primer artículo al arranque y tras cambio de receta; corte transversal semanal | 8 | 2 | 5 | H |
| RC-05 | Ensamble en tablero | Rutear cada ramal según el dibujo vigente | Ramal ruteado por trayectoria anterior; conector fuera de posición | Conector no alcanza su punto de montaje; función incorrecta en vehículo | Cambio de ingeniería liberado sin actualizar plantilla de tablero ni ayudas visuales | Control de cambios SOP-CAM-010 | Prueba eléctrica de continuidad; inspección final visual | 7 | 2 | 7 | M |
| RC-06 | Crimpado | Crimpar con el aplicador correspondiente al terminal | Geometría de crimpado no conforme | Crimpado débil, rechazo en auditoría | Aplicador equivocado montado en la prensa | Identificación de aplicador por código; WI-CRP-003 | Primer artículo tras cambio de aplicador | 7 | 2 | 3 | M |
| RC-07 | Crimpado | Ajustar altura de cierre (*shut height*) en setup | Altura de crimpado bajo el límite inferior (sobrecrimpado) | Hebras cortadas, fatiga y ruptura por vibración | Altura de cierre mal ajustada durante el setup | WI-CRP-003 | Primer artículo; altura al inicio de turno | 8 | 2 | 3 | M |
| RC-08 | Corte y desforre | Desforrar sin dañar hebras | Hebras cortadas o rayadas | Sección conductora reducida, ruptura | Cuchilla de desforre desgastada | Cambio de cuchilla por contador | Inspección visual de primer artículo | 7 | 3 | 5 | M |
| RC-09 | Corte y desforre | Desforrar completamente el aislamiento | Desforre incompleto | Hebras no atrapadas, crimpado débil | Variación de diámetro de aislamiento en lote de cable | Certificado del proveedor de cable | Primer artículo | 6 | 2 | 5 | L |
| RC-10 | Inserción | Insertar cada terminal en su cavidad | Terminal en cavidad equivocada | Función cruzada, posible daño a módulo | Ayuda visual con mapa de cavidades incorrecto | Ayudas visuales controladas | Prueba eléctrica de continuidad y mapa de pines | 8 | 2 | 2 | M |
| RC-11 | Retrabajo | Retirar terminal sin dañar cavidad | Cavidad o housing dañado | Retención deficiente, ingreso de humedad | Herramienta de extracción incorrecta durante retrabajo | Retrabajo solo por personal certificado | Inspección de retrabajo | 7 | 2 | 5 | M |
| RC-12 | Encintado | Proteger y agrupar ramales con cinta | Cinta desprendida o traslape insuficiente | Ruido, abrasión | Lote de cinta con adhesión baja | Certificado del proveedor de cinta | Inspección final visual | 5 | 2 | 5 | L |
| RC-13 | Encintado | Aplicar cinta con traslape y tensión especificados | Encintado flojo o irregular | Ruido, abrasión | Técnica de encintado inconsistente | Instrucción de trabajo y certificación de operador | Inspección final visual | 5 | 3 | 5 | L |
| RC-14 | Empaque | Identificar el arnés con la etiqueta correcta | Etiqueta con número de parte o revisión incorrecta | Mezcla de producto en cliente | Plantilla de etiqueta obsoleta en impresora | Control de plantillas por ingeniería | Escaneo de etiqueta en empaque | 6 | 2 | 4 | M |
| RC-15 | Ensamble en tablero | Rutear sin dañar aislamiento | Aislamiento raspado o cortado | Corto a tierra, fuga | Guía o soporte del tablero con borde filoso por desgaste | Revisión de tableros por mantenimiento | Inspección final visual | 8 | 2 | 6 | H |
| RC-16 | Ensamble en tablero | Formar ramales a la longitud especificada | Longitud de ramal fuera de especificación | Tensión en conector o dificultad de montaje | Plantilla de tablero movida o desgastada | Verificación de tablero al inicio de turno | Inspección final con calibrador de longitud | 6 | 2 | 4 | M |
| RC-17 | Ensamble en tablero | Colocar todos los clips y abrazaderas | Clip faltante | Vibración, ruido, abrasión | Omisión sin conteo ni verificación | Ayudas visuales | Inspección final visual | 6 | 3 | 6 | M |
| RC-18 | Almacenamiento | Mantener terminales limpias | Terminal contaminada (aceite, polvo) | Alta resistencia | Empaque abierto o almacenamiento sin protección | Almacenamiento cerrado FIFO | Ninguno específico | 7 | 1 | 7 | M |
| RC-19 | Prueba eléctrica | Detectar circuitos abiertos y cruzados | Escape o rechazo falso | Producto no conforme liberado | Adaptador (*fixture*) de prueba con pines desgastados | Mantenimiento de adaptadores | Verificación diaria con arnés patrón | 8 | 2 | 4 | M |
| RC-20 | Medición | Medir altura de crimpado con exactitud | Lecturas sesgadas | Producto no conforme aceptado | Micrómetro de crimpado sin calibración vigente | Programa de calibración | Verificación con patrón al inicio de turno | 7 | 1 | 5 | M |

## Historial de revisiones

| Revisión | Fecha | Cambio |
|---|---|---|
| E | 2025-11-20 | Se agregan filas RC-18 a RC-20 |
| F | 2026-03-15 | Revisión anual; sin cambios en controles de detección |
