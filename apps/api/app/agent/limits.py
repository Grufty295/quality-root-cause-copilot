"""Tope de análisis simultáneos: protege el pool de conexiones y la cola del modelo.

Un análisis dura minutos y retiene una conexión de la base durante toda la petición (ver
docs/operacion/prueba-de-carga.md, H1). Sin tope, unos cuantos análisis dejan sin conexiones al resto de la API, login
incluido. El tope **rechaza** (429 con `Retry-After`) en vez de encolar: una cola escondería minutos de espera detrás
de una petición abierta y agotaría igual los hilos y las conexiones.

Variables de entorno (0 = sin tope; sirve para medir la saturación sin protección):

    ANALYZE_MAX_CONCURRENT=8     análisis simultáneos en toda la API
    ANALYZE_MAX_PER_USER=2       análisis simultáneos por usuario
    ANALYZE_RETRY_AFTER_S=30     segundos que se sugieren al cliente

El valor global se debe fijar por debajo de la saturación medida (conexiones del pool menos las que consumen las
consultas cortas), no por encima.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from app.core.errors import TooManyRequests


class AnalysisLimiter:
    """Contadores en memoria de un solo proceso. Con varios procesos, cada uno aplica su propio tope."""

    def __init__(self, max_total: int = 8, max_per_user: int = 2, retry_after_s: int = 30) -> None:
        self.max_total = max_total
        self.max_per_user = max_per_user
        self.retry_after_s = retry_after_s
        self._total = 0
        self._per_user: Counter[UUID] = Counter()

    @classmethod
    def from_env(cls) -> AnalysisLimiter:
        def num(name: str, default: int) -> int:
            raw = os.environ.get(name, "").strip()
            return int(raw) if raw else default

        return cls(
            max_total=num("ANALYZE_MAX_CONCURRENT", 8),
            max_per_user=num("ANALYZE_MAX_PER_USER", 2),
            retry_after_s=num("ANALYZE_RETRY_AFTER_S", 30),
        )

    @property
    def in_flight(self) -> int:
        return self._total

    @contextmanager
    def slot(self, user_id: UUID) -> Iterator[None]:
        """Reserva un cupo o lanza `TooManyRequests`. Sin `await` entre la comprobación y la reserva: es atómico en el loop."""
        if self.max_per_user and self._per_user[user_id] >= self.max_per_user:
            raise TooManyRequests(
                f"Ya tienes {self.max_per_user} análisis en curso. Espera a que termine uno.",
                retry_after_s=self.retry_after_s,
            )
        if self.max_total and self._total >= self.max_total:
            raise TooManyRequests(
                "El agente está ocupado con otros análisis. Intenta de nuevo en unos minutos.",
                retry_after_s=self.retry_after_s,
            )
        self._total += 1
        self._per_user[user_id] += 1
        try:
            yield
        finally:
            self._total -= 1
            self._per_user[user_id] -= 1
            if self._per_user[user_id] <= 0:
                del self._per_user[user_id]
