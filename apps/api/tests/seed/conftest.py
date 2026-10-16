"""CSV mínimos con la misma forma que escribe data/generator/generate.py."""

from __future__ import annotations

from pathlib import Path

import pytest

CLIENTES = """cliente_id,nombre,tipo,confidencialidad
NOR,Norvane Motors,OEM,confidencial
KES,Kestrel Modules,Tier 1,interno
"""

PARTES = """numero_parte,tipo,descripcion,variante,cliente,confidencialidad
B3-FDH-0451,Arnés,"Arnés de puerta delantera, variante Base",Base,Kestrel Modules,interno
A7-DRH-2210-M,Arnés,"Arnés de puerta delantera, variante Media",Media,Norvane Motors,confidencial
TRM-A-1064,Terminal,"Terminal hembra 0.64 mm, estañada",,,interno
"""

DEFECTOS = """defecto_codigo,descripcion,estacion_origen_tipica
DEF-01,Crimpado fuera de especificación,Crimpado
DEF-02,Continuidad abierta,Prueba eléctrica
"""

USUARIOS = """usuario_id,rol,lineas
u-insp-l1,inspector,L1
u-insp-l2,inspector,L2
u-ingcal-1,ingeniero_calidad,L1 L2
u-gercal,gerente_calidad,L1 L2
u-auditor,auditor,L1 L2
"""


@pytest.fixture
def estructurados(tmp_path: Path) -> Path:
    est = tmp_path / "estructurados"
    est.mkdir()
    for name, body in {
        "catalogo_clientes.csv": CLIENTES,
        "catalogo_numeros_parte.csv": PARTES,
        "catalogo_defectos.csv": DEFECTOS,
        "usuarios_demo.csv": USUARIOS,
    }.items():
        (est / name).write_text(body, encoding="utf-8")
    return est
