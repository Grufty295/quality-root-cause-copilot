# CI/CD: tres capas

Workflows en `.github/workflows/`. Una regla ordena todo: **cada capa cuesta lo que protege**. Lo que no gasta tokens corre
en cada PR; lo que sí, corre a mano.

| Capa | Qué la dispara | Qué prueba | Llama al modelo | Bloquea |
|---|---|---|---|---|
| 1 · prompt | todo PR | detector de inyección, PII, clasificador, los 16 casos `PER-01..06` y `ADV-01..10` atados por `tests/test_security_manifest.py` | No (LLM falso) | Sí |
| 1b · promptfoo | todo PR | 104 casos de tolerancia cero (falsos positivos de entrada y de salida y 1,288 párrafos del corpus), regresión y validación del detector de inyección y de los guardrails de salida (`docs/seguridad/promptfoo.md`) | No | Sí (umbral de no regresión) |
| 2 · modelo | todo PR | `app.evalkit.gates` sobre el reporte congelado en `evals/reportes/` | No | Sí |
| 3 · integración | todo PR | suite completa contra Postgres 16 + pgvector, migraciones aplicadas en orden, `audit_verify()` | No | Sí |
| manual | `workflow_dispatch` | `evals-live.yml`: eval real de 3 casos con el modelo configurado | Sí (≈ US$0.05 medido; tope esperado US$0.15) | No |

Además:
- **`gitleaks`** (bloquea): el binario `v8.24.3` escanea **todo el historial** (`fetch-depth: 0`). No se usa `gitleaks-action` porque escanea el rango del push y falla con un commit raíz. Los hallazgos ya revisados se declaran por fingerprint en `.gitleaksignore` (ver abajo).
- **`pip-audit`** (avisa; `continue-on-error`): `uvx pip-audit -r /tmp/req.txt --no-deps --disable-pip`. `--no-deps` es obligatorio con `--disable-pip` cuando el requirements no trae hashes.
- **Web** (bloquea): `npx next typegen` antes de `npx tsc --noEmit` (los tipos globales `LayoutProps`/`PageProps` de Next 16 se generan, no vienen en el repo), y `npm run lint`.
- **API**: `[tool.uv] package = false` en `apps/api/pyproject.toml`. La API corre desde el código fuente (`uvicorn app.main:app`), no se instala como paquete; sin esto `uv sync` intenta construir uno.

## Qué NO hace este CI (y por qué se dice)

- **La capa 2 no prueba el modelo; prueba un reporte.** Si cambias el modelo o un prompt y no vuelves a correr el eval,
  el gate evalúa el reporte viejo y pasa. Por eso el cambio de modelo exige correr `evals-live` y congelar el reporte nuevo
  en el mismo PR; el diff del JSON es la evidencia.
- **`evals-live.yml` se probó en Actions el 19 oct 2026** (3 casos, `con_enlaces`, 1 repetición): 3 corridas válidas, 0 inválidas,
  0 salidas inseguras, costo US$0.054 estimado / US$0.050 reportado, p50 238 s con concurrencia 3. Fue una prueba de que **el camino
  funciona**, no una medición de calidad: n = 3 (pass@1 0.67 = 2 de 3) no sostiene ninguna conclusión sobre el modelo, y no sustituye
  al reporte completo de `evals/reportes/`. Descarga el modelo de embeddings (e5-large) en cada corrida, así que tarda. La corrida
  no queda atada a un commit (`código sin GIT_SHA` en el reporte) mientras el workflow no pase `GIT_SHA`.
  Antes de funcionar falló dos veces, por razones que solo una corrida real podía mostrar: (1) el seed y el eval usaban rutas del
  contenedor (`/workspace/data/seed`, `/workspace/evals`) que no existen en el runner; se pasan `--data` y `--evals` con
  `${{ github.workspace }}`; (2) `--variants base` no existe (las válidas son `sin_enlaces` y `con_enlaces`); el mismo error estaba en
  `make eval-smoke`.
- **El CI avisa pero no impide fusionar.** Sin protección de rama, un PR en rojo sigue teniendo el botón de fusión activo; se comprobó el 19 oct 2026 con la prueba A de `probar-ci.md`. Esa misma prueba demostró que una regresión del detector de inyección pone en rojo las capas 1, 1b y 3, y deja en verde la 2 (que evalúa un reporte, no el código).
- **No hay canary ni rollback automático.** No hay despliegue que revertir: el sistema corre en Docker Compose. El criterio
  de promoción y de retroceso está en el runbook (sección 9), no en un workflow.
- **El gate `salida-segura` es circular**: `unsafe_output` reutiliza `check_blame`/`check_closing`; con tolerancia cero prueba que nada se saltó el guardrail, no que no haya culpa o cierre que el guardrail no ve (recall medido en frases nuevas: 33 %, `docs/seguridad/promptfoo.md`).
- La capa 1 usa un LLM falso: demuestra que los controles de código funcionan, no que el modelo real obedezca. Esa medición
  (los 10 adversariales contra el modelo real) sigue pendiente.

## Secretos en el historial: `.gitleaksignore`

El job escanea todos los commits, así que borrar un valor del último commit no apaga el aviso: el hallazgo vive en el commit
viejo. Lo revisado se declara en `.gitleaksignore` (raíz del repo), una línea por fingerprint, tal como lo imprime gitleaks
(`commit:archivo:regla:línea`). Un secreto nuevo tendrá otro fingerprint y volverá a bloquear.

Estado al 19 oct 2026 (13 hallazgos, todos de la regla `generic-api-key`):
- 7 son literales de prueba o ejemplo (`idempotency_key` de tests, claves con patrón obvio `0123…cdef` / `abcd…1234`).
- 6 eran valores de `.env.langfuse.example` que parecían generados (no placeholders). Se **revocaron y regeneraron** y el
  ejemplo ahora lleva placeholders. Siguen en el historial, ya inservibles.
- No se reescribió el historial (`git filter-repo`): cambia todos los SHA, invalida PRs y checks, y con los valores revocados no añade seguridad.

Lección: un `.env.*.example` nunca se llena copiando el `.env` real y borrando "a mano"; se escribe desde cero con valores obvios
(`cambia-esto`). Y los ejemplos de claves falsas en docs deben construirse en el momento (ver `probar-ci.md`, prueba C) para no
disparar el escáner.

## Congelar el reporte para la capa 2

Después de una corrida válida del eval en dev, desde la raíz del repo:

```bash
mkdir -p evals/reportes
cp traces/evals/dev-v6.json evals/reportes/agente.json
cp traces/evals/recuperacion.json evals/reportes/recuperacion.json
git add evals/reportes && git commit -m "evals: congela reporte dev-v6"
```

`traces/` está en `.gitignore`; `evals/reportes/` no. Los reportes no llevan texto de NCR del usuario, pero revisa que
tampoco lleven secretos antes del primer commit. Sin ese archivo la capa 2 falla a propósito: sin dato no se aprueba.

## Secretos y variables que pide GitHub

Solo para `evals-live`: secreto `OPENROUTER_API_KEY`; variables `LLM_MODEL`, `LLM_PRICE_IN`, `LLM_PRICE_OUT`.

## Correr lo mismo en local

```bash
make test                      # capa 3, dentro de Docker
make eval-gates VARIANT=con_enlaces SPLIT=dev   # capa 2
```