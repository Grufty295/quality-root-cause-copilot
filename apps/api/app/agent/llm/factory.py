"""Construcción de los clientes por destino, para el lifespan de FastAPI.

async with lifespan(app):
    clients = build_clients(get_llm_settings())
    app.state.llm_clients = clients
    yield
    await close_clients(clients)
"""

from __future__ import annotations

from .client import LLMClient
from .config import LLMSettings
from .enums import Destination
from .openai_compat import OpenAICompatibleClient


def build_clients(settings: LLMSettings) -> dict[Destination, LLMClient]:
    clients: dict[Destination, LLMClient] = {Destination.LOCAL: OpenAICompatibleClient(settings.local)}
    if settings.api is not None:
        clients[Destination.API] = OpenAICompatibleClient(settings.api)
    return clients


async def close_clients(clients: dict[Destination, LLMClient]) -> None:
    for client in clients.values():
        await client.aclose()
