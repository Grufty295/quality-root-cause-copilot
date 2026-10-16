"""Esquemas de D2 y D4.

Dos niveles:

* `D2Draft` / `D4Draft`: lo que se le pide al modelo. Estrictos (D4: exactamente
  3 causas de ocurrencia y 1 de no detección).
* `D2Content` / `D4Content`: lo que se guarda en `section_version.content`. Lo
  produce el guardrail de salida, no el modelo: agrega el índice de fuentes y el
  respaldo de cada causa, y puede traer menos de 3 causas si alguna se descartó.

Una fuente se cita por id corto (`F1` fragmento, `T1` resultado de una tool,
`NCR` el reporte mismo). Los ids cortos reducen tokens y no se pueden inventar:
el guardrail comprueba que existan en el libro de evidencia del turno.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SOURCE_ID = re.compile(r"^(?:F\d{1,3}|T\d{1,3}|NCR)$")
OCCURRENCE_CODE = re.compile(r"^RC-\d{2}$")
NON_DETECTION_CODE = re.compile(r"^ND-\d{2}$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hecho(_Model):
    """Una afirmación y las fuentes que la respaldan."""

    texto: str = Field(min_length=3, max_length=500)
    fuentes: list[str] = Field(min_length=1, max_length=6)

    @field_validator("fuentes")
    @classmethod
    def _valid_ids(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if not SOURCE_ID.match(s)]
        if bad:
            raise ValueError(f"ids de fuente inválidos: {bad}; use F1, T1 o NCR")
        return list(dict.fromkeys(v))


class D2Draft(_Model):
    """Descripción del problema en formato 5W2H, sin nombres de personas."""

    que: Hecho
    por_que: Hecho
    donde: Hecho
    cuando: Hecho
    quien: Hecho
    """Área o punto de detección, nunca una persona."""
    como: Hecho
    cuanto: Hecho


class Causa(_Model):
    codigo: str
    explicacion: str = Field(min_length=20, max_length=800)
    evidencia: list[Hecho] = Field(min_length=1, max_length=4)
    pregunta_confirmacion: str = Field(min_length=10, max_length=300)
    """La pregunta o verificación que confirmaría esta causa."""
    evidencia_contradictoria: list[Hecho] = Field(default_factory=list, max_length=3)
    """Hechos de las fuentes que debilitan la hipótesis. Vacío si no hay; nunca se rellena."""
    refutaria: str | None = Field(default=None, max_length=300)
    """Qué resultado de la verificación descartaría la causa."""
    dato_faltante: str | None = Field(default=None, max_length=300)
    """Qué dato no está en las fuentes y haría falta para confirmarla o descartarla."""


EstadoD4 = Literal["candidato_respaldado", "evidencia_insuficiente"]
"""`candidato_respaldado`: la primera causa tiene respaldo en el caso (precedente o datos).
`evidencia_insuficiente`: las causas son hipótesis del catálogo que las fuentes no alcanzan a
sostener; el borrador es una lista de verificación, no una conclusión."""


class D4Draft(_Model):
    estado: EstadoD4
    causas_ocurrencia: list[Causa] = Field(min_length=3, max_length=3)
    """Ordenadas de más a menos probable. Sin porcentajes: los de un LLM no están calibrados."""
    causa_no_deteccion: Causa

    @model_validator(mode="after")
    def _codes(self) -> D4Draft:
        codes = [c.codigo for c in self.causas_ocurrencia]
        bad = [c for c in codes if not OCCURRENCE_CODE.match(c)]
        if bad:
            raise ValueError(
                f"las causas de ocurrencia usan códigos RC-xx; recibido: {bad}"
            )
        if len(set(codes)) != len(codes):
            raise ValueError("las 3 causas de ocurrencia deben tener códigos distintos")
        if not NON_DETECTION_CODE.match(self.causa_no_deteccion.codigo):
            raise ValueError("la causa de no detección usa un código ND-xx")
        return self


# --------------------------------------------------------------------------- lo que se guarda


class FuenteRef(_Model):
    """Qué es cada id citado. Hace el contenido legible sin el libro de evidencia del turno."""

    tipo: Literal["fragmento", "herramienta", "reporte"]
    fragment_id: str | None = None
    documento: str | None = None
    seccion: str | None = None
    herramienta: str | None = None
    parametros: dict[str, str] | None = None
    nivel: str | None = None


class D2Content(D2Draft):
    indice_fuentes: dict[str, FuenteRef]


class CausaVerificada(Causa):
    respaldo: Literal["caso", "solo_catalogo"]
    """`caso`: cita algo más que su propia fila del catálogo (8D, NCR, instrucción, datos).
    `solo_catalogo`: solo cita la fila del AMEF o del SOP. Lo calcula el guardrail, no el modelo."""


class Descarte(_Model):
    codigo: str
    motivo: str


class D4Content(_Model):
    estado: EstadoD4 = "candidato_respaldado"
    """El que queda después del guardrail. Borradores anteriores a la abstención no lo traen."""
    estado_motivo: str | None = None
    """Por qué el guardrail bajó `candidato_respaldado` a `evidencia_insuficiente`, si lo hizo."""
    causas_ocurrencia: list[CausaVerificada] = Field(max_length=3)
    causa_no_deteccion: CausaVerificada | None
    descartes: list[Descarte] = Field(default_factory=list)
    indice_fuentes: dict[str, FuenteRef]
