"""Salidas estables para el front (taller 05: output_pydantic)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class InformeCrew(BaseModel):
    """Informe de cualquier dominio de crew."""

    resumen: str = Field(
        description=(
            "Respuesta al usuario final en español: nombres, fechas, cupos. "
            "Nunca menciones MCP, sandbox, tools, protocolos ni 'análisis'."
        ),
    )
    tools_usadas: list[str] = Field(
        default_factory=list,
        description=(
            "Nombres exactos de tools llamadas, p.ej. listar_eventos_disponibles. "
            "Nunca MODEL CONTEXT PROTOCOL ni SANDBOX ENVIRONMENT."
        ),
    )
    via_mcp: bool = Field(
        default=False,
        description="True si alguna tool devolvió via='mcp'. No lo copies al resumen.",
    )
    via_sandbox: bool = Field(
        default=False,
        description="True si alguna tool devolvió via='sandbox'. No lo copies al resumen.",
    )
    fuente_tools: str = Field(
        default="agente",
        description="Uno de: mcp, sandbox, agente. Solo este campo; no lo copies al resumen.",
    )
    hallazgos: str = Field(
        description=(
            "Hechos para el usuario (eventos, cupos, fechas). Sin cifras inventadas. "
            "Sin MCP ni sandbox."
        ),
    )
    pendiente_confirmacion: bool = Field(
        default=False,
        description="True si el sandbox pidió Confirmo y aún no mutó.",
    )


class InformeInvestigacion(InformeCrew):
    """Alias pedagógico del informe de investigación."""


class DominioInfo(BaseModel):
    """Un dominio que el front puede pintar en un selector."""

    id: str
    via: str
    descripcion: str


class CrewWritesInfo(BaseModel):
    """Dónde escribe cada vía. Crew = sandbox; chat = MCP real."""

    crew: str = "sandbox"
    chat: str = "mcp"
    nota: str = ""


class CrewDominiosResponse(BaseModel):
    """GET /api/ai/crew/dominios."""

    dominios: list[DominioInfo]
    auto: str
    chat: str
    rol: str = "USUARIO"
    writes: CrewWritesInfo = Field(default_factory=CrewWritesInfo)


class CrewRunRequest(BaseModel):
    """Cuerpo de POST /api/ai/crew/run."""

    mensaje: str = Field(..., min_length=1, max_length=4000)
    dominio: str = Field(
        default="auto",
        description="auto | investigacion | quiz | competencia | automatizado | consulta",
    )


class CrewRunResponse(BaseModel):
    """JSON estable para el front."""

    dominio: str
    dominio_origen: str = Field(
        default="cliente",
        description="cliente | auto | confirmo",
    )
    intencion: Optional[str] = None
    confianza: Optional[float] = None
    fuente: str = "crew"
    informe: InformeCrew
