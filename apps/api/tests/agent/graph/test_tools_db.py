"""Tools de solo lectura: alcance, validación, presupuesto y as_of."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.agent.tools import QualityTools, ToolBudget, ToolError
from app.retrieval.service import RetrievalService

TODAY = datetime.now(UTC).date()


@pytest.fixture
def tools_for(env, user_of):
    def make(username="ing.l1", **kw):
        return QualityTools(
            env.conn, user_of(username), RetrievalService(env.conn, env.embedder), **kw
        )

    return make


def test_defect_summary_groups_and_percentages(tools_for):
    out = tools_for().defect_summary(
        "JRZ1", "L1", TODAY - timedelta(days=30), TODAY, group_by="estacion"
    )
    assert out.tool == "get_defect_summary"
    assert "Crimpado: 15 (88.2%)" in out.text and "total 17 piezas" in out.text
    assert out.params["linea"] == "L1"


def test_defect_summary_never_mixes_lines(tools_for):
    out = tools_for().defect_summary("JRZ1", "L1", TODAY - timedelta(days=30), TODAY)
    assert "99" not in out.text  # el evento de 99 piezas es de L2


def test_user_cannot_query_a_line_outside_their_scope(tools_for):
    with pytest.raises(ToolError, match="alcance"):
        tools_for("ing.l2").defect_summary(
            "JRZ1", "L1", TODAY - timedelta(days=5), TODAY
        )
    with pytest.raises(ToolError, match="alcance"):
        tools_for("ing.jrz2").defect_summary(
            "JRZ1", "L1", TODAY - timedelta(days=5), TODAY
        )


def test_empty_range_says_so_instead_of_inventing(tools_for):
    out = tools_for().defect_summary(
        "JRZ1", "L1", TODAY - timedelta(days=300), TODAY - timedelta(days=200)
    )
    assert "sin eventos" in out.text


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"date_from": TODAY, "date_to": TODAY - timedelta(days=1)}, "anterior"),
        ({"date_from": TODAY - timedelta(days=900), "date_to": TODAY}, "rango máximo"),
        (
            {
                "date_from": TODAY + timedelta(days=5),
                "date_to": TODAY + timedelta(days=9),
            },
            "futuro",
        ),
        (
            {"date_from": TODAY - timedelta(days=3), "date_to": TODAY, "shift": 7},
            "turno",
        ),
    ],
)
def test_invalid_parameters_are_rejected(tools_for, kw, message):
    with pytest.raises(ToolError, match=message):
        tools_for().defect_summary("JRZ1", "L1", **kw)


def test_as_of_caps_the_window(tools_for):
    """Con as_of hace 6 días, el evento de hace 3 días no existe todavía."""
    out = tools_for(as_of=TODAY - timedelta(days=6)).defect_summary(
        "JRZ1", "L1", TODAY - timedelta(days=30), TODAY, group_by="dia"
    )
    assert (
        "total 6 piezas" in out.text
        and (TODAY - timedelta(days=3)).isoformat() not in out.text
    )
    assert out.params["hasta"] == (TODAY - timedelta(days=6)).isoformat()


def test_maintenance_flags_overdue_orders(tools_for):
    out = tools_for().maintenance_history(
        "JRZ1", "L1", TODAY - timedelta(days=120), TODAY
    )
    assert "OT-T-001" in out.text and "VENCIDA sin completar (40 días)" in out.text
    assert "OT-T-002" in out.text and "completada" in out.text


def test_equipment_filter_and_validation(tools_for):
    out = tools_for().maintenance_history(
        "JRZ1", "L1", TODAY - timedelta(days=120), TODAY, equipment="APL-L1-02"
    )
    assert "OT-T-001" in out.text and "OT-T-002" not in out.text
    with pytest.raises(ToolError, match="equipo"):
        tools_for().maintenance_history(
            "JRZ1",
            "L1",
            TODAY - timedelta(days=5),
            TODAY,
            equipment="x'; DROP TABLE ncr;--",
        )


def test_call_budget_is_enforced(tools_for):
    tools = tools_for(budget=ToolBudget(max_calls=2))
    tools.defect_summary("JRZ1", "L1", TODAY - timedelta(days=5), TODAY)
    tools.defect_summary("JRZ1", "L1", TODAY - timedelta(days=5), TODAY)
    with pytest.raises(ToolError, match="límite"):
        tools.defect_summary("JRZ1", "L1", TODAY - timedelta(days=5), TODAY)


def test_retrieval_tools_respect_kinds_and_scope(tools_for):
    cases = tools_for().search_cases(
        "falso contacto intermitente terminal aplicador L1"
    )
    assert cases and {h.kind.value for h in cases} <= {"8d", "ncr"}
    controls = tools_for().search_controls("altura de crimpado")
    assert controls and {h.kind.value for h in controls} <= {
        "amef",
        "plan_control",
        "instruccion",
        "sop",
    }
    # El ingeniero de L2 no ve documentos exclusivos de L1.
    seen_l2 = tools_for("ing.l2").search_cases(
        "falso contacto intermitente aplicador APL-L1-02"
    )
    assert all(h.line_id in (None, "L2") for h in seen_l2)


def test_as_of_hides_future_maintenance(tools_for):
    """Con as_of hace 35 días, la OT-T-001 (vence hace 40) existe y la OT-T-002 (hace 30) no."""
    out = tools_for(as_of=TODAY - timedelta(days=35)).maintenance_history(
        "JRZ1", "L1", TODAY - timedelta(days=120), TODAY
    )
    assert "OT-T-001" in out.text and "OT-T-002" not in out.text
    assert out.params["hasta"] == (TODAY - timedelta(days=35)).isoformat()


# ---------------------------------------------------------------- datos reales: columnas nuevas


@pytest.mark.parametrize(
    "group_by",
    [
        "familia",
        "estacion",
        "turno",
        "dia",
        "semana",
        "aplicador",
        "lote_terminal",
        "deteccion",
        "estacion_turno",
    ],
)
def test_every_grouping_runs_and_adds_up(tools_for, group_by):
    """Cada dimensión se ejecuta (una vez 'familia' apuntó a una columna inexistente) y suma el total."""
    out = tools_for().defect_summary(
        "JRZ1", "L1", TODAY - timedelta(days=30), TODAY, group_by=group_by
    )
    assert out.params["agrupar_por"] == group_by
    shares = [line for line in out.text.splitlines() if line.startswith("- ")]
    counts = [int(line.split(": ")[1].split(" ")[0]) for line in shares]
    if group_by in ("aplicador", "lote_terminal"):
        assert sum(counts) == 15  # solo los eventos con el dato
    else:
        assert sum(counts) == 17 and "total 17 piezas" in out.text


def test_station_by_shift_shows_the_prior_period_as_baseline(tools_for):
    """Cada grupo trae lo que tenía en el periodo anterior; un pico sin antecedente se dice."""
    out = tools_for().defect_summary(
        "JRZ1", "L1", TODAY - timedelta(days=30), TODAY, group_by="estacion_turno"
    )
    rows = [line for line in out.text.splitlines() if line.startswith("- ")]
    assert rows and all(" · turno " in r and "periodo anterior: " in r for r in rows)
    assert any("(sin antecedente)" in r or "(×" in r for r in rows)  # Crimpado: 15 piezas


def test_baseline_is_only_added_to_the_cuts_that_ask_for_it(tools_for):
    out = tools_for().defect_summary(
        "JRZ1", "L1", TODAY - timedelta(days=30), TODAY, group_by="estacion"
    )
    assert "periodo anterior" not in out.text


def test_family_uses_the_catalog_name(tools_for):
    out = tools_for().defect_summary(
        "JRZ1", "L1", TODAY - timedelta(days=30), TODAY, group_by="familia"
    )
    assert "Crimpado fuera de especificación: 17 (100.0%)" in out.text


def test_group_by_applicator_counts_only_events_that_have_one_and_says_so(tools_for):
    out = tools_for().defect_summary(
        "JRZ1", "L1", TODAY - timedelta(days=30), TODAY, group_by="aplicador"
    )
    assert (
        "- APL-L1-02: 11 (73.3%)" in out.text and "- APL-L1-01: 4 (26.7%)" in out.text
    )
    assert "None" not in out.text and "(sin dato)" not in out.text
    assert (
        "Solo cuentan los eventos con aplicador registrado: 15 de 17 piezas del rango."
        in out.text
    )


def test_group_by_terminal_lot_and_detection_point(tools_for):
    window = (TODAY - timedelta(days=30), TODAY)
    lots = (
        tools_for().defect_summary("JRZ1", "L1", *window, group_by="lote_terminal").text
    )
    assert "- LT-A-01: 10 (66.7%)" in lots and "- LT-A-02: 5 (33.3%)" in lots
    points = (
        tools_for().defect_summary("JRZ1", "L1", *window, group_by="deteccion").text
    )
    assert "- CLIENTE: 5" in points and "- INF: 12" in points


def test_as_of_uses_the_detection_date_not_the_manufacturing_date(tools_for):
    """El evento fabricado hace 5 días lo reportó el cliente ayer: un corte de hace 2 días no lo conoce."""
    window = (TODAY - timedelta(days=30), TODAY)
    now = tools_for().defect_summary("JRZ1", "L1", *window)
    cut = tools_for(as_of=TODAY - timedelta(days=2)).defect_summary(
        "JRZ1", "L1", *window
    )
    assert "total 17 piezas" in now.text and "total 12 piezas" in cut.text
    assert "detectados hasta" in cut.text
    # Un corte posterior a la detección sí lo ve.
    assert (
        "total 17 piezas"
        in tools_for(as_of=TODAY).defect_summary("JRZ1", "L1", *window).text
    )


def test_daily_series_is_chronological_and_complete_when_truncated(env, tools_for):
    from sqlalchemy import text

    env.conn.execute(
        text(
            "INSERT INTO defect_event (occurred_at, detected_on, plant_id, line_id, shift, defect_family_id, station, quantity) "
            "SELECT d::timestamp AT TIME ZONE 'UTC', d::date, 'JRZ1', 'L2', 1, 'DEF-01', 'CRP-L2', 1 "
            "FROM generate_series(CAST(:a AS date), CAST(:b AS date), interval '1 day') d"
        ),
        {
            "a": TODAY - timedelta(days=60),
            "b": TODAY - timedelta(days=16),
        },  # 45 días distintos
    )
    out = tools_for("ing.l2").defect_summary(
        "JRZ1", "L2", TODAY - timedelta(days=90), TODAY, group_by="dia"
    )
    days = [line[2:12] for line in out.text.splitlines() if line.startswith("- ")]
    assert (
        days == sorted(days) and len(days) == 40
    )  # cronológico y con los más recientes
    assert (
        days[-1] == (TODAY - timedelta(days=2)).isoformat()
    )  # el evento de 99 piezas, el más reciente
    assert (
        days[0] > (TODAY - timedelta(days=60)).isoformat()
    )  # los más antiguos son los que se omiten
    assert (
        "total 144 piezas" in out.text
    )  # el total es del rango completo, no de las 40 filas mostradas
    assert "se muestran 40 de 46 grupos, los más recientes" in out.text


def test_maintenance_shows_status_reason_and_cycles(tools_for):
    out = (
        tools_for()
        .maintenance_history("JRZ1", "L1", TODAY - timedelta(days=120), TODAY)
        .text
    )
    assert (
        "OT-T-003 · APL-L1-03 · preventivo" in out
        and "REPROGRAMADA, no se ejecutó en la fecha programada" in out
    )
    assert "motivo: Falta de juego de punzón y yunque" in out
    assert "completada el" in out and "a los 187,000 ciclos" in out
    assert "OT-T-001" in out and "VENCIDA sin completar (40 días)" in out


def test_maintenance_completed_after_the_cut_counts_as_not_done_and_hides_its_cycles(
    tools_for,
):
    """OT-T-002 vencía hace 30 días y se completó hace 28: con corte hace 29 días seguía pendiente."""
    out = tools_for(as_of=TODAY - timedelta(days=29)).maintenance_history(
        "JRZ1", "L1", TODAY - timedelta(days=120), TODAY
    )
    line = next(item for item in out.text.splitlines() if "OT-T-002" in item)
    assert "completada" not in line and "187,000" not in line
    assert "VENCIDA sin completar (1 días)" in line
    done = (
        tools_for()
        .maintenance_history("JRZ1", "L1", TODAY - timedelta(days=120), TODAY)
        .text
    )
    assert "con 2 días de retraso, a los 187,000 ciclos" in done


def test_maintenance_keeps_the_most_recent_orders_when_there_are_too_many(
    env, tools_for
):
    from sqlalchemy import text

    env.conn.execute(
        text(
            "INSERT INTO maintenance_order (id, plant_id, line_id, equipment, order_type, due_date, status) "
            "SELECT 'OT-M-' || lpad(i::text, 3, '0'), 'JRZ1', 'L2', 'APL-L2-01', 'preventivo', "
            "CAST(:t AS date) - (40 - i), 'pendiente' FROM generate_series(1, 30) i"
        ),
        {"t": TODAY},
    )
    out = (
        tools_for("ing.l2")
        .maintenance_history("JRZ1", "L2", TODAY - timedelta(days=120), TODAY)
        .text
    )
    ids = [
        line.split(" · ")[0][2:] for line in out.splitlines() if line.startswith("- ")
    ]
    assert len(ids) == 25 and ids == sorted(ids)
    assert "OT-M-030" in ids and "OT-M-001" not in ids
    assert "se muestran las 25 más recientes" in out


# ---------------------------------------------------------------- desgaste de aplicadores


def _wear(tools_for, user="ing.l1", **kw):
    on = kw.pop("on", None)
    return tools_for(user, **kw).applicator_wear("JRZ1", "L1", on=on)


def _wear_line(out, equipment):
    return next(
        line for line in out.text.splitlines() if line.startswith(f"- {equipment} ")
    )


def test_wear_counts_cycles_since_the_last_service_against_the_threshold(tools_for):
    out = _wear(tools_for)
    done = _wear_line(out, "APL-L1-01")
    assert (
        "140,000 ciclos desde el último servicio (preventivo OT-T-002," in done
    )  # 28 días x 5 000
    assert "= 56% del umbral de PM de 250,000" in done and "EXCEDIDO" not in done
    assert out.params == {"linea": "L1", "al": TODAY.isoformat()}


def test_wear_flags_exceeded_applicators_and_lists_unexecuted_pm(tools_for):
    line = _wear_line(_wear(tools_for), "APL-L1-02")
    assert (
        "610,000 ciclos desde el inicio de los datos" in line
        and "no hay servicio previo" in line
    )
    assert "= 244% del umbral de PM de 250,000, EXCEDIDO por 360,000 ciclos" in line
    assert (
        f"PM sin ejecutar desde entonces: OT-T-001 (vence {TODAY - timedelta(days=40)})"
        in line
    )


def test_wear_lists_a_rescheduled_pm_as_unexecuted(tools_for):
    assert "OT-T-003" in _wear_line(_wear(tools_for), "APL-L1-03")


def test_wear_is_sorted_worst_first_and_skips_non_applicators(tools_for):
    rows = [
        line for line in _wear(tools_for).text.splitlines() if line.startswith("- ")
    ]
    assert [row.split(" ")[1] for row in rows] == [
        "APL-L1-02",
        "APL-L1-01",
        "APL-L1-03",
    ]
    assert not any(
        row.startswith("- PRS") for row in rows
    )  # la prensa es equipo, no aplicador


def test_wear_reports_data_gaps_and_stale_data(tools_for):
    line = _wear_line(_wear(tools_for), "APL-L1-03")
    assert "55,000 ciclos" in line and "= 22%" in line
    assert "faltan 1 días de ciclos en ese periodo" in line
    assert f"los ciclos registrados llegan al {TODAY - timedelta(days=5)}" in line


def test_wear_at_an_earlier_date_ignores_services_done_later(tools_for):
    """Cortado un día antes de completarse OT-T-002 (hace 28 días), ese servicio aún no existe."""
    out = _wear(tools_for, on=TODAY - timedelta(days=29))
    line = _wear_line(out, "APL-L1-01")
    assert "160,000 ciclos desde el inicio de los datos" in line  # 32 días x 5 000
    assert (
        f"PM sin ejecutar desde entonces: OT-T-002 (vence {TODAY - timedelta(days=30)})"
        in line
    )
    assert out.params["al"] == (TODAY - timedelta(days=29)).isoformat()


def test_wear_respects_as_of_and_rejects_future_dates(tools_for):
    cut = _wear(tools_for, as_of=TODAY - timedelta(days=29))
    assert "160,000 ciclos" in _wear_line(cut, "APL-L1-01")
    with pytest.raises(ToolError, match="futuro"):
        _wear(tools_for, on=TODAY + timedelta(days=1))
    with pytest.raises(ToolError, match="futuro"):
        _wear(tools_for, as_of=TODAY - timedelta(days=10), on=TODAY - timedelta(days=5))


def test_wear_single_equipment_scope_and_validation(tools_for):
    out = tools_for().applicator_wear("JRZ1", "L1", equipment="APL-L1-01")
    assert (
        out.text.count("\n- ") == 1
        and "APL-L1-01" in out.text
        and "APL-L1-02" not in out.text
    )
    with pytest.raises(ToolError, match="alcance"):
        tools_for("ing.l2").applicator_wear("JRZ1", "L1")
    with pytest.raises(ToolError, match="equipo"):
        tools_for().applicator_wear("JRZ1", "L1", equipment="x'; --")
    nothing = tools_for().applicator_wear("JRZ1", "L1", equipment="APL-L1-99")
    assert "no hay aplicadores registrados" in nothing.text


# ---------------------------------------------------------------- crimpado


def _crimp(tools_for, user="ing.l1", frm=20, to=0, **kw):
    equipment = kw.pop("equipment", None)
    return tools_for(user, **kw).crimp_summary(
        "JRZ1",
        "L1",
        TODAY - timedelta(days=frm),
        TODAY - timedelta(days=to),
        equipment=equipment,
    )


def _crimp_line(out, equipment):
    return next(
        line for line in out.text.splitlines() if line.startswith(f"- {equipment} ")
    )


def test_crimp_summary_reports_band_position_and_pull_margin_worst_first(tools_for):
    out = _crimp(tools_for)
    names = [
        line.split()[1] for line in out.text.splitlines() if line.startswith("- APL")
    ]
    assert names == ["APL-L1-03", "APL-L1-01"]  # posición media 0.83 antes que 0.5
    assert out.tool == "get_crimp_measurements"
    near = _crimp_line(out, "APL-L1-03")
    assert "21 mediciones" in near and "posición media 0.83" in near
    assert "margen medio +7%" in near and "0 NOK" in near
    assert "De " not in near  # sin NOK no se habla de acciones


def test_crimp_summary_counts_nok_and_describes_actions_without_quoting_them(
    tools_for,
):
    line = _crimp_line(_crimp(tools_for), "APL-L1-01")
    assert "Altura: media" in line and "1 NOK" in line  # altura
    assert "Tracción" in line and "peor -10%" in line  # (45-50)/50
    assert "máx 1.17" in line  # (0.84-0.77)/0.06
    assert "De 1 mediciones con NOK" in line
    assert "1 con re-medición de la misma pieza y 0 con repetición" in line
    assert (
        "dentro de especificación" not in line
    )  # texto libre de la planta, no se cita


def test_crimp_summary_adds_the_weekly_trend_only_for_one_equipment(tools_for):
    assert "Tendencia semanal" not in _crimp(tools_for).text
    out = _crimp(tools_for, equipment="APL-L1-01")
    assert "APL-L1-03" not in out.text
    weeks = [l for l in out.text.splitlines() if l.startswith("- semana del")]
    assert 3 <= len(weeks) <= 4
    dates = [l.split()[3].rstrip(":") for l in weeks]
    assert dates == sorted(dates)  # cronológico
    assert all(date.fromisoformat(d).weekday() == 0 for d in dates)  # lunes
    assert sum(int(l.split(": ")[1].split()[0]) for l in weeks) == 21
    assert sum("NOK altura 1" in l for l in weeks) == 1


def test_crimp_summary_respects_as_of_and_rejects_bad_input(tools_for):
    cut = _crimp(tools_for, as_of=TODAY - timedelta(days=5))
    line = _crimp_line(cut, "APL-L1-01")
    assert "0 NOK" in line and "De " not in line and "16 mediciones" in line
    with pytest.raises(ToolError, match="alcance"):
        _crimp(tools_for, user="ing.l2")
    with pytest.raises(ToolError, match="equipo"):
        _crimp(tools_for, equipment="APL-L1-01; DROP TABLE")
    with pytest.raises(ToolError):
        _crimp(tools_for, frm=0, to=5)


def test_crimp_summary_says_so_when_there_is_nothing_and_spends_the_budget(tools_for):
    out = _crimp(tools_for, frm=200, to=100)
    assert "sin mediciones" in out.text
    budget = ToolBudget(1)
    tools = tools_for(budget=budget)
    tools.crimp_summary("JRZ1", "L1", TODAY - timedelta(days=5), TODAY)
    with pytest.raises(ToolError):
        tools.crimp_summary("JRZ1", "L1", TODAY - timedelta(days=5), TODAY)


# ---------------------------------------------------------------- cambios


def _changes(tools_for, user="ing.l1", line="L1", frm=90, to=0, **kw):
    equipment = kw.pop("equipment", None)
    return tools_for(user, **kw).change_log(
        "JRZ1",
        line,
        TODAY - timedelta(days=frm),
        TODAY - timedelta(days=to),
        equipment=equipment,
    )


def _ids(out):
    return [
        line.split()[1] for line in out.text.splitlines() if line.startswith("- CHG")
    ]


def test_change_log_lists_only_the_changes_that_touch_the_line_oldest_first(tools_for):
    out = _changes(tools_for)
    assert out.tool == "get_change_log"
    assert _ids(out) == ["CHG-T-1", "CHG-T-2", "CHG-T-3"]  # T-4 es solo de L2
    assert _ids(_changes(tools_for, user="ing.l2", line="L2")) == ["CHG-T-2", "CHG-T-4"]


def test_change_log_shows_revisions_and_keeps_no_distinct_from_not_applicable(
    tools_for,
):
    lines = {
        line.split()[1]: line
        for line in _changes(tools_for).text.splitlines()
        if line.startswith("- CHG")
    }
    assert "revisión H → J" in lines["CHG-T-2"]
    assert "tablero actualizado: No" in lines["CHG-T-2"]
    assert "programa de prueba actualizado: No" in lines["CHG-T-2"]
    assert (
        "tablero actualizado" not in lines["CHG-T-1"]
    )  # sin dato: no se inventa un "No"
    assert "revisión" not in lines["CHG-T-3"]
    assert "equipos BRD-L1, BRD-L2" in lines["CHG-T-2"]


def test_change_log_filters_by_equipment_range_and_as_of(tools_for):
    assert _ids(_changes(tools_for, equipment="BRD-L1")) == ["CHG-T-2"]
    assert _ids(_changes(tools_for, frm=30)) == ["CHG-T-2", "CHG-T-3"]
    cut = _changes(tools_for, as_of=TODAY - timedelta(days=10))
    assert _ids(cut) == ["CHG-T-1", "CHG-T-2"]  # T-3 es de hace 5 días: aún no ocurre


def test_change_log_validation_scope_and_empty_range(tools_for):
    assert "sin cambios" in _changes(tools_for, frm=200, to=100).text
    with pytest.raises(ToolError, match="alcance"):
        _changes(tools_for, user="ing.l2", line="L1")
    with pytest.raises(ToolError, match="equipo"):
        _changes(tools_for, equipment="BRD-L1'; --")
    with pytest.raises(ToolError):
        _changes(tools_for, frm=0, to=5)
    tools = tools_for(budget=ToolBudget(1))
    tools.change_log("JRZ1", "L1", TODAY - timedelta(days=5), TODAY)
    with pytest.raises(ToolError):
        tools.change_log("JRZ1", "L1", TODAY - timedelta(days=5), TODAY)


# ---------------------------------------------------------------- lotes


def _lots(tools_for, user="ing.l1", frm=30, to=0, **kw):
    part = kw.pop("part_number", None)
    return tools_for(user, **kw).material_lots(
        "JRZ1",
        "L1",
        TODAY - timedelta(days=frm),
        TODAY - timedelta(days=to),
        part_number=part,
    )


def _lot_ids(out):
    return [
        line.split()[1] for line in out.text.splitlines() if line.startswith("- LT")
    ]


def test_lots_overlapping_the_range_are_listed_oldest_first_for_every_line(tools_for):
    out = _lots(tools_for)
    assert out.tool == "get_material_lots"
    assert _lot_ids(out) == ["LT-T-1", "LT-T-2", "LT-T-3", "LT-T-4"]
    assert _lot_ids(_lots(tools_for, frm=15, to=8)) == [
        "LT-T-2",
        "LT-T-3",
    ]  # por traslape
    assert _lot_ids(_lots(tools_for, part_number="TRM-B-2150")) == ["LT-T-2"]


def test_lot_line_shows_supplier_inspection_and_final_state(tools_for):
    line = next(
        line
        for line in _lots(tools_for).text.splitlines()
        if line.startswith("- LT-T-1")
    )
    assert "Proveedor Prueba" in line and "150,000 piezas" in line
    assert "inspección de recibo: Certificado (skip-lot), Liberado" in line
    assert "estado: Consumo detenido; devuelto al proveedor" in line
    reinforced = next(
        line
        for line in _lots(tools_for).text.splitlines()
        if line.startswith("- LT-T-3")
    )
    assert "Muestreo reforzado 32 piezas" in reinforced


def test_a_lot_still_being_consumed_hides_its_end_date_and_final_state(tools_for):
    line = next(
        line
        for line in _lots(tools_for).text.splitlines()
        if line.startswith("- LT-T-4")
    )
    assert "en consumo desde" in line and "estado:" not in line
    end = (TODAY + timedelta(days=6)).isoformat()
    assert end not in _lots(tools_for).text


def test_lots_respect_as_of_and_do_not_leak_what_happened_later(tools_for):
    cut = TODAY - timedelta(days=30)
    out = _lots(tools_for, frm=45, to=0, as_of=cut)
    assert _lot_ids(out) == ["LT-T-1"]  # los demás se recibieron después del corte
    line = out.text.splitlines()[-1]
    assert "en consumo desde" in line and "estado:" not in line
    assert (
        "devuelto" not in out.text
        and (TODAY - timedelta(days=20)).isoformat() not in out.text
    )


def test_lots_validation_scope_and_empty_range(tools_for):
    assert "sin lotes" in _lots(tools_for, frm=200, to=100).text
    with pytest.raises(ToolError, match="alcance"):
        tools_for("ing.l2").material_lots(
            "JRZ1", "L1", TODAY - timedelta(days=5), TODAY
        )
    with pytest.raises(ToolError, match="parte"):
        _lots(tools_for, part_number="TRM'; --")


# ---------------------------------------------------------------- tasas por producción


def _summary(tools_for, group_by, user="ing.l1", line="L1", frm=30, to=0, **kw):
    return tools_for(user, **kw).defect_summary(
        "JRZ1",
        line,
        TODAY - timedelta(days=frm),
        TODAY - timedelta(days=to),
        group_by=group_by,
    )


def test_rates_use_the_production_of_the_line_in_the_range(tools_for):
    out = _summary(tools_for, "turno")
    # 31 días × 150 unidades por turno; las 17 piezas son del turno 2.
    assert "turno 2: 17 (100.0%) · 3.66 por mil de 4,650 unidades" in out.text
    assert (
        "Producción de la línea en el rango: 13,950 unidades; tasa global 1.22 por mil."
        in out.text
    )
    assert "14,727" not in out.text  # no mezcla la producción de L2


def test_rates_by_part_use_each_parts_own_production_and_skip_unknown_parts(tools_for):
    text_ = _summary(tools_for, "parte").text
    assert "- B3-FDH-0451: 6 (35.3%) · 0.65 por mil de 9,300 unidades" in text_
    assert "- A7-DRH-2210-M: 4 (23.5%) · 0.86 por mil de 4,650 unidades" in text_
    unknown = next(l for l in text_.splitlines() if l.startswith("- (sin parte)"))
    assert "por mil" not in unknown  # sin parte no hay denominador


def test_rates_by_week_and_day_have_matching_denominators(tools_for):
    for group in ("semana", "dia"):
        out = _summary(tools_for, group, frm=9)
        assert "por mil de" in out.text
        total = int(
            out.text.split("Producción de la línea en el rango: ")[1]
            .split(" ")[0]
            .replace(",", "")
        )
        assert total == 10 * 450


def test_line_wide_dimensions_say_so_and_applicators_get_no_rate(tools_for):
    est = _summary(tools_for, "estacion").text
    assert "contra la producción de toda la línea" in est
    apl = _summary(tools_for, "aplicador").text
    assert "por mil de" not in apl and "tasa global" not in apl
    assert "Producción de la línea en el rango: 13,950 unidades." in apl


def test_without_production_in_the_range_there_are_no_rates(tools_for):
    out = _summary(tools_for, "estacion", user="ing.l2", line="L2", frm=5)
    assert "Sin producción registrada en el rango: no hay tasas." in out.text
    assert "por mil" not in out.text


def test_recent_windows_warn_that_late_claims_are_not_in_yet(tools_for):
    assert "pueden estar subestimados" in _summary(tools_for, "turno").text
    old = _summary(tools_for, "turno", frm=35, to=22)  # termina hace más de 10 días
    assert "pueden estar subestimados" not in old.text
    cut = _summary(tools_for, "turno", frm=35, to=0, as_of=TODAY - timedelta(days=20))
    assert "pueden estar subestimados" not in cut.text


def test_production_after_the_cut_is_not_counted(tools_for):
    out = _summary(tools_for, "turno", as_of=TODAY - timedelta(days=9))
    assert (
        "Producción de la línea en el rango: 9,900 unidades" in out.text
    )  # 22 días × 450
