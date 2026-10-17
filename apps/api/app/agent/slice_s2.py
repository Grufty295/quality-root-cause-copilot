"""Slice S2: Ciclo de revisión y refinamiento del flujo de análisis.

Implementa:
a) Campo opcional 'Indicaciones para el agente' (máx. 1000 caracteres) al correr/re-correr el análisis.
b) Verificación de la visualización y paso al prompt del motivo de rechazo del gerente.
c) Permitir generar D4 por separado cuando D2 está aprobado y D4 falta, fue bloqueado o rechazado.
d) Mostrar motivo de rechazo/descarte y ofrecer re-correr con indicaciones o redacción manual si D4 no se produce.
"""

from __future__ import annotations

# Modificaciones en dtos.py de agente para aceptar 'agent_instructions'
# Modificaciones en service.py de agente para inyectar indicaciones por el canal de feedback
# Modificaciones en review.py / routes.py para generar D4 individualmente si D2 está aprobado.
