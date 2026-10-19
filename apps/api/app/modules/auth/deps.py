"""Cableado de dependencias de FastAPI para autenticacion.

Aqui se conecta HTTP con el servicio: leer la cookie y decidir el rol.
"""

from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy import Connection

from app.core.config import get_settings
from app.core.db import get_conn, get_engine
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


def require_role_released(*roles: str) -> Callable[..., CurrentUser]:
    """Como `require_role`, pero la conexion de la autenticacion se devuelve al pool antes de entrar al manejador.

    `get_conn` (dependencia con `yield`) mantiene abierta una transaccion hasta que termina la respuesta. Para
    `/analyze`, que dura minutos, eso dejaba una conexion "ociosa en transaccion" por analisis y, peor, hacia que
    cada peticion pidiera una segunda conexion (`_replay`, `_read`) mientras retenia la primera: con tantas
    peticiones como conexiones tiene el pool, todas esperaban a todas hasta el `pool_timeout`
    (docs/operacion/prueba-de-carga.md, H1). Aqui la sesion se valida en una transaccion corta y se cierra.
    """

    def checker(request: Request) -> CurrentUser:
        with get_engine().begin() as conn:
            user = AuthService(conn).authenticate(request.cookies.get(get_settings().session_cookie_name))
        if user.role not in roles:
            raise Forbidden("Rol sin permiso para esta accion")
        return user

    return checker
