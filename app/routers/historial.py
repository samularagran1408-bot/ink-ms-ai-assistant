"""RF47/RF48 — comparativa mensual del historial y métricas del atleta."""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.agents.historial_agent import HistorialAgent
from app.deps.contexto import resolver_contexto

router = APIRouter()
agent = HistorialAgent()


@router.get("/comparar")
@router.get("/comparar/{usuario_id}")
async def comparar_historial(
    usuario_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """RF48 — compara inscripciones, RPE y planes del mes actual frente al anterior."""
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.comparar(ctx.id, ctx.authorization)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error comparando historial: {exc}")


@router.get("/metricas")
@router.get("/metricas/{usuario_id}")
async def metricas_usuario(
    usuario_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """RF47 — métricas del atleta más un resumen de la plataforma (users/eventos)."""
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.metricas(ctx.id, ctx.authorization)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error obteniendo métricas: {exc}")
