import json
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.chatbot_agent import ChatbotAgent
from app.deps.contexto import discapacidad_efectiva, resolver_contexto
from app.models.chat import ChatResponse

router = APIRouter()
agent = ChatbotAgent()


class ChatRequestAuth(BaseModel):
    mensaje: str
    usuario_id: Optional[str] = None
    disability_type: Optional[str] = Field(
        default=None,
        description="Ignorado salvo ADMIN/ENTRENADOR; el perfil del token manda",
    )
    conversacion_id: Optional[str] = None


@router.post("", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequestAuth,
    authorization: Optional[str] = Header(None),
):
    try:
        ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)
        discapacidad = discapacidad_efectiva(
            ctx, request.disability_type, permitir_override=True
        )
        resultado = await agent.procesar_mensaje(
            ctx.id,
            request.mensaje,
            discapacidad,
            ctx.authorization,
            request.conversacion_id,
        )
        return ChatResponse(
            conversacion_id=resultado.get("conversacion_id") or request.conversacion_id or "nueva",
            respuesta=resultado["respuesta"],
            intencion=resultado["intencion"],
            adaptada=resultado["adaptada"],
            confianza=resultado.get("confianza", 0.0),
            fuente=resultado.get("fuente", "motor_local"),
            agente=resultado.get("agente", "inklusport-profesional"),
            sugerencias=resultado.get("sugerencias") or [],
            datos={
                **(resultado.get("datos") or {}),
                "usuario": {
                    "id": ctx.id,
                    "email": ctx.email,
                    "fullName": ctx.full_name,
                    "disability": ctx.disability,
                    "roles": ctx.roles,
                },
            },
            herramientas_usadas=resultado.get("herramientas_usadas") or [],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error procesando el mensaje: {exc}")


@router.post("/stream")
async def chat_stream(
    request: ChatRequestAuth,
    authorization: Optional[str] = Header(None),
):
    ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)
    discapacidad = discapacidad_efectiva(
        ctx, request.disability_type, permitir_override=True
    )

    async def generador():
        try:
            async for evento in agent.procesar_mensaje_stream(
                ctx.id,
                request.mensaje,
                discapacidad,
                ctx.authorization,
                request.conversacion_id,
            ):
                yield f"data: {json.dumps(evento, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:
            error = {"evento": "error", "detalle": str(exc)}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generador(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
