"""Usuarios de demo.

La lista sale de data/seed/estructurados/usuarios_demo.csv, que escribe el
generador desde data/generator/config.py. Así los evals de permisos
(evals/casos_permisos.jsonl) y la base hablan de los mismos usuarios: el
`usuario_id` del dataset es el `username` de app_user.

Roles del dataset -> enum user_role:

    inspector          inspector   piso de producción: inspecciona, evalúa y reporta
    ingeniero_calidad  ingeniero   analiza lo reportado y diseña los planes de calidad
    gerente_calidad    gerente     nivel administrativo del departamento; aprueba
    auditor            auditor     solo lectura

Alcance: si las líneas del usuario son todas las de su planta se guarda como
alcance de planta completa (line_id NULL); si no, una fila por línea. La
diferencia importa: user_can_access(planta, NULL) solo lo concede el alcance de
planta (migración 0003), y es lo que permite consultar los datos de ambas
líneas a la vez.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from app.modules.auth import repository as repo

Role = Literal["inspector", "ingeniero", "gerente", "auditor"]

ROLE_BY_DATASET: dict[str, Role] = {
    "inspector": "inspector",
    "ingeniero_calidad": "ingeniero",
    "gerente_calidad": "gerente",
    "auditor": "auditor",
}

# El CSV no trae nombres para mostrar (el dataset no usa nombres de personas).
DISPLAY_NAMES: dict[str, str] = {
    "u-insp-l1": "Inspector línea 1",
    "u-insp-l2": "Inspector línea 2",
    "u-ingcal-1": "Ingeniero de calidad 1",
    "u-ingcal-2": "Ingeniero de calidad 2",
    "u-gercal": "Gerente de calidad",
    "u-auditor": "Auditor",
}

_REQUIRED_COLUMNS = {"usuario_id", "rol", "lineas"}


class DemoUser(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    username: str = Field(
        min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    )
    display_name: str = Field(min_length=1, max_length=120)
    role: Role
    lines: tuple[str, ...] = Field(min_length=1)
    plant_id: str | None = None
    """None = la planta que se está sembrando (JRZ1 por defecto)."""


OTHER_PLANT_USER = DemoUser(
    username="u-ingcal-jrz2",
    display_name="Ingeniero de calidad (otra planta)",
    role="ingeniero",
    lines=("L1",),
    plant_id="JRZ2",
)
"""No viene del dataset. El guion de la demo (PRD, paso 6) necesita un usuario de
otra planta que busque el mismo caso y no lo encuentre. Quitarlo es borrar esta
entrada y su uso en app.seed.service."""


JRZ2_EXTRA_USERS = (
    DemoUser(
        username="u-insp-jrz2",
        display_name="Inspector línea 1 (JRZ2)",
        role="inspector",
        lines=("L1",),
        plant_id="JRZ2",
    ),
    DemoUser(
        username="u-gercal-jrz2",
        display_name="Gerente de calidad (JRZ2)",
        role="gerente",
        lines=("L1",),
        plant_id="JRZ2",
    ),
    DemoUser(
        username="u-auditor-jrz2",
        display_name="Auditor (JRZ2)",
        role="auditor",
        lines=("L1",),
        plant_id="JRZ2",
    ),
)
"""Completan los 4 roles en JRZ2 para poder demostrar el flujo y el aislamiento."""


def read_roster(path: Path) -> list[DemoUser]:
    """Lee usuarios_demo.csv. Un rol desconocido es un error, no un valor por defecto."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = _REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: faltan columnas {sorted(missing)}")
        users: list[DemoUser] = []
        for line_no, row in enumerate(reader, start=2):
            role = ROLE_BY_DATASET.get(row["rol"].strip())
            if role is None:
                raise ValueError(
                    f"{path.name}, fila {line_no}: rol desconocido {row['rol']!r}"
                )
            username = row["usuario_id"].strip()
            users.append(
                DemoUser(
                    username=username,
                    display_name=DISPLAY_NAMES.get(username, username),
                    role=role,
                    lines=tuple(row["lineas"].split()),
                )
            )
    return users


def scopes_for(
    user: DemoUser, *, plant_id: str, plant_lines: Iterable[str]
) -> list[tuple[str, str | None]]:
    all_lines = set(plant_lines)
    unknown = set(user.lines) - all_lines
    if unknown:
        raise ValueError(
            f"{user.username}: líneas que no existen en {plant_id}: {sorted(unknown)}"
        )
    if set(user.lines) == all_lines:
        return [(plant_id, None)]
    return [(plant_id, line) for line in sorted(user.lines)]


def seed_demo_users(
    conn: Connection,
    users: Sequence[DemoUser],
    *,
    default_plant_id: str,
    lines_by_plant: Mapping[str, set[str]],
) -> int:
    """Crea o actualiza los usuarios y deja exactamente sus alcances. Idempotente."""
    for user in users:
        plant_id = user.plant_id or default_plant_id
        plant_lines = lines_by_plant.get(plant_id)
        if plant_lines is None:
            raise ValueError(f"{user.username}: la planta {plant_id!r} no existe")
        scopes = scopes_for(user, plant_id=plant_id, plant_lines=plant_lines)
        user_id = repo.upsert_user(
            conn, username=user.username, display_name=user.display_name, role=user.role
        )
        repo.replace_scopes(conn, user_id, scopes)
    return len(users)