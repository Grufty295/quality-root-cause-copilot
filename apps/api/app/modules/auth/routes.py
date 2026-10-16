"""Capa HTTP de autenticacion (en FastAPI, el router es el controller).

Regla: este modulo solo traduce HTTP a llamadas al servicio y de vuelta. No
contiene SQL, ni reglas, ni decisiones de seguridad distintas a la cookie.
"""

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.config import get_settings
from app.modules.auth.deps import current_user, get_auth_service
from app.modules.auth.dtos import DemoLoginIn, UserOut
from app.modules.auth.models import CurrentUser
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.session_cookie_name,
        value=token,
        max_age=s.session_ttl_hours * 3600,
        path="/",
        httponly=True,       # el JavaScript de la pagina no puede leerla
        secure=s.cookie_secure,
        samesite="lax",      # no viaja en POST iniciados desde otro sitio
    )


def _clear_session_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        s.session_cookie_name, path="/", httponly=True, secure=s.cookie_secure, samesite="lax"
    )


@router.get("/demo-users", response_model=list[UserOut])
def list_demo_users(service: AuthService = Depends(get_auth_service)) -> list[UserOut]:
    return [UserOut.from_model(u) for u in service.list_demo_users()]


@router.post("/demo-login", response_model=UserOut)
def demo_login(
    body: DemoLoginIn,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> UserOut:
    user, token = service.demo_login(body.username)
    _set_session_cookie(response, token)
    return UserOut.from_model(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> None:
    service.logout(request.cookies.get(get_settings().session_cookie_name))
    _clear_session_cookie(response)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser = Depends(current_user)) -> UserOut:
    return UserOut.from_model(user)
