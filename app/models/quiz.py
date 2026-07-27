from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class QuizGenerarRequest(BaseModel):
    usuario_id: str
    num_preguntas: int = Field(default=8, ge=5, le=15)
    dificultad: str = Field(default="media", description="baja | media | alta")


class QuizRespuestaItem(BaseModel):
    pregunta_id: str
    opcion_id: str  # a | b | c | d


class QuizEvaluarRequest(BaseModel):
    usuario_id: str
    quiz_id: str
    respuestas: List[QuizRespuestaItem]
    registrar_en_users: bool = Field(
        default=True,
        description="Si true, envía el score a ink-ms-users /api/users/verify/quiz/...",
    )


class OpcionPublica(BaseModel):
    id: str
    texto: str


class PreguntaPublica(BaseModel):
    id: str
    enunciado: str
    opciones: List[OpcionPublica]
    tema: str


class QuizGenerarResponse(BaseModel):
    quiz_id: str
    rol: str
    umbral_aprobacion: float
    num_preguntas: int
    preguntas: List[PreguntaPublica]
    contexto: Optional[Dict[str, Any]] = None
    mensaje: str


class QuizEvaluarResponse(BaseModel):
    quiz_id: str
    rol: str
    usuario_id: str
    score: float
    correctas: int
    total: int
    aprobado: bool
    umbral_aprobacion: float
    detalle: List[Dict[str, Any]]
    score_registrado_en_users: bool
    siguiente_paso: str
