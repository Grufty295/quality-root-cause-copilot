"""Capa de acceso a modelos: router de confidencialidad, clientes y gateway auditado."""

from .audit import SqlAuditSink
from .client import LLMClient
from .config import DestinationSettings, LLMSettings, get_llm_settings
from .enums import ConfidentialityLevel, Destination, ModelTier, Stage
from .errors import (
    LLMError,
    LLMRequestError,
    LLMResponseError,
    LLMTransportError,
    PolicyViolation,
    RedactionFailed,
    StructuredOutputError,
)
from .gateway import (
    AuditSink,
    CallMeta,
    GatewayResult,
    GatewayStructuredResult,
    ModelGateway,
)
from .inspector import CatalogInspector, PayloadInspector
from .router import ConfidentialityRouter
from .schemas import (
    LLMCallRecord,
    LLMRequest,
    LLMResult,
    Message,
    RouteContext,
    RouteDecision,
    ToolCall,
    ToolSpec,
    Usage,
)

__all__ = [
    "AuditSink",
    "CallMeta",
    "CatalogInspector",
    "ConfidentialityLevel",
    "ConfidentialityRouter",
    "Destination",
    "DestinationSettings",
    "GatewayResult",
    "GatewayStructuredResult",
    "LLMCallRecord",
    "LLMClient",
    "LLMError",
    "LLMRequest",
    "LLMRequestError",
    "LLMResponseError",
    "LLMResult",
    "LLMSettings",
    "LLMTransportError",
    "Message",
    "ModelGateway",
    "ModelTier",
    "PayloadInspector",
    "PolicyViolation",
    "RedactionFailed",
    "RouteContext",
    "RouteDecision",
    "SqlAuditSink",
    "Stage",
    "StructuredOutputError",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "get_llm_settings",
]
