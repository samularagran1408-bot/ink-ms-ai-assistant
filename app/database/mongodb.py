import re
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

client = None
db = None
_uri_activa: Optional[str] = None
_ultimo_error: Optional[str] = None


def ocultar_credenciales(uri: str) -> str:
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", uri or "")


def _uris_candidatas() -> list[str]:
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
        return uri

    _ultimo_error = " | ".join(errores)
    raise RuntimeError(f"Ninguna URI de MongoDB respondió: {_ultimo_error}")


async def close_mongo_connection():
    global client, db, _uri_activa
    if client:
        client.close()
    client = None
    db = None
    _uri_activa = None


def get_db():
    return db


def estado() -> dict:
    return {
        "conectado": db is not None,
        "uri": ocultar_credenciales(_uri_activa) if _uri_activa else None,
        "base_datos": settings.MONGODB_DB if db is not None else None,
        "error": _ultimo_error,
    }
