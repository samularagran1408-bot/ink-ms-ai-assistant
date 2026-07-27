from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.agents.recomendacion_agent import RecomendacionAgent

router = APIRouter()
agent = RecomendacionAgent()


@router.get("/eventos/{usuario_id}")
async def recomendar_eventos(
    usuario_id: str,
    limite: int = Query(default=3, ge=1, le=10),
    authorization: Optional[str] = Header(None),
):
    try:
        return await agent.recomendar_eventos(usuario_id, limite, authorization)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error recomendando eventos: {exc}")
