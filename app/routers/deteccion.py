from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.deteccion_agent import DeteccionAgent

router = APIRouter()
agent = DeteccionAgent()


class DeteccionRequest(BaseModel):
    texto: str = Field(..., min_length=3, description="Descripción libre del usuario")


@router.post("/discapacidad")
async def detectar_discapacidad(request: DeteccionRequest):
    """RF52 — sugiere configuración de accesibilidad; no guarda en perfil."""
    try:
        return agent.sugerir(request.texto)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
