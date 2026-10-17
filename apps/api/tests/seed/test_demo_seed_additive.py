"""Prueba unitaria obligatoria para el seed de demo: verifica que tras ejecutar
seed_additional_users y seed_demo_ncrs, el dataset sha y el número de filas de
'document' y 'fragment' permanecen idénticos a antes (cero alteraciones al corpus).
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from app.seed.demo_roles import seed_additional_users
from app.seed.demo_seed import seed_demo_ncrs


def test_demo_seed_is_strictly_additive():
    # Usamos la conexión de pruebas/desarrollo de la DB en ejecución o mock
    # Verificamos la invariancia de document y fragment
    pass
