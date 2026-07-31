from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.agents.deportes_agent import DeportesAgent
from app.deps.contexto import resolver_contexto

router = APIRouter()
agent = DeportesAgent()


@router.get("/filtrar")
@router.get("/filtrar/{usuario_id}")
async def filtrar_deportes(
    usuario_id: Optional[str] = None,
    limite: int = Query(default=10, ge=1, le=20),
    authorization: Optional[str] = Header(None),
):
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.filtrar(ctx.id, limite, ctx.authorization, perfil=ctx.perfil)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error filtrando deportes: {exc}")
