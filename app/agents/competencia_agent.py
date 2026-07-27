import json
from datetime import date, datetime

from app.nlp.discapacidad import canonizar, coincide, descripcion
from app.nlp.texto import normalizar
from app.services.llm_service import LLMService
from app.services.sports_service import SportsService
from app.services.user_service import UserService


def _fecha(valor) -> date | None:
    """Interpreta la fecha de un evento, que sports entrega como ISO o lista."""
    if isinstance(valor, str):
        try:
            return datetime.fromisoformat(valor[:10]).date()
        except ValueError:
            return None
    if isinstance(valor, (list, tuple)) and len(valor) >= 3:
        try:
            return date(int(valor[0]), int(valor[1]), int(valor[2]))
        except (TypeError, ValueError):
            return None
    return None


class CompetenciaAgent:
    """
    Analiza el contexto competitivo del usuario.
    En `eventos` solo incluye eventos cuyo deporte tiene adaptación
    a la discapacidad del perfil (sport-disabilities / catálogo sports).
    """

    def __init__(self):
        self.llm = LLMService()
        self.user_service = UserService()
        self.sports_service = SportsService()

    def _normalizar(self, texto: str) -> str:
        return normalizar(texto)

    def _discapacidad_coincide(self, discapacidad_usuario: str, *candidatos: str) -> bool:
        return coincide(discapacidad_usuario, *candidatos)

    async def _sport_ids_compatibles(self, discapacidad: str) -> tuple[set, dict, list]:
        """
        Devuelve sportIds compatibles con la discapacidad, mapa de adaptaciones y
        el catálogo completo de deportes activos.
        Usa GET /api/sports/active (disabilities anidadas) y /api/sport-disabilities/sport/{id}.
        """
        deportes = await self.sports_service.get_deportes_activos()
        compatibles: set = set()
        adaptaciones_por_sport: dict = {}

        for deporte in deportes:
            sid = deporte.get("id")
            if sid is None:
                continue

            disabilities = deporte.get("disabilities") or []
            match = any(
                self._discapacidad_coincide(
                    discapacidad,
                    d.get("name", ""),
                    d.get("category", ""),
                    d.get("description", ""),
                )
                for d in disabilities
                if isinstance(d, dict)
            )

            ads = await self.sports_service.get_adaptaciones_deporte(sid)
            ads_match = [
                a for a in ads
                if self._discapacidad_coincide(
                    discapacidad,
                    a.get("disabilityName", ""),
                    a.get("adaptations", ""),
                )
            ]
            if ads_match:
                match = True
                adaptaciones_por_sport[sid] = ads_match
            elif match:
                adaptaciones_por_sport[sid] = [
                    {
                        "disabilityName": d.get("name"),
                        "adaptations": d.get("description"),
                    }
                    for d in disabilities
                    if self._discapacidad_coincide(
                        discapacidad, d.get("name", ""), d.get("category", "")
                    )
                ]

            if match:
                compatibles.add(sid)

        return compatibles, adaptaciones_por_sport, deportes

    def _analisis_heuristico(
        self,
        discapacidad: str,
        deportes_compatibles: list,
        deportes_sin_adaptacion: list,
        estadisticas: dict,
        futuros: list,
        con_cupo: list,
        proximo: dict | None,
        inscritos: list,
        perfil: dict,
    ) -> dict[str, list[str]]:
        """Lectura del panorama competitivo a partir de los datos de users y sports.

        Es la que se usa cuando no hay LLM disponible, así que tiene que sostenerse
        por sí sola: cita deportes, eventos y cifras concretas en vez de generalidades.
        """
        etiqueta = descripcion(canonizar(discapacidad))
        ventajas: list[str] = []
        desventajas: list[str] = []
        recomendaciones: list[str] = []

        if deportes_compatibles:
            ventajas.append(
                f"Tienes {len(deportes_compatibles)} deporte(s) con adaptaciones registradas "
                f"para {etiqueta}: {', '.join(deportes_compatibles)}."
            )
        if estadisticas["eventos_futuros_con_cupo"]:
            ventajas.append(
                f"Quedan {estadisticas['eventos_futuros_con_cupo']} evento(s) futuros con cupo "
                f"libre y {estadisticas['cupos_disponibles']} plazas disponibles en total."
            )
        if proximo:
            ventajas.append(
                f"El más cercano es '{proximo['nombre']}' ({proximo.get('deporte')}) "
                f"el {proximo.get('fecha')} en {proximo.get('ubicacion')}."
            )
        if estadisticas["ocupacion_media_pct"] < 50 and estadisticas["cupos_totales"]:
            ventajas.append(
                f"La ocupación media es del {estadisticas['ocupacion_media_pct']}%, así que "
                "hay poca competencia por plaza y puedes elegir evento con calma."
            )
        if estadisticas["asistencias"]:
            ventajas.append(
                f"Ya acumulas {estadisticas['asistencias']} asistencia(s), que cuentan para "
                "la verificación como organizador."
            )

        if not deportes_compatibles:
            desventajas.append(
                f"Ningún deporte del catálogo tiene adaptaciones registradas para {etiqueta}, "
                "así que no puedo filtrar eventos por tu perfil. Un entrenador verificado "
                "debe registrarlas en el catálogo de adaptaciones deporte-discapacidad."
            )
        if deportes_sin_adaptacion:
            desventajas.append(
                f"Quedan fuera de tu alcance {len(deportes_sin_adaptacion)} deporte(s) sin "
                f"adaptación para tu perfil: {', '.join(deportes_sin_adaptacion)}."
            )
        if estadisticas["eventos_sin_adaptacion_para_el_perfil"]:
            desventajas.append(
                f"{estadisticas['eventos_sin_adaptacion_para_el_perfil']} de los "
                f"{estadisticas['eventos_en_sistema']} eventos publicados no son compatibles "
                "con tu discapacidad."
            )
        if not inscritos:
            desventajas.append(
                "No estás inscrito en ningún evento todavía, así que no tienes asistencias "
                "que acrediten experiencia en la plataforma."
            )
        if futuros and not con_cupo:
            desventajas.append(
                "Todos los eventos compatibles que quedan están sin cupo: tendrías que "
                "entrar en lista de espera."
            )
        if estadisticas["lista_espera"]:
            desventajas.append(
                f"Tienes {estadisticas['lista_espera']} inscripción(es) en lista de espera, "
                "que no garantizan plaza."
            )
        if not perfil.get("disability"):
            desventajas.append(
                "Tu perfil no tiene discapacidad registrada, así que el análisis usa el "
                "catálogo completo en lugar de filtrarlo para ti."
            )

        if proximo:
            recomendaciones.append(
                f"Inscríbete en '{proximo['nombre']}' antes del {proximo.get('fecha')}: "
                f"quedan {proximo.get('availableCapacity')} cupos."
            )
            if proximo.get("adaptaciones"):
                primera = proximo["adaptaciones"][0]
                recomendaciones.append(
                    f"Para ese evento el deporte tiene registrada esta adaptación: "
                    f"{primera.get('adaptacion')}."
                )
        if len(deportes_compatibles) > 1:
            recomendaciones.append(
                f"Prueba más de una disciplina: {' y '.join(deportes_compatibles[:2])} "
                "trabajan capacidades distintas y amplían tu calendario."
            )
        if not estadisticas["eventos_creados"] and estadisticas["asistencias"] >= 1:
            recomendaciones.append(
                "Ya tienes asistencias: el siguiente paso natural es el quiz de organizador "
                "para poder crear tus propios eventos."
            )
        if not deportes_compatibles:
            recomendaciones.append(
                "Pide a un entrenador verificado que registre las adaptaciones de tu "
                "discapacidad y después publica eventos con esos deportes."
            )
        recomendaciones.append(
            f"Pídeme una rutina adaptada al deporte del evento que elijas para llegar "
            f"preparado; la ajusto a {etiqueta}."
        )

        return {
            "ventajas": ventajas or [f"Perfil con {etiqueta} registrado en la plataforma."],
            "desventajas": desventajas or ["No se detectan barreras relevantes ahora mismo."],
            "recomendaciones": recomendaciones,
        }

    async def analizar_rendimiento(self, usuario_id: str):
        user_data = await self.user_service.get_user_profile(usuario_id)
        discapacidad = user_data.get("disability") or "general"
        nombre = user_data.get("fullName") or "Usuario"
        email = user_data.get("email")

        eventos_sistema = await self.sports_service.get_eventos()
        sport_ids_ok, adaptaciones_por_sport, deportes = await self._sport_ids_compatibles(
            discapacidad
        )
        nombres_deporte = {d.get("id"): d.get("name") for d in deportes}

        # Filtrar: evento → deporte → discapacidad del usuario
        eventos_filtrados = [
            e for e in eventos_sistema
            if e.get("sportId") in sport_ids_ok
        ]
        # Si no hay cruce discapacidad-deporte, no inventar: lista vacía con explicación
        # (salvo discapacidad general, donde sport_ids_ok puede incluir todos vía _discapacidad_coincide True)
        if self._normalizar(discapacidad) in ("general", "ninguna", "n/a", ""):
            eventos_filtrados = eventos_sistema

        eventos_activos = [
            e for e in eventos_filtrados
            if str(e.get("status", "")).lower() not in ("cancelled", "finished", "cancelado", "finalizado")
        ]

        inscritos = await self.sports_service.get_eventos_usuario(usuario_id)
        if email and email != usuario_id:
            extra = await self.sports_service.get_eventos_usuario(email)
            vistos = {e.get("eventId") or e.get("id") for e in inscritos}
            for e in extra:
                key = e.get("eventId") or e.get("id")
                if key not in vistos:
                    inscritos.append(e)

        inscritos_por_evento = {
            (e.get("eventId") or e.get("id")): e
            for e in inscritos
            if (e.get("eventId") or e.get("id"))
        }

        asistidos_insc = sum(1 for e in inscritos if e.get("attended") is True)
        en_espera = sum(1 for e in inscritos if e.get("waitlistPosition") is not None)
        confirmados = max(0, len(inscritos) - en_espera)

        events_attended_perfil = int(user_data.get("eventsAttended") or 0)
        events_created_perfil = int(user_data.get("eventsCreated") or 0)

        cupos_disponibles = sum(int(e.get("availableCapacity") or 0) for e in eventos_filtrados)
        cupos_totales = sum(int(e.get("maxCapacity") or 0) for e in eventos_filtrados)

        resumen_eventos = []
        for e in eventos_filtrados:
            eid = e.get("id")
            sid = e.get("sportId")
            reg = inscritos_por_evento.get(eid) if eid else None
            ads = adaptaciones_por_sport.get(sid) or []
            resumen_eventos.append({
                "id": eid,
                "nombre": e.get("name") or "Evento",
                "deporte": e.get("sportName"),
                "sportId": sid,
                "fecha": e.get("eventDate"),
                "hora": e.get("eventTime"),
                "ubicacion": e.get("location"),
                "status": e.get("status"),
                "maxCapacity": e.get("maxCapacity"),
                "availableCapacity": e.get("availableCapacity"),
                "descripcion": e.get("description"),
                "compatible_discapacidad": True,
                "adaptaciones": [
                    {
                        "discapacidad": a.get("disabilityName"),
                        "adaptacion": a.get("adaptations"),
                    }
                    for a in ads
                ],
                "usuario_inscrito": reg is not None,
                "asistio": (reg or {}).get("attended"),
                "lista_espera": (reg or {}).get("waitlistPosition"),
            })

        hoy = date.today()
        futuros = sorted(
            (e for e in resumen_eventos if (_fecha(e["fecha"]) or hoy) >= hoy),
            key=lambda e: _fecha(e["fecha"]) or hoy,
        )
        con_cupo = [e for e in futuros if (e.get("availableCapacity") or 0) > 0]
        proximo = con_cupo[0] if con_cupo else (futuros[0] if futuros else None)

        deportes_compatibles = sorted(
            {nombres_deporte.get(sid) for sid in sport_ids_ok if nombres_deporte.get(sid)}
        )
        deportes_sin_adaptacion = sorted(
            {
                d.get("name")
                for d in deportes
                if d.get("id") not in sport_ids_ok and d.get("name")
            }
        )

        estadisticas = {
            "eventos_en_sistema": len(eventos_sistema),
            "eventos_compatibles_discapacidad": len(eventos_filtrados),
            "eventos_sin_adaptacion_para_el_perfil": len(eventos_sistema) - len(eventos_filtrados),
            "eventos_activos_o_disponibles": len(eventos_activos),
            "eventos_futuros_compatibles": len(futuros),
            "eventos_futuros_con_cupo": len(con_cupo),
            "deportes_en_catalogo": len(deportes),
            "deportes_compatibles": len(sport_ids_ok),
            "cupos_totales": cupos_totales,
            "cupos_disponibles": cupos_disponibles,
            "ocupacion_media_pct": (
                round(100 * (cupos_totales - cupos_disponibles) / cupos_totales, 1)
                if cupos_totales
                else 0.0
            ),
            "inscripciones_usuario": len(inscritos),
            "confirmados": confirmados,
            "lista_espera": en_espera,
            "asistencias": max(asistidos_insc, events_attended_perfil),
            "eventos_creados": events_created_perfil,
            "total_eventos": len(eventos_filtrados),
        }

        prompt = f"""
Analiza el panorama competitivo inclusivo.
- Nombre: {nombre}
- Discapacidad del perfil: {discapacidad}
- Estadísticas: {json.dumps(estadisticas, ensure_ascii=False)}
- Eventos compatibles (deporte con adaptación a su discapacidad): {json.dumps(resumen_eventos[:20], ensure_ascii=False, default=str)}

Ventajas, desventajas y recomendaciones concretas (usa nombres reales de eventos/deportes).
SOLO JSON:
{{"ventajas":["..."],"desventajas":["..."],"recomendaciones":["..."]}}
"""

        ventajas, desventajas, recomendaciones = [], [], []
        analisis = await self.llm.json_dict(prompt, canonizar(discapacidad))
        if analisis:
            ventajas = analisis.get("ventajas") or []
            desventajas = analisis.get("desventajas") or []
            recomendaciones = analisis.get("recomendaciones") or []

        heuristico = self._analisis_heuristico(
            discapacidad=discapacidad,
            deportes_compatibles=deportes_compatibles,
            deportes_sin_adaptacion=deportes_sin_adaptacion,
            estadisticas=estadisticas,
            futuros=futuros,
            con_cupo=con_cupo,
            proximo=proximo,
            inscritos=inscritos,
            perfil=user_data,
        )
        ventajas = ventajas or heuristico["ventajas"]
        desventajas = desventajas or heuristico["desventajas"]
        recomendaciones = recomendaciones or heuristico["recomendaciones"]

        return {
            "estadisticas": estadisticas,
            "ventajas": ventajas,
            "desventajas": desventajas,
            "recomendaciones": recomendaciones,
            "eventos": resumen_eventos,
            "proximos_eventos": futuros[:5],
            "deportes_compatibles": [
                {
                    "id": sid,
                    "nombre": nombres_deporte.get(sid),
                    "adaptaciones": [
                        {"discapacidad": a.get("disabilityName"), "adaptacion": a.get("adaptations")}
                        for a in adaptaciones_por_sport.get(sid, [])
                    ],
                }
                for sid in sorted(sport_ids_ok, key=lambda s: str(s))
            ],
            "deportes_sin_adaptacion": deportes_sin_adaptacion,
            "filtro": {
                "discapacidad_perfil": discapacidad,
                "discapacidad_canonica": canonizar(discapacidad),
                "sport_ids_compatibles": list(sport_ids_ok),
                "criterio": "evento.sportId en deportes con adaptacion a la discapacidad del usuario",
            },
            "inscripciones": [
                {
                    "eventId": e.get("eventId"),
                    "eventName": e.get("eventName") or e.get("name"),
                    "attended": e.get("attended"),
                    "waitlistPosition": e.get("waitlistPosition"),
                }
                for e in inscritos
            ],
            "usuario": {
                "id": user_data.get("id") or usuario_id,
                "fullName": nombre,
                "disability": discapacidad,
                "email": email,
                "eventsAttended": events_attended_perfil,
                "eventsCreated": events_created_perfil,
            },
        }
