"""Agente de recomendación de eventos.

Puntúa los eventos reales de ink-ms-sports combinando compatibilidad con la
discapacidad del perfil, cercanía de la fecha, disponibilidad de cupos y estado
del evento. El LLM, si está disponible, solo redacta el mensaje de cierre: el
orden y los motivos se calculan con datos, no se inventan.
"""

from datetime import date
from typing import Any, Optional

from app.services.llm_service import LLMService
from app.services.sports_service import SportsService
from app.services.user_service import UserService
from app.nlp.discapacidad import canonizar, coincide, descripcion

ESTADOS_DESCARTADOS = {"cancelled", "finished", "cancelado", "finalizado"}


class RecomendacionAgent:
    def __init__(self):
        self.llm = LLMService()
        self.user_service = UserService()
        self.sports_service = SportsService()

    async def recomendar_eventos(
        self,
        usuario_id: str,
        limite: int = 3,
        authorization: Optional[str] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        perfil = perfil or await self.user_service.get_user_profile(usuario_id, authorization)
        discapacidad_origen = perfil.get("disability") or "general"
        discapacidad = canonizar(discapacidad_origen)
        nombre = perfil.get("fullName") or "Usuario"

        eventos = await self.sports_service.get_eventos(authorization)
        hoy = date.today()
        disponibles = [
            e for e in eventos
            if str(e.get("status", "")).lower() not in ESTADOS_DESCARTADOS
            # Un evento cuya fecha ya pasó no es recomendable por muy compatible
            # que sea; sin esto podía encabezar la lista por su puntaje.
            and (self._dias_hasta(e.get("eventDate"), hoy) or 0) >= 0
        ]

        usuario = {
            "id": perfil.get("id") or usuario_id,
            "fullName": nombre,
            "disability": discapacidad,
            "disability_origen": discapacidad_origen,
        }

        if not disponibles:
            return {
                "recomendaciones": [],
                "mensaje": (
                    "Todavía no hay eventos abiertos en la plataforma. Cuando un "
                    "organizador publique uno, te lo recomendaré según tu perfil."
                    if not eventos
                    else "Los eventos existentes ya pasaron, están cancelados o "
                         "finalizaron. En cuanto se publiquen nuevos, te aviso."
                ),
                "usuario": usuario,
                "total_eventos_disponibles": 0,
                "total_eventos_sistema": len(eventos),
            }

        inscripciones = await self._eventos_inscritos(usuario_id, perfil, authorization)
        candidatos = await self._puntuar_eventos(
            disponibles, discapacidad, inscripciones, authorization
        )

        recomendados = [c for c in candidatos if not c["ya_inscrito"]][:limite]
        if not recomendados:
            return {
                "recomendaciones": [],
                "mensaje": (
                    f"Ya estás inscrito en todos los eventos abiertos, {nombre}. "
                    "Te avisaré cuando se publiquen nuevos."
                ),
                "usuario": usuario,
                "total_eventos_disponibles": len(disponibles),
                "ya_inscrito_en": len(inscripciones),
            }

        compatibles = sum(1 for c in candidatos if c["compatible_discapacidad"])
        return {
            "recomendaciones": recomendados,
            "mensaje": await self._mensaje_cierre(
                nombre, discapacidad, recomendados, compatibles, len(disponibles)
            ),
            "usuario": usuario,
            "total_eventos_disponibles": len(disponibles),
            "total_eventos_sistema": len(eventos),
            "eventos_compatibles": compatibles,
            "criterio": (
                "compatibilidad con la discapacidad del perfil, cercanía de la fecha, "
                "cupos disponibles y estado del evento"
            ),
        }

    # ------------------------------------------------------------------ interno

    async def _eventos_inscritos(
        self, usuario_id: str, perfil: dict, authorization: Optional[str]
    ) -> set[str]:
        """Identificadores de eventos en los que el usuario ya está inscrito.

        Se consulta también por email porque las inscripciones se registran con
        el identificador del token, que puede ser el correo.
        """
        claves = {usuario_id}
        if perfil.get("email"):
            claves.add(perfil["email"])
        if perfil.get("id"):
            claves.add(str(perfil["id"]))

        inscritos: set[str] = set()
        for clave in claves:
            registros = await self.sports_service.get_eventos_usuario(clave, authorization)
            for registro in registros:
                identificador = registro.get("eventId")
                if identificador:
                    inscritos.add(str(identificador))
        return inscritos

    async def _puntuar_eventos(
        self,
        eventos: list[dict],
        discapacidad: str,
        inscripciones: set[str],
        authorization: Optional[str],
    ) -> list[dict[str, Any]]:
        adaptaciones_cache: dict[Any, list[dict]] = {}
        hoy = date.today()
        candidatos = []

        for evento in eventos:
            sport_id = evento.get("sportId")
            if sport_id not in adaptaciones_cache:
                adaptaciones_cache[sport_id] = (
                    await self.sports_service.get_adaptaciones_deporte(sport_id, authorization)
                    if sport_id is not None
                    else []
                )
            adaptaciones = adaptaciones_cache[sport_id]

            relevantes = [
                {"discapacidad": a.get("disabilityName"), "adaptacion": a.get("adaptations")}
                for a in adaptaciones
                if coincide(discapacidad, a.get("disabilityName"))
            ]
            compatible = bool(relevantes) and discapacidad != "general"

            puntaje = 0.0
            motivos = []

            if compatible:
                puntaje += 50
                motivos.append(
                    f"El deporte tiene adaptaciones registradas para {descripcion(discapacidad)}"
                )
            elif discapacidad == "general":
                puntaje += 20
                motivos.append("Evento abierto y compatible con tu perfil")
            else:
                motivos.append(
                    "Sin adaptaciones registradas para tu discapacidad; consulta con el organizador"
                )

            dias = self._dias_hasta(evento.get("eventDate"), hoy)
            if dias is not None:
                if dias < 0:
                    puntaje -= 10
                else:
                    puntaje += max(0.0, 20 - dias * 0.2)
                    if dias <= 14:
                        motivos.append(f"Se celebra pronto, en {dias} día(s)")

            cupos = evento.get("availableCapacity")
            maximo = evento.get("maxCapacity")
            if isinstance(cupos, int) and cupos > 0:
                puntaje += 10 if not maximo else 10 * min(1.0, cupos / max(1, maximo))
                motivos.append(f"Quedan {cupos} cupos disponibles")
            elif cupos == 0:
                puntaje -= 15
                motivos.append("Sin cupos: la inscripción entraría en lista de espera")

            if str(evento.get("status", "")).lower() in ("active", "activo"):
                puntaje += 5

            identificador = str(evento.get("id")) if evento.get("id") else None
            candidatos.append({
                "evento_id": identificador,
                "evento": evento.get("name") or "Evento",
                "deporte": evento.get("sportName"),
                "sportId": sport_id,
                "descripcion": evento.get("description"),
                "fecha": evento.get("eventDate"),
                "hora": evento.get("eventTime"),
                "ubicacion": evento.get("location"),
                "cupos_disponibles": cupos,
                "cupos_totales": maximo,
                "estado": evento.get("status"),
                "compatible_discapacidad": compatible,
                "adaptaciones": relevantes,
                "razon": ". ".join(motivos) + ".",
                "puntaje": round(puntaje, 2),
                "ya_inscrito": identificador in inscripciones if identificador else False,
            })

        candidatos.sort(key=lambda c: c["puntaje"], reverse=True)
        return candidatos

    @staticmethod
    def _dias_hasta(fecha_evento: Any, hoy: date) -> Optional[int]:
        if not fecha_evento:
            return None
        try:
            objetivo = date.fromisoformat(str(fecha_evento)[:10])
        except ValueError:
            return None
        return (objetivo - hoy).days

    async def _mensaje_cierre(
        self,
        nombre: str,
        discapacidad: str,
        recomendados: list[dict],
        compatibles: int,
        total: int,
    ) -> str:
        base = (
            f"{nombre}, encontré {len(recomendados)} evento(s) recomendables de "
            f"{total} disponibles"
        )
        base += (
            f", y {compatibles} tienen adaptaciones registradas para tu perfil."
            if compatibles
            else ". Ninguno tiene todavía adaptaciones registradas para tu discapacidad."
        )

        if not self.llm.disponible:
            return base

        listado = "; ".join(
            f"{r['evento']} ({r['deporte']}, {r['fecha']})" for r in recomendados
        )
        prompt = (
            f"Redacta en 2 frases un mensaje para {nombre}, con {descripcion(discapacidad)}, "
            f"presentando estos eventos ya seleccionados: {listado}. No añadas eventos que "
            "no estén en la lista ni cambies sus datos."
        )
        return await self.llm.texto(prompt, discapacidad) or base
