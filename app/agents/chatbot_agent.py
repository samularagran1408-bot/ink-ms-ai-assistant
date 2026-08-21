"""Agente conversacional profesional de InkluSport.

Orquesta: clasificación local → (opcional) tool-calling LLM → herramientas
locales (eventos, rutinas…) → síntesis. Sin LLM o sin soporte de tools, el
motor local responde completo.

El historial se persiste con cupos anti-basura (ver ConversacionService): el
usuario puede recuperarlo por API; al LLM solo llegan resumen + últimos turnos.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, timedelta
from typing import Any, AsyncIterator, Optional

from app.agents.dashboard_agent import DashboardAgent

from app.config import settings
from app.data.conocimiento import NO_ENTENDIDO, NO_ENTENDIDO_ADAPTADO
from app.data.quiz_banco import BANCOS
from app.database.repositorio import obtener_catalogo_ejercicios, obtener_conocimiento
from app.motor.rutinas import generar_rutina
from app.nlp.discapacidad import canonizar, coincide, descripcion
from app.nlp.intenciones import clasificar
from app.services.conversacion_service import ConversacionService
from app.services.llm_service import LLMService, _limpiar, system_prompt
from app.services.mcp_client import llamar_tool, listar_tools_openai
from app.services.sports_service import SportsService
from app.services.user_service import UserService
from app.tools.registry import (
    TOOL_DEFINITIONS,
    accion_de_tool,
    mensaje_tool_para_objetivo,
)
from app.tools.roles import TOOLS_LOCALES, filtrar_definiciones, nombres_permitidos
from app.tools.writes import (
    es_cancelacion,
    es_confirmacion,
    es_write,
    mensaje_pedir_confirmacion,
    resumen_write,
)

_ROTACION: dict[tuple[str, str], int] = {}
UMBRAL_CANDIDATO = 0.18
# Cortesía: respuesta local corta basta
_SOCIAL = frozenset({"saludo", "despedida", "agradecimiento"})
# Intenciones que disparan herramientas con datos reales
_CON_HERRAMIENTA = frozenset({
    "rutinas", "ejercicios", "eventos", "inscripcion", "deportes",
    "discapacidades", "adaptaciones", "quiz", "progreso", "cuenta",
    "crear_evento", "crear_deporte", "crear_rutina",
})

_ESTADOS_UI = {
    "analizando_intencion": "Entendiendo tu mensaje…",
    "agente_con_tools": "Decidiendo qué consultar…",
    "confirmando_accion": "Procesando tu confirmación…",
    "redactando_respuesta": "Redactando la respuesta…",
    "consultando_conocimiento": "Consultando el conocimiento de InkluSport…",
}

_TOOLS_UI = {
    "listar_eventos": "Consultando eventos publicados",
    "listar_deportes": "Revisando el catálogo de deportes",
    "listar_discapacidades": "Consultando discapacidades",
    "listar_adaptaciones": "Buscando adaptaciones",
    "generar_rutina": "Armando una rutina adaptada",
    "listar_ejercicios": "Eligiendo ejercicios",
    "info_quiz": "Revisando el quiz de aptitud",
    "consultar_mi_perfil": "Leyendo tu perfil",
    "estadisticas_usuario": "Calculando tus estadísticas",
    "recomendar_evento_nuevo": "Proponiendo un evento",
    "recomendar_deporte_nuevo": "Proponiendo un deporte",
    "recomendar_rutina_nueva": "Preparando una rutina para publicar",
    "eventos": "Consultando eventos publicados",
    "deportes": "Revisando el catálogo de deportes",
    "discapacidades": "Consultando discapacidades",
    "adaptaciones": "Buscando adaptaciones",
    "rutinas": "Armando una rutina adaptada",
    "ejercicios": "Eligiendo ejercicios",
    "quiz": "Revisando el quiz de aptitud",
    "cuenta": "Leyendo tu perfil",
    "progreso": "Calculando tus estadísticas",
    "crear_evento": "Preparando el alta del evento",
    "crear_deporte": "Preparando el alta del deporte",
    "crear_rutina": "Preparando el alta de la rutina",
    "inscripcion": "Revisando inscripciones",
    "bloquear_usuario": "Bloqueando usuario",
    "desactivar_usuario": "Desactivando usuario",
    "activar_usuario": "Activando usuario",
    "eliminar_usuario": "Eliminando usuario",
    "asignar_rol": "Asignando rol",
    "reemplazar_roles": "Actualizando roles",
    "listar_usuarios": "Listando usuarios",
    "buscar_usuarios": "Buscando usuarios",
    "consultar_dashboard": "Consultando el dashboard",
    "exportar_pdf_dashboard": "Preparando el PDF del dashboard",
    "editar_deporte": "Editando el deporte",
    "eliminar_deporte": "Eliminando el deporte",
}


def _evento_ui(
    evento: str,
    detalle: str,
    estado: Optional[str] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Evento SSE con texto legible para animar el chat."""
    if evento == "estado":
        mensaje = _ESTADOS_UI.get(detalle, "Trabajando en tu consulta…")
    else:
        label = _TOOLS_UI.get(detalle, "Consultando datos de la plataforma")
        mensaje = f"{label} — listo" if estado == "listo" else f"{label}…"
    payload: dict[str, Any] = {
        "evento": evento,
        "detalle": detalle,
        "mensaje": mensaje,
        **extra,
    }
    if estado:
        payload["estado"] = estado
    return payload


class _EmisorEventos:
    """Lista compatible con append() que también emite a la cola SSE."""

    def __init__(self, cola: Optional[asyncio.Queue] = None):
        self._items: list[dict[str, Any]] = []
        self._cola = cola

    def append(self, ev: dict[str, Any]) -> None:
        if not isinstance(ev, dict):
            return
        if "mensaje" not in ev:
            ev = _evento_ui(
                str(ev.get("evento") or "estado"),
                str(ev.get("detalle") or ""),
                ev.get("estado"),
                **{
                    k: v
                    for k, v in ev.items()
                    if k not in {"evento", "detalle", "estado", "mensaje"}
                },
            )
        self._items.append(ev)
        if self._cola is not None:
            self._cola.put_nowait(ev)

    def __iter__(self):
        return iter(self._items)


_SISTEMA_TOOLS = (
    "Puedes usar herramientas para obtener o cambiar datos reales de InkluSport "
    "(eventos, deportes, adaptaciones, inscripciones, discapacidades, usuarios, "
    "roles y reportes PDF). "
    "El usuario YA está autenticado: NUNCA pidas su email, correo ni ID. "
    "Para su perfil llama consultar_mi_perfil o consultar_usuario con 'me'. "
    "Para inscripciones no hace falta user_id. "
    "Si un admin pregunta por otra persona, busca por nombre con buscar_usuarios "
    "y luego estadisticas_usuario; no pidas identificadores. "
    "ADMIN: sí puedes bloquear, desactivar, activar y eliminar usuarios, "
    "asignar o reemplazar roles, gestionar deportes/discapacidades/adaptaciones "
    "y exportar el dashboard a PDF. Usa bloquear_usuario, activar_usuario, "
    "eliminar_usuario, asignar_rol, exportar_pdf_dashboard, etc. "
    "Nunca digas que no tienes herramienta para eso ni redirijas al panel. "
    "Organizador: si pide ideas o crear un evento, usa recomendar_evento_nuevo "
    "y ofrece crearlo con crear_evento. También puedes exportar el dashboard a PDF. "
    "Entrenador: si pide un deporte o rutina nueva, usa recomendar_deporte_nuevo "
    "o recomendar_rutina_nueva y ofrece crearlo en la plataforma. "
    "Las escrituras requieren que el usuario confirme; tú solo pide la tool. "
    "Cuando ya tengas los datos, responde en español, máximo 6 frases, "
    "sin Markdown y SIN pegar JSON."
)


class ChatbotAgent:
    def __init__(self):
        self.llm = LLMService()
        self.sports_service = SportsService()
        self.user_service = UserService()
        self.conversaciones = ConversacionService()
        self.dashboard = DashboardAgent()

    # ------------------------------------------------------------------ público

    async def _resolver_turno(
        self,
        usuario_id: str,
        mensaje: str,
        clave_discapacidad: str,
        authorization: Optional[str],
        historial_llm: list[dict[str, Any]],
        clasificacion: dict[str, Any],
        *,
        eventos: Optional[Any] = None,
        roles: Optional[list[str]] = None,
        conversacion_id: Optional[str] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Decide tool-calling / motor local / LLM conversacional."""
        intencion = clasificacion["nombre"]

        # 1) Social → plantillas locales (rápido, sin tokens)
        if intencion in _SOCIAL:
            return await self._responder_conocido(
                usuario_id, intencion, clave_discapacidad, authorization, mensaje,
                roles=roles or [], perfil=perfil,
            )

        # 2) Tool-calling LLM (estilo MCP) cuando está habilitado
        if settings.LLM_TOOL_CALLING_ENABLED and self.llm.disponible:
            con_tools = await self._responder_con_tools(
                mensaje,
                clave_discapacidad,
                authorization,
                historial_llm,
                usuario_id,
                intencion_hint=intencion or clasificacion.get("mejor_candidato"),
                eventos=eventos,
                roles=roles or [],
                perfil=perfil,
            )
            if con_tools:
                return con_tools

        # 3) Herramienta clara → datos reales + pulido LLM si hay
        if intencion in _CON_HERRAMIENTA:
            if eventos is not None:
                eventos.append(
                    {"evento": "herramienta", "detalle": intencion, "estado": "ejecutando"}
                )
            resultado = await self._responder_conocido(
                usuario_id, intencion, clave_discapacidad, authorization, mensaje,
                roles=roles or [], perfil=perfil,
            )
            if eventos is not None:
                eventos.append(
                    {"evento": "herramienta", "detalle": intencion, "estado": "listo"}
                )
            return await self._sintetizar_como_agente(
                mensaje, resultado, clave_discapacidad, historial_llm, clasificacion
            )

        # 4) Resto (FAQ, dudas, desconocido): chatbot LLM con contexto
        borrador = None
        if intencion:
            local = await self._responder_conocido(
                usuario_id, intencion, clave_discapacidad, authorization, mensaje,
                roles=roles or [], perfil=perfil,
            )
            borrador = local.get("respuesta")
            sugerencias = local.get("sugerencias") or []
        else:
            sugerencias = [
                "¿Quieres que te prepare una rutina adaptada?",
                "Puedo mostrarte los eventos compatibles con tu perfil",
            ]

        conversacional = await self._responder_conversacional(
            mensaje,
            clave_discapacidad,
            authorization,
            historial_llm,
            borrador=borrador,
            intencion_hint=intencion or clasificacion.get("mejor_candidato"),
            perfil=perfil,
            roles=roles or [],
        )
        if conversacional:
            conversacional["sugerencias"] = conversacional.get("sugerencias") or sugerencias
            return conversacional

        # 5) Sin LLM: plantilla / aproximación / no_entendido
        if intencion:
            return await self._responder_conocido(
                usuario_id, intencion, clave_discapacidad, authorization, mensaje,
                roles=roles or [], perfil=perfil,
            )
        return await self._responder_desconocido(
            usuario_id,
            mensaje,
            clave_discapacidad,
            clasificacion,
            authorization,
            historial_llm,
        )

    async def procesar_mensaje(
        self,
        usuario_id: str,
        mensaje: str,
        discapacidad: Optional[str] = None,
        authorization: Optional[str] = None,
        conversacion_id: Optional[str] = None,
        roles: Optional[list[str]] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        historial, cid_efectiva, resumen = await self.conversaciones.cargar_contexto_llm(
            usuario_id, conversacion_id or ""
        )
        # Sin id del cliente: continúa la última activa; si no hay, crea una nueva.
        conversacion_id = conversacion_id or cid_efectiva or str(uuid.uuid4())
        clave_discapacidad = canonizar(discapacidad)
        historial_llm = self.conversaciones.mensajes_para_llm(historial, resumen)
        roles = roles or []

        pendiente = await self.conversaciones.leer_pendiente_write(
            usuario_id, conversacion_id
        )
        if pendiente:
            resultado = await self._resolver_pendiente(
                usuario_id,
                mensaje,
                clave_discapacidad,
                authorization,
                roles,
                pendiente,
            )
        else:
            clasificacion = clasificar(mensaje)
            intencion = clasificacion["nombre"]
            resultado = await self._resolver_turno(
                usuario_id,
                mensaje,
                clave_discapacidad,
                authorization,
                historial_llm,
                clasificacion,
                roles=roles,
                conversacion_id=conversacion_id,
                perfil=perfil,
            )
            resultado["intencion"] = resultado.get("intencion") or intencion or "general"
            resultado["confianza"] = clasificacion["confianza"]
            resultado["terminos_detectados"] = clasificacion["terminos"]

        resultado["conversacion_id"] = conversacion_id
        resultado["agente"] = "inklusport-profesional"
        resultado["historial_turnos_contexto"] = len(historial) // 2
        resultado["historial_con_resumen"] = bool(resumen)

        await self.conversaciones.guardar_turno(
            usuario_id, conversacion_id, mensaje, resultado
        )
        return resultado

    async def procesar_mensaje_stream(
        self,
        usuario_id: str,
        mensaje: str,
        discapacidad: Optional[str] = None,
        authorization: Optional[str] = None,
        conversacion_id: Optional[str] = None,
        roles: Optional[list[str]] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Emite fases del agente (SSE) y cierra con la respuesta final."""
        yield _evento_ui("estado", "analizando_intencion")
        historial, cid_efectiva, resumen = await self.conversaciones.cargar_contexto_llm(
            usuario_id, conversacion_id or ""
        )
        conversacion_id = conversacion_id or cid_efectiva or str(uuid.uuid4())
        clave_discapacidad = canonizar(discapacidad)
        historial_llm = self.conversaciones.mensajes_para_llm(historial, resumen)
        roles = roles or []

        pendiente = await self.conversaciones.leer_pendiente_write(
            usuario_id, conversacion_id
        )
        cola: asyncio.Queue = asyncio.Queue()
        eventos_side = _EmisorEventos(cola)

        if pendiente:
            yield _evento_ui("estado", "confirmando_accion")

            async def _trabajo_pendiente():
                try:
                    res = await self._resolver_pendiente(
                        usuario_id,
                        mensaje,
                        clave_discapacidad,
                        authorization,
                        roles,
                        pendiente,
                    )
                    await cola.put({"evento": "_done", "resultado": res})
                except Exception as exc:
                    await cola.put({"evento": "_error", "detalle": str(exc)})

            tarea = asyncio.create_task(_trabajo_pendiente())
        else:
            clasificacion = clasificar(mensaje)
            intencion = clasificacion["nombre"]

            if settings.LLM_TOOL_CALLING_ENABLED and self.llm.disponible and intencion not in _SOCIAL:
                yield _evento_ui("estado", "agente_con_tools")
            elif intencion in _CON_HERRAMIENTA:
                yield _evento_ui("herramienta", intencion, "ejecutando")
            elif self.llm.disponible and intencion not in _SOCIAL:
                yield _evento_ui("estado", "redactando_respuesta")
            else:
                yield _evento_ui("estado", "consultando_conocimiento")

            async def _trabajo_turno():
                try:
                    res = await self._resolver_turno(
                        usuario_id,
                        mensaje,
                        clave_discapacidad,
                        authorization,
                        historial_llm,
                        clasificacion,
                        eventos=eventos_side,
                        roles=roles,
                        conversacion_id=conversacion_id,
                        perfil=perfil,
                    )
                    res["intencion"] = res.get("intencion") or intencion or "general"
                    res["confianza"] = clasificacion["confianza"]
                    res["terminos_detectados"] = clasificacion["terminos"]
                    await cola.put({"evento": "_done", "resultado": res})
                except Exception as exc:
                    await cola.put({"evento": "_error", "detalle": str(exc)})

            tarea = asyncio.create_task(_trabajo_turno())

        resultado: dict[str, Any] | None = None
        try:
            while True:
                ev = await cola.get()
                tipo = ev.get("evento")
                if tipo == "_done":
                    resultado = ev.get("resultado") or {}
                    break
                if tipo == "_error":
                    raise RuntimeError(ev.get("detalle") or "Error en el agente")
                yield ev
            await tarea
        except Exception:
            if not tarea.done():
                tarea.cancel()
            try:
                await tarea
            except (asyncio.CancelledError, Exception):
                pass
            raise

        if not resultado:
            raise RuntimeError("El agente no devolvió respuesta")

        resultado["conversacion_id"] = conversacion_id
        resultado["agente"] = "inklusport-profesional"
        resultado["historial_turnos_contexto"] = len(historial) // 2
        resultado["historial_con_resumen"] = bool(resumen)

        await self.conversaciones.guardar_turno(
            usuario_id, conversacion_id, mensaje, resultado
        )
        yield {"evento": "respuesta", "datos": resultado}
        yield {"evento": "fin", "conversacion_id": conversacion_id}

    # ---------------------------------------------------------- tool-calling

    async def _responder_con_tools(
        self,
        mensaje: str,
        discapacidad: str,
        authorization: Optional[str],
        historial: list[dict[str, Any]],
        usuario_id: str,
        *,
        intencion_hint: Optional[str] = None,
        eventos: Optional[Any] = None,
        roles: Optional[list[str]] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Loop LLM ↔ tools. Devuelve None para caer al motor local."""
        if not self.llm.disponible:
            return None

        hint = (
            f" Intención probable del clasificador local: {intencion_hint}."
            if intencion_hint
            else ""
        )
        sesion = self._texto_sesion(usuario_id, discapacidad, roles or [], perfil)
        mensajes: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(discapacidad, _SISTEMA_TOOLS + "\n" + sesion)},
            *historial,
            {
                "role": "user",
                "content": (
                    f"Mensaje del usuario: «{mensaje}».{hint} "
                    f"{sesion} "
                    "Usa herramientas si necesitas datos reales de la plataforma. "
                    "No pidas email ni ID."
                ),
            },
        ]

        herramientas_usadas: list[str] = []
        datos_acumulados: dict[str, Any] = {"modo": "tool_calling", "rondas": []}
        max_rondas = max(1, settings.LLM_TOOL_MAX_RONDAS)
        roles = roles or []
        tools_openai = await self._definiciones_tools(roles, authorization)
        if not tools_openai:
            return None

        try:
            for ronda in range(max_rondas):
                resultado_llm = await self.llm.completar(
                    mensajes,
                    temperatura=0.4,
                    tools=tools_openai,
                    tool_choice="auto",
                )

                if resultado_llm.tiene_tools:
                    mensajes.append(
                        {
                            "role": "assistant",
                            "content": resultado_llm.content,
                            "tool_calls": resultado_llm.tool_calls,
                        }
                    )
                    for tc in resultado_llm.tool_calls:
                        nombre = (tc.get("function") or {}).get("name") or ""
                        raw_args = (tc.get("function") or {}).get("arguments") or "{}"
                        try:
                            args = (
                                json.loads(raw_args)
                                if isinstance(raw_args, str)
                                else dict(raw_args)
                            )
                        except json.JSONDecodeError:
                            args = {}
                        if not isinstance(args, dict):
                            args = {}
                        args = self._fijar_actor(nombre, args, usuario_id, roles)

                        if es_write(nombre):
                            pendiente = {
                                "tool": nombre,
                                "args": args,
                                "resumen": resumen_write(nombre, args),
                            }
                            return {
                                "respuesta": mensaje_pedir_confirmacion(nombre, args),
                                "intencion": intencion_hint or "general",
                                "adaptada": discapacidad != "general",
                                "sugerencias": ["Confirmo", "Cancelar"],
                                "datos": {"pendiente_write": pendiente},
                                "fuente": "agente",
                                "herramientas_usadas": [nombre],
                                "sintesis_llm": False,
                                "tool_calling": True,
                                "modelo_llm": resultado_llm.modelo_usado,
                                "pendiente_write": pendiente,
                            }

                        if eventos is not None:
                            eventos.append(
                                {
                                    "evento": "herramienta",
                                    "detalle": nombre,
                                    "estado": "ejecutando",
                                    "ronda": ronda + 1,
                                }
                            )

                        texto, datos = await self._ejecutar_herramienta(
                            nombre,
                            args,
                            usuario_id,
                            discapacidad,
                            authorization,
                            mensaje,
                            roles,
                            perfil=perfil,
                        )
                        herramientas_usadas.append(nombre)
                        datos_acumulados["rondas"].append(
                            {"tool": nombre, "args": args, "ok": bool(texto or datos)}
                        )
                        if datos:
                            datos_acumulados[nombre] = datos

                        mensajes.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.get("id") or f"call_{nombre}",
                                "content": json.dumps(
                                    {"texto": texto, "datos": datos},
                                    ensure_ascii=False,
                                    default=str,
                                )[:6000],
                            }
                        )

                        if eventos is not None:
                            eventos.append(
                                {
                                    "evento": "herramienta",
                                    "detalle": nombre,
                                    "estado": "listo",
                                    "ronda": ronda + 1,
                                }
                            )
                    continue

                texto_final = (resultado_llm.content or "").strip()
                if eventos is not None:
                    eventos.append(_evento_ui("estado", "redactando_respuesta"))
                if not texto_final and herramientas_usadas:
                    texto_final = await self._sintesis_tras_tools(
                        mensaje, discapacidad, historial, datos_acumulados
                    ) or ""
                if not texto_final:
                    return None

                return {
                    "respuesta": _limpiar(texto_final),
                    "intencion": intencion_hint or "general",
                    "adaptada": discapacidad != "general",
                    "sugerencias": [],
                    "datos": datos_acumulados,
                    "fuente": "agente",
                    "herramientas_usadas": herramientas_usadas or ["tool_calling"],
                    "sintesis_llm": True,
                    "tool_calling": True,
                    "modelo_llm": resultado_llm.modelo_usado,
                }

            cierre = await self.llm.texto_mensajes(
                [
                    *mensajes,
                    {
                        "role": "user",
                        "content": (
                            "Con los resultados de las herramientas, responde ya "
                            "al usuario en español, máximo 6 frases, sin Markdown."
                        ),
                    },
                ],
                temperatura=0.5,
            )
            if not cierre:
                return None
            return {
                "respuesta": cierre,
                "intencion": intencion_hint or "general",
                "adaptada": discapacidad != "general",
                "sugerencias": [],
                "datos": datos_acumulados,
                "fuente": "agente",
                "herramientas_usadas": herramientas_usadas,
                "sintesis_llm": True,
                "tool_calling": True,
            }
        except Exception as exc:
            print(f"Tool-calling no disponible, fallback motor local: {exc}")
            return None

    async def _ejecutar_tool(
        self,
        nombre: str,
        args: dict[str, Any],
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje_usuario: str,
        roles: Optional[list[str]] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> tuple[str, dict[str, Any]]:
        accion = accion_de_tool(nombre)
        if not accion:
            return f"Herramienta desconocida: {nombre}", {"error": "tool_desconocida"}
        mensaje = mensaje_tool_para_objetivo(nombre, args, mensaje_usuario)
        if nombre == "estadisticas_usuario" and (args or {}).get("nombre_o_id"):
            mensaje = str(args.get("nombre_o_id"))
        return await self._enriquecer(
            accion, usuario_id, discapacidad, authorization, mensaje,
            roles=roles or [], perfil=perfil, args=args,
        )

    def _texto_sesion(
        self,
        usuario_id: str,
        discapacidad: str,
        roles: list[str],
        perfil: Optional[dict[str, Any]],
    ) -> str:
        nombre = (perfil or {}).get("fullName") or "Usuario"
        disc = (perfil or {}).get("disability") or discapacidad or "no indicada"
        roles_txt = ", ".join(str(r) for r in (roles or [])) or "USUARIO"
        return (
            f"Sesión: {nombre}. Discapacidad de perfil: {disc}. Roles: {roles_txt}. "
            "Identidad ya resuelta; no preguntes email ni ID."
        )

    def _claves_rol(self, roles: list[str]) -> set[str]:
        claves: set[str] = set()
        for rol in roles or []:
            r = str(rol).upper().replace("ROLE_", "")
            if r in ("ADMIN", "ADMINISTRADOR"):
                claves.add("admin")
            elif r in ("ORGANIZER", "ORGANIZADOR"):
                claves.add("organizador")
            elif r in ("TRAINER", "ENTRENADOR", "COACH"):
                claves.add("entrenador")
            elif r in ("USER", "USUARIO"):
                claves.add("usuario")
        return claves or {"usuario"}

    def _fijar_actor(
        self,
        nombre: str,
        args: dict[str, Any],
        usuario_id: str,
        roles: list[str],
    ) -> dict[str, Any]:
        args = dict(args or {})
        claves = self._claves_rol(roles)
        es_admin = "admin" in claves
        es_staff = bool(claves & {"admin", "entrenador", "organizador"})
        if nombre == "inscribirse_evento" and (not es_staff or not args.get("user_id")):
            args["user_id"] = usuario_id
        if nombre == "consultar_inscripciones":
            clave = str(args.get("user_id") or "").strip()
            if not clave or clave.lower() in ("me", "yo") or not es_admin:
                args["user_id"] = usuario_id
        if nombre == "consultar_usuario":
            clave = str(args.get("user_id_o_email") or "").strip()
            if not clave or clave.lower() in ("me", "yo") or not es_admin:
                args["user_id_o_email"] = "me"
        if nombre == "listar_rutinas_entrenador":
            clave = str(args.get("trainer_id") or "").strip()
            if not clave or clave.lower() in ("me", "yo"):
                args["trainer_id"] = usuario_id
        if nombre == "crear_evento" and not args.get("created_by"):
            args["created_by"] = usuario_id
        if nombre == "crear_rutina" and not args.get("trainer_id"):
            args["trainer_id"] = usuario_id
        if nombre == "estadisticas_usuario" and not es_admin:
            args.pop("nombre_o_id", None)
        return args

    async def _definiciones_tools(
        self, roles: list[str], authorization: Optional[str]
    ) -> list[dict[str, Any]]:
        mcp_tools = await listar_tools_openai(authorization)
        locales = [
            t
            for t in TOOL_DEFINITIONS
            if (t.get("function") or {}).get("name") in TOOLS_LOCALES
        ]
        combinadas = (mcp_tools + locales) if mcp_tools else list(TOOL_DEFINITIONS)
        return filtrar_definiciones(combinadas, roles)

    async def _ejecutar_herramienta(
        self,
        nombre: str,
        args: dict[str, Any],
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje_usuario: str,
        roles: list[str],
        perfil: Optional[dict[str, Any]] = None,
    ) -> tuple[str, dict[str, Any]]:
        if nombre not in nombres_permitidos(roles):
            return (
                f"No tienes permiso para la herramienta {nombre}.",
                {"success": False, "error": "tool_no_permitida"},
            )
        if (nombre or "") in TOOLS_LOCALES or accion_de_tool(nombre):
            if nombre in TOOLS_LOCALES or not settings.MCP_ENABLED:
                return await self._ejecutar_tool(
                    nombre, args, usuario_id, discapacidad, authorization, mensaje_usuario,
                    roles=roles, perfil=perfil,
                )
        mcp_datos = await llamar_tool(nombre, args, authorization)
        if isinstance(mcp_datos, dict) and mcp_datos.get("success") is False:
            if accion_de_tool(nombre):
                return await self._ejecutar_tool(
                    nombre, args, usuario_id, discapacidad, authorization, mensaje_usuario,
                    roles=roles, perfil=perfil,
                )
        texto = json.dumps(mcp_datos, ensure_ascii=False, default=str)[:6000]
        return texto, mcp_datos if isinstance(mcp_datos, dict) else {"data": mcp_datos}

    async def _resolver_pendiente(
        self,
        usuario_id: str,
        mensaje: str,
        discapacidad: str,
        authorization: Optional[str],
        roles: list[str],
        pendiente: dict[str, Any],
    ) -> dict[str, Any]:
        if es_cancelacion(mensaje):
            return {
                "respuesta": "Cancelado. No he ejecutado esa acción.",
                "intencion": "general",
                "adaptada": discapacidad != "general",
                "sugerencias": [],
                "datos": {},
                "fuente": "agente",
                "herramientas_usadas": [],
                "pendiente_write": None,
            }
        if not es_confirmacion(mensaje):
            return {
                "respuesta": (
                    f"Sigue pendiente: {pendiente.get('resumen')}. "
                    "Responde «Confirmo» o «Cancelar»."
                ),
                "intencion": "general",
                "adaptada": discapacidad != "general",
                "sugerencias": ["Confirmo", "Cancelar"],
                "datos": {"pendiente_write": pendiente},
                "fuente": "agente",
                "herramientas_usadas": [pendiente.get("tool") or ""],
                "pendiente_write": pendiente,
            }

        nombre = str(pendiente.get("tool") or "")
        args = self._fijar_actor(nombre, pendiente.get("args") or {}, usuario_id, roles)
        texto, datos = await self._ejecutar_herramienta(
            nombre, args, usuario_id, discapacidad, authorization, mensaje, roles
        )
        ok = isinstance(datos, dict) and datos.get("success") is not False
        respuesta = (
            "Listo. La acción se ejecutó en la plataforma."
            if ok
            else "No pude completar la acción. "
            + str((datos or {}).get("error") or texto)[:400]
        )
        return {
            "respuesta": _limpiar(respuesta),
            "intencion": "general",
            "adaptada": discapacidad != "general",
            "sugerencias": [],
            "datos": {nombre: datos} if datos else {},
            "fuente": "agente",
            "herramientas_usadas": [nombre],
            "tool_calling": True,
            "pendiente_write": None,
        }

    async def _sintesis_tras_tools(
        self,
        mensaje: str,
        discapacidad: str,
        historial: list[dict[str, Any]],
        datos: dict[str, Any],
    ) -> Optional[str]:
        return await self.llm.texto_mensajes(
            [
                {"role": "system", "content": system_prompt(discapacidad)},
                *historial,
                {
                    "role": "user",
                    "content": (
                        f"Mensaje: «{mensaje}»\n"
                        f"Datos de herramientas: "
                        f"{json.dumps(datos, ensure_ascii=False, default=str)[:3500]}\n"
                        "Responde en español, máximo 6 frases, sin Markdown y sin pegar JSON. "
                        "No pidas email ni ID. No inventes datos."
                    ),
                },
            ],
            temperatura=0.5,
        )

    # ---------------------------------------------------------------- redacción

    async def _responder_conocido(
        self,
        usuario_id: str,
        intencion: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje: str = "",
        *,
        roles: Optional[list[str]] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        conocimiento = await obtener_conocimiento(intencion) or {}
        adaptaciones = conocimiento.get("adaptaciones") or {}
        especifica = adaptaciones.get(discapacidad)

        if especifica:
            texto = especifica
        else:
            variantes = conocimiento.get("respuestas") or []
            texto = self._rotar(usuario_id, intencion, variantes) if variantes else ""

        datos: dict[str, Any] = {}
        accion = conocimiento.get("accion") or {
            "progreso": "estadisticas",
            "cuenta": "perfil",
            "crear_evento": "propuesta_evento",
            "crear_deporte": "propuesta_deporte",
            "crear_rutina": "propuesta_rutina",
        }.get(intencion)
        if accion:
            complemento, datos = await self._enriquecer(
                accion, usuario_id, discapacidad, authorization, mensaje,
                roles=roles or [], perfil=perfil,
            )
            if complemento:
                texto = f"{texto}\n\n{complemento}".strip()
        if not texto:
            texto = self._rotar(usuario_id, intencion, [])

        resultado = {
            "respuesta": texto,
            "intencion": intencion,
            "adaptada": bool(especifica),
            "sugerencias": conocimiento.get("sugerencias") or [],
            "datos": datos or None,
            "fuente": "motor_local",
            "herramientas_usadas": [accion] if accion else [],
        }
        if datos and datos.get("pendiente_write"):
            resultado["pendiente_write"] = datos["pendiente_write"]
            resultado["sugerencias"] = ["Confirmo", "Cancelar"]
        return resultado

    async def _responder_conversacional(
        self,
        mensaje: str,
        discapacidad: str,
        authorization: Optional[str],
        historial: list[dict[str, str]],
        *,
        borrador: Optional[str] = None,
        intencion_hint: Optional[str] = None,
        perfil: Optional[dict[str, Any]] = None,
        roles: Optional[list[str]] = None,
    ) -> Optional[dict[str, Any]]:
        """Chat normal con LLM: responde casi cualquier pregunta con contexto real."""
        if not self.llm.disponible:
            return None

        contexto = await self._contexto_plataforma(authorization, perfil=perfil)
        sesion = self._texto_sesion("sesion", discapacidad, roles or [], perfil)
        pista = ""
        if borrador:
            pista = (
                f"\n\nNotas internas de la plataforma (úsalas si aportan, "
                f"no las copies literales):\n{borrador[:900]}"
            )
        hint = f"\nIntención probable: {intencion_hint}." if intencion_hint else ""

        mensajes = [
            {
                "role": "system",
                "content": system_prompt(
                    discapacidad,
                    "Actúa como un chatbot conversacional útil: responde la pregunta "
                    "del usuario aunque no sea solo de deporte. Sé natural, breve y "
                    "varía el estilo. Si puedes enlazar con entrenamiento inclusivo o "
                    "eventos de InkluSport, hazlo al final sin forzar.",
                ),
            },
            *historial,
            {
                "role": "user",
                "content": (
                    f"Mensaje del usuario: «{mensaje}»{hint}\n\n"
                    f"Datos reales de InkluSport ahora mismo:\n{sesion}\n{contexto}"
                    f"{pista}\n\n"
                    "Responde en español, máximo 6 frases, sin Markdown y sin JSON. "
                    "No pidas email ni ID. No inventes eventos, deportes ni cupos: "
                    "solo los del contexto. "
                    "Si falta un dato, dilo y ofrece el siguiente paso "
                    "(rutina, eventos, adaptaciones o quiz)."
                ),
            },
        ]
        texto = await self.llm.texto_mensajes(mensajes, temperatura=0.75)
        if not texto:
            return None
        return {
            "respuesta": texto,
            "intencion": intencion_hint or "general",
            "adaptada": discapacidad != "general",
            "sugerencias": [],
            "datos": {"contexto_usado": True, "modo": "conversacional"},
            "fuente": "agente",
            "herramientas_usadas": ["catalogo_plataforma"],
            "sintesis_llm": True,
        }

    async def _responder_desconocido(
        self,
        usuario_id: str,
        mensaje: str,
        discapacidad: str,
        clasificacion: dict[str, Any],
        authorization: Optional[str],
        historial: list[dict[str, str]],
    ) -> dict[str, Any]:
        conversacional = await self._responder_conversacional(
            mensaje,
            discapacidad,
            authorization,
            historial,
            intencion_hint=clasificacion.get("mejor_candidato"),
        )
        if conversacional:
            return conversacional

        candidato = clasificacion.get("mejor_candidato")
        if candidato and clasificacion["confianza"] >= UMBRAL_CANDIDATO:
            resultado = await self._responder_conocido(
                usuario_id, candidato, discapacidad, authorization, mensaje
            )
            resultado["respuesta"] = (
                f"Entiendo que tu pregunta va por aquí; si no es esto, dímelo con otras "
                f"palabras.\n\n{resultado['respuesta']}"
            )
            resultado["aproximada"] = True
            return resultado

        adaptada = NO_ENTENDIDO_ADAPTADO.get(discapacidad)
        return {
            "respuesta": adaptada or self._rotar("global", "no_entendido", NO_ENTENDIDO),
            "intencion": "no_entendido",
            "adaptada": bool(adaptada),
            "sugerencias": [
                "Pídeme una rutina indicando tu objetivo",
                "Pregúntame qué eventos hay disponibles",
                "Consúltame las adaptaciones de un deporte",
            ],
            "datos": None,
            "fuente": "motor_local",
            "herramientas_usadas": [],
        }

    async def _sintetizar_como_agente(
        self,
        mensaje: str,
        resultado: dict[str, Any],
        discapacidad: str,
        historial: list[dict[str, str]],
        clasificacion: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Pule respuestas con herramientas para que suenen a chatbot, no a plantilla."""
        if resultado.get("fuente") == "agente":
            return resultado
        if resultado.get("pendiente_write"):
            resultado = dict(resultado)
            resultado["sintesis_llm"] = False
            return resultado
        if not self.llm.disponible:
            resultado = dict(resultado)
            resultado.setdefault("sintesis_llm", False)
            return resultado

        intencion = (resultado.get("intencion") or "").lower()
        if intencion in _SOCIAL:
            resultado = dict(resultado)
            resultado["sintesis_llm"] = False
            return resultado

        # Por defecto pulimos herramientas; las FAQ ya van por _responder_conversacional
        if intencion not in _CON_HERRAMIENTA and not settings.LLM_SINTESIS_INTENIONES_CONOCIDAS:
            if not resultado.get("aproximada"):
                resultado = dict(resultado)
                resultado["sintesis_llm"] = False
                return resultado

        borrador = resultado.get("respuesta") or ""
        datos = resultado.get("datos")
        herramientas = resultado.get("herramientas_usadas") or []
        mensajes = [
            {"role": "system", "content": system_prompt(discapacidad)},
            *historial,
            {
                "role": "user",
                "content": (
                    f"Mensaje del usuario: «{mensaje}»\n"
                    f"Intención detectada: {resultado.get('intencion')}\n"
                    f"Herramientas usadas: {', '.join(herramientas) or 'ninguna'}\n"
                    f"Datos estructurados: {datos}\n\n"
                    f"Borrador del motor local:\n{borrador}\n\n"
                    "Reescribe como chatbot natural de InkluSport: cercano, concreto y "
                    "sin sonar a plantilla repetida. Conserva todos los hechos del borrador "
                    "y de los datos (nombres, fechas, cupos). Máximo 6 frases. "
                    "No inventes nada nuevo."
                ),
            },
        ]
        pulido = await self.llm.texto_mensajes(mensajes, temperatura=0.65)
        if not pulido:
            resultado = dict(resultado)
            resultado["sintesis_llm"] = False
            return resultado

        resultado = dict(resultado)
        resultado["respuesta"] = pulido
        resultado["fuente"] = "agente"
        resultado["borrador_motor"] = borrador
        resultado["sintesis_llm"] = True
        return resultado

    async def _contexto_plataforma(
        self,
        authorization: Optional[str],
        perfil: Optional[dict[str, Any]] = None,
    ) -> str:
        try:
            deportes = await self.sports_service.get_deportes_activos(authorization)
            eventos = await self.sports_service.get_eventos_activos(authorization)
            discapacidades = await self.sports_service.get_discapacidades_activas(authorization)
        except Exception as exc:
            print(f"No se pudo construir el contexto para el LLM: {exc}")
            return "- Catálogo no disponible en este momento."

        lineas = []
        if perfil:
            lineas.append(
                f"- Atleta en sesión: {perfil.get('fullName') or 'Usuario'} "
                f"(discapacidad: {perfil.get('disability') or 'no indicada'})"
            )
        if deportes:
            nombres = ", ".join(str(d.get("name")) for d in deportes[:10])
            lineas.append(f"- Deportes activos: {nombres}")
        if discapacidades:
            nombres = ", ".join(str(d.get("name")) for d in discapacidades[:10])
            lineas.append(f"- Discapacidades contempladas: {nombres}")
        if eventos:
            lineas.append(f"- Eventos publicados: {len(eventos)}")
            for evento in eventos[:5]:
                lineas.append(
                    f"  · {evento.get('name')} ({evento.get('sportName')}) "
                    f"el {evento.get('eventDate')} en {evento.get('location')}"
                )
        return "\n".join(lineas) or "- Catálogo vacío."

    def _rotar(self, usuario_id: str, intencion: str, variantes: list[str]) -> str:
        if not variantes:
            return NO_ENTENDIDO[0]
        clave = (usuario_id, intencion)
        indice = _ROTACION.get(clave, -1) + 1
        _ROTACION[clave] = indice
        return variantes[indice % len(variantes)]

    # -------------------------------------------------------------- enriquecido

    async def _enriquecer(
        self,
        accion: str,
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje: str = "",
        *,
        roles: Optional[list[str]] = None,
        perfil: Optional[dict[str, Any]] = None,
        args: Optional[dict[str, Any]] = None,
    ) -> tuple[str, dict[str, Any]]:
        acciones = {
            "eventos": self._datos_eventos,
            "deportes": self._datos_deportes,
            "discapacidades": self._datos_discapacidades,
            "adaptaciones": self._datos_adaptaciones,
            "rutina": self._datos_rutina,
            "ejercicios": self._datos_ejercicios,
            "quiz": self._datos_quiz,
            "perfil": self._datos_perfil,
            "estadisticas": self._datos_estadisticas,
            "propuesta_evento": self._datos_propuesta_evento,
            "propuesta_deporte": self._datos_propuesta_deporte,
            "propuesta_rutina": self._datos_propuesta_rutina,
        }
        manejador = acciones.get(accion)
        if not manejador:
            return "", {}
        extra = {
            "roles": roles or [],
            "perfil": perfil,
            "args": args or {},
        }
        try:
            if accion in (
                "rutina",
                "ejercicios",
                "perfil",
                "estadisticas",
                "propuesta_evento",
                "propuesta_deporte",
                "propuesta_rutina",
            ):
                return await manejador(
                    usuario_id, discapacidad, authorization, mensaje, **extra
                )
            return await manejador(usuario_id, discapacidad, authorization)
        except TypeError:
            if accion in ("rutina", "ejercicios"):
                return await manejador(usuario_id, discapacidad, authorization, mensaje)
            return await manejador(usuario_id, discapacidad, authorization)
        except Exception as exc:
            print(f"No se pudo enriquecer la respuesta ({accion}): {exc}")
            return "", {}

    async def _datos_eventos(
        self, usuario_id: str, discapacidad: str, authorization: Optional[str]
    ) -> tuple[str, dict[str, Any]]:
        eventos = await self.sports_service.get_eventos_activos(authorization)
        if not eventos:
            return (
                "Ahora mismo no hay eventos publicados en la plataforma. En cuanto un "
                "organizador cree uno, te lo puedo recomendar.",
                {"eventos": [], "total": 0},
            )

        compatibles = []
        for evento in eventos[:12]:
            sport_id = evento.get("sportId")
            adaptaciones = (
                await self.sports_service.get_adaptaciones_deporte(sport_id, authorization)
                if sport_id is not None
                else []
            )
            compatible = any(
                coincide(discapacidad, a.get("disabilityName"))
                for a in adaptaciones
            )
            compatibles.append({
                "id": evento.get("id"),
                "nombre": evento.get("name"),
                "deporte": evento.get("sportName"),
                "fecha": evento.get("eventDate"),
                "hora": evento.get("eventTime"),
                "ubicacion": evento.get("location"),
                "cupos_disponibles": evento.get("availableCapacity"),
                "compatible": compatible,
            })

        ordenados = sorted(compatibles, key=lambda e: (not e["compatible"], str(e["fecha"])))
        seleccion = ordenados[:3]

        lineas = ["Estos son los que mejor encajan contigo:"]
        for evento in seleccion:
            detalle = f"- {evento['nombre']} ({evento['deporte']}) · {evento['fecha']}"
            if evento.get("ubicacion"):
                detalle += f" · {evento['ubicacion']}"
            if evento.get("cupos_disponibles") is not None:
                detalle += f" · {evento['cupos_disponibles']} cupos"
            if evento["compatible"]:
                detalle += " · con adaptaciones para tu perfil"
            lineas.append(detalle)

        return "\n".join(lineas), {
            "eventos": seleccion,
            "total": len(eventos),
            "compatibles": sum(1 for e in compatibles if e["compatible"]),
        }

    async def _datos_deportes(
        self, usuario_id: str, discapacidad: str, authorization: Optional[str]
    ) -> tuple[str, dict[str, Any]]:
        deportes = await self.sports_service.get_deportes_activos(authorization)
        if not deportes:
            return (
                "No pude consultar el catálogo de deportes en este momento.",
                {"deportes": []},
            )

        lineas = ["Deportes disponibles:"]
        resumen = []
        for deporte in deportes[:8]:
            resumen.append({
                "id": deporte.get("id"),
                "nombre": deporte.get("name"),
                "dificultad": deporte.get("difficulty"),
                "material": deporte.get("requiredMaterials"),
            })
            detalle = f"- {deporte.get('name')}"
            if deporte.get("difficulty"):
                detalle += f" · dificultad {deporte.get('difficulty')}"
            if deporte.get("requiredMaterials"):
                detalle += f" · material: {deporte.get('requiredMaterials')}"
            lineas.append(detalle)

        return "\n".join(lineas), {"deportes": resumen}

    async def _datos_discapacidades(
        self, usuario_id: str, discapacidad: str, authorization: Optional[str]
    ) -> tuple[str, dict[str, Any]]:
        catalogo = await self.sports_service.get_discapacidades_activas(authorization)
        if not catalogo:
            return "", {}

        lineas = ["Categorías registradas en la plataforma:"]
        for item in catalogo[:8]:
            detalle = f"- {item.get('name')}"
            if item.get("category"):
                detalle += f" ({item.get('category')})"
            lineas.append(detalle)
        return "\n".join(lineas), {
            "discapacidades": [
                {"id": d.get("id"), "nombre": d.get("name"), "categoria": d.get("category")}
                for d in catalogo[:8]
            ]
        }

    async def _datos_adaptaciones(
        self, usuario_id: str, discapacidad: str, authorization: Optional[str]
    ) -> tuple[str, dict[str, Any]]:
        deportes = await self.sports_service.get_deportes_activos(authorization)
        encontradas = []
        for deporte in deportes[:6]:
            sport_id = deporte.get("id")
            if sport_id is None:
                continue
            for adaptacion in await self.sports_service.get_adaptaciones_deporte(
                sport_id, authorization
            ):
                if discapacidad != "general" and not coincide(
                    discapacidad, adaptacion.get("disabilityName")
                ):
                    continue
                encontradas.append({
                    "deporte": adaptacion.get("sportName") or deporte.get("name"),
                    "discapacidad": adaptacion.get("disabilityName"),
                    "adaptacion": adaptacion.get("adaptations"),
                })

        if not encontradas:
            return (
                f"Aún no hay adaptaciones registradas para {descripcion(discapacidad)} en "
                "los deportes activos. Un entrenador verificado puede registrarlas.",
                {"adaptaciones": []},
            )

        lineas = ["Adaptaciones registradas:"]
        for item in encontradas[:5]:
            lineas.append(f"- {item['deporte']} · {item['discapacidad']}: {item['adaptacion']}")
        return "\n".join(lineas), {"adaptaciones": encontradas[:5]}

    async def _datos_rutina(
        self,
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje: str = "",
        **_kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        catalogo = await obtener_catalogo_ejercicios()
        rutina = generar_rutina(
            discapacidad=discapacidad,
            objetivo_texto=mensaje or "general",
            tipo_texto=mensaje or "",
            duracion_minutos=30,
            catalogo=catalogo,
        )
        lineas = [
            f"Propuesta de hoy · {rutina['objetivo']} "
            f"({rutina['duracion_estimada_minutos']} min aprox.):"
        ]
        for bloque in rutina["bloques"]:
            nombres = ", ".join(e["nombre"] for e in bloque["ejercicios"])
            lineas.append(f"- {bloque['bloque']}: {nombres}")
        if rutina.get("recomendaciones"):
            lineas.append(rutina["recomendaciones"][0])
        lineas.append(
            "Si quieres un plan de varias semanas, pide un plan de entrenamiento."
        )
        return "\n".join(lineas), {
            "rutina_sugerida": {
                "nombre": rutina["nombre"],
                "objetivo": rutina["objetivo"],
                "objetivo_clave": rutina.get("objetivo_clave"),
                "nivel": rutina["nivel"],
                "duracion_estimada_minutos": rutina["duracion_estimada_minutos"],
                "total_ejercicios": rutina["total_ejercicios"],
                "bloques": [
                    {"bloque": b["bloque"], "ejercicios": [e["nombre"] for e in b["ejercicios"]]}
                    for b in rutina["bloques"]
                ],
                "recomendaciones": rutina.get("recomendaciones") or [],
            }
        }

    async def _datos_ejercicios(
        self,
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje: str = "",
        **_kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        catalogo = await obtener_catalogo_ejercicios()
        rutina = generar_rutina(
            discapacidad=discapacidad,
            objetivo_texto=mensaje or "general",
            tipo_texto=mensaje or "",
            duracion_minutos=25,
            catalogo=catalogo,
        )
        seleccion = rutina["ejercicios"][:4]
        lineas = ["Algunos ejercicios adecuados para tu perfil:"]
        for ejercicio in seleccion:
            lineas.append(
                f"- {ejercicio['nombre']}: {ejercicio['series']} series de "
                f"{ejercicio['repeticiones']} · {ejercicio['instrucciones']}"
            )
        return "\n".join(lineas), {"ejercicios": seleccion}

    async def _datos_quiz(
        self, usuario_id: str, discapacidad: str, authorization: Optional[str]
    ) -> tuple[str, dict[str, Any]]:
        texto = (
            f"Tengo {len(BANCOS['ORGANIZADOR'])} preguntas para organizador y "
            f"{len(BANCOS['ENTRENADOR'])} para entrenador, y cada quiz se arma con una "
            "combinación distinta."
        )
        return texto, {
            "preguntas_organizador": len(BANCOS["ORGANIZADOR"]),
            "preguntas_entrenador": len(BANCOS["ENTRENADOR"]),
            "umbral_organizador": 70,
            "umbral_entrenador": 75,
        }

    async def _datos_perfil(
        self,
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje: str = "",
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        perfil = kwargs.get("perfil") or await self.user_service.get_my_profile(authorization)
        if not perfil:
            perfil = await self.user_service.get_user_profile(usuario_id, authorization)
        if not perfil:
            return "No pude leer tu perfil de la sesión. Recarga e inicia sesión de nuevo.", {}
        nombre = perfil.get("fullName") or "Usuario"
        disc = perfil.get("disability") or discapacidad or "no indicada"
        roles = perfil.get("roles") or kwargs.get("roles") or []
        if isinstance(roles, str):
            roles = [r.strip() for r in roles.split(",") if r.strip()]
        lineas = [
            f"Tu perfil en InkluSport, {nombre}:",
            f"- Discapacidad registrada: {disc}",
            f"- Roles: {', '.join(str(r) for r in roles) or 'USUARIO'}",
        ]
        if perfil.get("bio"):
            lineas.append(f"- Bio: {perfil.get('bio')}")
        if perfil.get("supportPreference"):
            lineas.append(f"- Preferencia de apoyo: {perfil.get('supportPreference')}")
        lineas.append("Si quieres cambiar algo, ábrelo desde tu ficha de perfil en la app.")
        return "\n".join(lineas), {
            "usuario_card": {
                "nombre": nombre,
                "discapacidad": disc,
                "roles": [str(r) for r in roles],
            }
        }

    async def _datos_estadisticas(
        self,
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje: str = "",
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        objetivo_id = usuario_id
        perfil = kwargs.get("perfil")
        roles = kwargs.get("roles") or []
        nombre_buscado = (mensaje or "").strip()
        args = kwargs.get("args") or {}
        if args.get("nombre_o_id"):
            nombre_buscado = str(args.get("nombre_o_id")).strip()
        if nombre_buscado and "admin" in self._claves_rol(roles):
            hallados = await self.user_service.search_users(
                nombre=nombre_buscado, authorization=authorization
            )
            if hallados:
                perfil = hallados[0]
                objetivo_id = str(perfil.get("id") or objetivo_id)
            elif len(nombre_buscado) > 8 and " " not in nombre_buscado:
                ajeno = await self.user_service.get_user_profile(nombre_buscado, authorization)
                if ajeno:
                    perfil = ajeno
                    objetivo_id = str(ajeno.get("id") or objetivo_id)
        dash = await self.dashboard.construir(
            usuario_id=objetivo_id,
            authorization=authorization,
            perfil=perfil,
        )
        texto = self.dashboard.resumen_texto(dash)
        return texto, {"vista": dash.get("vista"), "estadisticas": dash.get("vista")}

    def _proximo_sabado(self) -> str:
        hoy = date.today()
        dias = (5 - hoy.weekday()) % 7
        if dias == 0:
            dias = 7
        return (hoy + timedelta(days=dias)).isoformat()

    async def _datos_propuesta_evento(
        self,
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje: str = "",
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        deportes = await self.sports_service.get_deportes_activos(authorization)
        if not deportes:
            return (
                "No hay deportes en el catálogo para armar un evento. "
                "Un entrenador puede dar de alta uno primero.",
                {},
            )
        idea = (mensaje or "").lower()
        elegido = next(
            (d for d in deportes if idea and str(d.get("name") or "").lower() in idea),
            deportes[0],
        )
        fecha = self._proximo_sabado()
        nombre = f"Jornada inclusiva de {elegido.get('name')}"
        args = {
            "sport_id": int(elegido.get("id") or 0),
            "name": nombre,
            "event_date": fecha,
            "event_time": "10:00:00",
            "max_capacity": 24,
            "location": "Por confirmar",
            "description": (
                f"Evento propuesto por el asistente para {elegido.get('name')}. "
                f"Idea original: {mensaje or 'apertura de calendario'}."
            ),
            "created_by": usuario_id,
        }
        pendiente = {
            "tool": "crear_evento",
            "args": args,
            "resumen": resumen_write("crear_evento", args),
        }
        texto = (
            f"Te propongo crear «{nombre}» el {fecha} a las 10:00, "
            f"cupo 24, deporte {elegido.get('name')}. "
            "Si te encaja, responde Confirmo y lo creo en la plataforma."
        )
        return texto, {
            "pendiente_write": pendiente,
            "eventos": [
                {
                    "nombre": nombre,
                    "deporte": elegido.get("name"),
                    "fecha": fecha,
                    "ubicacion": "Por confirmar",
                    "cupos_disponibles": 24,
                }
            ],
        }

    async def _datos_propuesta_deporte(
        self,
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje: str = "",
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        idea = (mensaje or "Deporte inclusivo").strip() or "Deporte inclusivo"
        if len(idea) < 3:
            idea = "Deporte inclusivo"
        nombre = idea[:80]
        args = {
            "name": nombre,
            "description": f"Alta sugerida por el asistente. Contexto: {mensaje or nombre}",
            "difficulty": "intermedio",
            "required_materials": "Material adaptado según el perfil del grupo",
            "is_active": True,
        }
        pendiente = {
            "tool": "crear_deporte",
            "args": args,
            "resumen": resumen_write("crear_deporte", args),
        }
        texto = (
            f"Puedo dar de alta el deporte «{nombre}» (dificultad intermedia) "
            "en el catálogo. Responde Confirmo para crearlo."
        )
        return texto, {
            "pendiente_write": pendiente,
            "deportes": [{"nombre": nombre, "dificultad": "intermedio"}],
        }

    async def _datos_propuesta_rutina(
        self,
        usuario_id: str,
        discapacidad: str,
        authorization: Optional[str],
        mensaje: str = "",
        **kwargs: Any,
    ) -> tuple[str, dict[str, Any]]:
        perfil = kwargs.get("perfil") or {}
        texto_rutina, datos_rutina = await self._datos_rutina(
            usuario_id, discapacidad, authorization, mensaje
        )
        sugerida = (datos_rutina or {}).get("rutina_sugerida") or {}
        ejercicios = sugerida.get("bloques") or []
        payload_ej = []
        for bloque in ejercicios:
            for nom in bloque.get("ejercicios") or []:
                payload_ej.append({"nombre": nom, "bloque": bloque.get("bloque")})
        deportes = await self.sports_service.get_deportes_activos(authorization)
        sport_id = int(deportes[0]["id"]) if deportes and deportes[0].get("id") else None
        args = {
            "name": sugerida.get("nombre") or "Rutina adaptada",
            "description": texto_rutina[:400],
            "disability_focus": perfil.get("disability") or discapacidad,
            "level": sugerida.get("nivel") or "beginner",
            "duration_minutes": sugerida.get("duracion_estimada_minutos") or 30,
            "exercises_json": json.dumps(payload_ej, ensure_ascii=False),
            "max_capacity": 20,
            "trainer_id": usuario_id,
        }
        if sport_id:
            args["sport_id"] = sport_id
        pendiente = {
            "tool": "crear_rutina",
            "args": args,
            "resumen": resumen_write("crear_rutina", args),
        }
        texto = (
            f"{texto_rutina}\n\n"
            "Si quieres, la guardo como rutina de entrenador en la plataforma. "
            "Responde Confirmo para crearla (quedará en borrador hasta que la publiques)."
        )
        return texto, {**datos_rutina, "pendiente_write": pendiente}
