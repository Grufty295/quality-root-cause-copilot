"""Configuración de destinos de modelo.

Cada destino (local, api) tiene su propia URL, modelos y precios, y ambos hablan
el protocolo de OpenAI. Cambiar de OpenRouter a vLLM u Ollama en planta es
cambiar variables de entorno, no código.

Variables (delimitador anidado `__`):

    LLM_LOCAL__BASE_URL=http://ollama:11434/v1
    LLM_LOCAL__MODEL_SMALL=...
    LLM_LOCAL__SIMULATED=false
    LLM_API__BASE_URL=https://openrouter.ai/api/v1
    LLM_API__API_KEY=...
"""

from __future__ import annotations

import ipaddress
from decimal import Decimal
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    ValidationError,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from .enums import Destination, ModelTier


class DestinationSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: HttpUrl
    api_key: SecretStr | None = None
    model_small: str = Field(min_length=1)
    model_large: str = Field(min_length=1)

    provider_label: str = Field(min_length=1, max_length=64)
    """Etiqueta que va a `audit_log.provider` (p. ej. `ollama-planta`, `openrouter`)."""

    simulated: bool = False
    """Solo para el destino local: el 'local' en realidad se sirve por una API externa.

    Existe para desarrollar sin hardware. Queda registrado en la auditoría y
    desactiva el chequeo de red privada. Nunca debe estar en true en producción.
    """

    json_mode: bool = False
    """Si el servidor acepta `response_format={"type": "json_object"}`.

    Aunque sea true, la salida se valida igual con Pydantic: json_mode garantiza
    JSON, no que cumpla el esquema.
    """

    timeout_s: float = Field(default=60.0, gt=0, le=600)
    max_retries: int = Field(default=3, ge=0, le=8)

    price_in_per_mtok: Decimal = Field(default=Decimal("0"), ge=0)
    price_out_per_mtok: Decimal = Field(default=Decimal("0"), ge=0)
    """Precio en USD por millón de tokens. Se toma de la página del proveedor.

    Se usa para el costo estimado del audit log y el dashboard. En local puede
    reflejar la amortización del hardware o quedarse en 0.
    """

    extra_body: dict[str, Any] = Field(default_factory=dict)
    """Campos extra del request (p. ej. preferencias de proveedor de OpenRouter)."""

    def model_for(self, tier: ModelTier) -> str:
        return self.model_small if tier is ModelTier.SMALL else self.model_large

    def cost_usd(self, input_tokens: int, output_tokens: int) -> Decimal:
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * self.price_in_per_mtok
            + Decimal(output_tokens) * self.price_out_per_mtok
        ) / million


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    local: DestinationSettings
    api: DestinationSettings | None = None
    """Sin destino api, todo va al local: el sistema funciona aislado de internet."""

    allow_simulated_local: bool = False
    """Interruptor explícito para aceptar `local.simulated=true`. En producción, false."""

    @model_validator(mode="after")
    def _check_destinations(self) -> LLMSettings:
        if self.local.simulated:
            if not self.allow_simulated_local:
                raise ValueError(
                    "LLM_LOCAL__SIMULATED=true requiere LLM_ALLOW_SIMULATED_LOCAL=true"
                )
        elif not is_private_endpoint(str(self.local.base_url)):
            raise ValueError(
                f"el destino local apunta a un host público ({self.local.base_url.host}). "
                "Usa un host de la red privada o marca LLM_LOCAL__SIMULATED=true para desarrollo."
            )
        if self.api is not None and self.api.simulated:
            raise ValueError("'simulated' solo aplica al destino local")
        if self.api is not None and self.api.api_key is None:
            raise ValueError("el destino api requiere LLM_API__API_KEY")
        return self

    def destination(self, dest: Destination) -> DestinationSettings:
        if dest is Destination.LOCAL:
            return self.local
        if self.api is None:
            raise LookupError("el destino api no está configurado")
        return self.api


def is_private_endpoint(url: str) -> bool:
    """True si el host es loopback, de red privada o un nombre interno.

    Nombres de una sola etiqueta (`ollama`, `vllm`) son servicios de Docker Compose;
    `.local`, `.internal` y `.lan` son dominios que no resuelven en internet.
    No resuelve DNS: un nombre público que apunte a una IP privada se rechaza,
    y eso es intencional (falla del lado seguro, se corrige con la IP o el nombre interno).
    """
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host == "localhost" or "." not in host:
            return True
        return host.endswith((".local", ".internal", ".lan", ".localhost"))
    return ip.is_private or ip.is_loopback


_MISSING_LOCAL_HINT = (
    "No llegan variables LLM_LOCAL__* al proceso. Revisa en este orden:\n"
    "  1. En el .env de la raíz: grep -c '^LLM_LOCAL__' .env  (debe dar 11; si da 0, es un .env viejo: "
    "copia el bloque LLM_* del .env.example actual).\n"
    "  2. Dentro del contenedor: docker compose exec api printenv LLM_LOCAL__BASE_URL  (si sale vacío, "
    "el contenedor es anterior al .env).\n"
    "  3. Recrea el servicio para que relea el .env: docker compose up -d api "
    "(docker compose restart NO vuelve a leerlo)."
)


@lru_cache(maxsize=1)
def get_llm_settings() -> LLMSettings:
    """Dependencia de FastAPI. Falla al arrancar si la configuración viola la política."""
    try:
        return LLMSettings()  # type: ignore[call-arg]
    except ValidationError as exc:
        if any(
            err["loc"][:1] == ("local",) and err["type"] == "missing"
            for err in exc.errors()
        ):
            raise RuntimeError(_MISSING_LOCAL_HINT) from exc
        raise
