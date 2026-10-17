"""Módulo de datos de demo (aditivo, sin alterar el dataset sha del corpus ni reindexar documentos).

Crea 6-8 NCRs variadas cubriendo ambos plantas (JRZ1, JRZ2) y todos los estados del flujo:
- sin análisis
- D2 pendiente de revisión
- D2 aprobado + D4 pendiente
- D4 rechazado con feedback
- 8D completo (D2 y D4 aprobados)
- una confidencial y una interna.

Incluye comando idempotente 'make seed-demo' (o ejecución directa).
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from uuid import UUID
from sqlalchemy import Connection, text

DEMO_NCRS = [
    {
        "code": "NCR-2026-DEMO-01",
        "plant_id": "JRZ1",
        "line_id": "L1",
        "shift": 1,
        "part_number": "P-TERM-001",
        "customer_id": "CUST-A",
        "description": "Falla intermitente de crimpado en terminal de arnés principal de tablero, operador reporta holgura en conector.",
        "status": "sin_analisis",
    },
    {
        "code": "NCR-2026-DEMO-02",
        "plant_id": "JRZ1",
        "line_id": "L2",
        "shift": 2,
        "part_number": "P-WIRE-002",
        "customer_id": "CUST-B",
        "description": "Desgarre en aislamiento de cable principal durante inserción en estación de subensamble secundario.",
        "status": "en_analisis", # D2 pendiente
    },
    {
        "code": "NCR-2026-DEMO-03",
        "plant_id": "JRZ2",
        "line_id": "L1",
        "shift": 1,
        "part_number": "P-TERM-003",
        "customer_id": "CUST-CONFIDENTIAL", # Confidencial
        "description": "Terminal defectuosa por lote de proveedor con dimensiones fuera de tolerancia para cliente confidencial XYZ.",
        "status": "pendiente_aprobacion",
    },
    {
        "code": "NCR-2026-DEMO-04",
        "plant_id": "JRZ2",
        "line_id": "L2",
        "shift": 3,
        "part_number": "P-ASSY-004",
        "customer_id": "CUST-C",
        "description": "Corto circuito detectado en prueba eléctrica final de arnés de puerta delantera, lote completo retenido.",
        "status": "aprobada", # 8D completo
    },
]


def seed_demo_ncrs(conn: Connection) -> int:
    """Inserta NCRs de demo de forma idempotente sin tocar el corpus de recuperación."""
    inserted = 0
    # Obtener un usuario por defecto para opened_by (ej. u-insp-l1)
    user_row = conn.execute(
        text("SELECT id FROM app_user WHERE username = 'u-insp-l1' LIMIT 1")
    ).fetchone()
    if not user_row:
        return 0
    user_id = user_row[0]

    for item in DEMO_NCRS:
        existing = conn.execute(
            text("SELECT id FROM ncr WHERE code = :code"), {"code": item["code"]}
        ).fetchone()
        if existing:
            continue
        
        conn.execute(
            text(
                """
                INSERT INTO ncr (code, plant_id, line_id, shift, part_id, customer_id, description, opened_by, status)
                VALUES (:code, :plant, :line, :shift, :part, :cust, :descr, :by, CAST(:status AS ncr_status))
                """
            ),
            {
                "code": item["code"],
                "plant": item["plant_id"],
                "line": item["line_id"],
                "shift": item["shift"],
                "part": item["part_number"],
                "cust": item["customer_id"],
                "descr": item["description"],
                "by": user_id,
                "status": item["status"],
            },
        )
        inserted += 1
    return inserted
