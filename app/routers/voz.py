"""Puente de voz hacia acciones del asistente (RF46 + accessibility)."""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.chatbot_agent import ChatbotAgent
from app.deps.contexto import discapacidad_efectiva, resolver_contexto
from app.nlp.texto import normalizar
from app.services.accessibility_service import AccessibilityService

router = APIRouter()
chat_agent = ChatbotAgent()
accessibility = AccessibilityService()


class VozRequest(BaseModel):
    texto: str = Field(..., min_length=1)
    usuario_id: Optional[str] = None
    disability_type: Optional[str] = None
    language: str = "es"


@router.post("/comando")
async def comando_voz(request: VozRequest, authorization: Optional[str] = Header(None)):
    try:
        ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)
        discapacidad = discapacidad_efectiva(
            ctx, request.disability_type, permitir_override=True
        )
    except HTTPException:
        raise

    interpretacion = await accessibility.interpretar_voz(
        request.texto, request.language, ctx.authorization
    )
    limpio = normalizar(request.texto)

    accion = "chat"
    if any(p in limpio for p in ("rutina", "entrenamiento", "ejercicio")):
        accion = "rutina"
    elif any(p in limpio for p in ("evento", "competencia", "inscripcion")):
        accion = "eventos"
    elif any(p in limpio for p in ("deporte", "que puedo practicar")):
        accion = "deportes"

    resultado_chat = await chat_agent.procesar_mensaje(
        ctx.id,
        request.texto,
        discapacidad,
        ctx.authorization,
    )

    return {
        "accion": accion,
        "usuario": {
            "id": ctx.id,
            "email": ctx.email,
            "disability": ctx.disability,
            "roles": ctx.roles,
        },
        "interpretacion_accessibility": interpretacion,
        "respuesta_asistente": resultado_chat.get("respuesta"),
        "intencion": resultado_chat.get("intencion"),
        "sugerencias": resultado_chat.get("sugerencias") or [],
        "respuesta_auditiva": resultado_chat.get("respuesta"),
        "rf": "RF46",
    }
