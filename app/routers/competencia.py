from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.competencia_agent import CompetenciaAgent
from app.deps.contexto import resolver_contexto

router = APIRouter()
agent = CompetenciaAgent()


class ModoCompetenciaRequest(BaseModel):
    activar: bool = True
    evento_id: Optional[str] = None
    objetivo: Optional[str] = None
    semanas: int = Field(default=3, ge=1, le=8)


@router.get("/analizar")
@router.get("/analizar/{usuario_id}")
async def analizar_rendimiento(
    usuario_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """RF53 — panorama competitivo del usuario autenticado."""
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        result = await agent.analizar_rendimiento(ctx.id, authorization=ctx.authorization)
        if isinstance(result, dict):
            result["rf"] = "RF53"
            result["usuario_resuelto"] = {
                "id": ctx.id,
                "email": ctx.email,
                "disability": ctx.disability,
                "roles": ctx.roles,
            }
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/modo")
@router.post("/modo/{usuario_id}")
async def modo_competencia(
    usuario_id: Optional[str] = None,
    body: ModoCompetenciaRequest = Body(default_factory=ModoCompetenciaRequest),
    authorization: Optional[str] = Header(None),
):
    """RF53 — activa/desactiva modo competencia con plan de preparación."""
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.activar_modo(
            ctx.id,
            activar=body.activar,
            evento_id=body.evento_id,
            objetivo=body.objetivo,
            semanas=body.semanas,
            authorization=ctx.authorization,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
