"""Chat del asistente (RF46): mensaje, stream SSE e historial de conversaciones."""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from app.agents.chatbot_agent import ChatbotAgent
from app.deps.contexto import discapacidad_efectiva, resolver_contexto
from app.models.chat import ChatResponse
from app.services.chat_limite import consumir_cupo_hora, estado_cupo, liberar, reservar, turno_usuario
from app.services.conversacion_service import ConversacionService
from app.tools.cards import construir_cards
from app.tools.mcp import descripcion_protocolo, mcp_del_turno

router = APIRouter()
agent = ChatbotAgent()
conversaciones = ConversacionService()


class ChatRequestAuth(BaseModel):
    """Cuerpo del chat conversacional. No confundir con POST /api/ai/rutinas/generar.

    Acepta alias (`session_id`, `message`/`text`) para compatibilidad con Postman
    y el front. `limitacion` marca zonas de dolor en el mapa corporal.
    """

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
    limitacion: Optional[str] = Field(
        default=None,
        description="Dolor o limitación a marcar en rojo en el dibujo del cuerpo",
        max_length=400,
    )

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data):
        """Normaliza alias de cliente (`session_id`, `message`, `pain`) al esquema interno."""
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
        if not data.get("limitacion"):
            for clave in ("limitation", "dolor", "pain"):
                if data.get(clave):
                    data["limitacion"] = data[clave]
                    break
        return data

    @field_validator("mensaje")
    @classmethod
    def _mensaje_no_vacio(cls, v: str) -> str:
        """Rechaza mensajes en blanco o solo espacios."""
        t = (v or "").strip()
        if not t:
            raise ValueError("mensaje no puede estar vacío")
        return t

    @property
    def hilo_id(self) -> Optional[str]:
        """Identificador de conversación: `conversacion_id` o su alias `session_id`."""
        return self.conversacion_id or self.session_id


def _chat_response(
    ctx,
    resultado,
    request_hilo_id: Optional[str],
    cupo: Optional[dict] = None,
) -> ChatResponse:
    """Empaqueta el dict del agente en ChatResponse con cards, MCP y perfil de sesión."""
    cid = resultado.get("conversacion_id") or request_hilo_id or "nueva"
    herramientas = resultado.get("herramientas_usadas") or []
    datos_crudos = dict(resultado.get("datos") or {})
    if resultado.get("pendiente_write") and "pendiente_write" not in datos_crudos:
        datos_crudos["pendiente_write"] = resultado["pendiente_write"]
    cards = construir_cards(datos_crudos, herramientas)
    mcp = mcp_del_turno(
        tool_calling=bool(resultado.get("tool_calling")),
        herramientas_usadas=herramientas,
        modelo=resultado.get("modelo_llm"),
        fuente=resultado.get("fuente", "motor_local"),
        roles=ctx.roles,
    )
    cupo = cupo or estado_cupo(ctx.id)
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
            **datos_crudos,
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
            "cards": cards,
            "cupo": cupo,
        },
        herramientas_usadas=herramientas,
        cards=cards,
        mcp=mcp,
        cuerpo=(datos_crudos.get("cuerpo") if isinstance(datos_crudos, dict) else None)
        or resultado.get("cuerpo"),
        aviso=cupo.get("aviso") if isinstance(cupo, dict) else None,
        cupo=cupo,
    )


def _lista_hilos(usuario_id: str, items: list) -> dict:
    """Arma el listado de conversaciones con alias `sessions` y cupos del servicio."""
    estado = estado_cupo(usuario_id)
    return {
        "usuario_id": usuario_id,
        "total": len(items),
        "conversaciones": items,
        "sessions": items,  # alias para clientes que esperan "sessions"
        "limites": {
            "max_mensajes_por_conversacion": conversaciones.max_mensajes,
            "max_conversaciones_activas": conversaciones.max_conversaciones,
            "turnos_enviados_al_llm": conversaciones.turnos_llm,
            "max_mensajes_por_hora": estado["maximo"],
            "espera_limite_segundos": estado["espera_segundos"],
            "usados_hora": estado["usados"],
            "aviso": estado.get("aviso"),
        },
    }


@router.post("", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequestAuth,
    authorization: Optional[str] = Header(None),
):
    """Procesa un mensaje del chat y devuelve la respuesta del asistente (RF46).

    Continúa el hilo si llega `conversacion_id`/`session_id`; si no, reutiliza
    la última conversación activa o crea una nueva. Requiere autenticación.
    """
    try:
        ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)
        discapacidad = discapacidad_efectiva(
            ctx, request.disability_type, permitir_override=True
        )
        async with turno_usuario(ctx.id):
            cupo = consumir_cupo_hora(ctx.id)
            resultado = await agent.procesar_mensaje(
                ctx.id,
                request.mensaje,
                discapacidad,
                ctx.authorization,
                request.hilo_id,
                ctx.roles,
                ctx.perfil,
                request.limitacion,
            )
        return _chat_response(ctx, resultado, request.hilo_id, cupo)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error procesando el mensaje: {exc}")


@router.post("/stream")
async def chat_stream(
    request: ChatRequestAuth,
    authorization: Optional[str] = Header(None),
):
    """Chat en streaming SSE (RF46). Body: { "mensaje": "...", "conversacion_id"?: "..." }.

    Emite fases del agente (estado, herramientas) y cierra con el evento `respuesta`.
    No uses el body de rutinas (tipo/objetivo/duracion_minutos); eso va a
    POST /api/ai/rutinas/generar.
    """
    ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)
    discapacidad = discapacidad_efectiva(
        ctx, request.disability_type, permitir_override=True
    )
    reservar(ctx.id)
    try:
        cupo = consumir_cupo_hora(ctx.id)
    except HTTPException:
        liberar(ctx.id)
        raise

    async def generador():
        """Produce el flujo SSE: heartbeat inicial, eventos del agente y cierre."""
        try:
            yield ": connected\n\n"
            async for evento in agent.procesar_mensaje_stream(
                ctx.id,
                request.mensaje,
                discapacidad,
                ctx.authorization,
                request.hilo_id,
                ctx.roles,
                ctx.perfil,
                request.limitacion,
            ):
                if evento.get("evento") == "respuesta" and isinstance(evento.get("datos"), dict):
                    wrapped = _chat_response(ctx, evento["datos"], request.hilo_id, cupo)
                    evento = {**evento, "datos": wrapped.model_dump()}
                yield f"data: {json.dumps(evento, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:
            error = {"evento": "error", "detalle": str(exc)}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
        finally:
            liberar(ctx.id)

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


def _ids_alias(ctx) -> list[str]:
    """Ids extra con los que pudo persistirse el historial (email vs uuid)."""
    extra: list[str] = []
    perfil = getattr(ctx, "perfil", None) or {}
    for valor in (
        getattr(ctx, "email", None),
        perfil.get("id"),
        perfil.get("userId"),
        perfil.get("user_id"),
        perfil.get("sub"),
    ):
        texto = str(valor or "").strip()
        if texto and texto != str(ctx.id) and texto not in extra:
            extra.append(texto)
    return extra


async def _listar_hilos(
    authorization: Optional[str],
    incluir_archivadas: bool,
    limite: int,
):
    """Lista los hilos del usuario autenticado (activas o también archivadas)."""
    ctx = await resolver_contexto(authorization, require_auth=True)
    items = await conversaciones.listar(
        ctx.id,
        incluir_archivadas=incluir_archivadas,
        limite=limite,
        ids_alias=_ids_alias(ctx),
    )
    print(
        f"GET conversaciones: {len(items)} hilos (limite={limite})",
        flush=True,
    )
    return _lista_hilos(ctx.id, items)


async def _obtener_hilo(hilo_id: str, authorization: Optional[str]):
    """Devuelve una conversación del usuario o 404 si no existe."""
    ctx = await resolver_contexto(authorization, require_auth=True)
    doc = await conversaciones.obtener(ctx.id, hilo_id, ids_alias=_ids_alias(ctx))
    if not doc:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    # Alias session_id en la respuesta
    doc = {**doc, "session_id": doc.get("conversacion_id")}
    return doc


async def _borrar_hilo(hilo_id: str, authorization: Optional[str]):
    """Elimina una conversación del usuario; 404 si el id no pertenece al token."""
    ctx = await resolver_contexto(authorization, require_auth=True)
    ok = await conversaciones.borrar(ctx.id, hilo_id, ids_alias=_ids_alias(ctx))
    if not ok:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return {"ok": True, "conversacion_id": hilo_id, "session_id": hilo_id}


async def _archivar_hilo(hilo_id: str, authorization: Optional[str]):
    """Archiva un hilo para que deje de aparecer en el listado activo."""
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
    """Borra todo el historial del usuario; exige `confirmar=true` para evitar accidentes."""
    if not confirmar:
        raise HTTPException(
            status_code=400,
            detail="Pasa confirmar=true para borrar todo el historial del usuario",
        )
    ctx = await resolver_contexto(authorization, require_auth=True)
    borradas = await conversaciones.borrar_todas(ctx.id, ids_alias=_ids_alias(ctx))
    return {"ok": True, "borradas": borradas}


async def _nueva_sesion(authorization: Optional[str]):
    """Genera un UUID de hilo limpio sin escribir en Mongo hasta el primer mensaje."""
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


@router.get("/mcp")
async def describir_mcp(authorization: Optional[str] = Header(None)):
    """Describe el protocolo interno de tools (estilo MCP) y lista las herramientas disponibles."""
    await resolver_contexto(authorization, require_auth=True)
    return descripcion_protocolo()


@router.get("/conversaciones")
@router.get("/sessions")
@router.get("/sessions/")
async def listar_conversaciones(
    authorization: Optional[str] = Header(None),
    incluir_archivadas: bool = Query(False),
    limite: int = Query(20, ge=1, le=50),
):
    """Lista las conversaciones del usuario (alias `/sessions` para Postman/front)."""
    return await _listar_hilos(authorization, incluir_archivadas, limite)


@router.get("/conversaciones/{conversacion_id}")
@router.get("/sessions/{conversacion_id}")
@router.get("/sessions/{conversacion_id}/")
async def obtener_conversacion(
    conversacion_id: str,
    authorization: Optional[str] = Header(None),
):
    """Devuelve un hilo concreto del usuario autenticado, con alias `session_id`."""
    return await _obtener_hilo(conversacion_id, authorization)


@router.delete("/conversaciones/{conversacion_id}")
@router.delete("/sessions/{conversacion_id}")
@router.delete("/sessions/{conversacion_id}/")
async def borrar_conversacion(
    conversacion_id: str,
    authorization: Optional[str] = Header(None),
):
    """Elimina una conversación del historial del usuario autenticado."""
    return await _borrar_hilo(conversacion_id, authorization)


@router.post("/conversaciones/{conversacion_id}/archivar")
@router.post("/sessions/{conversacion_id}/archivar")
async def archivar_conversacion(
    conversacion_id: str,
    authorization: Optional[str] = Header(None),
):
    """Archiva una conversación para ocultarla del listado activo."""
    return await _archivar_hilo(conversacion_id, authorization)


@router.delete("/conversaciones")
@router.delete("/sessions")
@router.delete("/sessions/")
async def borrar_todas_conversaciones(
    authorization: Optional[str] = Header(None),
    confirmar: bool = Query(False, description="Debe ser true para borrar todo el historial"),
):
    """Borra todas las conversaciones del usuario. Requiere `confirmar=true`."""
    return await _borrar_todos(authorization, confirmar)


@router.post("/nueva")
@router.post("/sessions")
@router.post("/sessions/")
async def nueva_conversacion(authorization: Optional[str] = Header(None)):
    """Crea un id de hilo limpio (no escribe en Mongo hasta el primer mensaje).

    Úsalo en el próximo POST /api/ai/chat/ para no heredar el historial anterior.
    """
    return await _nueva_sesion(authorization)
