# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# UV_PYTHON_DOWNLOADS=never: si pyproject pide otro Python que el de la imagen,
# el build falla de forma visible en vez de bajar un interprete en silencio.
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /models /workspace/traces \
    && chown -R app:app /models /workspace

# Capa de dependencias: solo se reconstruye si cambian pyproject.toml o uv.lock
# Incluye dependencias de desarrollo (pytest) para que "make test" corra dentro
# del contenedor. En produccion: --no-dev y una imagen separada para pruebas.
# Grupos opcionales (make build-evals): "--group evals --group observabilidad".
ARG UV_EXTRA_GROUPS=""
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project ${UV_EXTRA_GROUPS}

COPY . .
# --no-install-project: el código corre desde /app (uvicorn app.main, alembic), no como paquete
# instalado. Sin el flag uv intenta construir el proyecto con el backend de build y falla.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project ${UV_EXTRA_GROUPS}

# Revisión de código en el manifiesto de cada corrida (app/agent/manifest.py).
ARG GIT_SHA=""
ENV GIT_SHA=${GIT_SHA}

USER app
EXPOSE 8000
# Migra al arrancar: "docker compose up" deja la base lista sin pasos extra.
# Con una sola replica de la API no hay carrera entre migraciones.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
