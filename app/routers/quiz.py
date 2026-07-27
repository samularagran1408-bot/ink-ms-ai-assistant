from fastapi import APIRouter, HTTPException
from app.agents.quiz_agent import QuizAgent
from app.models.quiz import (
    QuizGenerarRequest,
    QuizEvaluarRequest,
    QuizGenerarResponse,
    QuizEvaluarResponse,
)

router = APIRouter()
agent = QuizAgent()


@router.post("/organizer/generar", response_model=QuizGenerarResponse)
async def generar_quiz_organizador(request: QuizGenerarRequest):
    """
    Genera un quiz de aptitud para ORGANIZADOR (crear eventos inclusivos).
    Temas: /api/events, cupos, roles ORGANIZER, inclusión.
    """
    try:
        result = await agent.generar(
            "ORGANIZADOR",
            request.usuario_id,
            request.num_preguntas,
            request.dificultad,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trainer/generar", response_model=QuizGenerarResponse)
async def generar_quiz_entrenador(request: QuizGenerarRequest):
    """
    Genera un quiz de aptitud para ENTRENADOR (adaptaciones deporte-discapacidad).
    Temas: /api/sport-disabilities, /api/sports, /api/disabilities.
    """
    try:
        result = await agent.generar(
            "ENTRENADOR",
            request.usuario_id,
            request.num_preguntas,
            request.dificultad,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/organizer/evaluar", response_model=QuizEvaluarResponse)
async def evaluar_quiz_organizador(request: QuizEvaluarRequest):
    """
    Evalúa el quiz de organizador y registra score en
    POST /api/users/verify/quiz/organizer/{userId}?score= (umbral 70).
    """
    try:
        result = await agent.evaluar(
            "ORGANIZADOR",
            request.usuario_id,
            request.quiz_id,
            [r.model_dump() for r in request.respuestas],
            request.registrar_en_users,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trainer/evaluar", response_model=QuizEvaluarResponse)
async def evaluar_quiz_entrenador(request: QuizEvaluarRequest):
    """
    Evalúa el quiz de entrenador y registra score en
    POST /api/users/verify/quiz/trainer/{userId}?score= (umbral 75).
    """
    try:
        result = await agent.evaluar(
            "ENTRENADOR",
            request.usuario_id,
            request.quiz_id,
            [r.model_dump() for r in request.respuestas],
            request.registrar_en_users,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
