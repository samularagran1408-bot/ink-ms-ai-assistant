from fastapi import APIRouter, HTTPException
from app.agents.recomendacion_agent import RecomendacionAgent

router = APIRouter()
agent = RecomendacionAgent()

@router.get("/eventos/{usuario_id}")
async def recomendar_eventos(usuario_id: str):
    try:
        result = await agent.recomendar_eventos(usuario_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))