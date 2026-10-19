# CI/CD: tres capas

Workflows en `.github/workflows/`. Una regla ordena todo: **cada capa cuesta lo que protege**. Lo que no gasta tokens corre
en cada PR; lo que sí, corre a mano.

| Capa | Qué la dispara | Qué prueba | Llama al modelo | Bloquea |
|---|---|---|---|---|
| 1 · prompt | todo PR | detector de inyección, PII, clasificador, los 16 casos `PER-01..06` y `ADV-01..10` atados por `tests/test_security_manifest.py` | No (LLM falso) | Sí |
| 1b · promptfoo | todo PR | 104 casos de tolerancia cero (falsos positivos de entrada y de salida y 1,288 párrafos del corpus), regresión y validación del detector de inyección y de los guardrails de salida (`docs/seguridad/promptfoo.md`) | No | Sí (umbral de no regresión) |
| 2 · modelo | todo PR | `app.evalkit.gates` sobre el reporte congelado en `evals/reportes/` | No | Sí |
| 3 · integración | todo PR | suite completa contra Postgres 16 + pgvector, migraciones aplicadas en orden, `audit_verify()` | No | Sí |
| manual | `workflow_dispatch` | `evals-live.yml`: eval real de 3 casos con el modelo configurado | Sí (≈ US$0.15) | No |

Además: `gitleaks` sobre el historial (bloquea), `pip-audit` (avisa; no bloquea hasta versionar el lockfile), y tipos + lint del web.

## Qué NO hace este CI (y por qué se dice)

- **La capa 2 no prueba el modelo; prueba un reporte.** Si cambias el modelo o un prompt y no vuelves a correr el eval,
  el gate evalúa el reporte viejo y pasa. Por eso el cambio de modelo exige correr `evals-live` y congelar el reporte nuevo
  en el mismo PR; el diff del JSON es la evidencia.
- **`evals-live.yml` está sin probar en Actions.** Se escribió contra los comandos del `Makefile`. Descarga el modelo de
  embeddings (e5-large) en cada corrida, así que tarda.
- **No hay canary ni rollback automático.** No hay despliegue que revertir: el sistema corre en Docker Compose. El criterio
  de promoción y de retroceso está en el runbook (sección 9), no en un workflow.
- **El gate `salida-segura` es circular**: `unsafe_output` reutiliza `check_blame`/`check_closing`; con tolerancia cero prueba que nada se saltó el guardrail, no que no haya culpa o cierre que el guardrail no ve (recall medido en frases nuevas: 33 %, `docs/seguridad/promptfoo.md`).
- La capa 1 usa un LLM falso: demuestra que los controles de código funcionan, no que el modelo real obedezca. Esa medición
  (los 10 adversariales contra el modelo real) sigue pendiente.

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
