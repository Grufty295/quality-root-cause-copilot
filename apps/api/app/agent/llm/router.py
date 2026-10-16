"""Router de confidencialidad.

Orden de decisión (PRD, "Orden de routing"): primero confidencialidad, después costo.

1. El nivel del contexto es el más alto entre la NCR y los fragmentos que irán
   en el prompt. Sin clasificar = confidencial.
2. Confidencial -> local, siempre. No hay configuración que lo cambie.
3. Público o interno -> api si está configurada (con redacción obligatoria);
   si no, local.
4. El tamaño del modelo lo decide la etapa: D2 y D3 pequeño, D4 y el juez de evals grande, salvo que
   quien llama fije `ctx.tier` (cascada de D4: pequeño primero).

Es una función pura sobre la configuración: no llama a nada ni escribe nada,
así que se prueba sin red ni base de datos.
"""

from __future__ import annotations

from .config import LLMSettings
from .enums import ConfidentialityLevel, Destination, ModelTier, Stage
from .schemas import RouteContext, RouteDecision

_STAGE_TIER: dict[Stage, ModelTier] = {
    Stage.D2: ModelTier.SMALL,
    Stage.D3: ModelTier.SMALL,
    Stage.D4: ModelTier.LARGE,
    Stage.EVAL: ModelTier.LARGE,
}


class ConfidentialityRouter:
    def __init__(self, settings: LLMSettings) -> None:
        self._settings = settings

    def decide(self, ctx: RouteContext) -> RouteDecision:
        level = ctx.level
        tier = ctx.tier or _STAGE_TIER[ctx.stage]

        if level is ConfidentialityLevel.CONFIDENCIAL:
            destination = Destination.LOCAL
            reason = (
                "contexto sin clasificar: se trata como confidencial"
                if ctx.input_level is None
                else "contexto confidencial del cliente: solo local"
            )
        elif self._settings.api is None:
            destination = Destination.LOCAL
            reason = f"contexto {level.value}: destino api no configurado"
        else:
            destination = Destination.API
            reason = f"contexto {level.value}: api con identificadores redactados"

        dest_settings = self._settings.destination(destination)
        return RouteDecision(
            destination=destination,
            level=level,
            tier=tier,
            model=dest_settings.model_for(tier),
            simulated=dest_settings.simulated,
            must_redact=destination is Destination.API,
            must_pseudonymize=ctx.contains_pii,
            reason=reason,
        )
