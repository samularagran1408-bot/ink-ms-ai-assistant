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


async def _leer(coleccion: str, filtro: dict, limite: int = 500) -> list[dict[str, Any]]:
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
    documentos = await _leer(COL_EJERCICIOS, {"activo": True})
    return documentos or CATALOGO_EJERCICIOS


async def obtener_conocimiento(intencion: str) -> Optional[dict[str, Any]]:
    documentos = await _leer(COL_CONOCIMIENTO, {"intencion": intencion, "activo": True}, limite=1)
    if documentos:
        return documentos[0]
    base = CONOCIMIENTO.get(intencion)
    if base is None:
        return None
    return {"intencion": intencion, **base}


async def obtener_banco_quiz(rol: str) -> list[dict[str, Any]]:
    documentos = await _leer(COL_QUIZ, {"rol": rol, "activo": True})
    return documentos or BANCOS.get(rol, [])
