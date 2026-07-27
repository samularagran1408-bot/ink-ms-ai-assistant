from fastapi import APIRouter, HTTPException
from app.agents.rutinas_agent import RutinasAgent
from pydantic import BaseModel

router = APIRouter()
agent = RutinasAgent()

class RutinaRequest(BaseModel):
    usuario_id: str
    tipo: str
    objetivo: str
    discapacidad: str

@router.post("/generar")
async def generar_rutina(request: RutinaRequest):
    try:
        result = await agent.generar_rutina(
            request.usuario_id,
            request.tipo,
            request.objetivo,
            request.discapacidad
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))