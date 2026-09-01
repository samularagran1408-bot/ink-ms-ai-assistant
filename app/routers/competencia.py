"""RF53 — análisis competitivo, modo competencia, checklist y sesiones del plan."""

from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.competencia_agent import CompetenciaAgent
from app.agents.competencia_progreso import CompetenciaAccionError
from app.deps.contexto import resolver_contexto

router = APIRouter()
agent = CompetenciaAgent()


class ModoCompetenciaRequest(BaseModel):
    """Cuerpo para activar o desactivar el modo competencia y fijar meta/semanas."""

    activar: bool = True
    evento_id: Optional[str] = None
    objetivo: Optional[str] = None
    semanas: int = Field(default=3, ge=1, le=8)


class ChecklistRequest(BaseModel):
    """Identificador de un punto del plan y si queda marcado como hecho."""

    item_id: str = Field(..., min_length=1)
    hecho: bool = True


class SesionRequest(BaseModel):
    """Identificador de la rutina inscrita cuya sesión se registra hoy."""

    routine_id: str = Field(..., min_length=1)


def _accion_http(exc: CompetenciaAccionError) -> HTTPException:
    """Traduce un error de negocio del plan de competencia a HTTPException."""
    return HTTPException(status_code=exc.status, detail=exc.detail)


@router.get("/analizar")
@router.get("/analizar/{usuario_id}")
async def analizar_rendimiento(
    usuario_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """RF53 — panorama competitivo: eventos compatibles, ventajas y recomendaciones.

    Filtra el calendario al cruce deporte–discapacidad del perfil y añade
    `usuario_resuelto` para que el cliente muestre quién se analizó.
    """
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


@router.get("/modo")
@router.get("/modo/{usuario_id}")
async def obtener_modo_competencia(
    usuario_id: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """RF53 — estado persistido del modo competencia y % del plan (checklist + sesiones)."""
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.obtener_modo(ctx.id, authorization=ctx.authorization)
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
    """RF53 — activa o desactiva el modo competencia y genera el plan de preparación.

    Si `activar` es true, fija evento objetivo (explícito o el más próximo) y
    persiste fases, checklist y semanas. Si es false, vuelve a entrenamiento base.
    """
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


@router.post("/checklist")
@router.post("/checklist/{usuario_id}")
@router.patch("/checklist")
@router.patch("/checklist/{usuario_id}")
async def marcar_checklist(
    usuario_id: Optional[str] = None,
    body: ChecklistRequest = Body(...),
    authorization: Optional[str] = Header(None),
):
    """RF53 — marca o desmarca un ítem del checklist del plan activo."""
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.marcar_checklist(
            ctx.id,
            body.item_id,
            body.hecho,
            authorization=ctx.authorization,
        )
    except CompetenciaAccionError as exc:
        raise _accion_http(exc) from exc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sesion")
@router.post("/sesion/{usuario_id}")
async def registrar_sesion(
    usuario_id: Optional[str] = None,
    body: SesionRequest = Body(...),
    authorization: Optional[str] = Header(None),
):
    """RF53 — registra una sesión de rutina inscrita para avanzar el % del plan.

    Requiere modo competencia activo y que el atleta esté unido a esa rutina.
    Solo se admite una sesión por rutina y día.
    """
    try:
        ctx = await resolver_contexto(authorization, usuario_id, require_auth=True)
        return await agent.registrar_sesion(
            ctx.id,
            body.routine_id,
            authorization=ctx.authorization,
        )
    except CompetenciaAccionError as exc:
        raise _accion_http(exc) from exc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
