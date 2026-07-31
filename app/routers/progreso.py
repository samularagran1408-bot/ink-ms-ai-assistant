"""RF48 — alias canónico GET /api/ai/progreso/comparativa/{userId}."""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.agents.historial_agent import HistorialAgent
from app.deps.contexto import resolver_contexto

router = APIRouter()
agent = HistorialAgent()


@router.get("/comparativa")
@router.get("/comparativa/{usuario_id}")
async def progreso_comparativa(
    usuario_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """RF48 — alias de GET /api/ai/historial/comparar/{usuario_id}."""
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        result = await agent.comparar(ctx.id, ctx.authorization)
        if isinstance(result, dict):
            result["rf"] = "RF48"
            result["alias_de"] = "GET /api/ai/historial/comparar/{usuario_id}"
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error en comparativa de progreso: {exc}")
