"""Entorno de Alembic.

La URL sale de app.core.config (DATABASE_URL), igual que la API: no hay dos
fuentes de configuración de la base.

Las migraciones de este proyecto ejecutan SQL crudo desde db/migrations/sql/
(ver versions/). Eso necesita una conexión real, así que solo existe el modo
online: `alembic upgrade head`. El modo offline (generar SQL sin conectar) no
aplica.

No hay modelos ORM: target_metadata es None y `alembic revision --autogenerate`
no sirve aquí. Cada cambio de esquema se escribe a mano en sql/ y su versión
lo ejecuta.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = None


def run_migrations_offline() -> None:
    raise RuntimeError(
        "Las migraciones ejecutan SQL crudo sobre una conexión: usa `alembic upgrade head` con DATABASE_URL definido."
    )


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
