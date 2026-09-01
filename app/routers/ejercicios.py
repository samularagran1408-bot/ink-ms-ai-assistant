"""RF42 — alias canónico POST /api/ai/ejercicios/adaptar."""

from typing import Optional

from fastapi import APIRouter, Header

from app.routers.rutinas import AdaptarRequest, adaptar_ejercicio

router = APIRouter()


@router.post("/adaptar")
async def adaptar_ejercicio_alias(
    request: AdaptarRequest, authorization: Optional[str] = Header(None)
):
    """RF42 — adapta un ejercicio del catálogo a la discapacidad del perfil.

    Alias canónico de POST /api/ai/rutinas/adaptar: mismo cuerpo y misma respuesta
    (modificaciones, pauta y mapa corporal si hay limitación).
    """
    return await adaptar_ejercicio(request, authorization)
