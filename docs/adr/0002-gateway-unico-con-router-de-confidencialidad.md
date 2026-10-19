# ADR 0002 — Gateway único de modelos con router de confidencialidad

**Estado:** Aceptada

## Contexto
Lo confidencial (clientes, partes, programas) no puede salir de la planta; lo demás puede usar una API externa más capaz.

## Decisión
Todo acceso a un LLM pasa por `ModelGateway`: router → redactor → inspector → cliente → restauración → auditoría. El nivel más alto del
contexto (NCR, fragmentos y salidas de tools) decide el destino. Confidencial: solo local, con seudónimos de PII. Interno o público:
local o API, con redacción de clientes, partes y PII y un inspector que bloquea cualquier identificador restante.
Si la auditoría no se escribe, el resultado no se devuelve. Si el redactor falla, la llamada se bloquea (falla cerrada).

## Alternativas descartadas
- **Filtrar en cada nodo:** cada nodo nuevo podría olvidarlo. Los nodos reciben el gateway, no un cliente.
- **Presidio para PII:** suficiente con reglas y catálogo para las entidades del PoC; queda como diseño.
- **Todo local:** descarta la comparación con modelos más capaces y encarece el desarrollo.

## Consecuencias
- (+) Un solo punto que probar y auditar. La base impone la invariante aunque el código falle (ADR 0005).
- (−) El redactor es heurístico: un nombre sin rol ni etiqueta delante no se detecta; los marcadores son del dataset sintético.
- (−) Hoy el "local" se simula con OpenRouter (`LLM_LOCAL__SIMULATED=true`): la garantía de fondo no se cumple hasta que haya un modelo local real.

## Evidencia
`tests/agent/llm/test_gateway_redaction.py`, `test_llm_gateway.py`, `tests/agent/graph/test_security_gates_db.py` (ADV-04, 07, 08, 09, 10).
