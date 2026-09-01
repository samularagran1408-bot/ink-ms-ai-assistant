"""RF52 — sugerencia de configuración de discapacidad a partir de texto libre."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.deteccion_agent import DeteccionAgent

router = APIRouter()
agent = DeteccionAgent()


class DeteccionRequest(BaseModel):
    """Descripción libre del usuario para inferir un tipo de discapacidad."""

    texto: str = Field(..., min_length=3, description="Descripción libre del usuario")


@router.post("/discapacidad")
async def detectar_discapacidad(request: DeteccionRequest):
    """RF52 — sugiere una configuración de accesibilidad a partir del texto.

    No persiste nada en el perfil: el cliente debe confirmar antes de guardar.
    """
    try:
        return agent.sugerir(request.texto)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
