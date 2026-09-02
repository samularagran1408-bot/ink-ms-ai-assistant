"""Salidas estables para el front (taller 05: output_pydantic)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InformeCrew(BaseModel):
    """Informe de cualquier dominio de crew."""

    resumen: str = Field(description="Qué se preguntó y qué se obtuvo, en español.")
    tools_usadas: list[str] = Field(default_factory=list)
    via_mcp: bool = Field(
        default=False,
        description="True si alguna tool devolvió via='mcp'.",
    )
    via_sandbox: bool = Field(
        default=False,
        description="True si alguna tool devolvió via='sandbox'.",
    )
    fuente_tools: str = Field(
        default="agente",
        description="mcp | sandbox | agente (puede mezclarse en el resumen).",
    )
    hallazgos: str = Field(description="Hechos. Sin cifras inventadas.")


class InformeInvestigacion(InformeCrew):
    """Alias pedagógico del informe de investigación."""


class CrewRunRequest(BaseModel):
    """Cuerpo de POST /api/ai/crew/run."""

    mensaje: str = Field(..., min_length=1, max_length=4000)
    dominio: str = Field(
        default="investigacion",
        description="investigacion | quiz | competencia | automatizado | consulta",
    )


class CrewRunResponse(BaseModel):
    """JSON estable para el front."""

    dominio: str
    fuente: str = "crew"
    informe: InformeCrew
