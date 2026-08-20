"""Catálogo de tools OpenAI-compatible para el chatbot de InkluSport.

El LLM elige qué llamar; la ejecución real reutiliza las acciones del motor
local (`eventos`, `rutina`, etc.) vía `accion_de_tool`.
"""

from __future__ import annotations

from typing import Any, Optional

# name de la tool → acción interna de ChatbotAgent._enriquecer
_TOOL_A_ACCION: dict[str, str] = {
    "listar_eventos": "eventos",
    "listar_deportes": "deportes",
    "listar_discapacidades": "discapacidades",
    "listar_adaptaciones": "adaptaciones",
    "generar_rutina": "rutina",
    "listar_ejercicios": "ejercicios",
    "info_quiz": "quiz",
    "consultar_mi_perfil": "perfil",
    "estadisticas_usuario": "estadisticas",
    "recomendar_evento_nuevo": "propuesta_evento",
    "recomendar_deporte_nuevo": "propuesta_deporte",
    "recomendar_rutina_nueva": "propuesta_rutina",
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "listar_eventos",
            "description": (
                "Lista eventos deportivos publicados en InkluSport y señala "
                "cuáles encajan con el perfil de discapacidad del usuario. "
                "Úsala cuando pregunten por eventos, competencias o cupos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "solo_compatibles": {
                        "type": "boolean",
                        "description": "Si true, prioriza eventos compatibles con el perfil.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_deportes",
            "description": (
                "Catálogo de deportes activos en la plataforma (nombre, "
                "dificultad, material). Úsala para recomendar o listar deportes."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_discapacidades",
            "description": (
                "Categorías de discapacidad registradas en InkluSport."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_adaptaciones",
            "description": (
                "Adaptaciones deporte-discapacidad registradas. Úsala cuando "
                "pregunten cómo adaptar un deporte o qué apoyos hay."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generar_rutina",
            "description": (
                "Genera una rutina de entrenamiento adaptada al perfil del "
                "usuario. Úsala cuando pidan rutina, entrenamiento o plan corto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "objetivo": {
                        "type": "string",
                        "description": (
                            "Objetivo en lenguaje natural: fuerza, cardio, "
                            "movilidad, etc."
                        ),
                    },
                    "duracion_minutos": {
                        "type": "integer",
                        "description": "Duración aproximada deseada en minutos.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_ejercicios",
            "description": (
                "Sugiere ejercicios concretos adaptados al perfil (series, "
                "repeticiones e instrucciones)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "objetivo": {
                        "type": "string",
                        "description": "Enfoque del ejercicio (fuerza, movilidad…).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "info_quiz",
            "description": (
                "Información sobre los quices de aptitud para organizador y "
                "entrenador (cantidad de preguntas y umbrales)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_mi_perfil",
            "description": (
                "Lee el perfil del usuario autenticado (nombre, discapacidad, "
                "roles). Úsala cuando pregunten por su perfil, datos o "
                "adaptaciones personales. NUNCA pidas email ni ID: ya está "
                "en la sesión."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estadisticas_usuario",
            "description": (
                "Estadísticas del usuario de la sesión: inscripciones, "
                "comparativa, riesgo y alertas. Un admin puede pasar "
                "nombre_o_id de otra persona (nombre, no hace falta el ID)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nombre_o_id": {
                        "type": "string",
                        "description": (
                            "Solo admin/entrenador: nombre o id de otro usuario. "
                            "Vacío = el de la sesión."
                        ),
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recomendar_evento_nuevo",
            "description": (
                "Propone un evento nuevo listo para crear (organizador/admin): "
                "deporte, fecha, hora, cupo y nombre. Tras proponerlo, ofrece "
                "crearlo con crear_evento cuando el usuario confirme."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "idea": {
                        "type": "string",
                        "description": "Tema o deporte deseado, si lo mencionó.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recomendar_deporte_nuevo",
            "description": (
                "Propone un deporte para dar de alta en el catálogo "
                "(entrenador/admin), con nombre, dificultad y material."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "idea": {"type": "string", "description": "Nombre o enfoque del deporte."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recomendar_rutina_nueva",
            "description": (
                "Genera una rutina adaptada y la deja lista para guardarla "
                "en la plataforma (entrenador/admin) con crear_rutina."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "objetivo": {"type": "string", "description": "Objetivo de la rutina."},
                    "duracion_minutos": {"type": "integer"},
                },
            },
        },
    },
]


def accion_de_tool(nombre: str) -> Optional[str]:
    return _TOOL_A_ACCION.get((nombre or "").strip())


def nombres_tools() -> list[str]:
    return list(_TOOL_A_ACCION.keys())


def mensaje_tool_para_objetivo(nombre: str, argumentos: dict[str, Any], fallback: str) -> str:
    """Texto que se pasa a _enriquecer como 'mensaje' (objetivo de rutina, etc.)."""
    if nombre in ("generar_rutina", "listar_ejercicios"):
        objetivo = (argumentos or {}).get("objetivo")
        if objetivo and str(objetivo).strip():
            return str(objetivo).strip()
    return fallback
