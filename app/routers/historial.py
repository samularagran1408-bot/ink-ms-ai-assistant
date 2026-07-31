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
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.metricas(ctx.id, ctx.authorization)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error obteniendo métricas: {exc}")
