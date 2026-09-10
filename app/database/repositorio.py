"""Acceso de lectura a los datos del asistente.

Los catálogos viven en MongoDB para poder ajustarlos sin desplegar, pero el
código lleva la misma información como respaldo: si Mongo no está disponible o
una colección está vacía, el servicio sigue funcionando igual.
"""

from typing import Any, Optional

from app.data.conocimiento import CONOCIMIENTO
from app.data.ejercicios import CATALOGO_EJERCICIOS
from app.data.quiz_banco import BANCOS
from app.database.mongodb import get_db

COL_EJERCICIOS = "catalogo_ejercicios"
COL_CONOCIMIENTO = "conocimiento_chatbot"
COL_QUIZ = "banco_preguntas_quiz"
COL_CONVERSACIONES = "conversaciones_chatbot"
COL_QUIZZES = "quizzes_verificacion"
COL_PLANES = "planes_entrenamiento"
COL_SESIONES_RPE = "sesiones_rpe"
COL_ALERTAS = "alertas_entrenador"
COL_MODO_COMPETENCIA = "modo_competencia"
COL_ENTRENAMIENTO = "perfil_entrenamiento"
COL_EVALUACIONES_RIESGO = "evaluaciones_riesgo"

CAMPOS_EJERCICIO = ("id", "nombre", "fase", "series", "nivel", "posicion")


async def _leer(coleccion: str, filtro: dict, limite: int = 500) -> list[dict[str, Any]]:
    """Lee documentos de Mongo sin `_id`; lista vacía si no hay BD o hay error."""
    db = get_db()
    if db is None:
        return []
    try:
        cursor = db[coleccion].find(filtro, {"_id": 0}).limit(limite)
        return await cursor.to_list(length=limite)
    except Exception as exc:
        print(f"Error leyendo {coleccion}: {exc}")
        return []


async def obtener_catalogo_ejercicios() -> list[dict[str, Any]]:
    """Catálogo embebido más ejercicios extra de Mongo (ids que no están en código).

    El código es la fuente de los ejercicios oficiales (tags y objetivos nuevos
    llegan sin re-sembrar). Mongo solo aporta piezas personalizadas con otro `id`.
    """
    por_id: dict[str, dict[str, Any]] = {e["id"]: dict(e) for e in CATALOGO_EJERCICIOS}
    documentos = await _leer(COL_EJERCICIOS, {"activo": True})
    for d in documentos:
        eid = d.get("id")
        if not eid or not d.get("nombre") or not d.get("fase"):
            continue
        if eid in por_id:
            continue
        por_id[str(eid)] = d
    return list(por_id.values())


async def obtener_conocimiento(intencion: str) -> Optional[dict[str, Any]]:
    """Ficha de conocimiento de una intención: primero Mongo, si no el dict embebido."""
    documentos = await _leer(COL_CONOCIMIENTO, {"intencion": intencion, "activo": True}, limite=1)
    if documentos:
        return documentos[0]
    base = CONOCIMIENTO.get(intencion)
    if base is None:
        return None
    return {"intencion": intencion, **base}


async def obtener_banco_quiz(rol: str) -> list[dict[str, Any]]:
    """Preguntas del quiz para un rol (ORGANIZADOR/ENTRENADOR); si Mongo está vacío, el banco local."""
    documentos = await _leer(COL_QUIZ, {"rol": rol, "activo": True})
    return documentos or BANCOS.get(rol, [])
