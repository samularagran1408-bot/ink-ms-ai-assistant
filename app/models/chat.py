"""Esquemas Pydantic del chat: petición, respuesta y mensaje de historial."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Cuerpo de POST /chat: mensaje, conversación opcional y limitación corporal."""
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
    limitacion: Optional[str] = Field(
        default=None,
        description="Dolor o limitación corporal a marcar en el dibujo del cuerpo",
    )


class ChatResponse(BaseModel):
    """Respuesta del chatbot: texto, intención, cards, tools usadas y mapa corporal."""
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
    cuerpo: Optional[dict[str, Any]] = Field(
        default=None,
        description="Dibujo del cuerpo con zonas de dolor/limitación en rojo",
    )
    aviso: Optional[str] = Field(
        default=None,
        description="Aviso de cupo horario (se muestra al usuario, no lo inventa el LLM)",
    )
    cupo: Optional[dict[str, Any]] = Field(
        default=None,
        description="Uso del límite de mensajes por hora",
    )


class Mensaje(BaseModel):
    """Turno persistido en el historial de una conversación."""
    mensaje: str
    remitente: str
    intencion: Optional[str] = None
    fecha: datetime = Field(default_factory=datetime.utcnow)
