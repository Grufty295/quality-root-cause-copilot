# Agente de Causa Raíz 8D con router de confidencialidad

Una no conformidad (NCR) entra al sistema; un agente recupera casos y controles anteriores, consulta datos operativos y redacta
borradores de **D2** (5W2H) y **D4** (3 causas de ocurrencia del AMEF y 1 de no detección del SOP-QA-011), siempre con citas.
Un ingeniero los revisa y un gerente los aprueba: el agente nunca cierra un 8D. Lo confidencial va a un modelo local; lo demás
puede ir a una API externa, ya redactado.

> Proyecto de estudio. Todos los datos son sintéticos (planta ficticia de arneses en Ciudad Juárez). Hoy el modelo "local" se
> simula con OpenRouter y queda etiquetado como tal en la auditoría; con ese modo, la garantía "lo confidencial no sale de la
> planta" no se cumple.

## Resultado actual

Partición dev (12 casos, 3 episodios, 36 corridas, `deepseek-v4.1-flash`): **26–29 de 36** aciertos entre corridas equivalentes
(`dev-v6`: 26/36). La causa esperada está en el top-3 en todas; el fallo sistemático es el orden entre RC-02 y RC-03. La
partición sellada (E9, E10) no se ha abierto. Detalle y límites en [docs/evaluacion.md](docs/evaluacion.md).

## Arranque

Requisitos: Docker (Desktop o Engine) con Compose v2 y `make`. Los puertos 3000, 8000 y 5432 deben estar libres; corre un solo stack a la vez.

| Sistema | Qué necesitas |
|---|---|
| Linux | `make` (`sudo apt install make`) |
| macOS | `make`, que viene con las herramientas de línea de comandos de Apple (`xcode-select --install`) |
| Windows | **Git Bash o WSL**: `make` no existe en PowerShell. Clona con `git clone -c core.autocrlf=false <url>` para que los datos conserven sus saltos de línea (el seed compara hashes del contenido) |

Probado en Windows con Git Bash. El Makefile usa solo funciones de GNU Make 3.81 (la versión que trae macOS) y `sed -i.bak`, válido en BSD y GNU, pero no se ha ejecutado en Linux ni en macOS.

```bash
make init            # crea .env desde .env.example; revisa POSTGRES_PASSWORD y las llaves LLM_*
make up-d            # db, api y web en segundo plano
make seed            # catálogos, usuarios de demo y corpus
```

Sin `make` (PowerShell), el equivalente es:

```powershell
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up --build -d
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml exec api python -m app.seed
```

(Antes, copia `.env.example` a `.env` y crea la carpeta `traces/`, que es lo que hace `make init`.)

Web en <http://localhost:3000> (login de demo, sin contraseña); API en <http://localhost:8000/health>.
Los modelos van fijos en `.env` (`LLM_LOCAL__*`, `LLM_API__*`); sin llave no hay análisis. El proveedor puede ser OpenRouter
(por defecto) u OpenAI: el bloque "Usar OpenAI" de `.env.example` lista las variables, incluidas las de los modelos de razonamiento.

```bash
make test            # pruebas contra una base aparte (eightd_test)
make eval-retrieval  # recuperación, sin tokens
make eval-gates      # gates bloqueantes sobre los reportes, sin tokens
make audit           # verifica la cadena de hashes de la auditoría
make observability   # añade Langfuse local (UI en :3001)
```

`make help` lista todos los objetivos. El eval del agente (`make eval-agent`) gasta tokens: ver [el runbook](docs/operacion/runbook.md).

## Documentación

| Documento | Contenido |
|---|---|
| [docs/arquitectura/c4.md](docs/arquitectura/c4.md) | Contexto, contenedores, componentes y flujo de datos |
| [docs/defensa-de-decisiones.md](docs/defensa-de-decisiones.md) | **Empieza aquí.** Problema, decisiones, qué se sacrificó y qué falta demostrar, sin jerga |
| [docs/adr/](docs/adr/README.md) | 12 decisiones de arquitectura con alternativas y consecuencias |
| [docs/seguridad/modelo-de-amenazas.md](docs/seguridad/modelo-de-amenazas.md) | Amenazas, controles, OWASP LLM Top 10 y brechas abiertas |
| [docs/operacion/runbook.md](docs/operacion/runbook.md) | Operación, incidentes, rotación de llaves y evals |
| [docs/evaluacion.md](docs/evaluacion.md) | Métricas, partición sellada y gates |

## Estructura

```
apps/api     FastAPI, LangGraph, recuperación, gateway de modelos, evalkit, migraciones
apps/web     Next.js 16 (React 19, TanStack Query)
data         generador del dataset sintético, corpus y datos operativos
evals        casos de evaluación, adversariales y de permisos (los genera data/generator)
docs         arquitectura, ADRs, amenazas, runbook
```