from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    mensaje: str
    usuario_id: Optional[str] = None
    disability_type: Optional[str] = Field(
        default=None,
        description="visual | auditiva | motriz | cognitiva | intelectual | multiple",
    )
    conversacion_id: Optional[str] = Field(
        default=None,
        description="Reutiliza el id para mantener historial entre turnos",
    )


class ChatResponse(BaseModel):
    conversacion_id: str
    respuesta: str
    intencion: str
    adaptada: bool
    confianza: float = 0.0
    fuente: str = "motor_local"
    agente: str = "inklusport-profesional"
    sugerencias: list[str] = Field(default_factory=list)
    datos: Optional[dict[str, Any]] = None
    herramientas_usadas: list[str] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Hechos accionables (eventos, rutina, quiz) con CTA para el front",
    )
    mcp: Optional[dict[str, Any]] = Field(
        default=None,
        description="Metadatos del protocolo interno de tools (estilo MCP)",
    )


class Mensaje(BaseModel):
    mensaje: str
    remitente: str
    intencion: Optional[str] = None
    fecha: datetime = Field(default_factory=datetime.utcnow)
