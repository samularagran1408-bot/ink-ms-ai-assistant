"""Acceso de lectura a los datos del asistente.

Los catálogos viven en MongoDB para poder ajustarlos sin desplegar, pero el
código lleva la misma información como respaldo: si Mongo no está disponible o
una colección está vacía, el servicio sigue funcionando igual.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from app.data.conocimiento import CONOCIMIENTO
from app.data.ejercicios import CATALOGO_EJERCICIOS
from app.data.quiz_banco import BANCOS
from app.database.mongodb import get_db

_TTL_SEGUNDOS = 45.0
_catalogo_cache: tuple[float, list[dict[str, Any]]] | None = None
_banco_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

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


def _programar(coro) -> None:
    """Lanza un refresco en segundo plano si hay loop; si no, lo omite."""
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        return


async def obtener_catalogo_ejercicios() -> list[dict[str, Any]]:
    """Catálogo embebido al instante; Mongo solo suma extras en segundo plano."""
    global _catalogo_cache
    ahora = time.monotonic()
    if _catalogo_cache and _catalogo_cache[0] > ahora:
        return _catalogo_cache[1]
    local = [dict(e) for e in CATALOGO_EJERCICIOS]
    _catalogo_cache = (ahora + _TTL_SEGUNDOS, local)
    _programar(_refrescar_catalogo())
    return local


async def _refrescar_catalogo() -> None:
    """Mezcla ejercicios extra de Mongo en la caché, sin bloquear al usuario."""
    global _catalogo_cache
    por_id: dict[str, dict[str, Any]] = {e["id"]: dict(e) for e in CATALOGO_EJERCICIOS}
    documentos = await _leer(COL_EJERCICIOS, {"activo": True})
    for d in documentos:
        eid = d.get("id")
        if not eid or not d.get("nombre") or not d.get("fase"):
            continue
        if eid in por_id:
            continue
        por_id[str(eid)] = d
    _catalogo_cache = (time.monotonic() + _TTL_SEGUNDOS, list(por_id.values()))


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
    """Banco local al instante; Mongo solo refresca la caché en segundo plano."""
    ahora = time.monotonic()
    hit = _banco_cache.get(rol)
    if hit and hit[0] > ahora:
        return hit[1]
    local = list(BANCOS.get(rol, []))
    _banco_cache[rol] = (ahora + _TTL_SEGUNDOS, local)
    _programar(_refrescar_banco(rol))
    return local


async def _refrescar_banco(rol: str) -> None:
    """Sustituye la caché del quiz si Mongo trae preguntas activas."""
    documentos = await _leer(COL_QUIZ, {"rol": rol, "activo": True})
    _banco_cache[rol] = (
        time.monotonic() + _TTL_SEGUNDOS,
        documentos or list(BANCOS.get(rol, [])),
    )
