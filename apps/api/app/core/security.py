"""Defensa CSRF basica para autenticacion por cookie.

SameSite=Lax ya impide que la cookie viaje en POST iniciados desde otro sitio.
Esto agrega una segunda capa: las peticiones que modifican estado y traen un
header Origin solo se aceptan si ese origen esta permitido.

Sin header Origin (curl, tests, llamadas servidor a servidor) se aceptan: los
navegadores modernos siempre lo envian en POST, asi que no abre un hueco para
ataques desde el navegador.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin.rstrip("/") not in get_settings().allowed_origin_set:
                return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
        return await call_next(request)
