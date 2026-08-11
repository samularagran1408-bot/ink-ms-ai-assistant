"""Agente conversacional profesional de InkluSport.

Orquesta: clasificación local → (opcional) tool-calling LLM → herramientas
locales (eventos, rutinas…) → síntesis. Sin LLM o sin soporte de tools, el
motor local responde completo.

El historial se persiste con cupos anti-basura (ver ConversacionService): el
usuario puede recuperarlo por API; al LLM solo llegan resumen + últimos turnos.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator, Optional

from app.config import settings
from app.data.conocimiento import NO_ENTENDIDO, NO_ENTENDIDO_ADAPTADO
from app.data.quiz_banco import BANCOS
from app.database.repositorio import obtener_catalogo_ejercicios, obtener_conocimiento
from app.motor.rutinas import generar_rutina
from app.nlp.discapacidad import canonizar, coincide, descripcion
from app.nlp.intenciones import clasificar
from app.services.conversacion_service import ConversacionService
from app.services.llm_service import LLMService, _limpiar, system_prompt
from app.services.sports_service import SportsService
from app.services.user_service import UserService
from app.tools.registry import (
    TOOL_DEFINITIONS,
    accion_de_tool,
    mensaje_tool_para_objetivo,
)

_ROTACION: dict[tuple[str, str], int] = {}
UMBRAL_CANDIDATO = 0.18
# Cortesía: respuesta local corta basta
_SOCIAL = frozenset({"saludo", "despedida", "agradecimiento"})
# Intenciones que disparan herramientas con datos reales
_CON_HERRAMIENTA = frozenset({
    "rutinas", "ejercicios", "eventos", "inscripcion", "deportes",
    "discapacidades", "adaptaciones", "quiz",
})

_SISTEMA_TOOLS = (
    "Puedes usar herramientas para obtener datos reales de InkluSport "
    "(eventos, deportes, adaptaciones, rutinas, ejercicios, quiz). "
    "Si la pregunta necesita datos de plataforma, llama a la herramienta "
    "adecuada antes de responder. No inventes nombres, fechas ni cupos. "
    "Cuando ya tengas los datos, responde en español, máximo 6 frases, "
    "sin Markdown."
)


class ChatbotAgent:
    def __init__(self):
        self.llm = LLMService()
        self.sports_service = SportsService()
        self.user_service = UserService()
        self.conversaciones = ConversacionService()

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
        eventos: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Decide tool-calling / motor local / LLM conversacional."""
        intencion = clasificacion["nombre"]

        # 1) Social → plantillas locales (rápido, sin tokens)
        if intencion in _SOCIAL:
            return await self._responder_conocido(
                usuario_id, intencion, clave_discapacidad, authorization, mensaje
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
                usuario_id, intencion, clave_discapacidad, authorization, mensaje
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
                usuario_id, intencion, clave_discapacidad, authorization, mensaje
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
        )
        if conversacional:
            conversacional["sugerencias"] = conversacional.get("sugerencias") or sugerencias
            return conversacional

        # 5) Sin LLM: plantilla / aproximación / no_entendido
        if intencion:
            return await self._responder_conocido(
                usuario_id, intencion, clave_discapacidad, authorization, mensaje
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
    ) -> dict[str, Any]:
        historial, cid_efectiva, resumen = await self.conversaciones.cargar_contexto_llm(
            usuario_id, conversacion_id or ""
        )
        # Sin id del cliente: continúa la última activa; si no hay, crea una nueva.
        conversacion_id = conversacion_id or cid_efectiva or str(uuid.uuid4())
        clave_discapacidad = canonizar(discapacidad)
        historial_llm = self.conversaciones.mensajes_para_llm(historial, resumen)

        clasificacion = clasificar(mensaje)
        intencion = clasificacion["nombre"]

        resultado = await self._resolver_turno(
            usuario_id,
            mensaje,
            clave_discapacidad,
            authorization,
            historial_llm,
            clasificacion,
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
    ) -> AsyncIterator[dict[str, Any]]:
        """Emite fases del agente (SSE) y cierra con la respuesta final."""
        yield {"evento": "estado", "detalle": "analizando_intencion"}
        historial, cid_efectiva, resumen = await self.conversaciones.cargar_contexto_llm(
            usuario_id, conversacion_id or ""
        )
        conversacion_id = conversacion_id or cid_efectiva or str(uuid.uuid4())
        clave_discapacidad = canonizar(discapacidad)
        historial_llm = self.conversaciones.mensajes_para_llm(historial, resumen)

        clasificacion = clasificar(mensaje)
        intencion = clasificacion["nombre"]

        if settings.LLM_TOOL_CALLING_ENABLED and self.llm.disponible and intencion not in _SOCIAL:
            yield {"evento": "estado", "detalle": "agente_con_tools"}
        elif intencion in _CON_HERRAMIENTA:
            yield {"evento": "herramienta", "detalle": intencion, "estado": "ejecutando"}
        elif self.llm.disponible and intencion not in _SOCIAL:
            yield {"evento": "estado", "detalle": "redactando_respuesta"}
        else:
            yield {"evento": "estado", "detalle": "consultando_conocimiento"}

        eventos_side: list[dict[str, Any]] = []
        resultado = await self._resolver_turno(
            usuario_id,
            mensaje,
            clave_discapacidad,
            authorization,
            historial_llm,
            clasificacion,
            eventos=eventos_side,
        )
        for ev in eventos_side:
            yield ev

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
        eventos: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[dict[str, Any]]:
        """Loop LLM ↔ tools. Devuelve None para caer al motor local."""
        if not self.llm.disponible:
            return None

        hint = (
            f" Intención probable del clasificador local: {intencion_hint}."
            if intencion_hint
            else ""
        )
        mensajes: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(discapacidad, _SISTEMA_TOOLS)},
            *historial,
            {
                "role": "user",
                "content": (
                    f"Mensaje del usuario: «{mensaje}».{hint} "
                    "Usa herramientas si necesitas datos reales de la plataforma."
                ),
            },
        ]

        herramientas_usadas: list[str] = []
        datos_acumulados: dict[str, Any] = {"modo": "tool_calling", "rondas": []}
        max_rondas = max(1, settings.LLM_TOOL_MAX_RONDAS)

        try:
            for ronda in range(max_rondas):
                resultado_llm = await self.llm.completar(
                    mensajes,
                    temperatura=0.4,
                    tools=TOOL_DEFINITIONS,
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

                        if eventos is not None:
                            eventos.append(
                                {
                                    "evento": "herramienta",
                                    "detalle": nombre,
                                    "estado": "ejecutando",
                                    "ronda": ronda + 1,
                                }
                            )

                        texto, datos = await self._ejecutar_tool(
                            nombre,
                            args,
                            usuario_id,
                            discapacidad,
                            authorization,
                            mensaje,
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
    ) -> tuple[str, dict[str, Any]]:
        accion = accion_de_tool(nombre)
        if not accion:
            return f"Herramienta desconocida: {nombre}", {"error": "tool_desconocida"}
        mensaje = mensaje_tool_para_objetivo(nombre, args, mensaje_usuario)
        return await self._enriquecer(
            accion, usuario_id, discapacidad, authorization, mensaje
        )

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
                        "Responde en español, máximo 6 frases, sin inventar datos."
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
    ) -> dict[str, Any]:
        conocimiento = await obtener_conocimiento(intencion) or {}
        adaptaciones = conocimiento.get("adaptaciones") or {}
        especifica = adaptaciones.get(discapacidad)

        if especifica:
            texto = especifica
        else:
            variantes = conocimiento.get("respuestas") or []
            texto = self._rotar(usuario_id, intencion, variantes)

        datos: dict[str, Any] = {}
        accion = conocimiento.get("accion")
        if accion:
            complemento, datos = await self._enriquecer(
                accion, usuario_id, discapacidad, authorization, mensaje
            )
            if complemento:
                texto = f"{texto}\n\n{complemento}"

        return {
            "respuesta": texto,
            "intencion": intencion,
            "adaptada": bool(especifica),
            "sugerencias": conocimiento.get("sugerencias") or [],
            "datos": datos or None,
            "fuente": "motor_local",
            "herramientas_usadas": [accion] if accion else [],
        }

    async def _responder_conversacional(
        self,
        mensaje: str,
        discapacidad: str,
        authorization: Optional[str],
        historial: list[dict[str, str]],
        *,
        borrador: Optional[str] = None,
        intencion_hint: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Chat normal con LLM: responde casi cualquier pregunta con contexto real."""
        if not self.llm.disponible:
            return None

        contexto = await self._contexto_plataforma(authorization)
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
                    f"Datos reales de InkluSport ahora mismo:\n{contexto}"
                    f"{pista}\n\n"
                    "Responde en español, máximo 6 frases, sin Markdown. "
                    "No digas que no entiendes si puedes dar una respuesta razonable. "
                    "No inventes eventos, deportes ni cupos: solo los del contexto. "
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

    async def _contexto_plataforma(self, authorization: Optional[str]) -> str:
        try:
            deportes = await self.sports_service.get_deportes_activos(authorization)
            eventos = await self.sports_service.get_eventos_activos(authorization)
            discapacidades = await self.sports_service.get_discapacidades_activas(authorization)
        except Exception as exc:
            print(f"No se pudo construir el contexto para el LLM: {exc}")
            return "- Catálogo no disponible en este momento."

        lineas = []
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
    ) -> tuple[str, dict[str, Any]]:
        acciones = {
            "eventos": self._datos_eventos,
            "deportes": self._datos_deportes,
            "discapacidades": self._datos_discapacidades,
            "adaptaciones": self._datos_adaptaciones,
            "rutina": self._datos_rutina,
            "ejercicios": self._datos_ejercicios,
            "quiz": self._datos_quiz,
        }
        manejador = acciones.get(accion)
        if not manejador:
            return "", {}
        try:
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
