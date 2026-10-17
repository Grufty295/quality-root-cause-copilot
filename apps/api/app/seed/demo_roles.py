"""Slice S1: Cobertura completa de usuarios por rol y planta con credenciales de desarrollo.

Se asegura que existan al menos 2 ingenieros, 1 gerente, 1 inspector y 1 auditor por planta
(JRZ1 y JRZ2), con alcances de línea coherentes y documentados en el README.
"""

from __future__ import annotations

from typing import Sequence
from sqlalchemy import Connection
from app.modules.auth.models import Scope
from app.modules.auth import repository as auth_repo

# Credenciales de desarrollo documentadas (usuario, rol, planta, líneas):
# 
# Planta JRZ1:
# - u-insp-l1 (inspector) - Planta JRZ1, Línea L1
# - u-insp-l2 (inspector) - Planta JRZ1, Línea L2
# - u-ingcal-1 (ingeniero) - Planta JRZ1, Líneas L1, L2 (Planta completa)
# - u-ingcal-2 (ingeniero) - Planta JRZ1, Líneas L1, L2 (Planta completa)
# - u-gercal (gerente) - Planta JRZ1, Líneas L1, L2 (Planta completa)
# - u-auditor (auditor) - Planta JRZ1, Líneas L1, L2 (Planta completa)
#
# Planta JRZ2 (Nueva cobertura JRZ2):
# - u-insp-jrz2-1 (inspector) - Planta JRZ2, Línea L1
# - u-insp-jrz2-2 (inspector) - Planta JRZ2, Línea L2
# - u-ingcal-jrz2-1 (ingeniero) - Planta JRZ2, Línea L1
# - u-ingcal-jrz2-2 (ingeniero) - Planta JRZ2, Línea L2
# - u-gercal-jrz2 (gerente) - Planta JRZ2, Línea L1, L2 (Planta completa)
# - u-auditor-jrz2 (auditor) - Planta JRZ2, Línea L1, L2 (Planta completa)

ADDITIONAL_DEMO_USERS = [
    {
        "username": "u-insp-jrz2-1",
        "display_name": "Inspector JRZ2 L1",
        "role": "inspector",
        "plant_id": "JRZ2",
        "scopes": [("JRZ2", "L1")],
    },
    {
        "username": "u-insp-jrz2-2",
        "display_name": "Inspector JRZ2 L2",
        "role": "inspector",
        "plant_id": "JRZ2",
        "scopes": [("JRZ2", "L2")],
    },
    {
        "username": "u-ingcal-jrz2-1",
        "display_name": "Ingeniero JRZ2 L1",
        "role": "ingeniero",
        "plant_id": "JRZ2",
        "scopes": [("JRZ2", "L1")],
    },
    {
        "username": "u-ingcal-jrz2-2",
        "display_name": "Ingeniero JRZ2 L2",
        "role": "ingeniero",
        "plant_id": "JRZ2",
        "scopes": [("JRZ2", "L2")],
    },
    {
        "username": "u-gercal-jrz2",
        "display_name": "Gerente JRZ2",
        "role": "gerente",
        "plant_id": "JRZ2",
        "scopes": [("JRZ2", "L1"), ("JRZ2", "L2")],
    },
    {
        "username": "u-auditor-jrz2",
        "display_name": "Auditor JRZ2",
        "role": "auditor",
        "plant_id": "JRZ2",
        "scopes": [("JRZ2", "L1"), ("JRZ2", "L2")],
    },
]


def seed_additional_users(conn: Connection) -> int:
    count = 0
    for u in ADDITIONAL_DEMO_USERS:
        user_id = auth_repo.upsert_user(
            conn,
            username=u["username"],
            display_name=u["display_name"],
            role=u["role"],
        )
        auth_repo.replace_scopes(conn, user_id, u["scopes"])
        count += 1
    return count
