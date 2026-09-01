"""RF49 — recomendación de eventos reales según el perfil del atleta."""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.agents.recomendacion_agent import RecomendacionAgent
from app.deps.contexto import resolver_contexto

router = APIRouter()
agent = RecomendacionAgent()


@router.get("/eventos")
@router.get("/eventos/{usuario_id}")
async def recomendar_eventos(
    usuario_id: Optional[str] = None,
    limite: int = Query(default=3, ge=1, le=10),
    authorization: Optional[str] = Header(None),
):
    """RF49 — ranking de eventos abiertos compatibles con el perfil del token.

    El `usuario_id` de la ruta sólo lo pueden usar ADMIN/ENTRENADOR para consultar
    a otro atleta. `limite` acota cuántos eventos se recomiendan (1–10).
    """
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.recomendar_eventos(
            ctx.id, limite, ctx.authorization, perfil=ctx.perfil
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error recomendando eventos: {exc}")
