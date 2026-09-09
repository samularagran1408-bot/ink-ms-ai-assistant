"""Cliente asíncrono de MongoDB con URIs alternativas y estado de conexión."""

import re
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

client = None
db = None
_uri_activa: Optional[str] = None
_ultimo_error: Optional[str] = None


def ocultar_credenciales(uri: str) -> str:
    """Enmascara la contraseña de una URI Mongo para poder loguearla con seguridad."""
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", uri or "")


def _uris_candidatas() -> list[str]:
    """URI principal más las alternativas, sin duplicados y en ese orden."""
    candidatas = [settings.MONGODB_URI]
    for uri in settings.MONGODB_URI_ALTERNATIVAS:
        if uri not in candidatas:
            candidatas.append(uri)
    return candidatas


async def connect_to_mongo() -> str:
    """Conecta a MongoDB probando la URI configurada y luego las alternativas.

    Evita el caso habitual de arrancar en local con la URI de Docker (hostname
    `mongodb`) o con credenciales en una instancia sin autenticación.
    """
    global client, db, _uri_activa, _ultimo_error

    errores = []
    for uri in _uris_candidatas():
        candidato = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
        try:
            await candidato.admin.command("ping")
        except Exception as exc:
            candidato.close()
            errores.append(f"{ocultar_credenciales(uri)} -> {exc}")
            continue

        client = candidato
        db = candidato[settings.MONGODB_DB]
        _uri_activa = uri
        _ultimo_error = None
        await asegurar_indices()
        return uri

    _ultimo_error = " | ".join(errores)
    raise RuntimeError(f"Ninguna URI de MongoDB respondió: {_ultimo_error}")


async def close_mongo_connection():
    """Cierra el cliente Mongo y deja `client`/`db` en None."""
    global client, db, _uri_activa
    if client:
        client.close()
    client = None
    db = None
    _uri_activa = None


async def asegurar_indices() -> None:
    """Índices del historial de chat. Idempotente; no falla el arranque si Mongo rechaza uno."""
    if db is None:
        return
    col = db["conversaciones_chatbot"]
    indices = (
        ([("usuario_id", 1), ("ultima_interaccion", -1)], "usuario_ultima_idx", False),
        ([("usuario_id", 1), ("conversacion_id", 1)], "usuario_conversacion_uk", True),
        ([("usuario_id", 1), ("estado", 1)], "usuario_estado_idx", False),
    )
    for campos, nombre, unico in indices:
        try:
            await col.create_index(campos, name=nombre, unique=unico)
        except Exception as exc:
            print(f"Mongo índice {nombre}: {exc}")


def get_db():
    """Base de datos activa, o None si aún no hay conexión."""
    return db


def estado() -> dict:
    """Resumen de conexión (URI enmascarada, nombre de BD y último error)."""
    return {
        "conectado": db is not None,
        "uri": ocultar_credenciales(_uri_activa) if _uri_activa else None,
        "base_datos": settings.MONGODB_DB if db is not None else None,
        "error": _ultimo_error,
    }
