"""Contratos HTTP de las no conformidades."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.ncr.models import Ncr, NcrDraft, SectionView


class NcrIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plant_id: str = Field(min_length=1, max_length=32)
    line_id: str = Field(min_length=1, max_length=32)
    shift: int = Field(ge=1, le=3)
    description: str = Field(min_length=10, max_length=4000)
    part_number: str | None = Field(default=None, max_length=64)
    customer_id: str | None = Field(default=None, max_length=32)

    @field_validator("part_number", "customer_id", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    def to_draft(self) -> NcrDraft:
        return NcrDraft(
            plant_id=self.plant_id,
            line_id=self.line_id,
            shift=self.shift,
            description=self.description.strip(),
            part_number=self.part_number,
            customer_id=self.customer_id,
        )


class NcrOut(BaseModel):
    id: str
    code: str
    plant_id: str
    line_id: str
    shift: int
    part_number: str | None
    customer_id: str | None
    description: str
    detected_level: str | None
    contains_pii: bool | None
    classification_reasons: list[str] | None
    status: str
    opened_by: str
    created_at: datetime

    @classmethod
    def from_model(cls, n: Ncr) -> "NcrOut":
        return cls(
            id=str(n.id),
            code=n.code,
            plant_id=n.plant_id,
            line_id=n.line_id,
            shift=n.shift,
            part_number=n.part_number,
            customer_id=n.customer_id,
            description=n.description,
            detected_level=n.detected_level,
            contains_pii=n.contains_pii,
            classification_reasons=list(n.classification_reasons)
            if n.classification_reasons is not None
            else None,
            status=n.status,
            opened_by=str(n.opened_by),
            created_at=n.created_at,
        )


class SectionOut(BaseModel):
    discipline: str
    version_no: int
    kind: str
    content: dict[str, Any] | None
    feedback: str | None
    author: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, s: SectionView) -> "SectionOut":
        return cls(**s.__dict__)


Discipline = Literal["D2", "D3", "D4"]


class EditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    based_on_version: int = Field(ge=1)
    content: dict[str, Any]


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    based_on_version: int = Field(ge=1)
    feedback: str = Field(max_length=4000)
    # Opcional: el frontend actual no lo manda. Los valores validos estan en review.REJECT_REASONS.
    reason: str | None = Field(default=None, max_length=40)


class ApproveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    based_on_version: int = Field(ge=1)
