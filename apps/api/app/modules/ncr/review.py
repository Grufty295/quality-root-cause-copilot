"""Revision humana de los borradores: editar, rechazar y aprobar una seccion.

Reparto (ver docs/matriz-roles.md):

* el ingeniero edita y puede rechazar;
* el gerente aprueba y tambien puede rechazar, que es su forma de devolver una
  seccion con retroalimentacion para que se corrija antes de aprobarla.

Que solo un ingeniero edite, que solo un gerente apruebe y que quien abrio la NCR
no pueda aprobarla lo impone ademas el trigger section_version_rules en la base.
Aqui se decide el flujo: que version se revisa, en que estado puede hacerse cada
cosa y como cambia el estado de la NCR.

Cada accion exige `based_on_version`, la version que la persona tenia en pantalla.
Sin eso, el gerente podria aprobar un texto distinto del que leyo si el ingeniero
edita entre medias.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.agent.catalog import load_catalog
from app.core.errors import Conflict, Forbidden, Invalid
from app.modules.auth.models import CurrentUser
from app.modules.ncr import repository as repo
from app.modules.ncr.content import validate_content
from app.modules.ncr.models import LatestVersion, SectionView
from app.modules.ncr.service import NcrService

EDIT_ROLES: Final = ("ingeniero",)
REJECT_ROLES: Final = ("ingeniero", "gerente")
APPROVE_ROLES: Final = ("gerente",)

MIN_FEEDBACK_CHARS = 10

# Motivos tipificados del rechazo. Deben coincidir con el CHECK de la migracion 0014
# (section_version_feedback_reason_valid) y con los textos de app/agent/prompts.py.
REJECT_REASONS: Final = (
    "causa_incorrecta",
    "evidencia_insuficiente",
    "cita_irrelevante",
    "contexto_incompleto",
    "redaccion",
    "error_tecnico",
)

_INSUFFICIENT_PRIVILEGE = "42501"


class ReviewService:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._ncrs = NcrService(conn)

    # --- acciones -------------------------------------------------------

    def edit(
        self,
        user: CurrentUser,
        ncr_id: UUID,
        discipline: str,
        based_on: int,
        content: dict[str, Any],
    ) -> SectionView:
        self._require_role(user, EDIT_ROLES, "editar")
        catalog = load_catalog(self._conn, user.id) if discipline == "D4" else None
        validate_content(discipline, content, catalog)
        latest = self._open_for_review(user, ncr_id, discipline, based_on)
        if latest.kind == "aprobacion":
            raise Conflict("La seccion ya esta aprobada")
        return self._write(user, ncr_id, discipline, latest, "edicion", content=content)

    def reject(
        self,
        user: CurrentUser,
        ncr_id: UUID,
        discipline: str,
        based_on: int,
        feedback: str,
        *,
        reason: str | None = None,
    ) -> SectionView:
        self._require_role(user, REJECT_ROLES, "rechazar")
        if reason is not None and reason not in REJECT_REASONS:
            raise Invalid(
                f"Motivo de rechazo desconocido; usa uno de: {', '.join(REJECT_REASONS)}"
            )
        feedback = feedback.strip()
        if len(feedback) < MIN_FEEDBACK_CHARS:
            raise Invalid(
                "Explica el rechazo: el agente regenera con esa retroalimentacion"
            )
        latest = self._open_for_review(user, ncr_id, discipline, based_on)
        if latest.kind == "aprobacion":
            raise Conflict("La seccion ya esta aprobada")
        if latest.kind == "rechazo":
            raise Conflict("La seccion ya fue rechazada y espera una nueva version")
        return self._write(
            user,
            ncr_id,
            discipline,
            latest,
            "rechazo",
            feedback=feedback,
            feedback_reason=reason,
        )

    def approve(
        self, user: CurrentUser, ncr_id: UUID, discipline: str, based_on: int
    ) -> SectionView:
        self._require_role(user, APPROVE_ROLES, "aprobar")
        latest = self._open_for_review(user, ncr_id, discipline, based_on)
        if latest.kind == "aprobacion":
            raise Conflict("La seccion ya esta aprobada")
        if latest.kind == "rechazo" or latest.content is None:
            raise Conflict(
                "No hay un borrador que aprobar: la ultima version es un rechazo"
            )
        # La aprobacion guarda el texto exacto que se aprobo.
        return self._write(
            user, ncr_id, discipline, latest, "aprobacion", content=latest.content
        )

    # --- internos -------------------------------------------------------

    @staticmethod
    def _require_role(user: CurrentUser, allowed: tuple[str, ...], verb: str) -> None:
        if user.role not in allowed:
            raise Forbidden(f"Tu rol no puede {verb} secciones")

    def _open_for_review(
        self, user: CurrentUser, ncr_id: UUID, discipline: str, based_on: int
    ) -> LatestVersion:
        # 404 si no hay alcance sobre la NCR; despues el candado de la fila.
        self._ncrs.get(user, ncr_id)
        repo.lock_ncr(self._conn, ncr_id)
        latest = repo.latest_version(self._conn, ncr_id, discipline)
        if latest is None:
            raise Conflict(f"{discipline} todavia no tiene borrador")
        if latest.version_no != based_on:
            raise Conflict(
                f"La seccion cambio: la version vigente es la {latest.version_no}, no la {based_on}"
            )
        return latest

    def _write(
        self,
        user: CurrentUser,
        ncr_id: UUID,
        discipline: str,
        latest: LatestVersion,
        kind: str,
        *,
        content: dict[str, Any] | None = None,
        feedback: str | None = None,
        feedback_reason: str | None = None,
    ) -> SectionView:
        try:
            repo.insert_version(
                self._conn,
                ncr_id=ncr_id,
                discipline=discipline,
                version_no=latest.version_no + 1,
                kind=kind,
                content=content,
                feedback=feedback,
                feedback_reason=feedback_reason,
                author_id=user.id,
            )
        except DBAPIError as exc:
            # Las reglas del trigger (alcance, rol, quien redacta no aprueba) llegan como 42501.
            if getattr(exc.orig, "sqlstate", None) == _INSUFFICIENT_PRIVILEGE:
                diag = getattr(exc.orig, "diag", None)
                raise Forbidden(
                    getattr(diag, "message_primary", None) or "Sin permiso"
                ) from exc
            raise
        repo.set_status(
            self._conn, ncr_id, status_for(repo.latest_kinds(self._conn, ncr_id))
        )
        section = repo.latest_section(self._conn, ncr_id, discipline)
        assert section is not None  # acaba de insertarse
        return section


def status_for(kinds: list[str]) -> str:
    """Estado de la NCR segun la ultima version de cada disciplina con borrador.

    aprobada             todas aprobadas
    en_analisis          alguna rechazada: espera que el agente regenere
    pendiente_aprobacion el resto: hay borradores o ediciones por aprobar
    """
    if kinds and all(k == "aprobacion" for k in kinds):
        return "aprobada"
    if any(k == "rechazo" for k in kinds):
        return "en_analisis"
    return "pendiente_aprobacion"
