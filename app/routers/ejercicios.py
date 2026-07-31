"""RF42 — alias canónico POST /api/ai/ejercicios/adaptar."""

from typing import Optional

from fastapi import APIRouter, Header

from app.routers.rutinas import AdaptarRequest, adaptar_ejercicio

router = APIRouter()


@router.post("/adaptar")
async def adaptar_ejercicio_alias(
    request: AdaptarRequest, authorization: Optional[str] = Header(None)
):
    """RF42 — mismo contrato que POST /api/ai/rutinas/adaptar."""
    return await adaptar_ejercicio(request, authorization)
