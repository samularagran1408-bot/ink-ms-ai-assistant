"""Siembra de los catálogos en MongoDB al arrancar el servicio.

Es idempotente: solo inserta lo que falta, de modo que los ajustes hechos
directamente en la base de datos no se sobrescriben en cada reinicio. Con
`forzar=True` se reescriben los documentos desde el código.
"""

from typing import Any

from app.data.conocimiento import CONOCIMIENTO
from app.data.ejercicios import CATALOGO_EJERCICIOS
from app.data.quiz_banco import BANCOS
from app.database.mongodb import get_db
from app.database.repositorio import (
    COL_CONOCIMIENTO,
    COL_CONVERSACIONES,
    COL_EJERCICIOS,
    COL_QUIZ,
    COL_QUIZZES,
)


async def _sembrar_coleccion(
    coleccion: str,
    documentos: list[dict[str, Any]],
    clave: str,
    forzar: bool,
) -> dict[str, int]:
    db = get_db()
    insertados = 0
    actualizados = 0

    for documento in documentos:
        filtro = {clave: documento[clave]}
        if coleccion == COL_QUIZ:
            filtro["rol"] = documento["rol"]

        if forzar:
            await db[coleccion].replace_one(filtro, documento, upsert=True)
            actualizados += 1
            continue

        resultado = await db[coleccion].update_one(
            filtro, {"$setOnInsert": documento}, upsert=True
        )
        if resultado.upserted_id is not None:
            insertados += 1

    return {"insertados": insertados, "actualizados": actualizados}


async def sembrar_catalogos(forzar: bool = False) -> dict[str, Any]:
    """Inserta ejercicios, conocimiento del chatbot y bancos de quiz."""
    db = get_db()
    if db is None:
        return {"sembrado": False, "motivo": "MongoDB no disponible"}

    ejercicios = [{**e, "activo": True} for e in CATALOGO_EJERCICIOS]
    conocimiento = [
        {"intencion": intencion, **contenido, "activo": True}
        for intencion, contenido in CONOCIMIENTO.items()
    ]
    preguntas = [
        {**pregunta, "rol": rol, "activo": True}
        for rol, banco in BANCOS.items()
        for pregunta in banco
    ]

    resumen = {
        "ejercicios": await _sembrar_coleccion(COL_EJERCICIOS, ejercicios, "id", forzar),
        "conocimiento": await _sembrar_coleccion(COL_CONOCIMIENTO, conocimiento, "intencion", forzar),
        "preguntas_quiz": await _sembrar_coleccion(COL_QUIZ, preguntas, "id", forzar),
    }

    await _crear_indices()
    return {"sembrado": True, "forzado": forzar, "detalle": resumen}


async def _crear_indices() -> None:
    db = get_db()
    try:
        await db[COL_EJERCICIOS].create_index("id", unique=True)
        await db[COL_EJERCICIOS].create_index([("fase", 1), ("categoria", 1)])
        await db[COL_CONOCIMIENTO].create_index("intencion", unique=True)
        await db[COL_QUIZ].create_index([("rol", 1), ("id", 1)], unique=True)
        await db[COL_QUIZZES].create_index("quiz_id", unique=True)
        await db[COL_CONVERSACIONES].create_index([("usuario_id", 1), ("estado", 1)])
    except Exception as exc:
        print(f"No se pudieron crear todos los índices: {exc}")
