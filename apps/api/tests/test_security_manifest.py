"""Cada caso de seguridad de evals/ (ADV-01..10, PER-01..06) tiene una prueba que lo ejecuta.

`evals/casos_adversariales.jsonl` y `casos_permisos.jsonl` eran datos sin ejecutor: nada fallaba si un
caso dejaba de cumplirse. Este manifiesto ata cada id a la prueba que lo verifica; si el dataset gana o
pierde un caso, o una prueba se renombra o desaparece, esta prueba falla.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TESTS = Path(__file__).parent

ADV = "tests/agent/graph/test_security_gates_db.py::"
COVERAGE: dict[str, str] = {
    # permisos (API)
    "PER-01": "tests/retrieval/test_retrieval_db.py::test_permission_case_per_01",
    "PER-02": "tests/retrieval/test_retrieval_db.py::test_line_scope_hides_other_line",
    "PER-03": "tests/agent/graph/test_graph_db.py::test_only_engineers_run_the_agent_and_scope_applies",
    "PER-04": "tests/test_review_db.py::test_only_manager_approves",
    "PER-05": "tests/test_review_db.py::test_who_opened_cannot_approve",
    "PER-06": "tests/test_review_db.py::test_manager_approves_the_exact_text_reviewed",
    # adversariales
    "ADV-01": ADV + "test_adv_injection_in_the_ncr_stops_the_run_before_any_model_call",
    "ADV-02": ADV + "test_adv_injection_in_the_ncr_stops_the_run_before_any_model_call",
    "ADV-03": ADV + "test_adv_injection_in_the_ncr_stops_the_run_before_any_model_call",
    "ADV-04": ADV + "test_adv_04_a_whole_document_cannot_be_persisted_and_the_ncr_stays_local",
    "ADV-05": ADV + "test_adv_05_the_agent_has_no_tool_that_can_send_or_write_anything",
    "ADV-06": ADV + "test_adv_06_the_same_injection_inside_an_indexed_document_is_quarantined",
    "ADV-07": ADV + "test_adv_07_a_document_that_claims_to_be_public_keeps_the_level_of_its_front_matter",
    "ADV-08": ADV + "test_adv_hidden_confidential_content_never_reaches_the_api",
    "ADV-09": ADV + "test_adv_hidden_confidential_content_never_reaches_the_api",
    "ADV-10": ADV + "test_adv_10_pii_is_pseudonymized_in_every_payload_even_to_the_local_model",
}

# Los ids que el dataset declara hoy (data/generator/evals.py). Si cambian, se actualizan aquí y arriba.
EXPECTED_IDS = {f"PER-{i:02d}" for i in range(1, 7)} | {f"ADV-{i:02d}" for i in range(1, 11)}


def _evals_dir() -> Path | None:
    for parent in TESTS.resolve().parents:
        if (parent / "evals").is_dir():
            return parent / "evals"
    return None


def test_manifest_covers_exactly_the_declared_cases():
    assert set(COVERAGE) == EXPECTED_IDS


def test_manifest_matches_the_jsonl_files_when_they_are_present():
    evals = _evals_dir()
    ids: set[str] = set()
    for name in ("casos_adversariales.jsonl", "casos_permisos.jsonl"):
        path = evals / name if evals else None
        if path and path.exists():
            ids |= {json.loads(line)["caso_id"] for line in path.read_text(encoding="utf-8").splitlines() if line}
    if not ids:
        return  # los jsonl no se generaron en este entorno; EXPECTED_IDS sigue siendo la referencia
    assert ids == EXPECTED_IDS


def test_every_referenced_test_exists():
    missing = []
    for case_id, ref in COVERAGE.items():
        rel, name = ref.split("::")
        path = TESTS.parent / rel
        if not path.exists() or not re.search(rf"^(?:async )?def {re.escape(name)}\(", path.read_text(encoding="utf-8"), re.MULTILINE):
            missing.append(f"{case_id} -> {ref}")
    assert not missing, missing
