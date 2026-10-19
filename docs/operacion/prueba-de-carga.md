# Prueba de carga de `/analyze`

## Qué mide y qué no

Mide **la aplicación**: pool de conexiones, hilos, base de datos, persistencia. Usa un servidor falso de LLM
(`app/evalkit/stub_llm.py`) con latencia fija, así que el proveedor no entra en la medición. **No mide ningún modelo ni
la capacidad de una GPU**; eso se mide aparte rentando la tarjeta (ADR 0012).

Las latencias del stub son supuestos tomados del humo de Qwen 3.6 27B (D4 ≈ 100 s por llamada). La de D2 (40 s) no está
medida en ningún eval. Si cambian, hay que repetir.

## Escenario y criterio

Escenario de diseño (`docs/producto/restricciones-y-alcance.md`): 5 ingenieros pulsan "analizar" a la vez. Objetivo:
sostener 3× esa ráfaga (15 análisis simultáneos) sin errores, y reportar el punto donde la aplicación deja de cumplir.
"Deja de cumplir" = la primera ola con algún análisis fallido, o con el lector (que solo consulta) tardando más de 2 s.

## Hipótesis que la prueba confirma o descarta

**H1 — la conexión de base se queda tomada durante todo el análisis.** `current_user` depende de `get_conn`
(`app/modules/auth/deps.py`), que abre una transacción por petición y no la suelta hasta que termina. `/analyze` dura
minutos, así que cada análisis consume una conexión del pool (5 + 10 de desborde = 15, `pool_timeout` 30 s por defecto en
SQLAlchemy) todo ese tiempo. Además el grafo y la auditoría piden conexiones adicionales cortas.
Predicción: con unos 13–15 análisis simultáneos las conexiones transitorias esperan 30 s y fallan, y el lector deja de
poder autenticarse; **la aplicación entera deja de responder por culpa de unos pocos análisis**. Con 5 debe aguantar.
Si la predicción falla (satura mucho antes o mucho después), el modelo mental de la aplicación estaba mal y eso es lo que
hay que corregir.

**H2 — el primer análisis tras arrancar paga la carga del modelo de embeddings** (~30 s medidos en el humo, aún sin
confirmar como arranque en frío). Se mide con una ola de 1 justo después de reiniciar la API y otra después.

**H3 — con errores 429 sostenidos del proveedor, los reintentos multiplican la espera** (ADR 0010). Se mide con
`STUB_ERROR_RATE`.

## Medir sin protección y con protección

El tope de simultáneos (`app/agent/limits.py`) viene activo en la aplicación (global 8, por usuario 2), pero
`docker-compose.loadtest.yml` lo apaga por defecto (`ANALYZE_MAX_CONCURRENT=0`, `ANALYZE_MAX_PER_USER=0`) para medir la
saturación **real**. Con el punto medido, fija el tope global por debajo de él y repite una ola mayor que el tope:

```bash
ANALYZE_MAX_CONCURRENT=8 ANALYZE_MAX_PER_USER=4 docker compose -f docker-compose.yml -f docker-compose.langfuse.yml -f docker-compose.loadtest.yml up -d api
```

Lo esperado es que los análisis de más reciban 429 con `Retry-After` y que el lector siga respondiendo. Esa segunda tanda es
la evidencia de que el tope protege. Los ingenieros de la demo son pocos (`LOAD_USERS`): con el tope por usuario activo,
sube `ANALYZE_MAX_PER_USER` o agrega usuarios, o medirás el tope y no la aplicación.

## Preparación

```bash
pip install locust
mkdir -p traces/carga
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml -f docker-compose.loadtest.yml up -d --build api stub-llm
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml -f docker-compose.loadtest.yml exec api python -m app.seed
```

Comprueba que el stub contesta: `curl http://localhost:9000/health`. Al terminar, vuelve a la configuración normal:
`docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d api`.

## Olas

Una ola de N = N ingenieros que piden un análisis al mismo tiempo, más un lector. Cada ola dura ~5–6 min con los tiempos
del stub. Reinicia la API entre olas para partir de un pool limpio (`docker compose ... restart api`), salvo la ola de H2.

Terminal 1, el muestreador de conexiones (queda corriendo durante la ola):

```bash
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml -f docker-compose.loadtest.yml exec api python -m app.evalkit.pool_sampler --every 2 --for 420 > traces/carga/conexiones-ola-5.csv
```

Terminal 2, la ola (N = 5 de ejemplo; el `-u` es N + 1 por el lector):

```bash
locust -f loadtest/locustfile.py --headless -u 6 -r 6 -t 8m --host http://localhost:8000 --csv traces/carga/ola-5 Analista Lector
```

Repite con N = 1, 3, 5, 8, 10, 12, 15, 18 (`-u` = N + 1). Después de cada ola:

```bash
curl -s http://localhost:9000/stats
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml logs --tail=200 api | grep -i "QueuePool\|TimeoutError\|Traceback" | head
```

`max_in_flight` del stub confirma cuántas llamadas al modelo coincidieron de verdad. Si es menor que N, la ola no fue
simultánea y no vale.

### 429 sostenido (H3)

```bash
STUB_ERROR_RATE=0.5 STUB_ERROR_STATUS=429 docker compose -f docker-compose.yml -f docker-compose.langfuse.yml -f docker-compose.loadtest.yml up -d stub-llm
```

Una ola de 5. Revisa en `audit_log` el tag `http_attempts` y cuánto se alarga la duración total.

## Resultados (corrida del 19 oct 2026, antes de la corrección)

| Ola (N) | Completados | Fallidos | p50 / p95 `/analyze` (s) | `/auth/me` del lector: p95 / máx. | Conexiones (máx.; en transacción) | `max_in_flight` del stub |
|---|---|---|---|---|---|---|
| 1 | 1 | 0 | 190 / 190 | 26 ms / 88 ms | 3; 2 | 0 |
| 5 | 4 | 1 (a los 0.4 s) | 244 / 443 | 26 ms / 21.6 s | 10; 8 | 0 |
| 10 | 4 | 6 (a ~0.6 s) | 0.6 / 427 | 37 ms / 1.9 s | 21 (un instante), luego 11; 10 | 0 |
| 15 | 1 | **14, a los ~31 s** | 31 / 230 | 25 ms / **28.7 s** | 30 (un instante), luego 15; **15** | 0 |
| 18 | 2 | **16, a los ~31 s** | 31 / 336 | 17 ms / **28.4 s** | 20, luego 15; **16** | 0 |

Los percentiles de `/analyze` mezclan fallos y éxitos (así los reporta Locust). Las filas 5 y 10 tienen 4 éxitos cada una.

**Dos advertencias sobre la validez, antes de leer nada:**

1. **El stub no recibió ninguna llamada** (`calls: 0` en las cinco olas), así que por la regla de arriba (`max_in_flight`
   menor que N) las olas **no valen como medición del stub**. Además, el tiempo de los éxitos sube con la concurrencia
   (190 s con uno, ~310 s de promedio con cuatro), cosa que un stub de latencia fija no hace y un modelo real con cola
   sí. Lo más probable es que `api` siguiera apuntando a tu modelo local y no al stub (¿se levantó con los tres
   `-f`?). Verificación: `docker compose ... exec api env | grep LLM_LOCAL` debe mostrar `stub-llm:9000`.
2. **`POST /auth/demo-login` tarda ~21.3 s en todas las olas, también con 2 usuarios**, y las conexiones aparecen
   recién en el segundo 22. Es un retraso fijo antes de llegar a la base, no carga. Sospecha: `localhost` en Windows prueba
   `::1` antes que `127.0.0.1` y espera ~21 s a que falle. Pendiente de confirmar: repetir con `--host http://127.0.0.1:8000`.
   Hasta entonces, esas 21 s no deben leerse como latencia de la aplicación ni como H2.

**Lo que sí es independiente del modelo y está bien medido: el pool.**

- Con 5 y 10 peticiones simultáneas la aplicación aguantó (el lector, bien); con **15 y 18 colapsó**: todas las conexiones
  en transacción a la vez (15 = 5 + 10 de desborde), 14 de 15 y 16 de 18 análisis fallaron a los ~31 s (el `pool_timeout`
  de 30 s) con `QueuePool limit of size 5 overflow 10 reached`, y el lector, que solo consulta, vio esperas de 28 s.
- **Punto de saturación: entre 10 y 15 peticiones `/analyze` simultáneas**, que es el tamaño del pool, no una capacidad de
  cómputo. El objetivo de diseño (15 simultáneos sin errores) **no se cumplía**.

### H1: confirmada, y el mecanismo era peor que el predicho

La predicción (la conexión de `current_user` queda tomada durante todo el análisis y las cortas esperan) se cumplió. Lo que
no estaba en la predicción es que no es solo desperdicio: es un **bloqueo mutuo**. Cada petición toma una conexión para
autenticar (`get_conn`) y la retiene; al entrar al servicio pide **otra** (`_replay` con `Idempotency-Key`, luego `_read`).
Con tantas peticiones simultáneas como conexiones tiene el pool, cada una sostiene la primera y espera la segunda, y todas
esperan a todas hasta el `pool_timeout`. Por eso fallan casi todas y no solo las que sobran.

Consecuencia que descarta una defensa que yo había dado por buena: **el tope de simultáneos (`limits.py`) no habría evitado
este colapso**, porque se aplica *después* de `_replay`; para rechazar con 429 una petición ya necesita esa segunda
conexión. Con 8 análisis en curso (8 conexiones retenidas) y una ráfaga de 7 peticiones más, el pool se agotaba igual. En
la fase de recuperación de evidencia de las olas 5 y 10 se veían además 8 conexiones en transacción con solo 4 análisis
(dos por análisis), con lo que 8 análisis podían pedir 16 de 15.

**Corrección** (`require_role_released` en `app/modules/auth/deps.py`, usada solo por `/analyze`): la sesión se valida en
una transacción corta y la conexión vuelve al pool antes de entrar al análisis. Prueba de regresión
`test_analyze_does_not_hold_a_pool_connection_while_it_runs` (falla con el comportamiento anterior, pasa con el nuevo).
Queda una conexión tomada solo durante la recuperación de evidencia (`_gather_sync`), no durante las llamadas al modelo.
**Verificación sin repetir las olas:** `test_n_simultaneous_analyses_do_not_starve_a_pool_of_n` reproduce el bloqueo en
segundos con un pool de 3 conexiones y 3 peticiones simultáneas que piden una segunda conexión como `_replay`. Con la
autenticación anterior una de las tres da 500 (timeout del pool); con la corrección las tres dan 200. Es una prueba del
mecanismo, **no una medición de capacidad**: no dice cuántos análisis aguanta la aplicación completa, y las olas 10, 15 y 18
no se repitieron por falta de tiempo. El punto de saturación de arriba es el medido **antes** de la corrección.

### Ola 15 repetida con la corrección (19 oct 2026, 01:17): no validó la corrección, mostró otro fallo

Se reconstruyó la API, el login ya no tarda 21 s (150 ms con `127.0.0.1`; **confirma el retraso de IPv6 de `localhost` en Windows**,
no era la aplicación), y se lanzó la ola de 15.

| Dato | Resultado |
|---|---|
| `/analyze` | 15 de 15 fallaron, todos al mismo instante y a ~39 s, con estado 0 (sin respuesta HTTP) |
| Lector | `RemoteDisconnected: Remote end closed connection without response` (3 en `/auth/me`, 2 en `/ncrs`) |
| Conexiones | 15 en transacción desde el segundo 16; el muestreador **se detuvo a los 28 s** (iba a correr 420 s) |
| Stub | `calls: 0`: ningún análisis llegó a la etapa del modelo |
| Registro de errores | vacío (sin `QueuePool` ni traza) |

Lectura: ya no es el agotamiento del pool (no hay `QueuePool` ni esperas de 30 s). El proceso de la API **dejó de responder
de golpe** unos segundos después de empezar la ráfaga, y con él el muestreador, que corre dentro del mismo contenedor. Eso apunta a que
el contenedor se cayó o se reinició (memoria agotada, cierre del proceso), no a un error de la aplicación que se registre.
**Causa sin confirmar.** Hipótesis a verificar: antes de la corrección el pool retenía a la mayoría de las peticiones en la
autenticación y limitaba cuántas llegaban a la recuperación de evidencia (`_gather_sync`: búsqueda con embeddings); ahora llegan
las 15 a la vez, y esa etapa (CPU y memoria del modelo de embeddings) es el siguiente límite. Si es así, la corrección quitó un
freno accidental y el tope de simultáneos (`ANALYZE_MAX_CONCURRENT`, ahora sí efectivo porque `_replay` ya no se atasca) es lo que debe acotar.
Verificación: `docker inspect` (`OOMKilled`, `ExitCode`, `RestartCount`) y los registros del contenedor anterior.

**Estado honesto:** la corrección elimina el bloqueo mutuo en el mecanismo (test de regresión), pero **bajo 15 simultáneos sin
tope la aplicación no se sostuvo**. No hay una ola exitosa a 15.

### Qué falta por este lado

- **H2** (primer análisis en frío): no medible con esta corrida (ver la advertencia 2). Repetir la ola de 1 tras reiniciar la API.
- **H3** (429 sostenido): no se corrió.
- Los motivos de los fallos rápidos de las olas 5 y 10 (1 y 6 a ~0.5 s): con 2 usuarios de demo y tope por usuario de 2 serían
  429 del limitador (5 − 4 = 1 y 10 − 4 = 6, justo lo observado), pero eso es una inferencia; `ola-N_failures.csv` lo confirma.
- Tope global: con la corrección, 8 es razonable mientras se confirme con las olas. Sin ella, 4 como máximo.

## Límites de esta prueba

- Una sola instancia de la API y de la base, en la misma máquina que el generador de carga: los números absolutos sirven
  como orden de magnitud, no como capacidad de la planta.
- Las NCR se crean con una parte confidencial para que todo vaya al destino local; el camino a la API externa no se ejercita.
- No incluye la espera real del modelo local ni su cola: con una GPU, la ráfaga se limita antes por la memoria y los
  tokens por segundo (ADR 0012) que por el pool.
- Sin ejecutar todavía en esta versión del repositorio: los archivos de carga se verificaron por sintaxis y el stub por
  pruebas (`tests/agent/graph/test_stub_llm_db.py`), no con una ola completa.
