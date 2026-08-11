import json
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from app.agents.chatbot_agent import ChatbotAgent
from app.deps.contexto import discapacidad_efectiva, resolver_contexto
from app.models.chat import ChatResponse
from app.services.conversacion_service import ConversacionService

router = APIRouter()
agent = ChatbotAgent()
conversaciones = ConversacionService()


class ChatRequestAuth(BaseModel):
    """Body del chat. No confundir con POST /api/ai/rutinas/generar."""

    mensaje: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Texto del usuario. Obligatorio (no uses campos de rutina aquí).",
    )
    usuario_id: Optional[str] = None
    disability_type: Optional[str] = Field(
        default=None,
        description="Ignorado salvo ADMIN/ENTRENADOR; el perfil del token manda",
    )
    conversacion_id: Optional[str] = Field(
        default=None,
        description=(
            "Reutiliza el id para continuidad. Alias aceptado: session_id. "
            "Si se omite, se continúa la última conversación activa o se crea una nueva."
        ),
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Alias de conversacion_id (compatibilidad Postman/front)",
    )

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data):
        if not isinstance(data, dict):
            return data
        # session_id → conversacion_id
        if not data.get("conversacion_id") and data.get("session_id"):
            data["conversacion_id"] = data["session_id"]
        # message / text → mensaje (por si el cliente manda inglés)
        if not data.get("mensaje"):
            for clave in ("message", "text", "prompt", "query"):
                if data.get(clave):
                    data["mensaje"] = data[clave]
                    break
        return data

    @field_validator("mensaje")
    @classmethod
    def _mensaje_no_vacio(cls, v: str) -> str:
        t = (v or "").strip()
        if not t:
            raise ValueError("mensaje no puede estar vacío")
        return t

    @property
    def hilo_id(self) -> Optional[str]:
        return self.conversacion_id or self.session_id


def _chat_response(ctx, resultado, request_hilo_id: Optional[str]) -> ChatResponse:
    cid = resultado.get("conversacion_id") or request_hilo_id or "nueva"
    return ChatResponse(
        conversacion_id=cid,
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
            "historial_turnos_contexto": resultado.get("historial_turnos_contexto"),
            "historial_con_resumen": resultado.get("historial_con_resumen"),
            "sintesis_llm": resultado.get("sintesis_llm"),
            "tool_calling": resultado.get("tool_calling", False),
            "modelo_llm": resultado.get("modelo_llm"),
            "session_id": cid,
        },
        herramientas_usadas=resultado.get("herramientas_usadas") or [],
    )


def _lista_hilos(usuario_id: str, items: list) -> dict:
    return {
        "usuario_id": usuario_id,
        "total": len(items),
        "conversaciones": items,
        "sessions": items,  # alias para clientes que esperan "sessions"
        "limites": {
            "max_mensajes_por_conversacion": conversaciones.max_mensajes,
            "max_conversaciones_activas": conversaciones.max_conversaciones,
            "turnos_enviados_al_llm": conversaciones.turnos_llm,
        },
    }


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
            request.hilo_id,
        )
        return _chat_response(ctx, resultado, request.hilo_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error procesando el mensaje: {exc}")


@router.post("/stream")
async def chat_stream(
    request: ChatRequestAuth,
    authorization: Optional[str] = Header(None),
):
    """Chat con SSE. Body: { \"mensaje\": \"...\", \"conversacion_id\"?: \"...\" }.

    No uses el body de rutinas (tipo/objetivo/duracion_minutos); eso va a
    POST /api/ai/rutinas/generar.
    """
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
                request.hilo_id,
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


# ---------------------------------------------------------------- historial
# Rutas canónicas: /conversaciones
# Alias:        /sessions  (Postman / front que usen ese nombre)


async def _listar_hilos(
    authorization: Optional[str],
    incluir_archivadas: bool,
    limite: int,
):
    ctx = await resolver_contexto(authorization, require_auth=True)
    items = await conversaciones.listar(
        ctx.id, incluir_archivadas=incluir_archivadas, limite=limite
    )
    return _lista_hilos(ctx.id, items)


async def _obtener_hilo(hilo_id: str, authorization: Optional[str]):
    ctx = await resolver_contexto(authorization, require_auth=True)
    doc = await conversaciones.obtener(ctx.id, hilo_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    # Alias session_id en la respuesta
    doc = {**doc, "session_id": doc.get("conversacion_id")}
    return doc


async def _borrar_hilo(hilo_id: str, authorization: Optional[str]):
    ctx = await resolver_contexto(authorization, require_auth=True)
    ok = await conversaciones.borrar(ctx.id, hilo_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return {"ok": True, "conversacion_id": hilo_id, "session_id": hilo_id}


async def _archivar_hilo(hilo_id: str, authorization: Optional[str]):
    ctx = await resolver_contexto(authorization, require_auth=True)
    ok = await conversaciones.archivar(ctx.id, hilo_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return {
        "ok": True,
        "conversacion_id": hilo_id,
        "session_id": hilo_id,
        "estado": "archivada",
    }


async def _borrar_todos(authorization: Optional[str], confirmar: bool):
    if not confirmar:
        raise HTTPException(
            status_code=400,
            detail="Pasa confirmar=true para borrar todo el historial del usuario",
        )
    ctx = await resolver_contexto(authorization, require_auth=True)
    borradas = await conversaciones.borrar_todas(ctx.id)
    return {"ok": True, "borradas": borradas}


async def _nueva_sesion(authorization: Optional[str]):
    ctx = await resolver_contexto(authorization, require_auth=True)
    cid = str(uuid.uuid4())
    return {
        "conversacion_id": cid,
        "session_id": cid,
        "usuario_id": ctx.id,
        "mensaje": (
            "Usa este conversacion_id (o session_id) en el próximo POST /api/ai/chat/ "
            "para un hilo nuevo sin heredar el historial anterior."
        ),
    }


@router.get("/conversaciones")
@router.get("/sessions")
@router.get("/sessions/")
async def listar_conversaciones(
    authorization: Optional[str] = Header(None),
    incluir_archivadas: bool = Query(False),
    limite: int = Query(20, ge=1, le=50),
):
    return await _listar_hilos(authorization, incluir_archivadas, limite)


@router.get("/conversaciones/{conversacion_id}")
@router.get("/sessions/{conversacion_id}")
@router.get("/sessions/{conversacion_id}/")
async def obtener_conversacion(
    conversacion_id: str,
    authorization: Optional[str] = Header(None),
):
    return await _obtener_hilo(conversacion_id, authorization)


@router.delete("/conversaciones/{conversacion_id}")
@router.delete("/sessions/{conversacion_id}")
@router.delete("/sessions/{conversacion_id}/")
async def borrar_conversacion(
    conversacion_id: str,
    authorization: Optional[str] = Header(None),
):
    return await _borrar_hilo(conversacion_id, authorization)


@router.post("/conversaciones/{conversacion_id}/archivar")
@router.post("/sessions/{conversacion_id}/archivar")
async def archivar_conversacion(
    conversacion_id: str,
    authorization: Optional[str] = Header(None),
):
    return await _archivar_hilo(conversacion_id, authorization)


@router.delete("/conversaciones")
@router.delete("/sessions")
@router.delete("/sessions/")
async def borrar_todas_conversaciones(
    authorization: Optional[str] = Header(None),
    confirmar: bool = Query(False, description="Debe ser true para borrar todo el historial"),
):
    return await _borrar_todos(authorization, confirmar)


@router.post("/nueva")
@router.post("/sessions")
@router.post("/sessions/")
async def nueva_conversacion(authorization: Optional[str] = Header(None)):
    """Crea un id de hilo limpio (no escribe en Mongo hasta el primer mensaje)."""
    return await _nueva_sesion(authorization)
