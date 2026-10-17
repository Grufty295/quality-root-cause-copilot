"""Tools del agente: funciones de Python de solo lectura.

Las llama el grafo, no el modelo. En el MVP la etapa ya se conoce (D2 necesita el
volumen de defectos; D4 necesita casos similares, el AMEF y el mantenimiento), así
que dejar que el LLM decida qué consultar solo sumaría latencia, costo y superficie
de injection. Aun así cada tool valida sus parámetros como si vinieran del modelo
(el día que sean tool-calls, las validaciones ya están) y comparten un presupuesto
de llamadas por turno.

Alcance: el usuario viene del servidor (`CurrentUser`), nunca de un argumento. Una
línea fuera de su alcance se rechaza con `user_allowed_lines`, no con un WHERE
que el modelo pueda esquivar.

"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import Connection, text

from app.modules.auth.models import CurrentUser
from app.retrieval.models import DocumentKind, SearchHit, SearchMode, SearchQuery
from app.retrieval.service import RetrievalService

MAX_RANGE_DAYS = 400
MAX_ROWS = 25
GroupBy = Literal[
    "familia",
    "estacion",
    "turno",
    "dia",
    "semana",
    "aplicador",
    "lote_terminal",
    "deteccion",
    "parte",
]
MAX_GROUPS = 40
MAX_WEEKS = 13
_UTC_DAY = "(e.occurred_at AT TIME ZONE 'UTC')"
# group_by -> (expresión SQL, condición extra). La condición descarta los eventos que
# no tienen el dato (solo los de crimpado traen aplicador) para no inventar un grupo "sin dato".
_DIMENSIONS: dict[str, tuple[str, str | None]] = {
    "familia": ("coalesce(df.name, e.defect_family_id)", None),
    "estacion": ("coalesce(e.station, '(sin estación)')", None),
    "turno": ("'turno ' || e.shift::text", None),
    "dia": (f"to_char({_UTC_DAY}::date, 'YYYY-MM-DD')", None),
    "semana": (f"to_char(date_trunc('week', {_UTC_DAY}), 'YYYY-MM-DD')", None),
    "aplicador": ("e.applicator_id", "e.applicator_id IS NOT NULL"),
    "lote_terminal": ("e.terminal_lot", "e.terminal_lot IS NOT NULL"),
    "deteccion": ("coalesce(e.detection_point, '(sin dato)')", None),
    "parte": ("coalesce(p.part_number, '(sin parte)')", None),
}
# Dimensiones con denominador propio en `production`; las demás se miden contra la producción de la línea
# (familia, estación, punto de detección) o no tienen denominador (aplicador, lote).
_RATE_KEY = {
    "turno": "'turno ' || shift::text",
    "dia": "to_char(produced_on, 'YYYY-MM-DD')",
    "semana": "to_char(date_trunc('week', produced_on), 'YYYY-MM-DD')",
    "parte": "part_id",
}
_LINE_RATE = frozenset({"familia", "estacion", "deteccion"})
# Las detecciones tardías (cliente, laboratorio) llegan 3 a 10 días después de fabricar. Ojo con la
# redacción de los avisos: una frase como «reclamos de cliente» activa un marcador del clasificador
# y manda el D2 a local aunque el dato sea interno.
DETECTION_LAG_DAYS = 10
_DIM_LABEL = {"aplicador": "aplicador", "lote_terminal": "lote de terminal"}

_POS = "((m.height_mm - m.height_lsl) / (m.height_usl - m.height_lsl))"
_MARGIN = "((m.pull_n - m.pull_min_n) / m.pull_min_n)"
_CRIMP_SUMMARY_SQL = f"""
SELECT m.equipment_id, m.terminal_part_number, m.cable_part_number, count(*)::int,
       avg(m.height_mm)::float, min(m.height_mm)::float, max(m.height_mm)::float,
       avg({_POS})::float, max({_POS})::float, min({_POS})::float,
       count(*) FILTER (WHERE NOT m.height_ok)::int,
       avg(m.pull_n)::float, min(m.pull_n)::float, min(m.pull_min_n)::float,
       avg({_MARGIN})::float, min({_MARGIN})::float,
       count(*) FILTER (WHERE NOT m.pull_ok)::int,
       count(*) FILTER (WHERE m.action ILIKE '%re-medición de la misma pieza%')::int,
       count(*) FILTER (WHERE m.action ILIKE '%nueva muestra%')::int,
       count(*) FILTER (WHERE NOT m.height_ok OR NOT m.pull_ok)::int
FROM crimp_measurement m WHERE {{where}}
GROUP BY m.equipment_id, m.terminal_part_number, m.cable_part_number
ORDER BY avg({_POS}) DESC, m.equipment_id
"""
_CRIMP_WEEKLY_SQL = f"""
WITH w AS (
    SELECT date_trunc('week', m.measured_on)::date AS week, count(*)::int AS n,
           avg({_POS})::float AS pos, max({_POS})::float AS pos_max, avg({_MARGIN})::float AS margin,
           count(*) FILTER (WHERE NOT m.height_ok)::int AS nok_h, count(*) FILTER (WHERE NOT m.pull_ok)::int AS nok_p
    FROM crimp_measurement m WHERE {{where}} GROUP BY 1)
SELECT week, n, pos, pos_max, margin, nok_h, nok_p, (count(*) OVER ())::int FROM w
ORDER BY week DESC LIMIT :lim
"""

_WEAR_SQL = """
SELECT a.id, a.terminal_family, a.terminal_part_number, a.housed_in, a.pm_threshold_cycles,
       s.id, s.order_type, s.done, c.total, c.days, c.first_day, c.last_day, p.open_pm
FROM equipment a
LEFT JOIN LATERAL (
    SELECT m.id, m.order_type, (m.completed_at AT TIME ZONE 'UTC')::date AS done
    FROM maintenance_order m
    WHERE m.plant_id = a.plant_id AND m.equipment = a.id AND m.status = 'completada'
      AND (m.completed_at AT TIME ZONE 'UTC')::date <= :ref
    ORDER BY m.completed_at DESC, m.id DESC LIMIT 1
) s ON true
LEFT JOIN LATERAL (
    SELECT coalesce(sum(ac.cycles), 0)::bigint AS total, count(*)::int AS days,
           min(ac.day) AS first_day, max(ac.day) AS last_day
    FROM applicator_cycles ac
    WHERE ac.plant_id = a.plant_id AND ac.equipment_id = a.id AND ac.day <= :ref
      AND (s.done IS NULL OR ac.day > s.done)
) c ON true
LEFT JOIN LATERAL (
    SELECT array_agg(m.id || ' (vence ' || m.due_date || ')' ORDER BY m.due_date) AS open_pm
    FROM maintenance_order m
    WHERE m.plant_id = a.plant_id AND m.equipment = a.id AND m.order_type = 'preventivo'
      AND m.due_date <= :ref AND (s.done IS NULL OR m.due_date > s.done)
      AND (m.status <> 'completada' OR (m.completed_at AT TIME ZONE 'UTC')::date > :ref)
) p ON true
WHERE a.plant_id = :p AND a.line_id = :l AND lower(a.kind) = 'aplicador'
  AND (CAST(:eq AS text) IS NULL OR a.id = :eq)
ORDER BY a.id
"""
_EQUIPMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$")

CASE_KINDS = (DocumentKind.EIGHT_D, DocumentKind.NCR)
CONTROL_KINDS = (
    DocumentKind.AMEF,
    DocumentKind.PLAN_CONTROL,
    DocumentKind.INSTRUCCION,
    DocumentKind.SOP,
)


class ToolError(Exception):
    """Parámetros inválidos, fuera de alcance o presupuesto agotado. El mensaje es apto para la traza."""


@dataclass
class ToolBudget:
    max_calls: int = 8
    used: int = 0

    def spend(self, tool: str) -> None:
        if self.used >= self.max_calls:
            raise ToolError(
                f"límite de {self.max_calls} llamadas por turno alcanzado ({tool})"
            )
        self.used += 1


@dataclass(frozen=True)
class ToolOutput:
    tool: str
    params: dict[str, str]
    text: str


@dataclass
class QualityTools:
    conn: Connection
    user: CurrentUser
    retrieval: RetrievalService
    budget: ToolBudget = field(default_factory=ToolBudget)
    as_of: date | None = None
    today: date = field(default_factory=lambda: datetime.now(UTC).date())
    exclude_sources: tuple[str, ...] = ()
    """Documentos que la recuperación no devuelve (el propio caso en un replay)."""
    controls_mode: SearchMode = "hybrid"
    """Modo de `search_controls`. Distinto de `hybrid` solo en los experimentos del eval."""

    # ------------------------------------------------------------------ datos

    def defect_summary(
        self,
        plant_id: str,
        line_id: str,
        date_from: date,
        date_to: date,
        *,
        shift: int | None = None,
        group_by: GroupBy = "estacion",
    ) -> ToolOutput:
        """Piezas defectuosas fabricadas en el rango y conocidas al corte (`as_of`).

        El rango es de fabricación; el corte es de detección: un defecto que llegó por
        el cliente diez días después no existe todavía para un análisis hecho antes.
        """
        self.budget.spend("get_defect_summary")
        start, end, date_to = self._window(date_from, date_to)
        self._check_line(plant_id, line_id)
        if shift is not None and shift not in (1, 2, 3):
            raise ToolError("el turno debe ser 1, 2 o 3")
        expr, needs_value = _DIMENSIONS[group_by]
        by_time = group_by in ("dia", "semana")
        where = (
            "e.plant_id = :p AND e.line_id = :l AND e.occurred_at >= :s AND e.occurred_at < :e "
            "AND e.detected_on <= :known AND (CAST(:shift AS smallint) IS NULL OR e.shift = :shift)"
        )
        binds = {
            "p": plant_id,
            "l": line_id,
            "s": start,
            "e": end,
            "known": self._limit(),
            "shift": shift,
            "lim": MAX_GROUPS,
        }
        rows = self.conn.execute(
            text(
                f"WITH g AS (SELECT {expr} AS k, sum(e.quantity)::int AS n FROM defect_event e "
                "LEFT JOIN defect_family df ON df.id = e.defect_family_id "
                "LEFT JOIN part p ON p.id = e.part_id "
                f"WHERE {where}{' AND ' + needs_value if needs_value else ''} GROUP BY 1) "
                "SELECT k, n, (sum(n) OVER ())::int, (count(*) OVER ())::int FROM g "
                f"ORDER BY {'k DESC' if by_time else 'n DESC, k'} LIMIT :lim"
            ),
            binds,
        ).all()
        params = {
            "linea": line_id,
            "desde": date_from.isoformat(),
            "hasta": date_to.isoformat(),
            "agrupar_por": group_by,
            **({"turno": str(shift)} if shift else {}),
        }
        head = f"Defectos de la línea {line_id} del {date_from} al {date_to}"
        head += f", turno {shift}" if shift else ", todos los turnos"
        if self.as_of:
            head += f", detectados hasta {self.as_of}"
        if not rows:
            return ToolOutput(
                "get_defect_summary",
                params,
                f"{head}: sin eventos registrados en ese rango.",
            )
        total, groups = rows[0][2], rows[0][3]
        shown = (
            list(reversed(rows)) if by_time else rows
        )  # cronológico si es por tiempo
        lines = [f"{head}, por {group_by} (total {total} piezas):"]
        units, line_units = self._production(
            plant_id, line_id, date_from, date_to, shift, group_by
        )
        for k, n, *_ in shown:
            entry = f"- {k}: {n} ({100 * n / total:.1f}%)"
            base = (
                units.get(k)
                if units is not None
                else line_units
                if group_by in _LINE_RATE
                else None
            )
            if base:
                entry += f" · {1000 * n / base:.2f} por mil de {base:,} unidades"
            lines.append(entry)
        if line_units is not None:
            lines.append(
                f"Producción de la línea en el rango: {line_units:,} unidades"
                + (
                    f"; tasa global {1000 * total / line_units:.2f} por mil."
                    if group_by not in ("aplicador", "lote_terminal")
                    else "."
                )
            )
            if group_by in _LINE_RATE:
                lines.append(
                    "(la tasa de cada grupo es contra la producción de toda la línea)"
                )
        else:
            lines.append("Sin producción registrada en el rango: no hay tasas.")
        if date_to > self._limit() - timedelta(days=DETECTION_LAG_DAYS):
            lines.append(
                f"Aviso: los últimos {DETECTION_LAG_DAYS} días antes del corte pueden estar subestimados: "
                "las detecciones tardías (cliente, laboratorio) llegan hasta ese tiempo después de fabricar."
            )
        if groups > len(rows):
            which = "los más recientes" if by_time else "los de mayor cantidad"
            lines.append(f"(se muestran {len(rows)} de {groups} grupos, {which})")
        if needs_value:
            overall = self.conn.execute(
                text(
                    f"SELECT coalesce(sum(e.quantity), 0)::int FROM defect_event e WHERE {where}"
                ),
                binds,
            ).scalar_one()
            lines.append(
                f"Solo cuentan los eventos con {_DIM_LABEL[group_by]} registrado: "
                f"{total} de {overall} piezas del rango."
            )
        return ToolOutput("get_defect_summary", params, "\n".join(lines))

    def _production(
        self,
        plant_id: str,
        line_id: str,
        date_from: date,
        date_to: date,
        shift: int | None,
        group_by: str,
    ) -> tuple[dict[str, int] | None, int | None]:
        """(unidades por grupo si la dimensión las tiene, unidades de la línea). None = no hay producción."""
        binds = {
            "p": plant_id,
            "l": line_id,
            "f": date_from,
            "t": date_to,
            "shift": shift,
        }
        where = (
            "plant_id = :p AND line_id = :l AND produced_on BETWEEN :f AND :t "
            "AND (CAST(:shift AS smallint) IS NULL OR shift = :shift)"
        )
        total = self.conn.execute(
            text(f"SELECT sum(units)::int FROM production WHERE {where}"), binds
        ).scalar_one()
        if total is None:
            return None, None
        key = _RATE_KEY.get(group_by)
        if key is None:
            return None, total
        rows = self.conn.execute(
            text(
                f"SELECT {key}, sum(units)::int FROM production WHERE {where} GROUP BY 1"
            ),
            binds,
        ).all()
        return {k: n for k, n in rows}, total

    def maintenance_history(
        self,
        plant_id: str,
        line_id: str,
        date_from: date,
        date_to: date,
        *,
        equipment: str | None = None,
    ) -> ToolOutput:
        """Órdenes de mantenimiento con su estado al corte, de la más antigua a la más reciente."""
        self.budget.spend("get_maintenance_history")
        _, _, date_to = self._window(date_from, date_to)
        self._check_line(plant_id, line_id)
        if equipment is not None and not _EQUIPMENT.match(equipment):
            raise ToolError("identificador de equipo inválido")
        known = self._limit()
        rows = self.conn.execute(
            text(
                "SELECT id, equipment, order_type, due_date, (completed_at AT TIME ZONE 'UTC')::date, "
                "status, reschedule_reason, cycles_at_event, notes FROM maintenance_order "
                "WHERE plant_id = :p AND line_id = :l "
                "AND ((due_date BETWEEN :f AND :t) OR ((completed_at AT TIME ZONE 'UTC')::date BETWEEN :f AND :t)) "
                "AND (CAST(:eq AS text) IS NULL OR equipment = :eq) "
                "ORDER BY due_date DESC NULLS LAST, id DESC LIMIT :lim"
            ),
            {
                "p": plant_id,
                "l": line_id,
                "f": date_from,
                "t": date_to,
                "eq": equipment,
                "lim": MAX_ROWS + 1,
            },
        ).all()
        params = {
            "linea": line_id,
            "desde": date_from.isoformat(),
            "hasta": date_to.isoformat(),
            **({"equipo": equipment} if equipment else {}),
        }
        head = f"Órdenes de mantenimiento de la línea {line_id} del {date_from} al {date_to}"
        head += f", equipo {equipment}" if equipment else ""
        if not rows:
            return ToolOutput(
                "get_maintenance_history", params, f"{head}: sin órdenes en ese rango."
            )
        truncated = len(rows) > MAX_ROWS
        lines = [f"{head}:"]
        for oid, eq, kind, due, done, status, reason, cycles, notes in reversed(
            rows[:MAX_ROWS]
        ):
            # Una ejecución posterior al corte todavía no ocurre: la orden sigue sin hacerse.
            if done is not None and done > known:
                done, cycles = None, None
                status = "pendiente"
            line = (
                f"- {oid} · {eq} · {kind} · vence {due or 's/f'} · "
                f"{_maint_status(due, done, known, status, cycles)}"
            )
            if reason:
                line += f" · motivo: {reason[:160]}"
            if notes:
                line += f" · {notes[:160]}"
            lines.append(line)
        if truncated:
            lines.append(
                f"(se muestran las {MAX_ROWS} más recientes; hay órdenes más antiguas)"
            )
        return ToolOutput("get_maintenance_history", params, "\n".join(lines))

    def applicator_wear(
        self,
        plant_id: str,
        line_id: str,
        *,
        equipment: str | None = None,
        on: date | None = None,
    ) -> ToolOutput:
        """Ciclos de cada aplicador desde su último servicio completado, contra el umbral de PM.

        El contador se reinicia con cada servicio (preventivo o correctivo): son los ciclos
        de los días posteriores al servicio hasta `on` (por omisión, el corte). Un servicio
        completado después de `on` todavía no cuenta. Las PM sin ejecutar posteriores al
        último servicio se listan: son la causa típica de un aplicador pasado de umbral.
        """
        self.budget.spend("get_applicator_wear")
        self._check_line(plant_id, line_id)
        if equipment is not None and not _EQUIPMENT.match(equipment):
            raise ToolError("identificador de equipo inválido")
        known = self._limit()
        if on is not None and on > known:
            raise ToolError("la fecha está en el futuro")
        ref = on or known
        rows = self.conn.execute(
            text(_WEAR_SQL),
            {"p": plant_id, "l": line_id, "eq": equipment, "ref": ref},
        ).all()
        params = {
            "linea": line_id,
            "al": ref.isoformat(),
            **({"equipo": equipment} if equipment else {}),
        }
        head = f"Desgaste de aplicadores de la línea {line_id} al {ref}"
        if not rows:
            return ToolOutput(
                "get_applicator_wear",
                params,
                f"{head}: no hay aplicadores registrados con ese filtro.",
            )
        report: list[tuple[float, str]] = []
        for row in rows:
            report.append(self._wear_line(row, ref))
        report.sort(key=lambda item: -item[0])
        lines = [f"{head} (los ciclos se reinician con cada servicio completado):"]
        lines += [line for _, line in report]
        return ToolOutput("get_applicator_wear", params, "\n".join(lines))

    @staticmethod
    def _wear_line(row, ref: date) -> tuple[float, str]:
        (eq, family, terminal, press, threshold, svc_id, svc_kind, svc_day,
         total, days, first_day, last_day, open_pm) = row  # fmt: skip
        who = f"{eq} (familia {family}, {terminal}, prensa {press})"
        if last_day is None:
            return 0.0, f"- {who}: sin ciclos registrados hasta {ref}."
        since = (
            f"desde el último servicio ({svc_kind} {svc_id}, {svc_day})"
            if svc_id
            else f"desde el inicio de los datos ({first_day}); no hay servicio previo registrado"
        )
        ratio = total / threshold
        verdict = f"{ratio:.0%} del umbral de PM de {threshold:,}" + (
            f", EXCEDIDO por {total - threshold:,} ciclos" if total > threshold else ""
        )
        line = f"- {who}: {total:,} ciclos {since} = {verdict}."
        if open_pm:
            line += f" PM sin ejecutar desde entonces: {', '.join(open_pm)}."
        notes = []
        start = max(svc_day + timedelta(days=1), first_day) if svc_day else first_day
        missing = (last_day - start).days + 1 - days
        if missing > 0:
            notes.append(f"faltan {missing} días de ciclos en ese periodo")
        if (ref - last_day).days > 1:
            notes.append(f"los ciclos registrados llegan al {last_day}")
        if notes:
            line += f" ({'; '.join(notes)})"
        return ratio, line

    def change_log(
        self,
        plant_id: str,
        line_id: str,
        date_from: date,
        date_to: date,
        *,
        equipment: str | None = None,
    ) -> ToolOutput:
        """Cambios de proceso, receta, herramienta, plantilla, mano de obra y ECN, hasta el corte."""
        self.budget.spend("get_change_log")
        _, _, date_to = self._window(date_from, date_to)
        self._check_line(plant_id, line_id)
        if equipment is not None and not _EQUIPMENT.match(equipment):
            raise ToolError("identificador de equipo inválido")
        rows = self.conn.execute(
            text(
                "SELECT id, changed_on, kind, equipment_ids, part_number, variant, line_ids, previous_revision, "
                "new_revision, description, board_updated, test_program_updated, approved_by_role "
                "FROM change_log WHERE plant_id = :p AND :l = ANY(line_ids) "
                "AND changed_on BETWEEN :f AND :t "
                "AND (CAST(:eq AS text) IS NULL OR :eq = ANY(equipment_ids)) "
                "ORDER BY changed_on DESC, id DESC LIMIT :lim"
            ),
            {
                "p": plant_id,
                "l": line_id,
                "f": date_from,
                "t": date_to,
                "eq": equipment,
                "lim": MAX_ROWS + 1,
            },
        ).all()
        params = {
            "linea": line_id,
            "desde": date_from.isoformat(),
            "hasta": date_to.isoformat(),
            **({"equipo": equipment} if equipment else {}),
        }
        head = f"Cambios que tocan la línea {line_id} del {date_from} al {date_to}"
        head += f", equipo {equipment}" if equipment else ""
        if not rows:
            return ToolOutput(
                "get_change_log",
                params,
                f"{head}: sin cambios registrados en ese rango.",
            )
        lines = [f"{head}:"]
        for row in reversed(rows[:MAX_ROWS]):
            lines.append(_change_line(row))
        if len(rows) > MAX_ROWS:
            lines.append(
                f"(se muestran los {MAX_ROWS} más recientes; hay cambios más antiguos)"
            )
        return ToolOutput("get_change_log", params, "\n".join(lines))

    def material_lots(
        self,
        plant_id: str,
        line_id: str,
        date_from: date,
        date_to: date,
        *,
        part_number: str | None = None,
    ) -> ToolOutput:
        """Lotes de terminal que se consumieron en el rango, con su inspección de recibo.

        Los lotes son de la planta: los consumen todas las líneas, así que no se filtran por
        línea (`line_id` solo comprueba el alcance del usuario). Lo que pasó después del corte
        no se muestra: un lote cuyo consumo termina después sigue "en consumo", sin fecha de fin
        ni estado final.
        """
        self.budget.spend("get_material_lots")
        _, _, date_to = self._window(date_from, date_to)
        self._check_line(plant_id, line_id)
        if part_number is not None and not _EQUIPMENT.match(part_number):
            raise ToolError("número de parte inválido")
        known = self._limit()
        rows = self.conn.execute(
            text(
                "SELECT m.id, m.part_number, s.name, m.received_on, m.quantity, m.inspection_type, "
                "m.inspection_result, m.consumed_from, m.consumed_to, m.status FROM material_lot m "
                "JOIN supplier s ON s.id = m.supplier_id "
                "WHERE m.plant_id = :p AND m.consumed_from <= :t AND m.consumed_to >= :f AND m.received_on <= :known "
                "AND (CAST(:part AS text) IS NULL OR m.part_number = :part) "
                "ORDER BY m.consumed_from DESC, m.id DESC LIMIT :lim"
            ),
            {
                "p": plant_id,
                "f": date_from,
                "t": date_to,
                "known": known,
                "part": part_number,
                "lim": MAX_ROWS + 1,
            },
        ).all()
        params = {
            "linea": line_id,
            "desde": date_from.isoformat(),
            "hasta": date_to.isoformat(),
            **({"parte": part_number} if part_number else {}),
        }
        head = f"Lotes de terminal consumidos del {date_from} al {date_to}"
        head += f", parte {part_number}" if part_number else ""
        if not rows:
            return ToolOutput(
                "get_material_lots", params, f"{head}: sin lotes en ese rango."
            )
        note = (
            "los lotes los consumen todas las líneas; el defecto de un lote se ve con "
            "get_defect_summary agrupado por lote"
        )
        lines = [f"{head} ({note}):"]
        for row in reversed(rows[:MAX_ROWS]):
            lines.append(_lot_line(row, known))
        if len(rows) > MAX_ROWS:
            lines.append(
                f"(se muestran los {MAX_ROWS} más recientes; hay lotes más antiguos)"
            )
        return ToolOutput("get_material_lots", params, "\n".join(lines))

    def crimp_summary(
        self,
        plant_id: str,
        line_id: str,
        date_from: date,
        date_to: date,
        *,
        equipment: str | None = None,
    ) -> ToolOutput:
        """Altura y tracción de crimpado por aplicador en el rango, hasta el corte.

        La altura se resume como posición dentro de su banda de especificación (0 = límite
        inferior, 1 = superior) y la tracción como margen sobre el mínimo: así se ven
        derivas hacia un límite semanas antes de la primera pieza fuera de especificación,
        y valen para familias con bandas distintas. Con `equipment` agrega la tendencia semanal.
        """
        self.budget.spend("get_crimp_measurements")
        _, _, date_to = self._window(date_from, date_to)
        self._check_line(plant_id, line_id)
        if equipment is not None and not _EQUIPMENT.match(equipment):
            raise ToolError("identificador de equipo inválido")
        binds = {
            "p": plant_id,
            "l": line_id,
            "f": date_from,
            "t": date_to,
            "eq": equipment,
            "lim": MAX_WEEKS,
        }
        where = (
            "m.plant_id = :p AND m.line_id = :l AND m.measured_on BETWEEN :f AND :t "
            "AND (CAST(:eq AS text) IS NULL OR m.equipment_id = :eq)"
        )
        rows = self.conn.execute(
            text(_CRIMP_SUMMARY_SQL.format(where=where)), binds
        ).all()
        params = {
            "linea": line_id,
            "desde": date_from.isoformat(),
            "hasta": date_to.isoformat(),
            **({"equipo": equipment} if equipment else {}),
        }
        head = (
            f"Mediciones de crimpado de la línea {line_id} del {date_from} al {date_to}"
        )
        head += f", equipo {equipment}" if equipment else ""
        if not rows:
            return ToolOutput(
                "get_crimp_measurements",
                params,
                f"{head}: sin mediciones en ese rango.",
            )
        legend = (
            "Posición de altura: 0 = límite inferior, 1 = superior (fuera de [0, 1] es NOK). "
            "Margen de tracción: (medida − mínimo) / mínimo (negativo = bajo el mínimo)."
        )
        lines = [f"{head}. {legend}"]
        for r in rows:
            lines.append(_crimp_line(r))
        if equipment is not None:
            weeks = self.conn.execute(
                text(_CRIMP_WEEKLY_SQL.format(where=where)), binds
            ).all()
            if weeks:
                lines.append("Tendencia semanal (lunes de la semana):")
                lines += [_crimp_week_line(w) for w in reversed(weeks)]
                total = weeks[0][-1]
                if total > len(weeks):
                    lines.append(
                        f"(se muestran las {len(weeks)} semanas más recientes de {total})"
                    )
        return ToolOutput("get_crimp_measurements", params, "\n".join(lines))

    # ------------------------------------------------------------------ recuperación

    def search_cases(self, query: str, *, top_k: int = 5) -> list[SearchHit]:
        """8Ds y NCR históricas parecidas (solo lo que el usuario puede ver)."""
        self.budget.spend("search_similar_cases")
        return self.retrieval.search(
            self.user,
            SearchQuery(
                text=query,
                top_k=top_k,
                as_of=self.as_of,
                kinds=CASE_KINDS,
                exclude_sources=self.exclude_sources,
            ),
        )

    def search_controls(self, query: str, *, top_k: int = 6) -> list[SearchHit]:
        """Filas del AMEF, plan de control, instrucciones y SOPs relacionados."""
        self.budget.spend("search_amef_controls")
        return self.retrieval.search(
            self.user,
            SearchQuery(
                text=query,
                top_k=top_k,
                as_of=self.as_of,
                kinds=CONTROL_KINDS,
                exclude_sources=self.exclude_sources,
                mode=self.controls_mode,
            ),
        )

    def linked_case_causes(
        self, ocho_ds: Sequence[str], *, limit: int = 12
    ) -> list[SearchHit]:
        """Sección D4 (causa) de 8Ds ya identificados por el grafo, no por el LLM.

        La consulta del agente describe el síntoma y trae D2 o la NCR que cita el 8D, nunca
        la sección con la causa: esta llamada sigue ese enlace. Mismos permisos y corte.
        """
        self.budget.spend("get_linked_8d_causes")
        return self.retrieval.sections(
            self.user,
            ocho_ds,
            ("D4",),
            kinds=(DocumentKind.EIGHT_D,),
            as_of=self.as_of,
            exclude_sources=self.exclude_sources,
            limit=limit,
        )

    # ------------------------------------------------------------------ validación

    def _window(
        self, date_from: date, date_to: date
    ) -> tuple[datetime, datetime, date]:
        if date_to < date_from:
            raise ToolError("la fecha final es anterior a la inicial")
        if (date_to - date_from).days > MAX_RANGE_DAYS:
            raise ToolError(f"el rango máximo es de {MAX_RANGE_DAYS} días")
        limit = self._limit()
        if date_from > limit:
            raise ToolError("el rango empieza en el futuro")
        date_to = min(date_to, limit)  # nunca se ve más allá de `as_of`
        return (
            datetime.combine(date_from, time.min, UTC),
            datetime.combine(date_to + timedelta(days=1), time.min, UTC),
            date_to,
        )

    def _limit(self) -> date:
        """Hasta cuándo se sabe: `as_of` si se pidió, y nunca más allá de hoy."""
        return min(self.as_of, self.today) if self.as_of else self.today

    def _check_line(self, plant_id: str, line_id: str) -> None:
        allowed = set(
            self.conn.execute(
                text("SELECT user_allowed_lines(CAST(:u AS uuid), :p)"),
                {"u": self.user.id, "p": plant_id},
            ).scalars()
        )
        if line_id not in allowed:
            raise ToolError(
                "la línea está fuera de tu alcance o no existe en esa planta"
            )


def _maint_status(
    due: date | None, done: date | None, ref: date, status: str, cycles: int | None
) -> str:
    if done is not None:
        text_ = f"completada el {done}"
        if due is not None and done > due:
            text_ += f" con {(done - due).days} días de retraso"
        if cycles is not None:
            text_ += f", a los {cycles:,} ciclos"
        return text_
    if status == "reprogramada":
        return "REPROGRAMADA, no se ejecutó en la fecha programada"
    if due is not None and due < ref:
        return f"VENCIDA sin completar ({(ref - due).days} días)"
    return "pendiente"


def _crimp_line(r) -> str:
    (eq, terminal, cable, n, h_avg, h_min, h_max, pos_avg, pos_max, pos_min, nok_h,
     p_avg, p_min, p_spec, mg_avg, mg_min, nok_p, remeasured, resampled, nok_rows) = r  # fmt: skip
    line = (
        f"- {eq} ({terminal} / {cable}): {n} mediciones. "
        f"Altura: media {h_avg:.3f} mm [{h_min:.3f}–{h_max:.3f}], posición media {pos_avg:.2f} "
        f"(mín {pos_min:.2f}, máx {pos_max:.2f}), {nok_h} NOK. "
        f"Tracción: media {p_avg:.1f} N, mín {p_min:.1f} N (mínimo {p_spec:.1f}), "
        f"margen medio {mg_avg:+.0%} (peor {mg_min:+.0%}), {nok_p} NOK."
    )
    if nok_rows:
        line += (
            f" De {nok_rows} mediciones con NOK (no excluyentes): {remeasured} con re-medición de la"
            f" misma pieza y {resampled} con repetición sobre nueva muestra; en todas se continuó."
        )
    return line


def _crimp_week_line(w) -> str:
    week, n, pos, pos_max, margin, nok_h, nok_p, _total = w
    return (
        f"- semana del {week}: {n} mediciones, posición media {pos:.2f} (máx {pos_max:.2f}), "
        f"margen de tracción medio {margin:+.0%}, NOK altura {nok_h}, NOK tracción {nok_p}"
    )


def _change_line(r) -> str:
    (cid, day, kind, equipment, part, variant, _lines, prev, new, descr, board, test, role) = r  # fmt: skip
    parts = [f"- {cid} · {day} · {kind}"]
    if equipment:
        parts.append(f"equipos {', '.join(equipment)}")
    if part:
        parts.append(f"parte {part}" + (f" ({variant})" if variant else ""))
    if prev:
        parts.append(f"revisión {prev} → {new}")
    parts.append(descr[:400])
    if board is not None:
        parts.append(f"tablero actualizado: {board}")
    if test is not None:
        parts.append(f"programa de prueba actualizado: {test}")
    parts.append(f"aprobó: {role}")
    return " · ".join(parts)


def _lot_line(r, known: date) -> str:
    lot_id, part, supplier, received, qty, itype, ires, c_from, c_to, status = r
    # Después del corte no se conoce cuándo terminó el consumo ni cómo terminó el lote.
    ended = c_to <= known
    window = f"consumo {c_from} a {c_to}" if ended else f"en consumo desde {c_from}"
    return (
        f"- {lot_id} · {part} · {supplier} · recibido {received} · {qty:,} piezas · "
        f"inspección de recibo: {itype}, {ires} · {window}"
        + (f" · estado: {status}" if ended else "")
    )
