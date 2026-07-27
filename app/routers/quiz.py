from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.agents.quiz_agent import QuizAgent
from app.models.quiz import (
    QuizEvaluarRequest,
    QuizEvaluarResponse,
    QuizGenerarRequest,
    QuizGenerarResponse,
)

router = APIRouter()
agent = QuizAgent()


async def _generar(rol: str, request: QuizGenerarRequest, authorization: Optional[str]):
    try:
        return await agent.generar(
            rol,
            request.usuario_id,
            request.num_preguntas,
            request.dificultad,
            request.semilla,
            authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando el quiz: {exc}")


async def _evaluar(rol: str, request: QuizEvaluarRequest, authorization: Optional[str]):
    try:
        return await agent.evaluar(
            rol,
            request.usuario_id,
            request.quiz_id,
            [r.model_dump() for r in request.respuestas],
            request.registrar_en_users,
            authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error evaluando el quiz: {exc}")


@router.post("/organizer/generar", response_model=QuizGenerarResponse)
async def generar_quiz_organizador(
    request: QuizGenerarRequest, authorization: Optional[str] = Header(None)
):
    """Genera un quiz de aptitud para ORGANIZADOR (creación y gestión de eventos)."""
    return await _generar("ORGANIZADOR", request, authorization)


@router.post("/trainer/generar", response_model=QuizGenerarResponse)
async def generar_quiz_entrenador(
    request: QuizGenerarRequest, authorization: Optional[str] = Header(None)
):
    """Genera un quiz de aptitud para ENTRENADOR (adaptaciones y planificación)."""
    return await _generar("ENTRENADOR", request, authorization)


@router.post("/organizer/evaluar", response_model=QuizEvaluarResponse)
async def evaluar_quiz_organizador(
    request: QuizEvaluarRequest, authorization: Optional[str] = Header(None)
):
    """Evalúa el quiz de organizador y registra el puntaje en ink-ms-users (umbral 70)."""
    return await _evaluar("ORGANIZADOR", request, authorization)


@router.post("/trainer/evaluar", response_model=QuizEvaluarResponse)
async def evaluar_quiz_entrenador(
    request: QuizEvaluarRequest, authorization: Optional[str] = Header(None)
):
    """Evalúa el quiz de entrenador y registra el puntaje en ink-ms-users (umbral 75)."""
    return await _evaluar("ENTRENADOR", request, authorization)
