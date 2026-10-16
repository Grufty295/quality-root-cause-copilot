"""Lectura de los catálogos del dataset. Funciones puras: no tocan la base.

Fuente: data/seed/estructurados/*.csv, escritos por data/generator. Este módulo
no vive dentro de data/seed porque el generador borra esa carpeta completa
cada vez que corre.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Collection, Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LineDef(_Row):
    id: str
    name: str


class PlantDef(_Row):
    id: str
    name: str
    lines: tuple[LineDef, ...]


PLANTS: tuple[PlantDef, ...] = (
    PlantDef(
        id="JRZ1",
        name="Cablenova México, planta Juárez",
        lines=(LineDef(id="L1", name="Línea 1"), LineDef(id="L2", name="Línea 2")),
    ),
    # Solo para la demo de aislamiento entre plantas (PRD, paso 6). No tiene
    # documentos ni datos de producción.
    PlantDef(
        id="JRZ2",
        name="Planta 2 (demo de aislamiento)",
        lines=(LineDef(id="L1", name="Línea 1"),),
    ),
)


class CustomerRow(_Row):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    is_confidential: bool


class PartRow(_Row):
    part_number: str = Field(min_length=1)
    customer_id: str
    description: str | None = None


class DefectFamilyRow(_Row):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class Catalogs(_Row):
    customers: tuple[CustomerRow, ...]
    parts: tuple[PartRow, ...]
    skipped_parts: tuple[str, ...]
    """Números de parte sin cliente (terminales, cables): `part.customer_id` es
    NOT NULL, así que no se cargan. No son números de parte de cliente."""
    defect_families: tuple[DefectFamilyRow, ...]


def _rows(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: faltan columnas {sorted(missing)}")
        return [
            {k: (v or "").strip() for k, v in row.items() if k is not None}
            for row in reader
        ]


def read_catalogs(estructurados: Path) -> Catalogs:
    customers = tuple(
        CustomerRow(
            id=r["cliente_id"],
            name=r["nombre"],
            # Fail-safe: solo 'interno' o 'publico' bajan la bandera; cualquier otro valor la deja arriba.
            is_confidential=r["confidencialidad"].lower() not in {"interno", "publico"},
        )
        for r in _rows(
            estructurados / "catalogo_clientes.csv",
            {"cliente_id", "nombre", "confidencialidad"},
        )
    )
    by_name = {c.name.casefold(): c.id for c in customers}

    parts: list[PartRow] = []
    skipped: list[str] = []
    for r in _rows(
        estructurados / "catalogo_numeros_parte.csv",
        {"numero_parte", "descripcion", "cliente"},
    ):
        if not r["cliente"]:
            skipped.append(r["numero_parte"])
            continue
        customer_id = by_name.get(r["cliente"].casefold())
        if customer_id is None:
            raise ValueError(
                f"catalogo_numeros_parte.csv: {r['numero_parte']} usa el cliente desconocido {r['cliente']!r}"
            )
        parts.append(
            PartRow(
                part_number=r["numero_parte"],
                customer_id=customer_id,
                description=r["descripcion"] or None,
            )
        )

    families = tuple(
        DefectFamilyRow(id=r["defecto_codigo"], name=r["descripcion"])
        for r in _rows(
            estructurados / "catalogo_defectos.csv", {"defecto_codigo", "descripcion"}
        )
    )
    return Catalogs(
        customers=customers,
        parts=tuple(parts),
        skipped_parts=tuple(skipped),
        defect_families=families,
    )


# ---------------------------------------------------------------------------
# Datos operativos: eventos de defecto y órdenes de mantenimiento
# ---------------------------------------------------------------------------

_SHIFTS = {"T1": 1, "T2": 2, "T3": 3}
_ORDER_TYPES = {"preventivo": "preventivo", "correctivo": "correctivo"}
_ORDER_STATUS = {
    "completada": "completada",
    "reprogramada": "reprogramada",
    "pendiente": "pendiente",
}
_EQUIPMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$")
_MAX_REPORTED_ERRORS = 10


class DefectEventRow(_Row):
    source_id: str
    made_on: date
    """Fecha de fabricación."""
    detected_on: date
    """Cuándo se enteró la planta. Puede ser posterior (cliente, laboratorio)."""
    shift: int
    line_id: str
    station: str
    part_number: str
    defect_family_id: str
    quantity: int = Field(ge=1)
    detection_point: str | None = None
    applicator_id: str | None = None
    cutting_machine_id: str | None = None
    terminal_part_number: str | None = None
    terminal_lot: str | None = None
    cable_part_number: str | None = None


class MaintenanceOrderRow(_Row):
    id: str
    line_id: str
    equipment: str
    order_type: str
    due_date: date
    completed_on: date | None = None
    status: str
    reschedule_reason: str | None = None
    notes: str | None = None
    cycles_at_event: int | None = Field(default=None, ge=0)


class EquipmentRow(_Row):
    id: str
    line_id: str
    kind: str
    terminal_family: str | None = None
    terminal_part_number: str | None = None
    housed_in: str | None = None
    pm_threshold_cycles: int | None = Field(default=None, gt=0)

    @property
    def is_applicator(self) -> bool:
        return self.kind.casefold() == "aplicador"


class CycleRow(_Row):
    day: date
    equipment_id: str
    cycles: int = Field(ge=0)


class CrimpRow(_Row):
    measured_on: date
    shift: int
    line_id: str
    equipment_id: str
    press_id: str
    terminal_part_number: str
    cable_part_number: str
    height_mm: Decimal = Field(gt=0)
    height_lsl: Decimal
    height_usl: Decimal
    pull_n: Decimal = Field(ge=0)
    pull_min_n: Decimal = Field(gt=0)
    action: str | None = None


_CHANGE_KINDS = frozenset(
    {
        "Cambio de herramienta",
        "ECN",
        "Cambio de plantilla",
        "Receta de máquina",
        "Cambio de mano de obra",
    }
)


class ChangeRow(_Row):
    id: str
    changed_on: date
    kind: str
    equipment_ids: tuple[str, ...]
    part_number: str | None = None
    variant: str | None = None
    line_ids: tuple[str, ...]
    previous_revision: str | None = None
    new_revision: str | None = None
    description: str
    board_updated: str | None = None
    test_program_updated: str | None = None
    approved_by_role: str


class LotRow(_Row):
    id: str
    part_number: str
    family: str
    supplier_id: str
    supplier_name: str
    received_on: date
    quantity: int = Field(gt=0)
    inspection_type: str
    inspection_result: str
    consumed_from: date
    consumed_to: date
    status: str


class SupplierRow(_Row):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    supplies: tuple[str, ...]


class ProductionRow(_Row):
    produced_on: date
    shift: int
    line_id: str
    part_number: str
    units: int = Field(gt=0)


class Operational(_Row):
    defect_events: tuple[DefectEventRow, ...] | None
    """None = no había eventos_defecto.csv."""
    maintenance_orders: tuple[MaintenanceOrderRow, ...] | None
    equipment: tuple[EquipmentRow, ...] | None = None
    applicator_cycles: tuple[CycleRow, ...] | None = None
    crimp_measurements: tuple[CrimpRow, ...] | None = None
    changes: tuple[ChangeRow, ...] | None = None
    material_lots: tuple[LotRow, ...] | None = None
    suppliers: tuple[SupplierRow, ...] | None = None
    production: tuple[ProductionRow, ...] | None = None


class _Problems:
    """Junta los problemas de un CSV para mostrarlos todos juntos, no de uno en uno."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.items: list[str] = []

    def add(self, row_no: int, ref: str, message: str) -> None:
        where = f"fila {row_no} ({ref})" if row_no else ref
        self.items.append(f"{where}: {message}")

    def raise_if_any(self) -> None:
        if not self.items:
            return
        shown = self.items[:_MAX_REPORTED_ERRORS]
        more = len(self.items) - len(shown)
        tail = f"\n  … y {more} más" if more > 0 else ""
        raise ValueError(
            f"{self.filename}: {len(self.items)} filas inválidas\n  "
            + "\n  ".join(shown)
            + tail
        )


def _reason(exc: ValueError) -> str:
    """Una línea legible. Con pydantic, el campo y el motivo (no el encabezado genérico)."""
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
            for err in exc.errors(include_url=False)
        )
    return str(exc).splitlines()[0]


def _date(value: str) -> date:
    return date.fromisoformat(value)  # ISO estricto: 2026-04-01


def _opt(value: str) -> str | None:
    return value or None


def read_defect_events(
    path: Path,
    *,
    lines: Collection[str],
    family_ids: Collection[str],
    part_customer: Mapping[str, str],
    equipment: Mapping[str, EquipmentRow] | None = None,
) -> tuple[DefectEventRow, ...]:
    """`part_customer`: número de parte -> nombre del cliente (para detectar filas incoherentes)."""
    required = {
        "evento_id", "fecha_fabricacion", "fecha_deteccion", "turno", "linea",
        "estacion_origen", "aplicador_id", "maquina_corte", "numero_parte", "cliente",
        "defecto_codigo", "cantidad", "numero_parte_terminal", "lote_terminal",
        "numero_parte_cable", "detectado_en",
    }  # fmt: skip
    problems = _Problems(path.name)
    rows: list[DefectEventRow] = []
    seen: set[str] = set()
    for no, r in enumerate(_rows(path, required), start=2):
        ref = r["evento_id"] or "sin id"
        try:
            if not r["evento_id"]:
                raise ValueError("falta evento_id")
            if r["evento_id"] in seen:
                raise ValueError("evento_id repetido")
            seen.add(r["evento_id"])
            made, detected = _date(r["fecha_fabricacion"]), _date(r["fecha_deteccion"])
            if detected < made:
                raise ValueError("se detectó antes de fabricarse")
            if r["turno"] not in _SHIFTS:
                raise ValueError(f"turno desconocido {r['turno']!r}")
            if r["linea"] not in lines:
                raise ValueError(f"línea desconocida {r['linea']!r}")
            if not r["estacion_origen"]:
                raise ValueError("falta estacion_origen")
            if f"-{r['linea']}" not in r["estacion_origen"]:
                raise ValueError(
                    f"la estación {r['estacion_origen']!r} no es de la línea {r['linea']}"
                )
            if r["defecto_codigo"] not in family_ids:
                raise ValueError(f"defecto desconocido {r['defecto_codigo']!r}")
            customer = part_customer.get(r["numero_parte"])
            if customer is None:
                raise ValueError(f"número de parte desconocido {r['numero_parte']!r}")
            if r["cliente"].casefold() != customer.casefold():
                raise ValueError(
                    f"el cliente {r['cliente']!r} no es el de la parte {r['numero_parte']}"
                )
            if r["lote_terminal"] and not r["numero_parte_terminal"]:
                raise ValueError("hay lote de terminal sin número de parte de terminal")
            if equipment is not None:
                if r["aplicador_id"]:
                    _check_equipment(
                        equipment, r["aplicador_id"], r["linea"], applicator=True
                    )
                if r["maquina_corte"]:
                    _check_equipment(equipment, r["maquina_corte"], r["linea"])
            rows.append(
                DefectEventRow(
                    source_id=r["evento_id"],
                    made_on=made,
                    detected_on=detected,
                    shift=_SHIFTS[r["turno"]],
                    line_id=r["linea"],
                    station=r["estacion_origen"],
                    part_number=r["numero_parte"],
                    defect_family_id=r["defecto_codigo"],
                    quantity=int(r["cantidad"]),
                    detection_point=_opt(r["detectado_en"]),
                    applicator_id=_opt(r["aplicador_id"]),
                    cutting_machine_id=_opt(r["maquina_corte"]),
                    terminal_part_number=_opt(r["numero_parte_terminal"]),
                    terminal_lot=_opt(r["lote_terminal"]),
                    cable_part_number=_opt(r["numero_parte_cable"]),
                )
            )
        except ValueError as exc:  # incluye ValidationError
            problems.add(no, ref, _reason(exc))
    problems.raise_if_any()
    if not rows:
        raise ValueError(f"{path.name}: no tiene filas")
    return tuple(rows)


def _check_equipment(
    equipment: Mapping[str, EquipmentRow],
    equipment_id: str,
    line_id: str,
    *,
    applicator: bool = False,
) -> None:
    row = equipment.get(equipment_id)
    if row is None:
        raise ValueError(f"equipo desconocido {equipment_id!r}")
    if applicator and not row.is_applicator:
        raise ValueError(f"{equipment_id} no es un aplicador")
    if row.line_id != line_id:
        raise ValueError(
            f"{equipment_id} es de la línea {row.line_id}, no de {line_id}"
        )


def read_maintenance_orders(
    path: Path,
    *,
    lines: Collection[str],
    equipment: Mapping[str, EquipmentRow] | None = None,
) -> tuple[MaintenanceOrderRow, ...]:
    required = {
        "ot_id", "equipo_id", "linea", "tipo", "fecha_programada", "fecha_ejecucion",
        "estado", "motivo_reprogramacion", "descripcion", "ciclos_al_evento",
    }  # fmt: skip
    problems = _Problems(path.name)
    rows: list[MaintenanceOrderRow] = []
    seen: set[str] = set()
    for no, r in enumerate(_rows(path, required), start=2):
        ref = r["ot_id"] or "sin id"
        try:
            if not r["ot_id"]:
                raise ValueError("falta ot_id")
            if r["ot_id"] in seen:
                raise ValueError("ot_id repetido")
            seen.add(r["ot_id"])
            if not _EQUIPMENT_ID.match(r["equipo_id"]):
                raise ValueError(f"equipo_id inválido {r['equipo_id']!r}")
            if r["linea"] not in lines:
                raise ValueError(f"línea desconocida {r['linea']!r}")
            if equipment is not None:
                _check_equipment(equipment, r["equipo_id"], r["linea"])
            order_type = _ORDER_TYPES.get(r["tipo"].casefold())
            if order_type is None:
                raise ValueError(f"tipo desconocido {r['tipo']!r}")
            status = _ORDER_STATUS.get(r["estado"].casefold())
            if status is None:
                raise ValueError(f"estado desconocido {r['estado']!r}")
            done = _date(r["fecha_ejecucion"]) if r["fecha_ejecucion"] else None
            if (status == "completada") != (done is not None):
                raise ValueError(
                    "una orden completada necesita fecha_ejecucion y las demás no deben tenerla"
                )
            rows.append(
                MaintenanceOrderRow(
                    id=r["ot_id"],
                    line_id=r["linea"],
                    equipment=r["equipo_id"],
                    order_type=order_type,
                    due_date=_date(r["fecha_programada"]),
                    completed_on=done,
                    status=status,
                    reschedule_reason=_opt(r["motivo_reprogramacion"]),
                    notes=_opt(r["descripcion"]),
                    cycles_at_event=int(r["ciclos_al_evento"])
                    if r["ciclos_al_evento"]
                    else None,
                )
            )
        except ValueError as exc:
            problems.add(no, ref, _reason(exc))
    problems.raise_if_any()
    if not rows:
        raise ValueError(f"{path.name}: no tiene filas")
    return tuple(rows)


def read_equipment(path: Path, *, lines: Collection[str]) -> tuple[EquipmentRow, ...]:
    required = {
        "equipo_id", "tipo", "linea", "familia_terminal", "numero_parte_terminal",
        "aloja_en", "umbral_pm_ciclos",
    }  # fmt: skip
    problems = _Problems(path.name)
    rows: list[EquipmentRow] = []
    seen: set[str] = set()
    for no, r in enumerate(_rows(path, required), start=2):
        ref = r["equipo_id"] or "sin id"
        try:
            if not r["equipo_id"]:
                raise ValueError("falta equipo_id")
            if r["equipo_id"] in seen:
                raise ValueError("equipo_id repetido")
            seen.add(r["equipo_id"])
            if r["linea"] not in lines:
                raise ValueError(f"línea desconocida {r['linea']!r}")
            if not r["tipo"]:
                raise ValueError("falta tipo")
            row = EquipmentRow(
                id=r["equipo_id"],
                line_id=r["linea"],
                kind=r["tipo"],
                terminal_family=_opt(r["familia_terminal"]),
                terminal_part_number=_opt(r["numero_parte_terminal"]),
                housed_in=_opt(r["aloja_en"]),
                pm_threshold_cycles=int(r["umbral_pm_ciclos"])
                if r["umbral_pm_ciclos"]
                else None,
            )
            if row.is_applicator and row.pm_threshold_cycles is None:
                raise ValueError("un aplicador necesita umbral_pm_ciclos")
            rows.append(row)
        except ValueError as exc:
            problems.add(no, ref, _reason(exc))
    # Segunda pasada: a qué equipo aloja cada uno.
    ids = {row.id for row in rows}
    for row in rows:
        if row.housed_in is not None and row.housed_in not in ids:
            problems.add(
                0, row.id, f"aloja_en apunta a {row.housed_in!r}, que no existe"
            )
    problems.raise_if_any()
    if not rows:
        raise ValueError(f"{path.name}: no tiene filas")
    return tuple(rows)


def read_applicator_cycles(
    path: Path, *, equipment: Mapping[str, EquipmentRow]
) -> tuple[CycleRow, ...]:
    problems = _Problems(path.name)
    rows: list[CycleRow] = []
    seen: set[tuple[str, str]] = set()
    for no, r in enumerate(_rows(path, {"fecha", "aplicador_id", "ciclos"}), start=2):
        ref = f"{r['aplicador_id'] or 'sin aplicador'} {r['fecha']}"
        try:
            row = equipment.get(r["aplicador_id"])
            if row is None or not row.is_applicator:
                raise ValueError(f"aplicador desconocido {r['aplicador_id']!r}")
            key = (r["aplicador_id"], r["fecha"])
            if key in seen:
                raise ValueError("día repetido para el aplicador")
            seen.add(key)
            rows.append(
                CycleRow(
                    day=_date(r["fecha"]),
                    equipment_id=r["aplicador_id"],
                    cycles=int(r["ciclos"]),
                )
            )
        except ValueError as exc:
            problems.add(no, ref, _reason(exc))
    problems.raise_if_any()
    if not rows:
        raise ValueError(f"{path.name}: no tiene filas")
    return tuple(rows)


_COMBINATION = re.compile(r"^(\S+) / (\S+)$")


def _decimal(value: str, name: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{name} no es un número: {value!r}") from None


def read_crimp_measurements(
    path: Path, *, lines: Collection[str], equipment: Mapping[str, EquipmentRow]
) -> tuple[CrimpRow, ...]:
    """Verifica que el aplicador, su prensa y su terminal coincidan con el catálogo y que los
    resultados OK/NOK del CSV sean los que dicen los valores contra los límites."""
    required = {
        "fecha", "turno", "linea", "aplicador_id", "prensa_id", "combinacion", "altura_mm",
        "altura_lsl", "altura_usl", "resultado_altura", "traccion_n", "traccion_min",
        "resultado_traccion", "accion",
    }  # fmt: skip
    problems = _Problems(path.name)
    rows: list[CrimpRow] = []
    seen: set[tuple[str, ...]] = set()
    for no, r in enumerate(_rows(path, required), start=2):
        ref = f"{r['aplicador_id'] or 'sin aplicador'} {r['fecha']} {r['turno']}"
        try:
            if r["turno"] not in _SHIFTS:
                raise ValueError(f"turno desconocido {r['turno']!r}")
            if r["linea"] not in lines:
                raise ValueError(f"línea desconocida {r['linea']!r}")
            _check_equipment(equipment, r["aplicador_id"], r["linea"], applicator=True)
            applicator = equipment[r["aplicador_id"]]
            if r["prensa_id"] != applicator.housed_in:
                raise ValueError(
                    f"la prensa {r['prensa_id']!r} no es la que aloja a {applicator.id} ({applicator.housed_in})"
                )
            combo = _COMBINATION.match(r["combinacion"])
            if combo is None:
                raise ValueError(f"combinación inválida {r['combinacion']!r}")
            terminal, cable = combo.groups()
            if terminal != applicator.terminal_part_number:
                raise ValueError(
                    f"{applicator.id} crimpa {applicator.terminal_part_number}, no {terminal}"
                )
            height = _decimal(r["altura_mm"], "altura_mm")
            lsl, usl = (
                _decimal(r["altura_lsl"], "altura_lsl"),
                _decimal(r["altura_usl"], "altura_usl"),
            )
            pull, pull_min = (
                _decimal(r["traccion_n"], "traccion_n"),
                _decimal(r["traccion_min"], "traccion_min"),
            )
            if lsl >= usl:
                raise ValueError("el límite inferior de altura no es menor al superior")
            for name, ok, expected in (
                ("altura", r["resultado_altura"], lsl <= height <= usl),
                ("tracción", r["resultado_traccion"], pull >= pull_min),
            ):
                if ok not in ("OK", "NOK"):
                    raise ValueError(f"resultado de {name} desconocido {ok!r}")
                if (ok == "OK") != expected:
                    raise ValueError(
                        f"el resultado de {name} ({ok}) no corresponde a los valores"
                    )
            key = (r["aplicador_id"], r["fecha"], r["turno"], terminal, cable)
            if key in seen:
                raise ValueError("medición repetida")
            seen.add(key)
            rows.append(
                CrimpRow(
                    measured_on=_date(r["fecha"]),
                    shift=_SHIFTS[r["turno"]],
                    line_id=r["linea"],
                    equipment_id=r["aplicador_id"],
                    press_id=r["prensa_id"],
                    terminal_part_number=terminal,
                    cable_part_number=cable,
                    height_mm=height,
                    height_lsl=lsl,
                    height_usl=usl,
                    pull_n=pull,
                    pull_min_n=pull_min,
                    action=_opt(r["accion"]),
                )
            )
        except ValueError as exc:
            problems.add(no, ref, _reason(exc))
    problems.raise_if_any()
    if not rows:
        raise ValueError(f"{path.name}: no tiene filas")
    return tuple(rows)


def _split(value: str) -> tuple[str, ...]:
    """'L1, L2' -> ('L1', 'L2'). Sin repetidos ni elementos vacíos."""
    items = tuple(part.strip() for part in value.split(",") if part.strip())
    if len(set(items)) != len(items):
        raise ValueError(f"elementos repetidos en {value!r}")
    return items


def read_changes(
    path: Path,
    *,
    lines: Collection[str],
    equipment: Mapping[str, EquipmentRow] | None,
) -> tuple[ChangeRow, ...]:
    required = {
        "cambio_id", "fecha", "tipo", "equipo_id", "numero_parte", "variante", "linea",
        "revision_anterior", "revision_nueva", "descripcion", "tablero_actualizado",
        "programa_prueba_actualizado", "aprobado_por_rol",
    }  # fmt: skip
    problems = _Problems(path.name)
    rows: list[ChangeRow] = []
    seen: set[str] = set()
    for no, r in enumerate(_rows(path, required), start=2):
        ref = r["cambio_id"] or "sin id"
        try:
            if r["cambio_id"] in seen:
                raise ValueError("cambio_id repetido")
            seen.add(r["cambio_id"])
            if not r["descripcion"].strip():
                raise ValueError("descripcion vacía")
            if not r["aprobado_por_rol"].strip():
                raise ValueError("aprobado_por_rol vacío")
            if r["tipo"] not in _CHANGE_KINDS:
                raise ValueError(f"tipo desconocido {r['tipo']!r}")
            change_lines = _split(r["linea"])
            if not change_lines:
                raise ValueError("necesita al menos una línea")
            for line in change_lines:
                if line not in lines:
                    raise ValueError(f"línea desconocida {line!r}")
            equipment_ids = _split(r["equipo_id"])
            if equipment is not None:
                for eq in equipment_ids:
                    row = equipment.get(eq)
                    if row is None:
                        raise ValueError(f"equipo desconocido {eq!r}")
                    if row.line_id not in change_lines:
                        raise ValueError(
                            f"{eq} es de la línea {row.line_id}, que el cambio no declara ({r['linea']})"
                        )
            if bool(r["revision_anterior"]) != bool(r["revision_nueva"]):
                raise ValueError(
                    "revision_anterior y revision_nueva van juntas o ninguna"
                )
            if r["revision_anterior"] and r["revision_anterior"] == r["revision_nueva"]:
                raise ValueError("la revisión nueva es igual a la anterior")
            rows.append(
                ChangeRow(
                    id=r["cambio_id"],
                    changed_on=_date(r["fecha"]),
                    kind=r["tipo"],
                    equipment_ids=equipment_ids,
                    part_number=_opt(r["numero_parte"]),
                    variant=_opt(r["variante"]),
                    line_ids=change_lines,
                    previous_revision=_opt(r["revision_anterior"]),
                    new_revision=_opt(r["revision_nueva"]),
                    description=r["descripcion"].strip(),
                    board_updated=_opt(r["tablero_actualizado"]),
                    test_program_updated=_opt(r["programa_prueba_actualizado"]),
                    approved_by_role=r["aprobado_por_rol"].strip(),
                )
            )
        except ValueError as exc:
            problems.add(no, ref, _reason(exc))
    problems.raise_if_any()
    if not rows:
        raise ValueError(f"{path.name}: no tiene filas")
    return tuple(rows)


def read_material_lots(
    path: Path,
    *,
    equipment: Mapping[str, EquipmentRow] | None,
    suppliers: Mapping[str, SupplierRow],
) -> tuple[LotRow, ...]:
    required = {
        "lote_id", "numero_parte", "familia", "proveedor_id", "proveedor", "fecha_recepcion",
        "cantidad", "tipo_inspeccion", "resultado_inspeccion", "consumo_desde", "consumo_hasta",
        "estado",
    }  # fmt: skip
    crimped = (
        {
            (e.terminal_part_number, e.terminal_family)
            for e in equipment.values()
            if e.is_applicator
        }
        if equipment is not None
        else None
    )
    problems = _Problems(path.name)
    rows: list[LotRow] = []
    seen: set[str] = set()
    for no, r in enumerate(_rows(path, required), start=2):
        ref = r["lote_id"] or "sin id"
        try:
            if r["lote_id"] in seen:
                raise ValueError("lote_id repetido")
            seen.add(r["lote_id"])
            supplier = suppliers.get(r["proveedor_id"])
            if supplier is None:
                raise ValueError(f"proveedor desconocido {r['proveedor_id']!r}")
            if r["proveedor"] != supplier.name:
                raise ValueError(
                    f"el proveedor {supplier.id} se llama {supplier.name!r}, no {r['proveedor']!r}"
                )
            if r["numero_parte"] not in supplier.supplies:
                raise ValueError(
                    f"{supplier.name} no suministra {r['numero_parte']} "
                    f"(suministra {', '.join(supplier.supplies)})"
                )
            if crimped is not None and (r["numero_parte"], r["familia"]) not in crimped:
                raise ValueError(
                    f"ningún aplicador crimpa {r['numero_parte']} de la familia {r['familia']}"
                )
            row = LotRow(
                id=r["lote_id"],
                part_number=r["numero_parte"],
                family=r["familia"],
                supplier_id=r["proveedor_id"],
                supplier_name=r["proveedor"],
                received_on=_date(r["fecha_recepcion"]),
                quantity=int(r["cantidad"]),
                inspection_type=r["tipo_inspeccion"],
                inspection_result=r["resultado_inspeccion"],
                consumed_from=_date(r["consumo_desde"]),
                consumed_to=_date(r["consumo_hasta"]),
                status=r["estado"],
            )
            if not row.received_on <= row.consumed_from <= row.consumed_to:
                raise ValueError(
                    "las fechas deben cumplir recepción <= consumo_desde <= consumo_hasta"
                )
            for name in ("inspection_type", "inspection_result", "status"):
                if not getattr(row, name).strip():
                    raise ValueError(f"{name} vacío")
            rows.append(row)
        except ValueError as exc:
            problems.add(no, ref, _reason(exc))
    problems.raise_if_any()
    if not rows:
        raise ValueError(f"{path.name}: no tiene filas")
    return tuple(rows)


def read_suppliers(path: Path) -> tuple[SupplierRow, ...]:
    required = {"proveedor_id", "nombre", "categoria", "suministra"}
    problems = _Problems(path.name)
    rows: list[SupplierRow] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for no, r in enumerate(_rows(path, required), start=2):
        ref = r["proveedor_id"] or "sin id"
        try:
            if r["proveedor_id"] in seen_ids:
                raise ValueError("proveedor_id repetido")
            if r["nombre"] in seen_names:
                raise ValueError(f"nombre repetido {r['nombre']!r}")
            seen_ids.add(r["proveedor_id"])
            seen_names.add(r["nombre"])
            supplies = _split(r["suministra"])
            if not supplies:
                raise ValueError("suministra necesita al menos un número de parte")
            rows.append(
                SupplierRow(
                    id=r["proveedor_id"],
                    name=r["nombre"],
                    category=r["categoria"],
                    supplies=supplies,
                )
            )
        except ValueError as exc:
            problems.add(no, ref, _reason(exc))
    problems.raise_if_any()
    if not rows:
        raise ValueError(f"{path.name}: no tiene filas")
    return tuple(rows)


def read_production(
    path: Path,
    *,
    lines: Collection[str],
    part_customer: Mapping[str, str],
) -> tuple[ProductionRow, ...]:
    required = {
        "fecha",
        "turno",
        "linea",
        "numero_parte",
        "variante",
        "cliente",
        "unidades",
    }
    problems = _Problems(path.name)
    rows: list[ProductionRow] = []
    seen: set[tuple[str, ...]] = set()
    variant_of: dict[str, str] = {}
    for no, r in enumerate(_rows(path, required), start=2):
        ref = f"{r['fecha']} {r['turno']} {r['linea']} {r['numero_parte']}"
        try:
            if r["turno"] not in _SHIFTS:
                raise ValueError(f"turno desconocido {r['turno']!r}")
            if r["linea"] not in lines:
                raise ValueError(f"línea desconocida {r['linea']!r}")
            customer = part_customer.get(r["numero_parte"])
            if customer is None:
                raise ValueError(f"número de parte desconocido {r['numero_parte']!r}")
            if r["cliente"] != customer:
                raise ValueError(
                    f"{r['numero_parte']} es de {customer}, no de {r['cliente']!r}"
                )
            if variant_of.setdefault(r["numero_parte"], r["variante"]) != r["variante"]:
                raise ValueError(
                    f"{r['numero_parte']} aparece con dos variantes "
                    f"({variant_of[r['numero_parte']]!r} y {r['variante']!r})"
                )
            key = (r["fecha"], r["turno"], r["linea"], r["numero_parte"])
            if key in seen:
                raise ValueError("producción repetida")
            seen.add(key)
            rows.append(
                ProductionRow(
                    produced_on=_date(r["fecha"]),
                    shift=_SHIFTS[r["turno"]],
                    line_id=r["linea"],
                    part_number=r["numero_parte"],
                    units=int(r["unidades"]),
                )
            )
        except ValueError as exc:
            problems.add(no, ref, _reason(exc))
    problems.raise_if_any()
    if not rows:
        raise ValueError(f"{path.name}: no tiene filas")
    return tuple(rows)


def _check_events_against_production(
    events: Sequence[DefectEventRow], production: Sequence[ProductionRow]
) -> None:
    """Un defecto necesita producción ese día, turno, línea y parte, y no puede exceder lo producido."""
    units = {
        (p.produced_on, p.shift, p.line_id, p.part_number): p.units for p in production
    }
    defects: dict[tuple[date, int, str, str], int] = {}
    for ev in events:
        key = (ev.made_on, ev.shift, ev.line_id, ev.part_number)
        defects[key] = defects.get(key, 0) + ev.quantity
    problems = _Problems("eventos_defecto.csv (contra produccion.csv)")
    for key, quantity in sorted(defects.items()):
        day, shift, line, part = key
        ref = f"{day} T{shift} {line} {part}"
        produced = units.get(key)
        if produced is None:
            problems.add(0, ref, "hay defectos y no hay producción registrada")
        elif quantity > produced:
            problems.add(
                0, ref, f"{quantity} piezas defectuosas de {produced} producidas"
            )
    problems.raise_if_any()


def _check_events_against_lots(
    events: Sequence[DefectEventRow], lots: Sequence[LotRow]
) -> None:
    """La trazabilidad de los eventos debe cuadrar con los lotes: existe, misma parte, mismo periodo."""
    by_id = {lot.id: lot for lot in lots}
    problems = _Problems("eventos_defecto.csv (contra lotes_material.csv)")
    for ev in events:
        if ev.terminal_lot is None:
            continue
        lot = by_id.get(ev.terminal_lot)
        if lot is None:
            problems.add(
                0,
                ev.source_id,
                f"el lote {ev.terminal_lot!r} no está en lotes_material.csv",
            )
        elif ev.terminal_part_number != lot.part_number:
            problems.add(
                0,
                ev.source_id,
                f"el lote {lot.id} es de {lot.part_number}, no de {ev.terminal_part_number}",
            )
        elif not lot.consumed_from <= ev.made_on <= lot.consumed_to:
            problems.add(
                0,
                ev.source_id,
                f"fabricado el {ev.made_on} fuera de la ventana de consumo del lote {lot.id}"
                f" ({lot.consumed_from} a {lot.consumed_to})",
            )
    problems.raise_if_any()


def read_operational(
    estructurados: Path, catalogs: Catalogs, *, lines: Collection[str]
) -> Operational:
    """Lee lo que exista; un archivo ausente se informa como None, no como error.

    Con el catálogo de equipos presente, los aplicadores y máquinas de los eventos y
    las órdenes se validan contra él (existen y son de la línea que dicen).
    """
    equipment_path = estructurados / "catalogo_equipos.csv"
    cycles_path = estructurados / "ciclos_aplicador.csv"
    events_path = estructurados / "eventos_defecto.csv"
    orders_path = estructurados / "mantenimiento.csv"

    equipment_rows = (
        read_equipment(equipment_path, lines=lines) if equipment_path.exists() else None
    )
    equipment = (
        {e.id: e for e in equipment_rows} if equipment_rows is not None else None
    )
    crimp_path = estructurados / "mediciones_crimpado.csv"
    for dependent in (cycles_path, crimp_path):
        if dependent.exists() and equipment is None:
            raise ValueError(f"{dependent.name} necesita catalogo_equipos.csv")

    changes_path = estructurados / "cambios.csv"
    lots_path = estructurados / "lotes_material.csv"
    suppliers_path = estructurados / "catalogo_proveedores.csv"
    suppliers = read_suppliers(suppliers_path) if suppliers_path.exists() else None
    if lots_path.exists() and suppliers is None:
        raise ValueError(f"{lots_path.name} necesita catalogo_proveedores.csv")
    material_lots = (
        read_material_lots(
            lots_path,
            equipment=equipment,
            suppliers={sup.id: sup for sup in suppliers or ()},
        )
        if lots_path.exists()
        else None
    )
    production_path = estructurados / "produccion.csv"

    customer_of = {c.id: c.name for c in catalogs.customers}
    part_customer = {p.part_number: customer_of[p.customer_id] for p in catalogs.parts}
    defect_events = (
        read_defect_events(
            events_path,
            lines=lines,
            family_ids={f.id for f in catalogs.defect_families},
            part_customer=part_customer,
            equipment=equipment,
        )
        if events_path.exists()
        else None
    )
    if defect_events is not None and material_lots is not None:
        _check_events_against_lots(defect_events, material_lots)
    production = (
        read_production(production_path, lines=lines, part_customer=part_customer)
        if production_path.exists()
        else None
    )
    if defect_events is not None and production is not None:
        _check_events_against_production(defect_events, production)
    return Operational(
        defect_events=defect_events,
        maintenance_orders=read_maintenance_orders(
            orders_path, lines=lines, equipment=equipment
        )
        if orders_path.exists()
        else None,
        equipment=equipment_rows,
        applicator_cycles=read_applicator_cycles(cycles_path, equipment=equipment)
        if cycles_path.exists() and equipment is not None
        else None,
        crimp_measurements=read_crimp_measurements(
            crimp_path, lines=lines, equipment=equipment
        )
        if crimp_path.exists() and equipment is not None
        else None,
        changes=read_changes(changes_path, lines=lines, equipment=equipment)
        if changes_path.exists()
        else None,
        material_lots=material_lots,
        suppliers=suppliers,
        production=production,
    )
