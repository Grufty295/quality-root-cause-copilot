import pytest
from app.evalkit.agent import classify_run, is_invalid


def row(generated=False, llm_errors=(), error=None, blocked=None, classes=()):
    return {
        "score": {"generated": generated},
        "llm_errors": list(llm_errors),
        "llm_error_classes": list(classes),
        "error": error,
        "blocked": blocked or {},
    }


@pytest.mark.parametrize(
    "r,esperado",
    [
        (row(generated=True), "ok"),
        (
            row(generated=True, llm_errors=["LLMTransportError: HTTP 503"]),
            "ok",
        ),  # se recuperó
        (row(llm_errors=["LLMTransportError: HTTP 503"]), "invalida"),
        (row(llm_errors=["LLMRequestError: HTTP 404"]), "invalida"),
        (row(llm_errors=["LLMResponseError"]), "invalida"),
        (row(error="Timeout"), "invalida"),
        (row(llm_errors=["StructuredOutputError"]), "fail"),
        (
            row(llm_errors=["StructuredOutputError", "LLMTransportError: HTTP 503"]),
            "invalida",
        ),
        (row(llm_errors=["PolicyViolation: payload"]), "bloqueada"),
        (row(llm_errors=["RedactionFailed", "StructuredOutputError"]), "bloqueada"),
        (row(llm_errors=["ClaseNueva"]), "invalida"),
        (
            row(blocked={"D4": "No se pudo obtener una respuesta del modelo (X)."}),
            "invalida",
        ),
        (row(blocked={"D4": "Se descartaron todas las causas"}), "ok"),
        # El caso clave: sin fila de auditoría de error, el evento basta para clasificar fail.
        (
            row(
                classes=["StructuredOutputError"],
                blocked={
                    "D4": "No se pudo obtener una respuesta del modelo (StructuredOutputError)."
                },
            ),
            "fail",
        ),
    ],
)
def test_clasificacion(r, esperado):
    assert classify_run(r) == esperado


def test_solo_infra_se_repite():
    assert is_invalid(row(llm_errors=["LLMTransportError: HTTP 503"]))
    assert not is_invalid(row(llm_errors=["StructuredOutputError"]))
    assert not is_invalid(row(llm_errors=["PolicyViolation: payload"]))


def test_observed_concurrency_counts_overlaps():
    from app.evalkit.agent import observed_concurrency

    def r(a, b):
        return {
            "started_at": f"2026-10-16T10:{a}:00+00:00",
            "finished_at": f"2026-10-16T10:{b}:00+00:00",
        }

    assert observed_concurrency([r("00", "05"), r("05", "10")]) == 1  # una tras otra
    assert observed_concurrency([r("00", "05"), r("01", "06"), r("02", "07")]) == 3
    assert observed_concurrency([{}]) is None
