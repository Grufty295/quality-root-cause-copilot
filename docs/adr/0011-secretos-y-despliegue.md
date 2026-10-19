# ADR 0011 — Secretos en .env y despliegue con Docker Compose (alcance de PoC)

**Estado:** Aceptada para el PoC; deuda declarada

## Contexto
El proyecto corre en Docker Compose en una sola máquina, con datos sintéticos.

## Decisión
Los secretos (`LLM_*__API_KEY`, `POSTGRES_PASSWORD`, llaves de Langfuse) viven en `.env`, que está en `.gitignore`; `.env.example` solo trae marcadores. Las llaves de modelos se rotan
cambiando `.env` y recreando el servicio. La base solo escucha en `127.0.0.1`. La defensa CSRF usa cookie `SameSite=Lax` y comprobación de `Origin` contra `ALLOWED_ORIGINS`.

## Qué no cubre
- No hay secret manager ni rotación automática. Una key de OpenRouter llegó a escribirse en `.env.example` y se revocó. Desde el 19 oct 2026 el CI escanea todo el historial con gitleaks y bloquea (`ci.md`); su primera corrida encontró además 6 valores de ejemplo de Langfuse que parecían generados, que se rotaron. Los hallazgos revisados se declaran por fingerprint en `.gitleaksignore`. Límite: el escaneo avisa después del commit; no hay hook local que lo evite antes del push.
- Un único usuario de base para la aplicación; los invariantes críticos viven en triggers y `CHECK`, no en privilegios separados.
- Hay tope de análisis simultáneos (`ANALYZE_MAX_CONCURRENT`, `ANALYZE_MAX_PER_USER`); no hay límite de tasa en el resto de rutas ni presupuesto de costo con alertas (diseño, no construido).
- `COOKIE_SECURE=false` por defecto: exige HTTPS en un despliegue real.

## Camino a producción
Secret manager del proveedor de nube, hook local de secretos (pre-commit) además del escaneo de CI, roles de base separados (migraciones, aplicación, solo lectura para auditoría), límite de tasa y cuota de costo por usuario.