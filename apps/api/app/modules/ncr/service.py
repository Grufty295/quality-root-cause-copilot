"""Reglas de negocio de la no conformidad.

Quien puede abrir una NCR lo decide la ruta con require_role (ver OPEN_ROLES);
aqui se decide que esa persona tenga alcance en la planta y linea que reporta.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Connection

from app.confidentiality import ConfidentialityLevel
from app.confidentiality.classifier import Classification, RuleClassifier
from app.core.errors import Forbidden, Invalid, NotFound
from app.modules.auth import repository as auth_repo
from app.modules.auth.models import CurrentUser
from app.modules.ncr import repository as repo
from app.modules.ncr.models import Ncr, NcrDraft, SectionView

OPEN_ROLES = ("inspector", "ingeniero")
"""El inspector reporta desde el piso; el ingeniero tambien puede abrir. Ver docs/matriz-roles.md."""

MAX_LIST = 100


class NcrService:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def open(self, user: CurrentUser, draft: NcrDraft) -> Ncr:
        if user.role not in OPEN_ROLES:
            raise Forbidden("Tu rol no abre no conformidades")
        if not repo.line_exists(self._conn, draft.plant_id, draft.line_id):
            raise Invalid("La linea no existe en esa planta")
        # La linea concreta, no la planta: el inspector de L1 no reporta en L2.
        if not auth_repo.user_can_access(
            self._conn, user.id, draft.plant_id, draft.line_id
        ):
            raise Forbidden("Fuera de tu alcance de planta o linea")

        draft = self._resolve_part_and_customer(draft)
        classification = self._classify(draft)
        code = repo.next_code(self._conn, datetime.now(UTC).year)
        ncr_id = repo.insert(
            self._conn,
            code=code,
            draft=draft,
            opened_by=user.id,
            classification=classification,
        )
        created = repo.get(self._conn, ncr_id, user.id)
        if created is None:  # no deberia pasar: acaba de pasar la validacion de alcance
            raise NotFound()
        return created

    def get(self, user: CurrentUser, ncr_id: UUID) -> Ncr:
        # Fuera de alcance responde igual que inexistente: no revela que existe.
        ncr = repo.get(self._conn, ncr_id, user.id)
        if ncr is None:
            raise NotFound()
        return ncr

    def list_visible(self, user: CurrentUser, limit: int = MAX_LIST) -> list[Ncr]:
        return repo.list_visible(self._conn, user.id, min(limit, MAX_LIST))

    def sections(self, user: CurrentUser, ncr_id: UUID) -> list[SectionView]:
        """Ultimo borrador de cada disciplina. Lectura para todos los roles con alcance."""
        self.get(user, ncr_id)
        return repo.latest_sections(self._conn, ncr_id)

    def _classify(self, draft: NcrDraft) -> Classification:
        """Nivel y PII de la NCR. Se fija al abrirla y el router lo lee de la base."""
        structured: list[ConfidentialityLevel | None] = []
        if draft.customer_id is not None:
            confidential = repo.customer_is_confidential(self._conn, draft.customer_id)
            structured.append(
                None if confidential is None else repo.level_of(confidential)
            )
        classifier = RuleClassifier(repo.catalog_terms(self._conn))
        return classifier.classify(draft.description, structured_levels=structured)

    def _resolve_part_and_customer(self, draft: NcrDraft) -> NcrDraft:
        part, customer = draft.part_number, draft.customer_id
        if part is not None:
            exists, part_customer = repo.part_customer(self._conn, part)
            if not exists:
                raise Invalid(f"El numero de parte {part!r} no existe")
            if (
                customer is not None
                and part_customer is not None
                and customer != part_customer
            ):
                raise Invalid("El cliente no coincide con el de la parte")
            customer = customer or part_customer
        if customer is not None and not repo.customer_exists(self._conn, customer):
            raise Invalid(f"El cliente {customer!r} no existe")
        return NcrDraft(
            plant_id=draft.plant_id,
            line_id=draft.line_id,
            shift=draft.shift,
            description=draft.description,
            part_number=part,
            customer_id=customer,
        )
