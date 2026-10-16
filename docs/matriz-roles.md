# Matriz de roles y permisos

Cuatro roles, todos con alcance por planta y línea (`user_scope`). El alcance acota *qué* datos ve cada rol; el rol acota *qué puede hacer* con ellos.

| Rol | Qué hace en la planta | Qué hace en el sistema |
|---|---|---|
| Inspector | Inspecciona y evalúa en el piso de producción | Abre NCRs. Lee los borradores del agente de su alcance, sin editarlos |
| Ingeniero de calidad | Analiza lo reportado y diseña y ajusta los planes de calidad | Abre NCRs, corre el agente, edita y rechaza secciones |
| Gerente de calidad | Nivel administrativo del departamento | Aprueba secciones y puede rechazarlas con retroalimentación. Lee borradores |
| Auditor | Revisa la evidencia | Solo lectura: borradores, trazas, citas y log de auditoría |

## Acciones

| Acción | Inspector | Ingeniero | Gerente | Auditor |
|---|---|---|---|---|
| Abrir NCR | sí | sí | no | no |
| Correr el agente | no | sí | no | no |
| Ver borradores y citas (en su alcance) | sí, lectura | sí | sí, lectura | sí, lectura |
| Editar una sección | no | sí | no | no |
| Rechazar una sección (devolverla con retroalimentación) | no | sí | sí | no |
| Aprobar una sección | no | no | sí* | no |
| Ver trazas y log de auditoría | no | su alcance | su alcance | sí |

\* El gerente no puede aprobar una NCR que abrió ni una sección que editó (hoy no abre NCRs; la regla protege un cambio futuro).

## Dónde se aplica cada regla

| Regla | Dónde |
|---|---|
| Solo un ingeniero edita; solo un gerente aprueba; quien abrió o editó no aprueba | Base de datos: trigger `section_version_rules` (migración 0001) |
| Alcance por planta y línea | Base de datos: `visible_fragments`, `user_can_access`, `user_allowed_lines` |
| Quién abre NCRs, quién corre el agente, quién ve trazas | API: `require_role(...)`, no en la base |
| Quién rechaza una sección (ingeniero o gerente) | API (`require_role(...)`). El trigger no restringe el rechazo por rol |
| Aprobar exige la versión que el gerente leyó (`based_on_version`); una sección aprobada es final | API (`review.py`) |
| El rol `inspector` existe | Migración 0006 |

## Fuera del alcance del MVP

- Planes de calidad: el ingeniero los diseña en la planta, pero el sistema no los gestiona. El plan de control es un documento del corpus.
- Comentarios entre inspector e ingeniero: si el inspector ve una desviación en un borrador, se la comunica al ingeniero por fuera del sistema, y el ingeniero ajusta el análisis.
