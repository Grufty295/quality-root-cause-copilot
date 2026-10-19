"""Errores de dominio. Los servicios los lanzan; no conocen HTTP.

main.py los traduce a respuestas HTTP con un unico exception handler. Asi la
capa de negocio se puede probar sin FastAPI y los codigos de estado viven en
un solo lugar.
"""


class AppError(Exception):
    status_code: int = 500
    default_detail: str = "Error interno"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class Unauthenticated(AppError):
    status_code = 401
    default_detail = "No autenticado"


class Forbidden(AppError):
    status_code = 403
    default_detail = "Sin permiso para esta accion"


class NotFound(AppError):
    status_code = 404
    default_detail = "No encontrado"


class Invalid(AppError):
    status_code = 422
    default_detail = "Datos invalidos"


class Conflict(AppError):
    status_code = 409
    default_detail = "Conflicto con el estado actual"


class TooManyRequests(AppError):
    status_code = 429
    default_detail = "Demasiadas peticiones"

    def __init__(self, detail: str | None = None, *, retry_after_s: int | None = None) -> None:
        super().__init__(detail)
        self.retry_after_s = retry_after_s
