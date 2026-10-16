"""Acceso a datos de autenticacion. Unico modulo con SQL de usuarios y sesiones.

Las funciones reciben una conexion y no hacen commit: la transaccion la
controla la peticion (ver app.core.db.get_conn). Las reglas de acceso viven
en funciones SQL (user_can_access, user_allowed_lines, session_user_id); aqui
solo se invocan.
"""

from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy import Connection, text

from app.modules.auth.models import CurrentUser, Scope


def find_active_user_id(conn: Connection, username: str) -> UUID | None:
    return conn.execute(
        text("SELECT id FROM app_user WHERE username = :u AND is_active"),
        {"u": username},
    ).scalar_one_or_none()


def list_active_user_ids(conn: Connection) -> list[UUID]:
    return list(
        conn.execute(
            text("SELECT id FROM app_user WHERE is_active ORDER BY role, username")
        ).scalars()
    )


def get_user(conn: Connection, user_id: UUID) -> CurrentUser | None:
    row = conn.execute(
        text(
            "SELECT id, username, display_name, role FROM app_user WHERE id = :id AND is_active"
        ),
        {"id": user_id},
    ).one_or_none()
    if row is None:
        return None
    # Los alcances se leen en cada peticion: un cambio de permisos aplica de inmediato.
    scope_rows = conn.execute(
        text(
            "SELECT plant_id, line_id FROM user_scope WHERE user_id = :id "
            "ORDER BY plant_id, line_id NULLS FIRST"
        ),
        {"id": user_id},
    ).all()
    return CurrentUser(
        id=row.id,
        username=row.username,
        display_name=row.display_name,
        role=str(row.role),
        scopes=tuple(Scope(s.plant_id, s.line_id) for s in scope_rows),
    )


def insert_session(
    conn: Connection, token_hash: bytes, user_id: UUID, ttl: timedelta
) -> None:
    # Limpieza oportunista: las sesiones vencidas de este usuario ya no sirven.
    conn.execute(
        text("DELETE FROM app_session WHERE user_id = :uid AND expires_at <= now()"),
        {"uid": user_id},
    )
    conn.execute(
        text(
            "INSERT INTO app_session (token_hash, user_id, expires_at) VALUES (:h, :uid, now() + :ttl)"
        ),
        {"h": token_hash, "uid": user_id, "ttl": ttl},
    )


def resolve_session_user_id(conn: Connection, token_hash: bytes) -> UUID | None:
    user_id = conn.execute(
        text("SELECT session_user_id(:h)"), {"h": token_hash}
    ).scalar_one()
    if user_id is not None:
        # Como maximo una escritura cada 5 minutos, no en cada peticion.
        conn.execute(
            text(
                "UPDATE app_session SET last_seen_at = now() "
                "WHERE token_hash = :h AND last_seen_at < now() - interval '5 minutes'"
            ),
            {"h": token_hash},
        )
    return user_id


def revoke_session(conn: Connection, token_hash: bytes) -> None:
    conn.execute(
        text(
            "UPDATE app_session SET revoked_at = now() WHERE token_hash = :h AND revoked_at IS NULL"
        ),
        {"h": token_hash},
    )


def revoke_all_sessions(conn: Connection, user_id: UUID) -> None:
    """Respuesta a incidente: cierra todas las sesiones de un usuario."""
    conn.execute(
        text(
            "UPDATE app_session SET revoked_at = now() WHERE user_id = :uid AND revoked_at IS NULL"
        ),
        {"uid": user_id},
    )


def user_can_access(
    conn: Connection, user_id: UUID, plant_id: str, line_id: str | None
) -> bool:
    return bool(
        conn.execute(
            text("SELECT user_can_access(:uid, :plant, :line)"),
            {"uid": user_id, "plant": plant_id, "line": line_id},
        ).scalar_one()
    )


def allowed_lines(conn: Connection, user_id: UUID, plant_id: str) -> list[str]:
    return list(
        conn.execute(
            text("SELECT user_allowed_lines(:uid, :plant)"),
            {"uid": user_id, "plant": plant_id},
        ).scalars()
    )


# --- alta de usuarios (seed de demo y pruebas) --------------------------------


def upsert_user(
    conn: Connection, *, username: str, display_name: str, role: str
) -> UUID:
    """Crea el usuario o actualiza su nombre y rol. No toca is_active: si alguien
    lo desactivo a mano, volver a cargar el seed no lo reactiva."""
    user_id: UUID = conn.execute(
        text(
            """
            INSERT INTO app_user (username, display_name, role)
            VALUES (:u, :d, CAST(:r AS user_role))
            ON CONFLICT (username) DO UPDATE SET display_name = EXCLUDED.display_name, role = EXCLUDED.role
            RETURNING id
            """
        ),
        {"u": username, "d": display_name, "r": role},
    ).scalar_one()
    return user_id


def replace_scopes(
    conn: Connection, user_id: UUID, scopes: Sequence[tuple[str, str | None]]
) -> None:
    """Deja exactamente estos alcances. line_id None = toda la planta."""
    conn.execute(text("DELETE FROM user_scope WHERE user_id = :id"), {"id": user_id})
    if scopes:
        conn.execute(
            text(
                "INSERT INTO user_scope (user_id, plant_id, line_id) VALUES (:id, :p, :l)"
            ),
            [{"id": user_id, "p": plant, "l": line} for plant, line in scopes],
        )
