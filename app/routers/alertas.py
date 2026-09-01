"""RF55 — endpoints de alertas inteligentes para entrenadores."""

from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.alertas_agent import AlertasAgent
from app.deps.contexto import resolver_contexto

router = APIRouter()
agent = AlertasAgent()


class AlertaRequest(BaseModel):
    """Cuerpo para evaluar riesgo del atleta y notificar a entrenadores (RF55)."""

    usuario_id: Optional[str] = Field(
        default=None,
        description="Atleta a evaluar. Por defecto el del token. ENTRENADOR/ADMIN pueden indicar otro.",
    )
    entrenador_ids: list[str] = Field(default_factory=list)
    rpe_reciente: Optional[float] = Field(default=None, ge=0, le=10)
    dolor_reportado: bool = False
    dias_sin_descanso: int = Field(default=0, ge=0, le=30)


async def _alertas(
    usuario_id: Optional[str],
    entrenador_ids: list[str],
    rpe_reciente: Optional[float],
    dolor_reportado: bool,
    dias_sin_descanso: int,
    authorization: Optional[str],
):
    """Evalúa el riesgo del atleta y, si el rol lo permite, notifica a los entrenadores.

    Solo ENTRENADOR/ADMIN pueden enviar `entrenador_ids`. Si el llamante es
    entrenador y no indica destinos, se notifica a sí mismo.
    """
    ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
    if not ctx.tiene_rol("ENTRENADOR", "ADMIN") and entrenador_ids:
        raise HTTPException(
            status_code=403,
            detail="Sólo ENTRENADOR o ADMIN pueden disparar notificaciones a entrenadores.",
        )
    destinos = list(entrenador_ids)
    if ctx.tiene_rol("ENTRENADOR") and not destinos:
        destinos = [ctx.id]
    result = await agent.evaluar_y_notificar(
        usuario_id=ctx.id,
        entrenador_ids=destinos,
        rpe_reciente=rpe_reciente,
        dolor_reportado=dolor_reportado,
        dias_sin_descanso=dias_sin_descanso,
        authorization=ctx.authorization,
    )
    if isinstance(result, dict):
        result["rf"] = "RF55"
    return result


@router.post("")
@router.post("/")
@router.post("/entrenador")
async def alertas_entrenador(
    body: AlertaRequest = Body(default_factory=AlertaRequest),
    authorization: Optional[str] = Header(None),
):
    """RF55 — genera alertas del atleta y notifica a entrenadores (POST /api/ai/alertas).

    Requiere autenticación. Sólo ENTRENADOR o ADMIN pueden disparar notificaciones
    a otros entrenadores; el atleta puede evaluarse a sí mismo sin destinos.
    """
    try:
        return await _alertas(
            body.usuario_id,
            body.entrenador_ids,
            body.rpe_reciente,
            body.dolor_reportado,
            body.dias_sin_descanso,
            authorization,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando alertas: {exc}")


@router.post("/{entrenador_id}")
async def alertas_por_entrenador(
    entrenador_id: str,
    body: AlertaRequest = Body(default_factory=AlertaRequest),
    authorization: Optional[str] = Header(None),
):
    """RF55 — alias canónico POST /api/ai/alertas/{entrenadorId}.

    Fuerza el `entrenador_id` de la ruta como destinatario de la notificación,
    además de cualquier lista enviada en el cuerpo.
    """
    try:
        destinos = body.entrenador_ids or [entrenador_id]
        if entrenador_id not in destinos:
            destinos = [entrenador_id, *destinos]
        return await _alertas(
            body.usuario_id,
            destinos,
            body.rpe_reciente,
            body.dolor_reportado,
            body.dias_sin_descanso,
            authorization,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando alertas: {exc}")
