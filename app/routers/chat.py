from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.agents.chatbot_agent import ChatbotAgent
from app.models.chat import ChatRequest, ChatResponse
from app.services.auth_service import AuthService

router = APIRouter()
agent = ChatbotAgent()
auth_service = AuthService()

USUARIO_DEMO = {"id": "demo-user", "email": "demo@user.com", "roles": ["USUARIO"]}


async def get_current_user(authorization: Optional[str] = Header(None)):
    """Resuelve el usuario del token; sin token válido se usa un perfil de demo."""
    if not authorization or not authorization.strip():
        return USUARIO_DEMO
    if not authorization.startswith("Bearer ") or not authorization[7:].strip():
        return USUARIO_DEMO
    return await auth_service.validate_token(authorization) or USUARIO_DEMO


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user_data: dict = Depends(get_current_user),
    authorization: Optional[str] = Header(None),
):
    try:
        usuario_id = request.usuario_id or user_data.get("id") or "demo-user"
        discapacidad = request.disability_type or user_data.get("disability")

        resultado = await agent.procesar_mensaje(
            usuario_id, request.mensaje, discapacidad, authorization
        )
        return ChatResponse(
            conversacion_id=request.conversacion_id or "nueva",
            respuesta=resultado["respuesta"],
            intencion=resultado["intencion"],
            adaptada=resultado["adaptada"],
            confianza=resultado.get("confianza", 0.0),
            fuente=resultado.get("fuente", "motor_local"),
            sugerencias=resultado.get("sugerencias") or [],
            datos=resultado.get("datos"),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error procesando el mensaje: {exc}")
