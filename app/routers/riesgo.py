from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.riesgo_agent import RiesgoAgent
from app.deps.contexto import resolver_contexto

router = APIRouter()
agent = RiesgoAgent()


class RiesgoRequest(BaseModel):
    usuario_id: Optional[str] = Field(
        default=None,
        description="Opcional. Con token se usa el perfil autenticado. Sólo ADMIN/ENTRENADOR pueden indicar otro id.",
    )
    rpe_reciente: Optional[float] = Field(default=None, ge=0, le=10)
    dolor_reportado: bool = False
    dias_sin_descanso: int = Field(default=0, ge=0, le=30)


async def _evaluar(
    usuario_id: Optional[str],
    rpe_reciente: Optional[float],
    dolor_reportado: bool,
    dias_sin_descanso: int,
    authorization: Optional[str],
):
    ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
    result = await agent.evaluar(
        usuario_id=ctx.id,
        rpe_reciente=rpe_reciente,
        dolor_reportado=dolor_reportado,
        dias_sin_descanso=dias_sin_descanso,
        authorization=ctx.authorization,
        perfil=ctx.perfil,
    )
    if isinstance(result, dict):
        result["rf"] = "RF43"
    return result


@router.post("/evaluar")
async def evaluar_riesgo(
    request: RiesgoRequest,
    authorization: Optional[str] = Header(None),
):
    """RF43 — predicción heurística de riesgo de lesión según perfil del token."""
    try:
        return await _evaluar(
            request.usuario_id,
            request.rpe_reciente,
            request.dolor_reportado,
            request.dias_sin_descanso,
            authorization,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error evaluando riesgo: {exc}")


@router.post("/lesiones/{usuario_id}")
async def riesgo_lesiones(
    usuario_id: str,
    body: RiesgoRequest = Body(default_factory=RiesgoRequest),
    authorization: Optional[str] = Header(None),
):
    """RF43 — alias canónico POST /api/ai/riesgo/lesiones/{userId}."""
    try:
        return await _evaluar(
            usuario_id,
            body.rpe_reciente,
            body.dolor_reportado,
            body.dias_sin_descanso,
            authorization,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error evaluando riesgo: {exc}")
