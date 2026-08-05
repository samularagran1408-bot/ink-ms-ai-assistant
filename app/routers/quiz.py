from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.quiz_agent import QuizAgent
from app.deps.contexto import resolver_contexto
from app.models.quiz import (
    QuizEvaluarRequest,
    QuizEvaluarResponse,
    QuizGenerarRequest,
    QuizGenerarResponse,
    QuizRespuestaItem,
)

router = APIRouter()
agent = QuizAgent()


class QuizGenerarBody(BaseModel):
    """
    /**
     * Body para generar un quiz de aptitud.
     */
    """
    usuario_id: Optional[str] = None
    num_preguntas: int = Field(default=8, ge=5, le=15)
    dificultad: str = Field(default="media")
    semilla: Optional[int] = None
    discipline_sport_ids: Optional[list[int]] = None


class QuizEvaluarBody(BaseModel):
    """
    /**
     * Body para evaluar las respuestas de un quiz previamente generado.
     */
    """
    usuario_id: Optional[str] = None
    quiz_id: str
    respuestas: list[QuizRespuestaItem]
    registrar_en_users: bool = True


async def _generar(rol: str, request: QuizGenerarBody, authorization: Optional[str]):
    """
    /**
     * Resuelve el usuario autenticado y delega la generación al QuizAgent.
     */
    """
    ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)
    try:
        return await agent.generar(
            rol,
            ctx.id,
            request.num_preguntas,
            request.dificultad,
            request.semilla,
            ctx.authorization,
            request.discipline_sport_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando el quiz: {exc}")


async def _evaluar(rol: str, request: QuizEvaluarBody, authorization: Optional[str]):
    """
    /**
     * Resuelve el usuario autenticado y delega la evaluación al QuizAgent.
     */
    """
    ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)
    try:
        return await agent.evaluar(
            rol,
            ctx.id,
            request.quiz_id,
            [r.model_dump() for r in request.respuestas],
            request.registrar_en_users,
            ctx.authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error evaluando el quiz: {exc}")


@router.post("/organizer/generar", response_model=QuizGenerarResponse)
async def generar_quiz_organizador(
    request: QuizGenerarBody, authorization: Optional[str] = Header(None)
):
    """
    /**
     * Endpoint: genera el quiz de aptitud para ORGANIZADOR.
     */
    """
    return await _generar("ORGANIZADOR", request, authorization)


@router.post("/trainer/generar", response_model=QuizGenerarResponse)
async def generar_quiz_entrenador(
    request: QuizGenerarBody, authorization: Optional[str] = Header(None)
):
    """
    /**
     * Endpoint: genera el quiz de aptitud para ENTRENADOR.
     */
    """
    return await _generar("ENTRENADOR", request, authorization)


@router.post("/organizer/evaluar", response_model=QuizEvaluarResponse)
async def evaluar_quiz_organizador(
    request: QuizEvaluarBody, authorization: Optional[str] = Header(None)
):
    """
    /**
     * Endpoint: evalúa el quiz de ORGANIZADOR y registra el score en users.
     */
    """
    return await _evaluar("ORGANIZADOR", request, authorization)


@router.post("/trainer/evaluar", response_model=QuizEvaluarResponse)
async def evaluar_quiz_entrenador(
    request: QuizEvaluarBody, authorization: Optional[str] = Header(None)
):
    """
    /**
     * Endpoint: evalúa el quiz de ENTRENADOR y registra el score en users.
     */
    """
    return await _evaluar("ENTRENADOR", request, authorization)
