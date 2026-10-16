"""Escritura de la auditoría en `audit_log`.

Implementa `AuditSink` del gateway. Dos decisiones que importan:

* **Transacción propia.** Cada registro se confirma por su cuenta. Si el turno del
  agente falla y su transacción se revierte, la llamada al modelo ya ocurrió (o se
  bloqueó) y debe seguir registrada. Auditar dentro de la transacción de la
  petición borraría justo los casos que más interesan.
* **Sin contenido.** `LLMCallRecord` solo lleva metadatos e IDs; aquí no se agrega
  nada más.

El hash encadenado lo calcula el trigger de la base (`audit_log_chain`), no esta
clase: así ningún camino de código puede escribir una fila fuera de la cadena.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import Connection, text

from .schemas import LLMCallRecord

ConnectionFactory = Callable[[], AbstractContextManager[Connection]]

_INSERT = text(
    "INSERT INTO audit_log (user_id, ncr_id, stage, detected_level, destination, provider, model, "
    "fragment_ids, redaction_applied, pseudonymized, tokens_in, tokens_out, cost_usd, latency_ms, "
    "trace_id, tags) "
    "VALUES (:user_id, :ncr_id, :stage, CAST(:level AS confidentiality_level), "
    "CAST(:destination AS llm_destination), :provider, :model, :fragment_ids, :redacted, :pseudonymized, "
    ":tokens_in, :tokens_out, :cost, :latency_ms, :trace_id, CAST(:tags AS jsonb))"
)


class SqlAuditSink:
    def __init__(self, begin: ConnectionFactory) -> None:
        """`begin`: abre una transacción nueva y la confirma al salir (p. ej. `engine.begin`)."""
        self._begin = begin

    async def record(self, entry: LLMCallRecord) -> None:
        # El driver es sincrono: se manda a un hilo para no bloquear el bucle de eventos.
        await asyncio.to_thread(self._insert, entry)

    def _insert(self, entry: LLMCallRecord) -> None:
        with self._begin() as conn:
            conn.execute(
                _INSERT,
                {
                    "user_id": entry.user_id,
                    "ncr_id": entry.ncr_id,
                    "stage": entry.stage.value,
                    "level": entry.detected_level.value,
                    "destination": entry.destination.value,
                    "provider": entry.provider,
                    "model": entry.model,
                    "fragment_ids": list(entry.fragment_ids),
                    "redacted": entry.redacted,
                    "pseudonymized": entry.pseudonymized,
                    "tokens_in": entry.input_tokens,
                    "tokens_out": entry.output_tokens,
                    "cost": entry.cost_usd,
                    "latency_ms": entry.latency_ms,
                    "trace_id": entry.trace_id,
                    "tags": json.dumps(entry.tags, ensure_ascii=False),
                },
            )
