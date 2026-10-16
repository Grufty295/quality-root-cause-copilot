"""Cableado de dependencias de FastAPI para autenticacion.

Aqui se conecta HTTP con el servicio: leer la cookie y decidir el rol.
"""

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy import Connection

from app.core.config import get_settings
from app.core.db import get_conn
from app.core.errors import Forbidden
from app.modules.auth.models import CurrentUser
from app.modules.auth.service import AuthService


def get_auth_service(conn: Connection = Depends(get_conn)) -> AuthService:
    return AuthService(conn)


def current_user(request: Request, service: AuthService = Depends(get_auth_service)) -> CurrentUser:
    return service.authenticate(request.cookies.get(get_settings().session_cookie_name))


def require_role(*roles: str) -> Callable[..., CurrentUser]:
    """Uso: user: CurrentUser = Depends(require_role("gerente"))."""

    def checker(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in roles:
            raise Forbidden("Rol sin permiso para esta accion")
        return user

    return checker
