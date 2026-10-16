"""run_case: armado del NCR a partir de ncr.csv (sin base de datos ni modelo)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent import run_case
from app.agent.run_case import draft_from, load_case

ROW = {
    "ncr_id": "NCR-X",
    "linea": "L1, L2",
    "turno": "",
    "numero_parte": "A7-DRH-2210-M",
    "descripcion": "Reclamo: terminal fuera del conector.",
    "causa_preliminar": "no debe llegar al agente",
}


def test_multi_line_ncr_uses_the_first_line_unless_told_otherwise_and_blank_shift_is_1():
    draft = draft_from(ROW, None)
    assert (draft.line_id, draft.shift, draft.part_number) == ("L1", 1, "A7-DRH-2210-M")
    assert draft_from(ROW, "L2").line_id == "L2"


def test_the_plants_answer_never_reaches_the_draft():
    draft = draft_from(ROW, None)
    assert "no debe llegar" not in repr(draft)
    assert draft.description == "Reclamo: terminal fuera del conector."


def test_a_line_the_ncr_does_not_cover_is_rejected():
    with pytest.raises(SystemExit, match="no de L9"):
        draft_from(ROW, "L9")


def test_unknown_case_is_reported(tmp_path):
    (tmp_path / "ncr.csv").write_text("ncr_id,linea\nNCR-A,L1\n", encoding="utf-8")
    assert load_case(tmp_path, "NCR-A")["linea"] == "L1"
    with pytest.raises(SystemExit, match="NCR-B"):
        load_case(tmp_path, "NCR-B")


def test_resolve_out_relative_goes_to_traces(tmp_path):
    assert (
        run_case.resolve_out(Path("caso.json"), base=tmp_path) == tmp_path / "caso.json"
    )


def test_resolve_out_rejects_missing_folder_before_spending_tokens(tmp_path):
    # Lo que Git Bash hace con /tmp/caso.json: una ruta de Windows que no existe en Linux.
    with pytest.raises(SystemExit, match="traces/caso.json"):
        run_case.resolve_out(
            Path("C:/Users/x/AppData/Local/Temp/caso.json"), base=tmp_path
        )
