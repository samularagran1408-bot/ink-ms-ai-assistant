from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class ChatRequest(BaseModel):
    usuario_id: Optional[str] = None
    mensaje: str
    disability_type: str = "visual"
    conversacion_id: Optional[str] = None

class ChatResponse(BaseModel):
    conversacion_id: str
    respuesta: str
    intencion: str
    adaptada: bool

class Mensaje(BaseModel):
    mensaje: str
    remitente: str
    intencion: Optional[str] = None
    fecha: datetime = datetime.utcnow()