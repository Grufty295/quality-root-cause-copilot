"""Entorno de las pruebas del grafo: corpus real indexado, datos de defectos y un LLM falso.

Todo ocurre en UNA transacción que se revierte al final del módulo: el corpus, las
NCR y los borradores no quedan en la base ni afectan a otras pruebas. Para que el
grafo (que abre sus propias conexiones y las usa desde hilos) vea esos datos sin
confirmar, el "engine" de las pruebas entrega siempre la misma conexión.
"""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.agent.graph import AgentDeps
from app.agent.llm import (
    CatalogInspector,
    Destination,
    LLMResult,
    LLMSettings,
    ModelGateway,
    SqlAuditSink,
    Usage,
)
from app.confidentiality.classifier import CatalogTerm
from app.confidentiality.levels import ConfidentialityLevel
from app.confidentiality.pseudonyms import InMemoryPseudonymStore
from app.confidentiality.redactor import RuleRedactor
from app.ingest.service import IngestService
from app.modules.auth import repository as auth_repo
from app.modules.ncr import repository as ncr_repo
from tests.agent.llm.conftest import _api, _local
from tests.paths import CORPUS_DIR
from tests.retrieval.fakes import HashingEmbedder

CORPUS = CORPUS_DIR


class SingleConnEngine:
    """Hace pasar una conexión ya abierta por `Engine`: `connect()` y `begin()` la devuelven."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def connect(self):
        return nullcontext(self._conn)

    def begin(self):
        return nullcontext(self._conn)


@pytest.fixture(scope="module")
def env(db_engine, catalog_and_users):
    if not CORPUS.exists():
        pytest.skip("no está data/seed/corpus")
    conn = db_engine.connect()
    trans = conn.begin()
    engine = SingleConnEngine(conn)
    conn.execute(
        text(
            "INSERT INTO customer (id, name, is_confidential) VALUES "
            "('NOR','Norvane Motors', true), ('KES','Kestrel Modules', false) ON CONFLICT DO NOTHING"
        )
    )
    conn.execute(
        text(
            "INSERT INTO part (id, part_number, customer_id, description) VALUES "
            "('A7-DRH-2210-M','A7-DRH-2210-M','NOR','Arnés'), ('B3-FDH-0451','B3-FDH-0451','KES','Arnés') "
            "ON CONFLICT DO NOTHING"
        )
    )
    conn.execute(
        text(
            "INSERT INTO defect_family (id, name) VALUES ('DEF-01','Crimpado fuera de especificación') ON CONFLICT DO NOTHING"
        )
    )
    embedder = HashingEmbedder()
    report = IngestService(engine.begin, embedder, plant_id="JRZ1").ingest_directory(
        CORPUS
    )
    assert not report.failed, report.failed
    _seed_operational_data(conn)
    yield type("Env", (), {"conn": conn, "engine": engine, "embedder": embedder})
    trans.rollback()
    conn.close()


def _seed_operational_data(conn) -> None:
    now = datetime.now(UTC)
    today = now.date()

    def event(
        days_ago,
        line,
        station,
        qty,
        *,
        applicator=None,
        lot=None,
        detected_days_ago=None,
        point="INF",
        part=None,
    ):
        made = today - timedelta(days=days_ago)
        detected = today - timedelta(
            days=days_ago if detected_days_ago is None else detected_days_ago
        )
        conn.execute(
            text(
                "INSERT INTO defect_event (occurred_at, detected_on, plant_id, line_id, shift, defect_family_id, "
                "station, quantity, detection_point, applicator_id, terminal_lot, part_id) "
                "VALUES (CAST(:m AS timestamp) AT TIME ZONE 'UTC', :d, 'JRZ1', :l, 2, 'DEF-01', :s, :q, :pt, :a, :lot, :part)"
            ),
            {
                "m": made,
                "d": detected,
                "l": line,
                "s": station,
                "q": qty,
                "pt": point,
                "a": applicator,
                "lot": lot,
                "part": part,
            },
        )

    event(
        3,
        "L1",
        "Crimpado",
        6,
        applicator="APL-L1-02",
        lot="LT-A-01",
        part="B3-FDH-0451",
    )
    # Fabricado hace 5 días pero detectado por el cliente ayer: no existe para un corte anterior.
    event(
        5,
        "L1",
        "Crimpado",
        5,
        applicator="APL-L1-02",
        lot="LT-A-02",
        detected_days_ago=1,
        point="CLIENTE",
    )
    event(9, "L1", "Prueba eléctrica", 2)
    event(
        12,
        "L1",
        "Crimpado",
        4,
        applicator="APL-L1-01",
        lot="LT-A-01",
        part="A7-DRH-2210-M",
    )
    event(2, "L2", "Crimpado", 99)

    def order(
        oid,
        equipment,
        kind,
        due_days,
        done_days,
        status,
        *,
        reason=None,
        cycles=None,
        line="L1",
    ):
        conn.execute(
            text(
                "INSERT INTO maintenance_order (id, plant_id, line_id, equipment, order_type, due_date, completed_at, "
                "status, reschedule_reason, cycles_at_event, notes) VALUES "
                "(:id, 'JRZ1', :l, :eq, :k, :due, CAST(:done AS timestamp) AT TIME ZONE 'UTC', :st, :r, :c, :n)"
            ),
            {
                "id": oid, "l": line, "eq": equipment, "k": kind, "st": status, "r": reason, "c": cycles,
                "due": today - timedelta(days=due_days),
                "done": None if done_days is None else today - timedelta(days=done_days),
                "n": "PM de aplicador" if kind == "preventivo" else "Correctivo por desgaste",
            },
        )  # fmt: skip

    _seed_production(conn, today)
    _seed_wear(conn, today)
    order("OT-T-001", "APL-L1-02", "preventivo", 40, None, "pendiente")
    order("OT-T-002", "APL-L1-01", "preventivo", 30, 28, "completada", cycles=187000)
    order(
        "OT-T-003",
        "APL-L1-03",
        "preventivo",
        20,
        None,
        "reprogramada",
        reason="Falta de juego de punzón y yunque",
    )


def _seed_production(conn, today) -> None:
    """L1: 40 días atrás hasta hoy, tres turnos; B3 100 y A7 50 unidades por turno (450 al día).
    L2: solo hace 20 días (777 unidades), sin producción en los días del evento de L2."""
    conn.execute(
        text(
            "INSERT INTO production (plant_id, produced_on, shift, line_id, part_id, units) "
            "SELECT 'JRZ1', d::date, s, 'L1', pt.id, pt.units "
            "FROM generate_series(CAST(:a AS date), CAST(:b AS date), interval '1 day') d, "
            "generate_series(1, 3) s, (VALUES ('B3-FDH-0451', 100), ('A7-DRH-2210-M', 50)) AS pt(id, units)"
        ),
        {"a": today - timedelta(days=40), "b": today},
    )
    conn.execute(
        text(
            "INSERT INTO production (plant_id, produced_on, shift, line_id, part_id, units) "
            "VALUES ('JRZ1', :d, 1, 'L2', 'A7-DRH-2210-M', 777)"
        ),
        {"d": today - timedelta(days=20)},
    )


def _seed_wear(conn, today) -> None:
    """Tres aplicadores con ciclos diarios constantes; los totales de las pruebas salen de aquí.

    APL-L1-02: 10 000/día de hace 60 días a hoy.  APL-L1-01: 5 000/día, igual.
    APL-L1-03: 1 000/día de hace 60 a hace 5 días, sin el día -30.
    """
    for eq, family, terminal, press in (
        ("APL-L1-01", "A", "TRM-A-1064", "PRS-L1-01"),
        ("APL-L1-02", "A", "TRM-A-1064", "PRS-L1-02"),
        ("APL-L1-03", "B", "TRM-B-2150", "PRS-L1-01"),
    ):
        conn.execute(
            text(
                "INSERT INTO equipment (plant_id, id, line_id, kind, terminal_family, terminal_part_number, housed_in, "
                "pm_threshold_cycles) VALUES ('JRZ1', :id, 'L1', 'Aplicador', :f, :t, :p, 250000)"
            ),
            {"id": eq, "f": family, "t": terminal, "p": press},
        )
    conn.execute(
        text(
            "INSERT INTO equipment (plant_id, id, line_id, kind) VALUES ('JRZ1', 'PRS-L1-01', 'L1', 'Prensa de crimpado')"
        )
    )
    for eq, per_day, last, skip in (
        ("APL-L1-02", 10000, 0, None),
        ("APL-L1-01", 5000, 0, None),
        ("APL-L1-03", 1000, 5, 30),
    ):
        conn.execute(
            text(
                "INSERT INTO applicator_cycles (plant_id, equipment_id, day, cycles) "
                "SELECT 'JRZ1', :eq, d::date, :n FROM generate_series(CAST(:a AS date), CAST(:b AS date), interval '1 day') d "
                "WHERE d::date <> COALESCE(CAST(:skip AS date), DATE '1900-01-01')"
            ),
            {
                "eq": eq,
                "n": per_day,
                "a": today - timedelta(days=60),
                "b": today - timedelta(days=last),
                "skip": None if skip is None else today - timedelta(days=skip),
            },
        )

    _seed_crimp(conn, today)
    _seed_changes_and_lots(conn, today)


def _seed_crimp(conn, today) -> None:
    """Un turno por día los últimos 21 días.

    APL-L1-01 (banda 0.77–0.83): altura 0.80 (posición 0.50) y tracción 60 N sobre mínimo 50 (+20 %);
    hace 3 días una pieza fuera de especificación en ambas, re-medida sobre la misma pieza.
    APL-L1-03 (banda 1.32–1.38): altura 1.37 (posición 0.83) y tracción 150 N sobre 140 (+7 %).
    """
    for eq, terminal, cable, lsl, usl, h, pull, pmin in (
        ("APL-L1-01", "TRM-A-1064", "WIR-035", 0.77, 0.83, 0.80, 60, 50),
        ("APL-L1-03", "TRM-B-2150", "WIR-100", 1.32, 1.38, 1.37, 150, 140),
    ):
        conn.execute(
            text(
                "INSERT INTO crimp_measurement (plant_id, equipment_id, measured_on, shift, terminal_part_number, "
                "cable_part_number, line_id, press_id, height_mm, height_lsl, height_usl, pull_n, pull_min_n, action) "
                "SELECT 'JRZ1', :eq, d::date, 1, :t, :c, 'L1', 'PRS-L1-01', "
                "CASE WHEN :eq = 'APL-L1-01' AND d::date = CAST(:nok AS date) THEN 0.84 ELSE :h END, :lsl, :usl, "
                "CASE WHEN :eq = 'APL-L1-01' AND d::date = CAST(:nok AS date) THEN 45 ELSE :p END, :pmin, "
                "CASE WHEN :eq = 'APL-L1-01' AND d::date = CAST(:nok AS date) "
                "THEN 'Re-medición de la misma pieza dentro de especificación; se continúa' END "
                "FROM generate_series(CAST(:a AS date), CAST(:b AS date), interval '1 day') d"
            ),
            {
                "eq": eq,
                "t": terminal,
                "c": cable,
                "lsl": lsl,
                "usl": usl,
                "h": h,
                "p": pull,
                "pmin": pmin,
                "nok": today - timedelta(days=3),
                "a": today - timedelta(days=20),
                "b": today,
            },
        )


def _seed_changes_and_lots(conn, today) -> None:
    """Cambios y lotes con fechas relativas a hoy; los asserts de las tools salen de aquí."""

    def day(n: int):
        return today + timedelta(days=n)

    for cid, n, kind, eq, part, lines, rev, board, test, role in (
        ("CHG-T-1", -60, "Receta de máquina", ["CUT-L1-01"], "WIR-050", ["L1"], ("C", "D"), None, None, "Ingeniería de proceso"),
        ("CHG-T-2", -20, "ECN", ["BRD-L1", "BRD-L2"], "A7-DRH-2210-H", ["L1", "L2"], ("H", "J"), "No", "No", "Ingeniería de producto"),
        ("CHG-T-3", -5, "Cambio de herramienta", ["APL-L1-01"], "TRM-A-1064", ["L1"], (None, None), None, None, "Mantenimiento"),
        ("CHG-T-4", -10, "Receta de máquina", ["CUT-L2-01"], "WIR-050", ["L2"], ("C", "D"), None, None, "Ingeniería de proceso"),
    ):  # fmt: skip
        conn.execute(
            text(
                "INSERT INTO change_log (plant_id, id, changed_on, kind, equipment_ids, part_number, line_ids, "
                "previous_revision, new_revision, description, board_updated, test_program_updated, approved_by_role) "
                "VALUES ('JRZ1', :id, :d, :kind, :eq, :part, :lines, :prev, :new, :descr, :board, :test, :role)"
            ),
            {
                "id": cid,
                "d": day(n),
                "kind": kind,
                "eq": eq,
                "part": part,
                "lines": lines,
                "prev": rev[0],
                "new": rev[1],
                "descr": f"descripción de {cid}",
                "board": board,
                "test": test,
                "role": role,
            },
        )
    conn.execute(
        text(
            "INSERT INTO supplier (id, name, category, supplies) "
            "VALUES ('PRV-9', 'Proveedor Prueba', 'A', ARRAY['TRM-A-1064', 'TRM-B-2150'])"
        )
    )
    for lid, part, fam, recv, c_from, c_to, itype, status in (
        ("LT-T-1", "TRM-A-1064", "A", -40, -35, -20, "Certificado (skip-lot)", "Consumo detenido; devuelto al proveedor"),
        ("LT-T-2", "TRM-B-2150", "B", -25, -22, -8, "Certificado (skip-lot)", "Consumido"),
        ("LT-T-3", "TRM-A-1064", "A", -12, -9, -1, "Muestreo reforzado 32 piezas", "Consumido"),
        ("LT-T-4", "TRM-A-1064", "A", -3, -2, 6, "Certificado (skip-lot)", "En consumo"),
    ):  # fmt: skip
        conn.execute(
            text(
                "INSERT INTO material_lot (plant_id, id, part_number, family, supplier_id, received_on, "
                "quantity, inspection_type, inspection_result, consumed_from, consumed_to, status) "
                "VALUES ('JRZ1', :id, :part, :fam, 'PRV-9', :recv, 150000, :itype, 'Liberado', "
                ":cfrom, :cto, :status)"
            ),
            {
                "id": lid,
                "part": part,
                "fam": fam,
                "recv": day(recv),
                "cfrom": day(c_from),
                "cto": day(c_to),
                "itype": itype,
                "status": status,
            },
        )


@pytest.fixture(autouse=True)
def _savepoint(env):
    """Cada prueba en su savepoint: sus NCR y borradores no se ven en las demás y un error SQL no las contamina."""
    sp = env.conn.begin_nested()
    yield
    if sp.is_active:
        sp.rollback()


@pytest.fixture
def user_of(env):
    def load(username: str):
        uid = auth_repo.find_active_user_id(env.conn, username)
        assert uid is not None, username
        user = auth_repo.get_user(env.conn, uid)
        assert user is not None
        return user

    return load


# ------------------------------------------------------------------ LLM falso


class FakeAgentLLM:
    """Lee los ids del prompt y arma un JSON válido. Los modos de falla se piden por modelo.

    `bad_for`: nombres de modelo para los que D4 sale con una causa que cita solo una tool.
    `raw`: si se da, devuelve ese texto tal cual.
    """

    def __init__(
        self,
        *,
        occ=("RC-01", "RC-03", "RC-02"),
        nd="ND-01",
        bad_for=(),
        blame_for=(),
        on_call=None,
        estado="candidato_respaldado",
        contra=False,
    ):
        self.occ, self.nd, self.bad_for, self.blame_for, self.on_call = (
            occ,
            nd,
            set(bad_for),
            set(blame_for),
            on_call,
        )
        self.estado, self.contra = estado, contra
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        if self.on_call:
            self.on_call(request)
        prompt = "\n".join(m.content or "" for m in request.messages)
        body = (
            self._d4(request, prompt)
            if "D4 (causa raíz)" in prompt
            else self._d2(prompt)
        )
        return LLMResult(
            content=json.dumps(body, ensure_ascii=False),
            usage=Usage(input_tokens=len(prompt) // 4, output_tokens=200),
            model=request.model,
            latency_ms=3,
        )

    @staticmethod
    def _h(texto, *fuentes):
        return {"texto": texto, "fuentes": list(fuentes)}

    def _d2(self, prompt):
        tools = re.findall(r'<fuente id="(T\d+)"', prompt)
        src = ["NCR", *tools[:1]]
        return {
            k: self._h(f"{k}: descrito a partir del reporte y los datos", *src)
            for k in ("que", "por_que", "donde", "cuando", "quien", "como", "cuanto")
        }

    def _d4(self, request, prompt):
        catalog = {
            code: fid
            for fid, code in re.findall(
                r"- \[(F\d+)\] [^\n]*?(RC-\d\d|ND-\d\d) — ", prompt
            )
        }
        blocks = re.findall(
            r'<fuente id="(F\d+|T\d+)"[^>]*>(.*?)</fuente>', prompt, re.DOTALL
        )
        tool = next((i for i, _ in blocks if i.startswith("T")), "NCR")

        def cause(code, bad=False, blame=False):
            case = [i for i, b in blocks if i.startswith("F") and code in b]
            cites = [tool] if bad else [*case[:1], catalog.get(code, "F1")]
            expl = "Desgaste de herramental por operar más ciclos de los permitidos sin mantenimiento."
            if blame:
                expl = "Fue un error del operador al crimpar la terminal en el turno."
            return {
                "codigo": code,
                "explicacion": expl,
                "evidencia": [
                    self._h("hecho respaldado por las fuentes citadas", *cites)
                ],
                "pregunta_confirmacion": "¿Qué dicen las hojas de verificación del equipo en ese periodo?",
            }

        bad = request.model in self.bad_for
        blame = request.model in self.blame_for
        first = cause(self.occ[0], bad=bad, blame=blame)
        if self.contra:
            first["evidencia_contradictoria"] = [
                self._h("los datos del lote no muestran anomalía", tool)
            ]
            first["refutaria"] = "Que la altura de crimpado del periodo esté centrada."
            first["dato_faltante"] = "Conteo de ciclos del aplicador al momento del defecto."
        return {
            "estado": self.estado,
            "causas_ocurrencia": [
                first,
                cause(self.occ[1]),
                cause(self.occ[2]),
            ],
            "causa_no_deteccion": cause(self.nd),
        }

    async def aclose(self):
        return None


# ------------------------------------------------------------------ gateway


def make_deps(
    env, *, local=None, api=None, redactor_terms=None, store=None
) -> AgentDeps:
    settings = LLMSettings(
        local=_local(), api=_api() if api is not None else None, _env_file=None
    )  # type: ignore[call-arg]
    terms = redactor_terms
    if terms is None:
        terms = ncr_repo.catalog_terms(env.conn)
    forbidden = {
        kind: [
            t.term
            for t in terms
            if t.kind == kind and t.level is ConfidentialityLevel.CONFIDENCIAL
        ]
        for kind in ("cliente", "parte")
    }
    clients = {Destination.LOCAL: local or FakeAgentLLM()}
    if api is not None:
        clients[Destination.API] = api
    gateway = ModelGateway(
        settings,
        clients,
        SqlAuditSink(env.engine.begin),
        CatalogInspector(forbidden),
        RuleRedactor(terms, store or InMemoryPseudonymStore()),
    )
    return AgentDeps(engine=env.engine, gateway=gateway, embedder=env.embedder)


__all__ = ["CatalogTerm", "FakeAgentLLM", "SingleConnEngine", "make_deps"]
