"""Tools LOCALES (nunca MCP). fuente agente ≠ via mcp."""

from __future__ import annotations

import json
from typing import Any

from crewai.tools import tool

from app.agents.competencia_agent import CompetenciaAgent
from app.agents.quiz_agent import UMBRALES
from app.agents.recomendacion_agent import RecomendacionAgent
from app.agents.riesgo_agent import RiesgoAgent
from app.crew.ctx import (
    authorization,
    correr_async,
    discapacidad,
    log_taller,
    registrar_lectura,
    usuario_id,
)
from app.data.quiz_banco import BANCO_ENTRENADOR, BANCO_ORGANIZADOR
from app.motor.rutinas import generar_rutina as motor_rutina
from app.services.user_service import UserService


def _texto(datos: dict[str, Any]) -> str:
    return json.dumps(datos, ensure_ascii=False, default=str)[:6000]


def _local(accion: str, data: Any) -> dict[str, Any]:
    payload = {
        "success": True,
        "via": "agente",
        "fuente": "agente",
        "accion": accion,
        "data": data,
    }
    registrar_lectura(accion, payload)
    return payload


@tool("info_quiz")
def info_quiz() -> str:
    """Umbrales y tamaño del banco de quiz organizador/entrenador. No usa MCP."""
    log_taller("👉 [Tool] info_quiz (local)")
    datos = {
        "umbrales": UMBRALES,
        "preguntas_banco": {
            "ORGANIZADOR": len(BANCO_ORGANIZADOR),
            "ENTRENADOR": len(BANCO_ENTRENADOR),
        },
        "nota": (
            "Organizador aprueba con 70+. Entrenador con 75+. "
            "Generar/evaluar el quiz real sigue en POST /api/ai/quiz/..."
        ),
    }
    return _texto(_local("info_quiz", datos))


@tool("muestra_preguntas_quiz")
def muestra_preguntas_quiz(rol: str = "ORGANIZADOR") -> str:
    """Muestra 3 preguntas del banco (sin la respuesta correcta). No toca Users."""
    log_taller(f"👉 [Tool] muestra_preguntas_quiz rol={rol!r}")
    clave = (rol or "ORGANIZADOR").upper()
    banco = BANCO_ENTRENADOR if clave.startswith("ENTREN") else BANCO_ORGANIZADOR
    muestra = [
        {
            "id": p.get("id"),
            "enunciado": p.get("enunciado"),
            "opciones": p.get("opciones"),
            "tema": p.get("tema"),
        }
        for p in banco[:3]
    ]
    return _texto(_local("muestra_preguntas_quiz", {"rol": clave, "preguntas": muestra}))


@tool("panorama_competencia")
def panorama_competencia() -> str:
    """Panorama competitivo y plan (CompetenciaAgent). No es dashboard admin."""
    log_taller("👉 [Tool] panorama_competencia (local)")
    uid = usuario_id() or "demo-user"

    async def _go() -> dict[str, Any]:
        return await CompetenciaAgent().analizar_rendimiento(uid, authorization())

    return _texto(_local("panorama_competencia", correr_async(_go)))


@tool("evaluar_riesgo_plan")
def evaluar_riesgo_plan() -> str:
    """Riesgo/fatiga heurístico a nivel de plan (RiesgoAgent). No es diagnóstico."""
    log_taller("👉 [Tool] evaluar_riesgo_plan (local)")
    uid = usuario_id() or "demo-user"

    async def _go() -> dict[str, Any]:
        return await RiesgoAgent().evaluar(
            usuario_id=uid,
            authorization=authorization(),
        )

    return _texto(_local("evaluar_riesgo_plan", correr_async(_go)))


@tool("consultar_mi_perfil")
def consultar_mi_perfil() -> str:
    """Perfil de la sesión (Users HTTP, no MCP). No pidas email ni id."""
    log_taller("👉 [Tool] consultar_mi_perfil (local)")

    async def _go() -> dict[str, Any]:
        return await UserService().get_my_profile(authorization())

    perfil = correr_async(_go)
    return _texto(_local("consultar_mi_perfil", perfil))


@tool("generar_rutina")
def generar_rutina(objetivo: str = "general") -> str:
    """Rutina adaptada del motor local. No publica en Sports."""
    log_taller(f"👉 [Tool] generar_rutina objetivo={objetivo!r}")
    rutina = motor_rutina(discapacidad(), objetivo_texto=objetivo or "general")
    return _texto(_local("generar_rutina", rutina))


@tool("recomendar_evento_nuevo")
def recomendar_evento_nuevo() -> str:
    """Recomienda eventos reales para ESTA persona (heurística local)."""
    log_taller("👉 [Tool] recomendar_evento_nuevo (local)")
    uid = usuario_id() or "demo-user"

    async def _go() -> dict[str, Any]:
        return await RecomendacionAgent().recomendar_eventos(uid, authorization=authorization())

    return _texto(_local("recomendar_evento_nuevo", correr_async(_go)))


@tool("recomendar_deporte_nuevo")
def recomendar_deporte_nuevo(idea: str = "") -> str:
    """Propone un deporte inclusivo (borrador local, no crea en el catálogo)."""
    log_taller(f"👉 [Tool] recomendar_deporte_nuevo idea={idea!r}")
    propuesta = {
        "name": (idea or "Deporte adaptado de prueba").strip()[:80],
        "nota": "Borrador local. Para simular el alta usa el dominio automatizado (sandbox).",
    }
    return _texto(_local("recomendar_deporte_nuevo", propuesta))


@tool("recomendar_rutina_nueva")
def recomendar_rutina_nueva(objetivo: str = "general") -> str:
    """Propone una rutina del motor local como recomendación de plan."""
    log_taller(f"👉 [Tool] recomendar_rutina_nueva objetivo={objetivo!r}")
    rutina = motor_rutina(discapacidad(), objetivo_texto=objetivo or "general")
    return _texto(_local("recomendar_rutina_nueva", rutina))


TOOLS_QUIZ = (info_quiz, muestra_preguntas_quiz)
TOOLS_COMPETENCIA_LOCAL = (panorama_competencia, evaluar_riesgo_plan)
TOOLS_CONSULTA_LOCAL = (
    consultar_mi_perfil,
    generar_rutina,
    recomendar_evento_nuevo,
    recomendar_deporte_nuevo,
    recomendar_rutina_nueva,
)
