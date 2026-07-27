from fastapi import APIRouter, HTTPException, Header, Depends
from typing import Optional
from app.models.chat import ChatRequest, ChatResponse
from app.agents.chatbot_agent import ChatbotAgent
from app.services.auth_service import AuthService

router = APIRouter()
agent = ChatbotAgent()
auth_service = AuthService()

async def get_current_user(authorization: Optional[str] = Header(None)):
    # 👇 IGNORAR HEADER VACÍO
    if not authorization or not authorization.strip():
        return {"id": "demo-user", "email": "demo@user.com", "roles": ["USUARIO"]}
    
    if not authorization.startswith("Bearer "):
        return {"id": "demo-user", "email": "demo@user.com", "roles": ["USUARIO"]}
    
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return {"id": "demo-user", "email": "demo@user.com", "roles": ["USUARIO"]}
    
    user_data = await auth_service.validate_token(authorization)
    return user_data or {"id": "demo-user", "email": "demo@user.com", "roles": ["USUARIO"]}

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user_data: dict = Depends(get_current_user)
):
    try:
        usuario_id = request.usuario_id or user_data.get("id") or "demo-user"
        
        result = await agent.procesar_mensaje(
            usuario_id,
            request.mensaje,
            request.disability_type
        )
        return ChatResponse(
            conversacion_id=request.conversacion_id or "nueva",
            respuesta=result["respuesta"],
            intencion=result["intencion"],
            adaptada=result["adaptada"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")