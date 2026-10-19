# ADR 0006 — Cuatro roles; quien redacta no aprueba

**Estado:** Aceptada

## Contexto
Un borrador del agente nunca debe llegar a un 8D sin revisión humana independiente.

## Decisión
Inspector (abre y lee), ingeniero de calidad (corre el agente, edita, rechaza), gerente de calidad (aprueba; no lo que abrió o editó), auditor (solo lectura).
La regla de aprobación vive en un trigger de la base (`section_version_rules`) además de la API; cada acción exige `based_on_version`. Las ediciones humanas pasan por
`validate_content` con los mismos esquemas del agente.

## Alternativas descartadas
- **El ingeniero aprueba:** rompe la separación de funciones.
- **Validar solo en la API:** una ruta nueva o un script podrían saltarla.

## Consecuencias
- (+) `test_who_opened_cannot_approve`, `test_only_manager_approves`, `test_stale_version_is_conflict`.
- (−) Los usuarios son de demostración (login sin contraseña con `DEMO_LOGIN=true`); la integración con un proveedor de identidad (Keycloak/OIDC) está fuera del PoC.

## Evidencia
`apps/api/app/modules/ncr/review.py`, `content.py`, `tests/test_review_db.py`, `tests/test_ncr_content.py`.
