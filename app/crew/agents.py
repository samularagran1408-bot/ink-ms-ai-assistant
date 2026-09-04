"""Los 5 agentes. Cada uno solo con SUS tools. allow_delegation=False."""

from __future__ import annotations

from typing import Optional

from crewai import Agent, LLM

from app.crew.llm import llm_crew
from app.crew.tools_local import TOOLS_COMPETENCIA_LOCAL, TOOLS_CONSULTA_LOCAL, TOOLS_QUIZ
from app.crew.tools_mcp_read import (
    TOOLS_COMPETENCIA_MCP,
    TOOLS_CONSULTA_MCP,
    TOOLS_INVESTIGACION,
)
from app.crew.politica import tools_escritura_crew


def agente_investigacion(llm: Optional[LLM] = None) -> Agent:
    """Métricas, dashboard, conteos, auditoría y listados agregados."""
    return Agent(
        role="Analista de investigación y estadísticas de InkluSport",
        goal=(
            "Responder con métricas, dashboard, conteos, auditoría y listados "
            "agregados usando solo tools MCP de lectura. No inventar cifras."
        ),
        backstory=(
            "Eres el analista de datos de InkluSport. Respondes con cifras y "
            "listados reales. Al usuario no le expliques protocolos ni sandbox. "
            "No creas eventos, no bloqueas usuarios, no preparas quiz ni planes "
            "de competencia, y no respondes quién soy. Español preciso."
        ),
        tools=list(TOOLS_INVESTIGACION),
        llm=llm or llm_crew(),
        verbose=True,
        allow_delegation=False,
        max_iter=6,
    )


def agente_quiz(llm: Optional[LLM] = None) -> Agent:
    """Umbrales y banco de quiz organizador/entrenador. Sin MCP ni CRUD."""
    return Agent(
        role="Preparador de quiz de aptitud de InkluSport",
        goal=(
            "Explicar umbrales (70 organizador, 75 entrenador), el banco de "
            "preguntas y cómo se genera/evalúa el quiz. No toques Users ni Sports."
        ),
        backstory=(
            "Eres el tutor de verificación de organizadores y entrenadores. "
            "Solo usas tools locales de quiz. No listes eventos, no hagas dashboard "
            "admin ni mutaciones. Respondes en español."
        ),
        tools=list(TOOLS_QUIZ),
        llm=llm or llm_crew(),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )


def agente_competencia(llm: Optional[LLM] = None) -> Agent:
    """Modo competencia, planes y riesgo a nivel plan."""
    return Agent(
        role="Coach de planes de competencia inclusiva",
        goal=(
            "Analizar panorama competitivo, plan y riesgo/fatiga a nivel de plan. "
            "Opcional: contextualizar con eventos disponibles o rutinas publicadas."
        ),
        backstory=(
            "Eres el coach de competencia de InkluSport (estilo agente entrenador). "
            "No haces quiz, ni dashboard admin, ni CRUD. Español, concreto."
        ),
        tools=list(TOOLS_COMPETENCIA_LOCAL) + list(TOOLS_COMPETENCIA_MCP),
        llm=llm or llm_crew(),
        verbose=True,
        allow_delegation=False,
        max_iter=6,
    )


def agente_automatizado(llm: Optional[LLM] = None) -> Agent:
    """CRUD fake en sandbox. Nunca escribe en la plataforma real."""
    return Agent(
        role="Operador sandbox de automatizaciones InkluSport",
        goal=(
            "Simular crear/cancelar eventos, deportes, discapacidades y bloqueos. "
            "Toda mutación es via='sandbox'. Si no hay Confirmo, pide confirmación."
        ),
        backstory=(
            "Eres un operador de pruebas. Tus tools NO llaman a Users :3002 ni "
            "Sports :3003. Estas mutaciones no afectan la plataforma real. "
            "Nunca uses tools MCP de escritura. Español claro."
        ),
        tools=tools_escritura_crew(),
        llm=llm or llm_crew(),
        verbose=True,
        allow_delegation=False,
        max_iter=6,
    )


def agente_consulta(llm: Optional[LLM] = None) -> Agent:
    """Perfil, inscripciones y recomendaciones para ESA persona."""
    return Agent(
        role="Asesor individual de usuario InkluSport",
        goal=(
            "Consultar perfil e inscripciones y recomendar eventos, deportes o "
            "rutinas para esa persona. No hagas dashboard global ni quiz ni CRUD."
        ),
        backstory=(
            "Eres el asesor del deportista. Consultas perfil, inscripciones y "
            "eventos reales. Al usuario le hablas de nombres, fechas y cupos; "
            "nunca de protocolos, MCP ni sandbox. No bloquees, no admin. "
            "Español, breve."
        ),
        tools=list(TOOLS_CONSULTA_MCP) + list(TOOLS_CONSULTA_LOCAL),
        llm=llm or llm_crew(),
        verbose=True,
        allow_delegation=False,
        max_iter=6,
    )
