from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracion leida de variables de entorno (ver .env.example)."""

    model_config = SettingsConfigDict(extra="ignore")

    database_url: str

    # Login de demo: se elige un usuario precargado, sin contrasena.
    # Apagarlo fuera de la demo: DEMO_LOGIN=false.
    demo_login: bool = True

    session_ttl_hours: int = 10
    session_cookie_name: str = "sid"
    # true detras de HTTPS. En http://localhost se deja en false para que
    # funcione tambien si el evaluador entra por IP o por otro host.
    cookie_secure: bool = False

    # Origenes permitidos para peticiones que modifican estado (CSRF).
    # Separados por coma.
    allowed_origins: str = "http://localhost:3000"

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        return frozenset(o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
