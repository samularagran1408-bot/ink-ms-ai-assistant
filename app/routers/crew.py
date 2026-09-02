"""POST /api/ai/crew/run y GET /api/ai/crew/dominios."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.crew.crews import resultado_a_informe, run_dominio
from app.crew.enrutar import (
    EnrutadoAlChat,
    EnrutadoAmbiguo,
    EnrutadoProhibido,
    catalogo_para_roles,
    resolver_dominio,
    rol_principal,
)
from app.crew.politica import descripcion_escritura
from app.crew.schemas import CrewDominiosResponse, CrewRunRequest, CrewRunResponse
from app.deps.contexto import resolver_contexto

router = APIRouter()


@router.get("/dominios", response_model=CrewDominiosResponse)
async def crew_dominios(authorization: Optional[str] = Header(None)):
    """Catálogo filtrado por rol JWT. El selector del front no pinta lo prohibido."""
    ctx = await resolver_contexto(authorization, require_auth=True)
    catalogo = catalogo_para_roles(ctx.roles)
    rol = rol_principal(ctx.roles)
    return CrewDominiosResponse(
        dominios=catalogo,
        rol=rol,
        writes=descripcion_escritura(),
        auto=(
            "Si dominio es auto u omite, se clasifica el mensaje con las "
            "intenciones del chat, solo entre los dominios de tu rol."
        ),
        chat="Saludos, ayuda y soporte van a POST /api/ai/chat, no a un crew.",
    )


@router.post("/run", response_model=CrewRunResponse)
async def crew_run(
    request: CrewRunRequest,
    authorization: Optional[str] = Header(None),
):
    """Ejecuta un crew sequential. Requiere JWT.

    ``dominio=auto`` (o omitido) clasifica el mensaje. El ChatbotAgent sigue
    para saludos en ``POST /api/ai/chat``.
    """
    ctx = await resolver_contexto(authorization, require_auth=True)
    catalogo = catalogo_para_roles(ctx.roles)

    try:
        ruta = resolver_dominio(request.mensaje, request.dominio, roles=ctx.roles)
    except EnrutadoAlChat as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "usar_chat": True,
                "endpoint": "POST /api/ai/chat",
                "intencion": exc.intencion,
                "confianza": exc.confianza,
                "mensaje": exc.detalle,
            },
        ) from exc
    except EnrutadoAmbiguo as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "usar_chat": False,
                "dominios": [item["id"] for item in catalogo],
                "intencion": exc.intencion,
                "confianza": exc.confianza,
                "mensaje": exc.detalle,
            },
        ) from exc
    except EnrutadoProhibido as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "usar_chat": False,
                "dominio": exc.dominio,
                "dominios": exc.permitidos,
                "intencion": exc.intencion,
                "confianza": exc.confianza,
                "mensaje": exc.detalle,
            },
        ) from exc

    try:
        resultado = await asyncio.wait_for(
            asyncio.to_thread(
                run_dominio,
                ruta.dominio,
                request.mensaje,
                ctx.authorization,
                ctx.id,
                ctx.disability,
            ),
            timeout=float(settings.CREW_TIMEOUT_SEGUNDOS),
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                f"El crew tardó más de {settings.CREW_TIMEOUT_SEGUNDOS}s. "
                "Reintenta o sube CREW_TIMEOUT_SEGUNDOS."
            ),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error ejecutando el crew: {exc}"
        ) from exc

    informe = resultado_a_informe(resultado)
    return CrewRunResponse(
        dominio=ruta.dominio or "",
        dominio_origen=ruta.origen,
        intencion=ruta.intencion,
        confianza=ruta.confianza,
        fuente="crew",
        informe=informe,
    )
