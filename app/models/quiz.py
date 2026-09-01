"""Esquemas Pydantic de generación y evaluación de quices de aptitud."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class QuizGenerarRequest(BaseModel):
    """Petición para armar un quiz: usuario, número de preguntas y dificultad."""
    usuario_id: str
    num_preguntas: int = Field(default=8, ge=5, le=15)
    dificultad: str = Field(default="media", description="baja | media | alta")
    semilla: Optional[int] = Field(
        default=None,
        description="Fija la selección de preguntas para obtener un quiz reproducible",
    )


class QuizRespuestaItem(BaseModel):
    """Una respuesta del usuario: identificador de pregunta y opción elegida (a–d)."""
    pregunta_id: str
    opcion_id: str  # a | b | c | d


class QuizEvaluarRequest(BaseModel):
    """Envío de respuestas para puntuar el quiz y, si aplica, registrar el score en users."""
    usuario_id: str
    quiz_id: str
    respuestas: List[QuizRespuestaItem]
    registrar_en_users: bool = Field(
        default=True,
        description="Si true, envía el score a ink-ms-users /api/users/verify/quiz/...",
    )


class OpcionPublica(BaseModel):
    """Opción visible al usuario, sin indicar si es la correcta."""
    id: str
    texto: str


class PreguntaPublica(BaseModel):
    """Pregunta expuesta en la generación: enunciado, opciones barajadas y tema."""
    id: str
    enunciado: str
    opciones: List[OpcionPublica]
    tema: str


class QuizGenerarResponse(BaseModel):
    """Quiz listo para responder: id, umbral, preguntas públicas y mensaje de contexto."""
    quiz_id: str
    rol: str
    umbral_aprobacion: float
    num_preguntas: int
    preguntas: List[PreguntaPublica]
    contexto: Optional[Dict[str, Any]] = None
    mensaje: str


class QuizEvaluarResponse(BaseModel):
    """Resultado de la evaluación: score, aprobación, temas a reforzar y siguiente paso."""
    quiz_id: str
    rol: str
    usuario_id: str
    score: float
    correctas: int
    total: int
    aprobado: bool
    umbral_aprobacion: float
    detalle: List[Dict[str, Any]]
    temas_a_reforzar: List[str] = Field(default_factory=list)
    score_registrado_en_users: bool
    siguiente_paso: str
