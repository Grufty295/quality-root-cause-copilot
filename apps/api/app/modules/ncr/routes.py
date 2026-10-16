"""Capa HTTP de las no conformidades. Solo traduce HTTP al servicio."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import Connection

from app.core.db import get_conn
from app.modules.auth.deps import current_user, require_role
from app.modules.auth.models import CurrentUser
from app.modules.ncr.dtos import (
    ApproveIn,
    Discipline,
    EditIn,
    NcrIn,
    NcrOut,
    RejectIn,
    SectionOut,
)
from app.modules.ncr.review import (
    APPROVE_ROLES,
    EDIT_ROLES,
    REJECT_ROLES,
    ReviewService,
)
from app.modules.ncr.service import MAX_LIST, OPEN_ROLES, NcrService

router = APIRouter(prefix="/ncrs", tags=["ncr"])


def get_ncr_service(conn: Connection = Depends(get_conn)) -> NcrService:
    return NcrService(conn)


def get_review_service(conn: Connection = Depends(get_conn)) -> ReviewService:
    return ReviewService(conn)


@router.post("", response_model=NcrOut, status_code=status.HTTP_201_CREATED)
def open_ncr(
    body: NcrIn,
    user: CurrentUser = Depends(require_role(*OPEN_ROLES)),
    service: NcrService = Depends(get_ncr_service),
) -> NcrOut:
    return NcrOut.from_model(service.open(user, body.to_draft()))


@router.get("", response_model=list[NcrOut])
def list_ncrs(
    limit: int = Query(default=50, ge=1, le=MAX_LIST),
    user: CurrentUser = Depends(current_user),
    service: NcrService = Depends(get_ncr_service),
) -> list[NcrOut]:
    return [NcrOut.from_model(n) for n in service.list_visible(user, limit)]


@router.get("/{ncr_id}", response_model=NcrOut)
def get_ncr(
    ncr_id: UUID,
    user: CurrentUser = Depends(current_user),
    service: NcrService = Depends(get_ncr_service),
) -> NcrOut:
    return NcrOut.from_model(service.get(user, ncr_id))


@router.get("/{ncr_id}/sections", response_model=list[SectionOut])
def get_sections(
    ncr_id: UUID,
    user: CurrentUser = Depends(current_user),
    service: NcrService = Depends(get_ncr_service),
) -> list[SectionOut]:
    """Ultimo borrador por disciplina, en solo lectura para todos los roles con alcance."""
    return [SectionOut.from_model(s) for s in service.sections(user, ncr_id)]


@router.post("/{ncr_id}/sections/{discipline}/edit", response_model=SectionOut)
def edit_section(
    ncr_id: UUID,
    discipline: Discipline,
    body: EditIn,
    user: CurrentUser = Depends(require_role(*EDIT_ROLES)),
    service: ReviewService = Depends(get_review_service),
) -> SectionOut:
    return SectionOut.from_model(
        service.edit(user, ncr_id, discipline, body.based_on_version, body.content)
    )


@router.post("/{ncr_id}/sections/{discipline}/reject", response_model=SectionOut)
def reject_section(
    ncr_id: UUID,
    discipline: Discipline,
    body: RejectIn,
    user: CurrentUser = Depends(require_role(*REJECT_ROLES)),
    service: ReviewService = Depends(get_review_service),
) -> SectionOut:
    return SectionOut.from_model(
        service.reject(
            user,
            ncr_id,
            discipline,
            body.based_on_version,
            body.feedback,
            reason=body.reason,
        )
    )


@router.post("/{ncr_id}/sections/{discipline}/approve", response_model=SectionOut)
def approve_section(
    ncr_id: UUID,
    discipline: Discipline,
    body: ApproveIn,
    user: CurrentUser = Depends(require_role(*APPROVE_ROLES)),
    service: ReviewService = Depends(get_review_service),
) -> SectionOut:
    return SectionOut.from_model(
        service.approve(user, ncr_id, discipline, body.based_on_version)
    )
