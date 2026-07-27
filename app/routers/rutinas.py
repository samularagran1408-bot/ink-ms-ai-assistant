from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.rutinas_agent import RutinasAgent

router = APIRouter()
agent = RutinasAgent()


class RutinaRequest(BaseModel):
    usuario_id: str
    tipo: str = Field(default="general", description="fuerza | resistencia | movilidad | en silla | piscina...")
    objetivo: str = Field(default="general", description="Objetivo en texto libre")
    discapacidad: Optional[str] = Field(
        default=None, description="Si se omite, se toma del perfil del usuario"
    )
    nivel: Optional[str] = Field(default=None, description="principiante | intermedio | avanzado")
    duracion_minutos: int = Field(default=35, ge=10, le=90)
    semilla: Optional[int] = Field(
        default=None,
        description="Fija la selección de ejercicios para obtener una rutina reproducible",
    )


@router.post("/generar")
async def generar_rutina(request: RutinaRequest, authorization: Optional[str] = Header(None)):
    try:
        return await agent.generar_rutina(
            usuario_id=request.usuario_id,
            tipo=request.tipo,
            objetivo=request.objetivo,
            discapacidad=request.discapacidad,
            nivel=request.nivel,
            duracion_minutos=request.duracion_minutos,
            semilla=request.semilla,
            authorization=authorization,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando la rutina: {exc}")
