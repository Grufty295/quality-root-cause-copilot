"""Reglas de negocio de autenticacion y autorizacion.

No conoce HTTP ni cookies: recibe y devuelve tokens y modelos de dominio. Lanza
errores de app.core.errors.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import Connection

from app.core.config import get_settings
from app.core.errors import Forbidden, NotFound, Unauthenticated
from app.modules.auth import repository as repo
from app.modules.auth.models import CurrentUser
from app.utils.crypto import hash_token, new_token

MAX_TOKEN_LENGTH = 128


class AuthService:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._settings = get_settings()

    # --- login de demo -------------------------------------------------

    def _require_demo_login(self) -> None:
        # Con el login de demo apagado la funcionalidad no existe: 404, no 403.
        if not self._settings.demo_login:
            raise NotFound()

    def list_demo_users(self) -> list[CurrentUser]:
        self._require_demo_login()
        users = (repo.get_user(self._conn, uid) for uid in repo.list_active_user_ids(self._conn))
        return [u for u in users if u is not None]

    def demo_login(self, username: str) -> tuple[CurrentUser, str]:
        """Crea una sesion y devuelve (usuario, token en claro). El token no se vuelve a ver."""
        self._require_demo_login()
        user_id = repo.find_active_user_id(self._conn, username)
        user = repo.get_user(self._conn, user_id) if user_id else None
        if user is None:
            raise Unauthenticated("Usuario desconocido o inactivo")

        token = new_token()
        ttl = timedelta(hours=self._settings.session_ttl_hours)
        repo.insert_session(self._conn, hash_token(token), user.id, ttl)
        return user, token

    # --- sesion ----------------------------------------------------------

    def logout(self, token: str | None) -> None:
        if token:
            repo.revoke_session(self._conn, hash_token(token))

    def authenticate(self, token: str | None) -> CurrentUser:
        """Devuelve el usuario de una sesion vigente o lanza Unauthenticated."""
        if not token or len(token) > MAX_TOKEN_LENGTH:
            raise Unauthenticated()
        user_id = repo.resolve_session_user_id(self._conn, hash_token(token))
        user = repo.get_user(self._conn, user_id) if user_id else None
        if user is None:
            raise Unauthenticated()
        return user

    def revoke_all_sessions(self, user_id: UUID) -> None:
        """Para respuesta a incidentes. No expuesto por HTTP todavia."""
        repo.revoke_all_sessions(self._conn, user_id)

    # --- autorizacion ----------------------------------------------------

    def ensure_access(self, user: CurrentUser, plant_id: str, line_id: str | None) -> None:
        """line_id None = consulta de toda la planta."""
        if not repo.user_can_access(self._conn, user.id, plant_id, line_id):
            raise Forbidden("Fuera de tu alcance de planta o linea")

    def allowed_lines(self, user: CurrentUser, plant_id: str) -> list[str]:
        """Lineas consultables. Las tools del agente filtran con esto, no con el argumento del LLM."""
        return repo.allowed_lines(self._conn, user.id, plant_id)
