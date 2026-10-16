# Cambios al PRD por el rol inspector

Cada punto dice dónde y qué reemplazar. Va como lista y no como PRD reescrito para no tocar los diagramas incrustados.

1. **Usuarios y flujo principal, párrafo inicial.** "El usuario principal es el ingeniero de calidad; el gerente de calidad y el auditor consumen la trazabilidad." →
   "El usuario principal es el ingeniero de calidad. El inspector reporta desde el piso, el gerente aprueba y el auditor consume la trazabilidad."
2. **Tabla de usuarios.** Agregar al inicio: `Inspector | Reportar lo que ve en el piso y seguir lo que el análisis concluye | Abrir NCRs, leer borradores en solo lectura`.
   Fila del gerente: necesidad "Aprobar con criterio y saber que no se repiten causas conocidas"; usa "Aprobación, historial de 8Ds y casos similares".
3. **Flujo, paso 1.** "El ingeniero registra la no conformidad…" → "El inspector (o el ingeniero) registra la no conformidad…".
4. **Flujo, paso 6.** "El ingeniero aprueba, edita o rechaza cada sección; si rechaza…" →
   "El ingeniero edita cada sección. El ingeniero o el gerente pueden rechazarla con retroalimentación; entonces el ingeniero corrige o el agente regenera. El gerente aprueba."
5. **RF-11.** "(ingeniero, gerente, auditor)" → "(inspector, ingeniero, gerente, auditor)".
6. **RBAC, en Mecanismos.** "tres roles (ingeniero de calidad, gerente, auditor)" → "cuatro roles (inspector, ingeniero de calidad, gerente, auditor)". Mantener "Quien redacta un 8D no puede aprobarlo".
7. **Resumen ejecutivo.** "El ingeniero de calidad revisa y aprueba" → "El ingeniero de calidad revisa y edita; el gerente aprueba".
8. **Contexto y supuestos, fila "Usuario principal".** Sin cambio de fondo; opcional: "…que gestiona los 8D; el inspector los abre desde el piso".
9. **Compliance, "Matriz de roles y permisos".** Remitir a `docs/matriz-roles.md`.
10. **No-objetivos.** Agregar: "Gestionar los planes de calidad que diseña el ingeniero" y "Comentarios o chat entre inspector e ingeniero dentro del sistema".
11. **Entregable local, usuarios de demo.** "uno por rol y planta" → "dos inspectores (L1 y L2), dos ingenieros, un gerente, un auditor y un ingeniero de otra planta (JRZ2) para la demo de aislamiento".
12. **Guion de la demo.**
    - Paso 1: "Un inspector de la línea 2 abre una NCR…".
    - Paso 5: "El ingeniero edita una causa. El gerente la aprueba; la versión queda guardada con su traza."
    - Paso nuevo tras el 4: "El inspector abre el borrador en solo lectura."
    - Con esto la demo cambia de usuario varias veces; si el tiempo aprieta, el ingeniero también puede abrir la NCR.
13. **MVP, fila "Acceso".** "Usuarios simulados por rol y línea (L1, L2)" → "Usuarios simulados por rol (4) y línea (L1, L2)".
