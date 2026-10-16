"""SQL del seed de catálogos. Mismo estilo que los demás repositorios: recibe una
conexión y no hace commit. Todo es upsert: correr el seed dos veces deja lo mismo."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Connection, text

from app.seed.sources import (
    ChangeRow,
    CrimpRow,
    CustomerRow,
    CycleRow,
    DefectEventRow,
    DefectFamilyRow,
    EquipmentRow,
    LotRow,
    MaintenanceOrderRow,
    PartRow,
    PlantDef,
    ProductionRow,
    SupplierRow,
)


def upsert_plants(conn: Connection, plants: Sequence[PlantDef]) -> None:
    for plant in plants:
        conn.execute(
            text(
                "INSERT INTO plant (id, name) VALUES (:id, :name) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"
            ),
            {"id": plant.id, "name": plant.name},
        )
        for line in plant.lines:
            conn.execute(
                text(
                    "INSERT INTO line (id, plant_id, name) VALUES (:id, :plant, :name) "
                    "ON CONFLICT (plant_id, id) DO UPDATE SET name = EXCLUDED.name"
                ),
                {"id": line.id, "plant": plant.id, "name": line.name},
            )


def upsert_customers(conn: Connection, customers: Sequence[CustomerRow]) -> None:
    for c in customers:
        conn.execute(
            text(
                "INSERT INTO customer (id, name, is_confidential) VALUES (:id, :name, :conf) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, is_confidential = EXCLUDED.is_confidential"
            ),
            {"id": c.id, "name": c.name, "conf": c.is_confidential},
        )


def upsert_parts(conn: Connection, parts: Sequence[PartRow]) -> None:
    for p in parts:
        # El número de parte es legible y único; sirve también de id.
        conn.execute(
            text(
                "INSERT INTO part (id, part_number, customer_id, description) VALUES (:pn, :pn, :cust, :descr) "
                "ON CONFLICT (id) DO UPDATE SET customer_id = EXCLUDED.customer_id, description = EXCLUDED.description"
            ),
            {"pn": p.part_number, "cust": p.customer_id, "descr": p.description},
        )


def upsert_defect_families(
    conn: Connection, families: Sequence[DefectFamilyRow]
) -> None:
    for f in families:
        conn.execute(
            text(
                "INSERT INTO defect_family (id, name) VALUES (:id, :name) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"
            ),
            {"id": f.id, "name": f.name},
        )


def lines_by_plant(conn: Connection) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for plant_id, line_id in conn.execute(text("SELECT plant_id, id FROM line")).all():
        result.setdefault(plant_id, set()).add(line_id)
    # Una planta sin líneas también existe.
    for (plant_id,) in conn.execute(text("SELECT id FROM plant")).all():
        result.setdefault(plant_id, set())
    return result


_EVENT_UPSERT = text(
    "INSERT INTO defect_event (source_id, occurred_at, detected_on, plant_id, line_id, shift, part_id, "
    "defect_family_id, station, quantity, detection_point, applicator_id, cutting_machine_id, "
    "terminal_part_number, terminal_lot, cable_part_number) "
    "VALUES (:source_id, CAST(:made AS date)::timestamp AT TIME ZONE 'UTC', :detected, :plant, :line, :shift, "
    ":part, :family, :station, :quantity, :point, :applicator, :cutter, :terminal, :lot, :cable) "
    "ON CONFLICT (source_id) DO UPDATE SET occurred_at = EXCLUDED.occurred_at, "
    "detected_on = EXCLUDED.detected_on, plant_id = EXCLUDED.plant_id, line_id = EXCLUDED.line_id, "
    "shift = EXCLUDED.shift, part_id = EXCLUDED.part_id, defect_family_id = EXCLUDED.defect_family_id, "
    "station = EXCLUDED.station, quantity = EXCLUDED.quantity, detection_point = EXCLUDED.detection_point, "
    "applicator_id = EXCLUDED.applicator_id, cutting_machine_id = EXCLUDED.cutting_machine_id, "
    "terminal_part_number = EXCLUDED.terminal_part_number, terminal_lot = EXCLUDED.terminal_lot, "
    "cable_part_number = EXCLUDED.cable_part_number"
)


def sync_defect_events(
    conn: Connection, plant_id: str, events: Sequence[DefectEventRow]
) -> int:
    """Upsert por `source_id` y borra, en esa planta, lo cargado antes que ya no está en el CSV.

    Devuelve cuántas filas obsoletas se borraron. Las filas sin `source_id`
    (capturadas a mano) no se tocan.
    """
    conn.execute(
        _EVENT_UPSERT,
        [
            {
                "source_id": e.source_id,
                "made": e.made_on.isoformat(),
                "detected": e.detected_on,
                "plant": plant_id,
                "line": e.line_id,
                "shift": e.shift,
                "part": e.part_number,
                "family": e.defect_family_id,
                "station": e.station,
                "quantity": e.quantity,
                "point": e.detection_point,
                "applicator": e.applicator_id,
                "cutter": e.cutting_machine_id,
                "terminal": e.terminal_part_number,
                "lot": e.terminal_lot,
                "cable": e.cable_part_number,
            }
            for e in events
        ],
    )
    removed = conn.execute(
        text(
            "DELETE FROM defect_event WHERE plant_id = :p AND source_id IS NOT NULL "
            "AND source_id <> ALL(CAST(:ids AS text[]))"
        ),
        {"p": plant_id, "ids": [e.source_id for e in events]},
    )
    return removed.rowcount


_ORDER_UPSERT = text(
    "INSERT INTO maintenance_order (id, plant_id, line_id, equipment, order_type, due_date, completed_at, "
    "notes, status, reschedule_reason, cycles_at_event) "
    "VALUES (:id, :plant, :line, :equipment, :type, :due, "
    "CAST(CAST(:done AS date) AS timestamp) AT TIME ZONE 'UTC', :notes, :status, :reason, :cycles) "
    "ON CONFLICT (id) DO UPDATE SET plant_id = EXCLUDED.plant_id, line_id = EXCLUDED.line_id, "
    "equipment = EXCLUDED.equipment, order_type = EXCLUDED.order_type, due_date = EXCLUDED.due_date, "
    "completed_at = EXCLUDED.completed_at, notes = EXCLUDED.notes, status = EXCLUDED.status, "
    "reschedule_reason = EXCLUDED.reschedule_reason, cycles_at_event = EXCLUDED.cycles_at_event"
)


def sync_maintenance_orders(
    conn: Connection, plant_id: str, orders: Sequence[MaintenanceOrderRow]
) -> int:
    """Igual que los eventos: el CSV es la fuente de verdad de las órdenes de la planta."""
    conn.execute(
        _ORDER_UPSERT,
        [
            {
                "id": o.id,
                "plant": plant_id,
                "line": o.line_id,
                "equipment": o.equipment,
                "type": o.order_type,
                "due": o.due_date,
                "done": o.completed_on.isoformat() if o.completed_on else None,
                "notes": o.notes,
                "status": o.status,
                "reason": o.reschedule_reason,
                "cycles": o.cycles_at_event,
            }
            for o in orders
        ],
    )
    removed = conn.execute(
        text(
            "DELETE FROM maintenance_order WHERE plant_id = :p AND id <> ALL(CAST(:ids AS text[]))"
        ),
        {"p": plant_id, "ids": [o.id for o in orders]},
    )
    return removed.rowcount


def sync_equipment(
    conn: Connection,
    plant_id: str,
    equipment: Sequence[EquipmentRow],
    cycles: Sequence[CycleRow] | None,
) -> int:
    """Catálogo de equipos (y, si viene, sus ciclos diarios). Devuelve cuántos equipos se borraron.

    Los ciclos son derivados puros del CSV: si viene, se reemplazan completos para la planta.
    Antes de borrar un equipo obsoleto se borran sus ciclos (la FK lo exige).
    """
    conn.execute(
        text(
            "INSERT INTO equipment (plant_id, id, line_id, kind, terminal_family, terminal_part_number, "
            "housed_in, pm_threshold_cycles) VALUES (:plant, :id, :line, :kind, :family, :terminal, :housed, :thr) "
            "ON CONFLICT (plant_id, id) DO UPDATE SET line_id = EXCLUDED.line_id, kind = EXCLUDED.kind, "
            "terminal_family = EXCLUDED.terminal_family, terminal_part_number = EXCLUDED.terminal_part_number, "
            "housed_in = EXCLUDED.housed_in, pm_threshold_cycles = EXCLUDED.pm_threshold_cycles"
        ),
        [
            {
                "plant": plant_id,
                "id": e.id,
                "line": e.line_id,
                "kind": e.kind,
                "family": e.terminal_family,
                "terminal": e.terminal_part_number,
                "housed": e.housed_in,
                "thr": e.pm_threshold_cycles,
            }
            for e in equipment
        ],
    )
    ids = [e.id for e in equipment]
    if cycles is not None:
        conn.execute(
            text("DELETE FROM applicator_cycles WHERE plant_id = :p"), {"p": plant_id}
        )
        conn.execute(
            text(
                "INSERT INTO applicator_cycles (plant_id, equipment_id, day, cycles) "
                "VALUES (:plant, :eq, :day, :cycles)"
            ),
            [
                {
                    "plant": plant_id,
                    "eq": c.equipment_id,
                    "day": c.day,
                    "cycles": c.cycles,
                }
                for c in cycles
            ],
        )
    conn.execute(
        text(
            "DELETE FROM applicator_cycles WHERE plant_id = :p AND equipment_id <> ALL(CAST(:ids AS text[]))"
        ),
        {"p": plant_id, "ids": ids},
    )
    conn.execute(  # mediciones de equipos que salen del catálogo (como aplicador o como prensa)
        text(
            "DELETE FROM crimp_measurement WHERE plant_id = :p "
            "AND (equipment_id <> ALL(CAST(:ids AS text[])) OR press_id <> ALL(CAST(:ids AS text[])))"
        ),
        {"p": plant_id, "ids": ids},
    )
    removed = conn.execute(
        text(
            "DELETE FROM equipment WHERE plant_id = :p AND id <> ALL(CAST(:ids AS text[]))"
        ),
        {"p": plant_id, "ids": ids},
    )
    return removed.rowcount


def replace_crimp_measurements(
    conn: Connection, plant_id: str, rows: Sequence[CrimpRow]
) -> None:
    """Las mediciones son datos derivados del CSV: se reemplazan completas para la planta."""
    conn.execute(
        text("DELETE FROM crimp_measurement WHERE plant_id = :p"), {"p": plant_id}
    )
    conn.execute(
        text(
            "INSERT INTO crimp_measurement (plant_id, equipment_id, measured_on, shift, terminal_part_number, "
            "cable_part_number, line_id, press_id, height_mm, height_lsl, height_usl, pull_n, pull_min_n, action) "
            "VALUES (:plant, :eq, :day, :shift, :terminal, :cable, :line, :press, :h, :lsl, :usl, :pull, :pmin, :action)"
        ),
        [
            {
                "plant": plant_id,
                "eq": m.equipment_id,
                "day": m.measured_on,
                "shift": m.shift,
                "terminal": m.terminal_part_number,
                "cable": m.cable_part_number,
                "line": m.line_id,
                "press": m.press_id,
                "h": m.height_mm,
                "lsl": m.height_lsl,
                "usl": m.height_usl,
                "pull": m.pull_n,
                "pmin": m.pull_min_n,
                "action": m.action,
            }
            for m in rows
        ],
    )


def replace_change_log(
    conn: Connection, plant_id: str, rows: Sequence[ChangeRow]
) -> None:
    """La bitácora no tiene dependientes: se reemplaza completa para la planta."""
    conn.execute(text("DELETE FROM change_log WHERE plant_id = :p"), {"p": plant_id})
    conn.execute(
        text(
            "INSERT INTO change_log (plant_id, id, changed_on, kind, equipment_ids, part_number, variant, line_ids, "
            "previous_revision, new_revision, description, board_updated, test_program_updated, approved_by_role) "
            "VALUES (:plant, :id, :day, :kind, :eq, :part, :variant, :lines, :prev, :new, :descr, :board, :test, :role)"
        ),
        [
            {
                "plant": plant_id,
                "id": c.id,
                "day": c.changed_on,
                "kind": c.kind,
                "eq": list(c.equipment_ids),
                "part": c.part_number,
                "variant": c.variant,
                "lines": list(c.line_ids),
                "prev": c.previous_revision,
                "new": c.new_revision,
                "descr": c.description,
                "board": c.board_updated,
                "test": c.test_program_updated,
                "role": c.approved_by_role,
            }
            for c in rows
        ],
    )


def replace_material_lots(
    conn: Connection, plant_id: str, rows: Sequence[LotRow]
) -> None:
    conn.execute(text("DELETE FROM material_lot WHERE plant_id = :p"), {"p": plant_id})
    conn.execute(
        text(
            "INSERT INTO material_lot (plant_id, id, part_number, family, supplier_id, received_on, "
            "quantity, inspection_type, inspection_result, consumed_from, consumed_to, status) "
            "VALUES (:plant, :id, :part, :family, :sid, :recv, :qty, :itype, :ires, :cfrom, :cto, :status)"
        ),
        [
            {
                "plant": plant_id,
                "id": lot.id,
                "part": lot.part_number,
                "family": lot.family,
                "sid": lot.supplier_id,
                "recv": lot.received_on,
                "qty": lot.quantity,
                "itype": lot.inspection_type,
                "ires": lot.inspection_result,
                "cfrom": lot.consumed_from,
                "cto": lot.consumed_to,
                "status": lot.status,
            }
            for lot in rows
        ],
    )


def upsert_suppliers(conn: Connection, suppliers: Sequence[SupplierRow]) -> None:
    """Catálogo global, como clientes y partes: se actualiza, no se borra (los lotes lo referencian)."""
    for sup in suppliers:
        conn.execute(
            text(
                "INSERT INTO supplier (id, name, category, supplies) VALUES (:id, :name, :cat, :supplies) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, category = EXCLUDED.category, "
                "supplies = EXCLUDED.supplies"
            ),
            {
                "id": sup.id,
                "name": sup.name,
                "cat": sup.category,
                "supplies": list(sup.supplies),
            },
        )


def replace_production(
    conn: Connection, plant_id: str, rows: Sequence[ProductionRow]
) -> None:
    """La producción es derivada del CSV: se reemplaza completa para la planta."""
    conn.execute(text("DELETE FROM production WHERE plant_id = :p"), {"p": plant_id})
    conn.execute(
        text(
            "INSERT INTO production (plant_id, produced_on, shift, line_id, part_id, units) "
            "VALUES (:plant, :day, :shift, :line, :part, :units)"
        ),
        [
            {
                "plant": plant_id,
                "day": x.produced_on,
                "shift": x.shift,
                "line": x.line_id,
                "part": x.part_number,
                "units": x.units,
            }
            for x in rows
        ],
    )
