"""Agente conversacional del asistente.

Flujo: se clasifica la intención del mensaje con el motor local, se redacta la
respuesta desde la base de conocimiento y, cuando la intención lo requiere, se
enriquece con datos reales de ink-ms-sports (eventos, deportes, adaptaciones) o
con el motor de rutinas. El LLM solo entra en juego para mensajes que el motor
local no sabe clasificar, y su ausencia nunca deja al usuario sin respuesta útil.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from app.data.conocimiento import NO_ENTENDIDO, NO_ENTENDIDO_ADAPTADO
from app.data.quiz_banco import BANCOS
from app.database.mongodb import get_db
from app.database.repositorio import COL_CONVERSACIONES, obtener_catalogo_ejercicios, obtener_conocimiento
from app.motor.rutinas import generar_rutina
from app.nlp.discapacidad import canonizar, coincide, descripcion
from app.nlp.intenciones import clasificar
from app.services.llm_service import LLMService
from app.services.sports_service import SportsService
from app.services.user_service import UserService

# Rotación de redacciones por usuario e intención, para no repetir la misma
# frase en mensajes consecutivos.
_ROTACION: dict[tuple[str, str], int] = {}

# Por debajo del umbral de clasificación pero suficiente para responder sobre el
# tema en lugar de admitir que no se entendió nada.
UMBRAL_CANDIDATO = 0.18


class ChatbotAgent:
    def __init__(self):
        self.llm = LLMService()
        self.sports_service = SportsService()
        self.user_service = UserService()

    # ------------------------------------------------------------------ público

    async def procesar_mensaje(
        self,
        usuario_id: str,
        mensaje: str,
        discapacidad: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        clave_discapacidad = canonizar(discapacidad)
        clasificacion = clasificar(mensaje)
        intencion = clasificacion["nombre"]

        if intencion:
            resultado = await self._responder_conocido(
                usuario_id, intencion, clave_discapacidad, authorization
            )
        else:
            resultado = await self._responder_desconocido(
                usuario_id, mensaje, clave_discapacidad, clasificacion, authorization
            )

        resultado["intencion"] = resultado.get("intencion") or intencion or "no_entendido"
        resultado["confianza"] = clasificacion["confianza"]
        resultado["terminos_detectados"] = clasificacion["terminos"]

        await self._guardar_conversacion(usuario_id, mensaje, resultado)
        return resultado

    # ---------------------------------------------------------------- redacción

    async def _responder_conocido(
        self, usuario_id: str, intencion: str, discapacidad: str, authorization: Optional[str]
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
                accion, usuario_id, discapacidad, authorization
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
        }

    async def _responder_desconocido(
        self,
        usuario_id: str,
        mensaje: str,
        discapacidad: str,
        clasificacion: dict[str, Any],
        authorization: Optional[str],
    ) -> dict[str, Any]:
        """Responde lo que el motor local no supo clasificar.

        Se intenta en tres niveles: el LLM con el catálogo real como contexto, la
        mejor intención candidata aunque no llegara al umbral, y por último el
        mensaje de no entendido.
        """
        contexto = await self._contexto_plataforma(authorization)
        prompt = (
            f"El usuario del asistente de InkluSport pregunta: «{mensaje}»\n\n"
            f"Datos reales de la plataforma ahora mismo:\n{contexto}\n\n"
            "Responde en un máximo de 4 frases. Si la pregunta es sobre deporte, "
            "entrenamiento, salud, eventos o accesibilidad, respóndela apoyándote en "
            "esos datos reales y no inventes eventos ni deportes que no estén en la "
            "lista. Si es una pregunta general ajena a la plataforma, contéstala igual "
            "de forma breve y correcta, y después ofrece ayuda con entrenamiento o "
            "eventos. No dejes nunca al usuario sin respuesta."
        )
        texto = await self.llm.texto(prompt, discapacidad)
        if texto:
            return {
                "respuesta": texto,
                "intencion": "general",
                "adaptada": discapacidad != "general",
                "sugerencias": [
                    "¿Quieres que te prepare una rutina adaptada?",
                    "Puedo mostrarte los eventos compatibles con tu perfil",
                ],
                "datos": {"contexto_usado": True},
                "fuente": "llm",
            }

        # Sin LLM: si el clasificador tenía un candidato razonable, es mejor
        # responder sobre ese tema que decir que no se ha entendido nada.
        candidato = clasificacion.get("mejor_candidato")
        if candidato and clasificacion["confianza"] >= UMBRAL_CANDIDATO:
            resultado = await self._responder_conocido(
                usuario_id, candidato, discapacidad, authorization
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
        }

    async def _contexto_plataforma(self, authorization: Optional[str]) -> str:
        """Resumen corto del catálogo real, para que el LLM no invente datos."""
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
        self, accion: str, usuario_id: str, discapacidad: str, authorization: Optional[str]
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
        self, usuario_id: str, discapacidad: str, authorization: Optional[str]
    ) -> tuple[str, dict[str, Any]]:
        catalogo = await obtener_catalogo_ejercicios()
        rutina = generar_rutina(
            discapacidad=discapacidad,
            objetivo_texto="general",
            duracion_minutos=30,
            catalogo=catalogo,
        )
        lineas = [f"Propuesta de hoy ({rutina['duracion_estimada_minutos']} min aprox.):"]
        for bloque in rutina["bloques"]:
            nombres = ", ".join(e["nombre"] for e in bloque["ejercicios"])
            lineas.append(f"- {bloque['bloque']}: {nombres}")
        lineas.append(
            "Dime tu objetivo (fuerza, resistencia, movilidad o equilibrio) y te la ajusto."
        )
        return "\n".join(lineas), {
            "rutina_sugerida": {
                "nombre": rutina["nombre"],
                "duracion_estimada_minutos": rutina["duracion_estimada_minutos"],
                "bloques": [
                    {"bloque": b["bloque"], "ejercicios": [e["nombre"] for e in b["ejercicios"]]}
                    for b in rutina["bloques"]
                ],
            }
        }

    async def _datos_ejercicios(
        self, usuario_id: str, discapacidad: str, authorization: Optional[str]
    ) -> tuple[str, dict[str, Any]]:
        catalogo = await obtener_catalogo_ejercicios()
        rutina = generar_rutina(
            discapacidad=discapacidad, objetivo_texto="general", duracion_minutos=25,
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

    # ------------------------------------------------------------ persistencia

    async def _guardar_conversacion(
        self, usuario_id: str, mensaje: str, resultado: dict[str, Any]
    ) -> None:
        db = get_db()
        if db is None:
            return
        ahora = datetime.now(timezone.utc)
        try:
            await db[COL_CONVERSACIONES].update_one(
                {"usuario_id": usuario_id, "estado": "activa"},
                {
                    "$push": {"mensajes": {"$each": [
                        {"mensaje": mensaje, "remitente": "usuario", "fecha": ahora},
                        {
                            "mensaje": resultado["respuesta"],
                            "remitente": "asistente",
                            "intencion": resultado["intencion"],
                            "fuente": resultado.get("fuente"),
                            "fecha": ahora,
                        },
                    ]}},
                    "$set": {"ultima_interaccion": ahora},
                    "$setOnInsert": {"creada_en": ahora},
                },
                upsert=True,
            )
        except Exception as exc:
            print(f"Error guardando conversación: {exc}")
