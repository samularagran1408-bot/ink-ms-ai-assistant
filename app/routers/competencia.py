from fastapi import APIRouter, HTTPException
from app.agents.competencia_agent import CompetenciaAgent

router = APIRouter()
agent = CompetenciaAgent()

@router.get("/analizar/{usuario_id}")
async def analizar_rendimiento(usuario_id: str):
    try:
        result = await agent.analizar_rendimiento(usuario_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))