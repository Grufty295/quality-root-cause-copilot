# Fase A — Mapa del flujo y roles del agente y revisión humana

## 1. Máquina de estados de una sección (D2 / D4) y el botón "Correr análisis"
- **Estados posibles de una sección (`section_version.kind`)**:
  - `borrador`: Creado automáticamente por el agente al correr el análisis por primera vez.
  - `edicion`: Modificado manualmente por un ingeniero.
  - `rechazo`: Devuelto por el gerente (o ingeniero) con retroalimentación y un motivo tipificado (`feedback_reason`).
  - `aprobacion`: Aprobado formalmente por el gerente (estado final, inalterable por triggers de base de datos).
- **Quiénes y con qué endpoints transicionan**:
  - `POST /ncrs/{id}/analyze`: El agente lee el estado previo. Si no hay sección o la última es `rechazo`, genera un nuevo borrador. Si hay borrador sin revisar u otro estado activo, respeta la regla de no sobrescribir sin rechazo previo.
  - `POST /ncrs/{id}/sections/{discipline}/edit`: Ingeniero (`EDIT_ROLES = ("ingeniero",)`). Pasa a estado `edicion`.
  - `POST /ncrs/{id}/sections/{discipline}/reject`: Ingeniero o Gerente (`REJECT_ROLES = ("ingeniero", "gerente")`). Pasa a estado `rechazo` y exige retroalimentación de al menos 10 caracteres y motivo.
  - `POST /ncrs/{id}/sections/{discipline}/approve`: Gerente (`APPROVE_ROLES = ("gerente",)`). Pasa a estado `aprobacion`.
- **Callejones sin salida y comportamiento del botón "Correr análisis" (`POST /ncrs/{id}/analyze`)**:
  - *Callejón sin salida principal*: Si D2 ya está `aprobado`, es una sección final y no se regenera. Si D2 está `pendiente_aprobacion` o D4 tiene un borrador sin revisar, el servicio de análisis (`AnalysisService`) decide no sobrescribir ni re-correr automáticamente para evitar pisar trabajo humano pendiente de revisión.
  - *Qué hace hoy el botón "Correr análisis"*: Evalúa disciplina por disciplina. Si una disciplina no tiene borrador o su última versión es `rechazo` (contiene feedback), ejecuta la recolección de datos y la llamada al LLM para generar un nuevo borrador incrementando el `version_no`. Si la disciplina ya cuenta con un borrador activo o está aprobada, el análisis se salta esa sección (`skipped`).

## 2. Motivo de rechazo del gerente
- **Dónde se guarda**: En la tabla `section_version`, columna `feedback_reason` (así como el texto libre en `feedback`), asociado a la versión de tipo `rechazo`.
- **Si la UI lo muestra**: Actualmente la API expone `feedback` y el modelo de dominio incluye `feedback_reason`, pero en la implementación actual del frontend la visualización completa del motivo tipificado en la vista de la NCR puede requerir integración explícita (tarea pendiente en Fase B si no se muestra de forma dedicada).
- **Si entra al prompt en la regeneración**: Sí. `repository.prior_sections` extrae el `feedback` de la última versión rechazada y el grafo (`AgentGraph._run_tier`) lo inyecta como `prior.feedback` en el prompt correspondiente (`prompts.py: rectification / feedback`).

## 3. Edición humana y validación del servidor
- **Cómo se edita hoy**: A través de `POST /ncrs/{id}/sections/{discipline}/edit` enviando un objeto JSON en el cuerpo (`EditIn`) que contiene `based_on_version` y `content` (un diccionario libre).
- **Qué valida el servidor**:
  - Que el usuario tenga el rol autorizado (`ingeniero`).
  - Que el usuario tenga alcance sobre la planta y línea de la NCR.
  - Que la sección no esté aprobada (`kind != 'aprobacion'`).
  - Que la versión enviada coincida exactamente con la vigente (`based_on_version == latest.version_no`) mediante candado de fila (`FOR UPDATE`), previniendo condiciones de carrera.
  - `validate_content`: Valida que el JSON no esté vacío y que su tamaño serializado no supere 64 KB. No valida esquemas específicos de D2 o D4 a nivel estructural profundo (permite un diccionario JSON arbitrario).

## 4. Descripciones de NCR repetidas en la UI
- **Origen**: Las NCRs se muestran desde las **filas de la aplicación** en la tabla relacional `ncr` (abiertas por inspectores o ingenieros), y **no** provienen del corpus indexado de documentos de referencia (AMEF, SOP, etc.).
- **Por qué se ven repetidas**: Al generar datos sintéticos o inicializar la base con scripts de prueba (`seed`), pueden crearse múltiples registros en la tabla `ncr` con descripciones idénticas o plantillas muy similares. En la base analizada se observan varios casos de descripciones duplicadas correspondientes a corridas de prueba o escenarios repetidos del generador dev.

## 5. Matriz de usuarios por rol y planta/línea (Huecos)
| Rol | Planta | Líneas autorizadas | Estado / Hueco detectado |
|---|---|---|---|
| Inspector (`inspector`) | JRZ1 | L1, L2 | Cubierto para apertura en piso |
| Ingeniero (`ingeniero`) | JRZ1 | L1, L2, L3, L4 | Cubierto para análisis y edición |
| Gerente (`gerente`) | JRZ1 | L1, L2, L3, L4 | Cubierto para aprobación y rechazo |
| Auditor (`auditor`) | JRZ1 | Todas / Global | Cubierto para lectura y trazabilidad |
| *Hueco detectado* | JRZ2 (Planta Juárez 2) | L1, L2 | Faltaban credenciales preconfiguradas explícitas para demo en la segunda planta (JRZ2), requeridas para la Fase B (S1). |
