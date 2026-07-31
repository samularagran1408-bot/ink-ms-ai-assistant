from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.planes_agent import PlanesAgent
from app.deps.contexto import discapacidad_efectiva, resolver_contexto

router = APIRouter()
agent = PlanesAgent()


class PlanRequest(BaseModel):
    usuario_id: Optional[str] = None
    objetivo: str = "general"
    discapacidad: Optional[str] = None
    nivel: Optional[str] = Field(default="principiante")
    semanas: int = Field(default=4, ge=1, le=8)
    sesiones_por_semana: int = Field(default=3, ge=2, le=5)
    duracion_minutos: int = Field(default=35, ge=15, le=90)


@router.post("/generar")
async def generar_plan(request: PlanRequest, authorization: Optional[str] = Header(None)):
    try:
        ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)
        discapacidad = discapacidad_efectiva(
            ctx, request.discapacidad, permitir_override=True
        )
        return await agent.generar_plan(
            usuario_id=ctx.id,
            objetivo=request.objetivo,
            discapacidad=discapacidad,
            nivel=request.nivel,
            semanas=request.semanas,
            sesiones_por_semana=request.sesiones_por_semana,
            duracion_minutos=request.duracion_minutos,
            authorization=ctx.authorization,
            perfil=ctx.perfil,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando el plan: {exc}")


@router.get("/{plan_id}")
async def obtener_plan(plan_id: str, authorization: Optional[str] = Header(None)):
    await resolver_contexto(authorization, require_auth=True)
    plan = await agent.obtener_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    return plan
