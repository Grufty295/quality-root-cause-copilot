"""Errores de la capa LLM. Ninguno lleva contenido del prompt en el mensaje."""

from __future__ import annotations


class LLMError(Exception):
    """Base. El mensaje es apto para el audit log y la UI."""


class LLMTransportError(LLMError):
    """Red, timeout o 5xx/429 después de agotar los reintentos."""

    def __init__(self, message: str, *, status_code: int | None = None, attempts: int = 1) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts


class LLMRequestError(LLMError):
    """4xx no reintentable: modelo inexistente, key inválida, request malformado."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMResponseError(LLMError):
    """La respuesta no tiene la forma esperada del protocolo."""


class StructuredOutputError(LLMError):
    """El modelo no produjo una salida válida para el esquema tras los reintentos."""

    def __init__(self, message: str, *, attempts: int, last_error: str) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


class PolicyViolation(LLMError):
    """Una llamada habría violado la política de confidencialidad. Nunca se reintenta."""


class RedactionFailed(PolicyViolation):
    """El redactor no pudo procesar el payload; no se envía nada hacia api."""
