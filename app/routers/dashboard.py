"""RF47 — GET /api/ai/dashboard/{userId}."""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.agents.dashboard_agent import DashboardAgent
from app.deps.contexto import resolver_contexto

router = APIRouter()
agent = DashboardAgent()


@router.get("")
@router.get("/")
@router.get("/{usuario_id}")
async def dashboard_usuario(
    usuario_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """RF47 — panel agregado de métricas, riesgo, inscripciones y modo competencia.

    Devuelve KPIs del atleta autenticado (o de otro usuario si ADMIN/ENTRENADOR
    indica `usuario_id`). Incluye comparativa, snapshot de riesgo y alertas sugeridas.
    """
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.construir(
            usuario_id=ctx.id,
            authorization=ctx.authorization,
            perfil=ctx.perfil,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error construyendo dashboard: {exc}")
