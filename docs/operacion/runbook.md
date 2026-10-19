# Runbook de operación

Todos los comandos se ejecutan desde la raíz del repositorio. `make help` lista los objetivos.

## 1. Arranque, parada y salud

| Acción | Comando |
|---|---|
| Crear `.env` desde el ejemplo | `make init` (revisa `POSTGRES_PASSWORD` y las llaves `LLM_*`) |
| Levantar db, api y web | `make up-d` |
| Cargar catálogos, usuarios de demo y corpus | `make seed` |
| Estado de los servicios | `make ps` |
| Logs de la API | `make logs` |
| Detener (conserva los datos) | `make down` |
| Aplicar migraciones | `make migrate` (la API también migra al arrancar) |

Salud: `GET http://localhost:8000/health` debe responder 200; Compose la usa como `healthcheck` de `api`, y `web` espera a que `api` esté sana.
**Un cambio en `.env` no se relee con `restart`:** usa `docker compose up -d api`.

## 2. Verificaciones periódicas

| Qué | Comando | Resultado sano |
|---|---|---|
| Cadena de auditoría | `make audit` | Sin filas con `problem`; última fila `registros verificados: N` y el `head_hash` |
| Pruebas | `make test` (base aparte `eightd_test`) | Todas verdes; nunca contra la base de la demo |
| Gates del eval | `make eval-gates VARIANT=con_enlaces SPLIT=all` | Código de salida 0. No llama al modelo |

Anota el `head_hash` de `make audit` en cada verificación: es la única forma de detectar que alguien reescribió toda la cadena (ver ADR 0005).

## 3. Incidentes

### 3.1 El proveedor del modelo responde lento, con 429 o cae

**Síntomas:** el análisis falla con un error de proveedor tras agotar los reintentos, o tarda mucho más que el p50 observado (85 s por corrida de D4 en `dev-v6`; p95 130 s).

1. Diagnosticar: `make llm-diagnose` (destino local) y `make llm-diagnose DEST=api`. Muestra la configuración efectiva, el estado de la llave y los proveedores del modelo.
2. El cliente ya reintenta 408, 409, 425, 429 y 5xx con backoff y respeta `Retry-After` (con tope). Esperar suele bastar para un 429.
3. Un análisis fallido **no escribe ningún borrador**: la persistencia ocurre después del grafo. La misma `Idempotency-Key` devuelve el resultado de la corrida ya registrada (también si falló) y responde 409 mientras sigue `en_curso`; para reintentar tras un fallo usa una clave nueva.
4. **No hay fallback automático de modelo** (ADR 0010, propuesta). Para una NCR confidencial no se debe redirigir a la API bajo ninguna circunstancia.
5. Cuántos intentos HTTP hizo cada llamada queda en el tag `http_attempts`:
   ```sql
   SELECT tags->>'http_attempts' AS intentos, count(*) FROM audit_log GROUP BY 1 ORDER BY 1;
   ```
   Una proporción alta de 2 o más intentos con latencias cercanas al timeout indica que las llamadas se cortan y se repiten.
6. Si el problema persiste, bajar la concurrencia de quien lanza análisis y revisar `LLM_*__TIMEOUT_S` (el valor por defecto del código es 60 s; el `.env.example` trae 180 s).

### 3.2 El inspector bloquea una llamada (`PolicyViolation`)

Significa que el payload ya redactado todavía contenía un identificador confidencial. **No es un error por silenciar.**

1. Buscar la fila en `audit_log` (tag `outcome`) y la NCR asociada.
2. Revisar si el catálogo de clientes y partes está desactualizado: el redactor y el inspector no se recargan solos; reiniciar la API (`docker compose up -d api`) tras cambiar el catálogo.
3. Nunca desactivar el inspector para "destrabar" un análisis. Si la NCR es legítimamente confidencial, debe ir a un modelo local.

### 3.3 `make audit` reporta registros rotos

1. No escribir más en `audit_log`; conservar la base tal como está (copia del volumen).
2. Identificar el primer `id` con `problem`: *prev_hash no coincide* indica un registro faltante o reordenado; *el contenido no coincide* indica una fila alterada.
3. Comparar el `head_hash` con el último anotado (sección 2). Restaurar desde la copia de seguridad más reciente que verifique y reportar el incidente.

### 3.4 Langfuse no está disponible

La API **no se rompe**: un observador que falla se registra y el análisis continúa. Para no perder trazas, poner `TRACE_EXPORTER=json` en `.env` y recrear la API; las trazas locales quedan en `traces/`. Las trazas de Langfuse no contienen texto, solo ids, conteos y tiempos (ADR 0008).

### 3.5 La base de datos no responde

La API no devuelve resultados de modelo si la auditoría no se puede escribir (ADR 0002): el síntoma esperado es un error en `/analyze`, no un borrador sin registro. Revisar `make ps`, `make logs` y el espacio del volumen `pgdata`.

### 3.6 Una corrida quedó `en_curso` tras un reinicio

La siguiente corrida de la misma NCR la marca `abandonada` al encontrarla vieja (ciclo de estados en `app/agent/runs.py`). No requiere limpieza manual.

## 4. Rotación de llaves

| Llave | Dónde | Pasos |
|---|---|---|
| `LLM_LOCAL__API_KEY` / `LLM_API__API_KEY` | `.env` | Revocar en OpenRouter, poner la nueva, `docker compose up -d api`, `make llm-diagnose` para comprobar |
| `POSTGRES_PASSWORD` | `.env` y volumen existente | La contraseña solo se aplica al crear el volumen; cambiarla exige `ALTER USER` dentro de la base y actualizar `.env` |
| Llaves de Langfuse | `.env`, `.env.langfuse` | Crear llaves nuevas en el proyecto de Langfuse, actualizar `.env`, recrear la API |

Si una llave aparece en el repositorio (incluido `.env.example`): revocarla primero, luego quitarla del historial.

## 5. Evals y cambios de modelo, prompt o índice

| Qué | Comando | Costo |
|---|---|---|
| Recuperación | `make eval-retrieval` | Sin tokens |
| Línea base trivial | `make eval-baseline` | Sin tokens |
| Humo del agente | `make eval-agent ARGS="--casos EV-01,EV-05,EV-09 --repeats 1"` | Centavos |
| Agente dev completo | `make eval-agent ARGS="--name <nombre> --variants con_enlaces --repeats 3 --concurrency 3"` | ≈ $0.22 por 36 corridas (costo reportado en `dev-v6`) |
| Gates sobre los reportes | `make eval-gates` | Sin tokens |
| Partición sellada | `--test`, **una sola vez** con la configuración congelada | Igual que dev |

Criterio de regresión: comparar contra el último reporte válido **por episodio**, no por caso; con 12 casos dev el rango entre corridas equivalentes es 26–29 de 36, así que una diferencia de 1–2 casos no es una regresión.
La partición sellada no se usa para elegir entre configuraciones.

## 6. Costo

Cada llamada queda en `audit_log` con tokens, costo estimado y tags. Consulta de costo por NCR:

```sql
SELECT ncr_id, count(*) AS llamadas, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out,
       sum(cost_usd) AS costo_estimado
FROM audit_log GROUP BY ncr_id ORDER BY costo_estimado DESC LIMIT 20;
```

El costo estimado depende de `LLM_*__PRICE_IN_PER_MTOK` y `PRICE_OUT_PER_MTOK`; se comparan con el costo reportado por el proveedor en cada reporte del eval. Anota la fecha en que tomaste los precios.

## 7. Respaldo y restauración

```bash
bash scripts/backup.sh                        # volcado + huella de la cadena de auditoría en ./backups
bash scripts/restore-check.sh backups/<archivo>.dump   # restaura en una base temporal y compara la cadena
```

`backup.sh` guarda el volcado (`pg_dump -Fc`), su `.sha256` y un `.audit` con el resultado de `audit_verify()` (registros y
hash de la cabeza). `restore-check.sh` restaura en una base temporal (`eightd_restore_check`), vuelve a correr
`audit_verify()` y falla (código 1) si el hash de la cabeza o el número de registros no coinciden. No toca la base real y
borra la temporal al terminar. Hay que correrlo de vez en cuando: un respaldo que nunca se restauró no es un respaldo.

**Probado:** en un Postgres 16 de pruebas con 180 registros de auditoría, la restauración conservó la cadena íntegra y el
script detectó una huella alterada. **Sin probar:** dentro de tu Docker Compose real (los scripts usan `docker compose exec`).

Política propuesta (supuestos que se confirman con quien opera la planta):

| Parámetro | Valor propuesto | Por qué |
|---|---|---|
| RPO (datos que se aceptan perder) | 24 h | Un respaldo diario en el cambio de turno; el volumen es de unas NCR por día |
| RTO (tiempo para volver a operar) | 2 h | Servidor nuevo con Docker, clonar el repositorio, restaurar el volcado, `make up-d` |
| Retención | 14 diarios y 12 semanales | Los registros de calidad pueden exigir más: **confirmar con calidad** |
| Copia fuera del servidor | Obligatoria | **No está automatizada**: el script deja el archivo en el mismo servidor |

Restaurar sobre la base real (después de un desastre): detener `api`, `dropdb` y `createdb` de la base de la aplicación,
`pg_restore --no-owner -d <base> <volcado>`, `audit_verify()` y levantar `api`. Se pierde lo ocurrido desde el último respaldo.

No cubre: la base de Langfuse (volúmenes `langfuse_*`, sus propias trazas), el archivo `.env` (guárdalo en un gestor de
secretos, no junto al volcado) ni el caché de modelos de embeddings, que se vuelve a descargar.

## 8. Objetivos de servicio (propuestos; la prueba de carga los confirma)

| Objetivo | Valor | Cómo se mide |
|---|---|---|
| Disponibilidad de la API en turnos | ≥ 99 % semanal | `/health` cada minuto en horario de turnos |
| Latencia p95 de un análisis, modelo por API | ≤ 180 s | `analysis_run.duration_ms` |
| Latencia p95 de un análisis, modelo local | ≤ 20 min | Ídem; depende del hardware (ADR 0012) |
| Análisis fallidos | < 5 % por día | `analysis_run.status` |
| Costo p95 por análisis (ruta API) | ≤ US$0.10 | Consulta de costo en `observabilidad.md` |

Son propuestas derivadas del escenario (`docs/producto/restricciones-y-alcance.md`), no mediciones. La herramienta no está
en la ruta crítica de producción, por eso no se pide 99.9 %.

## 9. Cambios y retroceso (no hay canary)

**Por qué no hay canary.** Es una instancia con ~0.44 NCR por día. Detectar una caída de pass@1 de 0.72 a 0.60 con
significancia necesita unas 240 corridas por grupo: más de 18 meses de tráfico. Un canary no tendría poder estadístico.
La alternativa que sí se sostiene es un **gate offline** (CI capa 2 y `evals-live`) y, más adelante, un modo sombra (la
versión nueva corre sobre las mismas NCR sin mostrarse). El modo sombra **no está construido**.

**Promoción.** Un cambio se despliega si: (1) el CI está en verde en las tres capas, (2) un cambio de modelo o de prompt trae
el reporte nuevo congelado y pasa los gates, (3) se despliega en el cambio de turno, y (4) el humo posterior pasa:
`/health` responde y un análisis de una NCR de prueba termina `completada`.

**Retroceso (manual, con criterio escrito).** Se retrocede si ocurre cualquiera de: el humo falla, más de 5 % de análisis
fallidos en una hora, `audit_verify()` reporta un problema, o un guardrail de tolerancia cero se dispara en producción.

```bash
git checkout <sha-anterior>
GIT_SHA=<sha-anterior> docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d --build api web
```

**Límite importante:** las migraciones solo avanzan. Retroceder el código no revierte el esquema. Regla: cada migración
debe ser compatible con la versión anterior del código; si una no lo es, el retroceso exige restaurar el respaldo (con su RPO).
**No hay retroceso automático.**

## 10. Alertas

No existe ninguna alerta. La alternativa mínima es una consulta programada sobre `audit_log` y `analysis_run`
(`observabilidad.md`) que avise por correo o chat. Umbrales propuestos: costo p95 por análisis > US$0.10, tasa de
escalamiento > 60 %, análisis fallidos > 5 % en un día, `audit_verify()` con problemas.

## 11. Aún pendiente

- Copia de seguridad fuera del servidor, automatizada, y respaldo de Langfuse.
- Las alertas de arriba, construidas.
- Modo sombra para cambios de modelo.
- Valores de los objetivos confirmados con la prueba de carga y con los datos reales de la planta.
