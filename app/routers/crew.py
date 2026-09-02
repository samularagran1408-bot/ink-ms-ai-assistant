"""POST /api/ai/crew/run — un crew por dominio."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.crew.crews import resultado_a_informe, run_dominio
from app.crew.schemas import CrewRunRequest, CrewRunResponse
from app.deps.contexto import resolver_contexto

router = APIRouter()

DOMINIOS = frozenset(
    {"investigacion", "quiz", "competencia", "automatizado", "consulta"}
)
DOMINIOS_LISTOS = DOMINIOS


@router.post("/run", response_model=CrewRunResponse)
async def crew_run(
    request: CrewRunRequest,
    authorization: Optional[str] = Header(None),
):
    """Ejecuta un crew sequential según ``dominio``. Requiere JWT.

    El ChatbotAgent sigue para saludos en ``POST /api/ai/chat``.
    """
    dominio = (request.dominio or "investigacion").strip().lower()
    if dominio not in DOMINIOS:
        raise HTTPException(
            status_code=422,
            detail=f"dominio debe ser uno de: {', '.join(sorted(DOMINIOS))}",
        )

    ctx = await resolver_contexto(authorization, require_auth=True)

    try:
        resultado = await asyncio.to_thread(
            run_dominio,
            dominio,
            request.mensaje,
            ctx.authorization,
            ctx.id,
            ctx.disability,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error ejecutando el crew: {exc}"
        ) from exc

    informe = resultado_a_informe(resultado)
    return CrewRunResponse(dominio=dominio, fuente="crew", informe=informe)
