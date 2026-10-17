import pytest
from uuid import uuid4
from app.agent.evidence import EvidenceBook, Evidence
from app.agent.graph import build_query
from app.confidentiality import ConfidentialityLevel

def test_build_query_part_at_start():
    # 5. build_query: número de parte al inicio, antes de truncar a 600
    q = build_query("Falla de crimpado en terminal", part_number="P-100")
    assert q.startswith("P-100 Falla de crimpado")
    assert len(q) <= 600

def test_catalog_deduplicate_ordering():
    # BUG-07: dedupe mantiene catalog_code sin importar el orden de llegada
    book = EvidenceBook()
    fid = uuid4()
    
    # Llega primero sin catalog_code
    e1 = book.add_fragment(
        fragment_id=fid,
        document="DOC-1",
        section="RC-01",
        title="T1",
        content="Texto 1",
        level=ConfidentialityLevel.PUBLICO,
        contains_pii=False,
        catalog_code=None
    )
    assert e1.catalog_code is None

    # Llega después con catalog_code
    e2 = book.add_fragment(
        fragment_id=fid,
        document="DOC-1",
        section="RC-01",
        title="T1",
        content="Texto 1",
        level=ConfidentialityLevel.PUBLICO,
        contains_pii=False,
        catalog_code="RC-01"
    )
    assert e2.catalog_code == "RC-01"
