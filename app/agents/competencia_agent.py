import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from app.database.mongodb import get_db
from app.nlp.discapacidad import canonizar, coincide, descripcion
from app.nlp.texto import normalizar
from app.services.llm_service import LLMService
from app.services.sports_service import SportsService
from app.services.user_service import UserService

COL_MODO_COMPETENCIA = "modo_competencia"


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

    async def _sport_ids_compatibles(
        self, discapacidad: str, authorization: str | None = None
    ) -> tuple[set, dict, list]:
        """
        Devuelve sportIds compatibles con la discapacidad, mapa de adaptaciones y
        el catálogo completo de deportes activos.
        Usa GET /api/sports/active (disabilities anidadas) y /api/sport-disabilities/sport/{id}.
        """
        deportes = await self.sports_service.get_deportes_activos(authorization)
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

            ads = await self.sports_service.get_adaptaciones_deporte(sid, authorization)
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

    async def analizar_rendimiento(
        self, usuario_id: str, authorization: str | None = None
    ):
        user_data = await self.user_service.get_user_profile(usuario_id, authorization)
        discapacidad = user_data.get("disability") or "general"
        nombre = user_data.get("fullName") or "Usuario"
        email = user_data.get("email")

        eventos_sistema = await self.sports_service.get_eventos(authorization)
        sport_ids_ok, adaptaciones_por_sport, deportes = await self._sport_ids_compatibles(
            discapacidad, authorization
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

        inscritos = await self.sports_service.get_eventos_usuario(usuario_id, authorization)
        if email and email != usuario_id:
            extra = await self.sports_service.get_eventos_usuario(email, authorization)
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

        payload = {
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
        payload["vista"] = self._vista_analisis(payload)
        return payload

    async def activar_modo(
        self,
        usuario_id: str,
        *,
        activar: bool = True,
        evento_id: Optional[str] = None,
        objetivo: Optional[str] = None,
        semanas: int = 3,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """RF53 — activa o desactiva el modo competencia con plan de preparación."""
        semanas = max(1, min(int(semanas or 3), 8))
        analisis = await self.analizar_rendimiento(usuario_id, authorization)
        usuario = analisis.get("usuario") or {}
        discapacidad = usuario.get("disability") or "general"
        proximo = None
        if evento_id:
            for e in analisis.get("eventos") or []:
                if str(e.get("id")) == str(evento_id):
                    proximo = e
                    break
        if proximo is None:
            proximos = analisis.get("proximos_eventos") or []
            proximo = proximos[0] if proximos else None

        if not activar:
            await self._guardar_modo(
                usuario_id,
                {
                    "usuario_id": usuario_id,
                    "activo": False,
                    "evento_id": None,
                    "objetivo": None,
                    "semanas": semanas,
                    "actualizado": datetime.now(timezone.utc).isoformat(),
                },
            )
            mensaje = "Modo competencia desactivado. Vuelve a entrenamiento base."
            retorno = [
                "Reduce la intensidad un 20–30% durante 3–5 días.",
                "Prioriza movilidad, técnica y sueño.",
                "Retoma volumen progresivo antes de la siguiente meta.",
            ]
            return {
                "activo": False,
                "mensaje": mensaje,
                "recomendaciones_retorno": retorno,
                "usuario": usuario,
                "rf": "RF53",
                "vista": self._vista_modo(
                    activo=False,
                    objetivo=None,
                    semanas=semanas,
                    evento=None,
                    plan={},
                    nota=mensaje,
                    analisis_base={},
                    recomendaciones=retorno,
                ),
            }

        objetivo_txt = objetivo or (
            f"Preparación para {proximo.get('nombre')}" if proximo else "Preparación competitiva general"
        )
        plan = self._plan_preparacion(
            discapacidad=discapacidad,
            semanas=semanas,
            evento=proximo,
            objetivo=objetivo_txt,
            recomendaciones=analisis.get("recomendaciones") or [],
        )

        prompt = f"""
Redacta un cierre breve (máx 3 frases) para un atleta inclusivo en modo competencia.
Discapacidad: {discapacidad}. Objetivo: {objetivo_txt}. Semanas: {semanas}.
Evento: {json.dumps(proximo or {}, ensure_ascii=False, default=str)}.
Sólo texto plano, sin JSON.
"""
        nota_llm = await self.llm.texto(prompt, canonizar(discapacidad))

        estado = {
            "usuario_id": usuario_id,
            "activo": True,
            "evento_id": (proximo or {}).get("id") or evento_id,
            "objetivo": objetivo_txt,
            "semanas": semanas,
            "plan": plan,
            "actualizado": datetime.now(timezone.utc).isoformat(),
        }
        await self._guardar_modo(usuario_id, estado)

        analisis_base = {
            "ventajas": (analisis.get("ventajas") or [])[:3],
            "desventajas": (analisis.get("desventajas") or [])[:3],
            "recomendaciones": (analisis.get("recomendaciones") or [])[:3],
        }
        nota = nota_llm or plan.get("nota_local")
        return {
            "activo": True,
            "objetivo": objetivo_txt,
            "semanas": semanas,
            "evento_objetivo": proximo,
            "plan": plan,
            "checklist": plan.get("checklist") or [],
            "riesgos": plan.get("riesgos") or [],
            "nota": nota,
            "analisis_base": analisis_base,
            "usuario": usuario,
            "rf": "RF53",
            "vista": self._vista_modo(
                activo=True,
                objetivo=objetivo_txt,
                semanas=semanas,
                evento=proximo,
                plan=plan,
                nota=nota,
                analisis_base=analisis_base,
            ),
        }

    def _item_evento(self, evento: Optional[dict]) -> Optional[dict[str, Any]]:
        if not isinstance(evento, dict) or not evento:
            return None
        cupos = evento.get("availableCapacity")
        meta = [
            x
            for x in (
                evento.get("fecha") or evento.get("eventDate"),
                evento.get("ubicacion") or evento.get("location"),
                f"{cupos} cupos" if cupos is not None else None,
                "Inscrito" if evento.get("usuario_inscrito") else None,
            )
            if x
        ]
        return {
            "titulo": evento.get("nombre") or evento.get("eventName") or "Evento",
            "subtitulo": evento.get("deporte") or evento.get("sportName") or "",
            "meta": meta,
            "id": str(evento.get("id") or evento.get("eventId") or ""),
        }

    def _vista_analisis(self, analisis: dict[str, Any]) -> dict[str, Any]:
        """Bloques listos para pintar (iconos + listas), sin JSON crudo."""
        stats = analisis.get("estadisticas") or {}
        usuario = analisis.get("usuario") or {}
        proximos = analisis.get("proximos_eventos") or analisis.get("eventos") or []
        return {
            "tipo": "analisis",
            "activo": False,
            "titulo": "Panorama competitivo",
            "perfil": {
                "nombre": usuario.get("fullName") or "Usuario",
                "discapacidad": usuario.get("disability") or "—",
            },
            "kpis": [
                {
                    "clave": "compatibles",
                    "icono": "trophy",
                    "valor": stats.get("eventos_compatibles_discapacidad") or 0,
                    "label": "Eventos compatibles",
                },
                {
                    "clave": "cupos",
                    "icono": "calendar-days",
                    "valor": stats.get("cupos_disponibles") or 0,
                    "label": "Cupos libres",
                },
                {
                    "clave": "inscripciones",
                    "icono": "user",
                    "valor": stats.get("inscripciones_usuario") or 0,
                    "label": "Tus inscripciones",
                },
                {
                    "clave": "deportes",
                    "icono": "heart",
                    "valor": stats.get("deportes_compatibles") or 0,
                    "label": "Deportes adaptados",
                },
            ],
            "ventajas": analisis.get("ventajas") or [],
            "desventajas": analisis.get("desventajas") or [],
            "recomendaciones": analisis.get("recomendaciones") or [],
            "eventos": [
                item
                for e in proximos[:6]
                if isinstance(e, dict)
                for item in [self._item_evento(e)]
                if item
            ],
            "fases": [],
            "checklist": [],
            "riesgos": [],
            "objetivo": None,
            "semanas": None,
            "evento_objetivo": None,
            "nota": None,
        }

    def _vista_modo(
        self,
        *,
        activo: bool,
        objetivo: Optional[str],
        semanas: int,
        evento: Optional[dict],
        plan: dict[str, Any],
        nota: Optional[str],
        analisis_base: dict[str, Any],
        recomendaciones: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Plan de competencia listo para pintar, sin serializar JSON al usuario."""
        if not activo:
            return {
                "tipo": "modo",
                "activo": False,
                "titulo": "Modo competencia desactivado",
                "nota": nota,
                "recomendaciones": recomendaciones or [],
                "kpis": [],
                "ventajas": [],
                "desventajas": [],
                "eventos": [],
                "fases": [],
                "checklist": [],
                "riesgos": [],
                "objetivo": None,
                "semanas": semanas,
                "evento_objetivo": None,
            }

        evento_item = self._item_evento(evento)
        fases = []
        for fase in (plan or {}).get("fases") or []:
            if not isinstance(fase, dict):
                continue
            fases.append(
                {
                    "semana": fase.get("semana"),
                    "foco": fase.get("foco"),
                    "intensidad": fase.get("intensidad"),
                    "sesiones": fase.get("sesiones_sugeridas"),
                    "nota": fase.get("nota"),
                }
            )
        checklist = (plan or {}).get("checklist") or []
        riesgos = (plan or {}).get("riesgos") or []
        return {
            "tipo": "modo",
            "activo": True,
            "titulo": "Modo competencia activo",
            "objetivo": objetivo,
            "semanas": semanas,
            "nota": nota,
            "evento_objetivo": evento_item,
            "kpis": [
                {
                    "clave": "semanas",
                    "icono": "calendar-days",
                    "valor": semanas,
                    "label": "Semanas de plan",
                },
                {
                    "clave": "sesiones",
                    "icono": "bolt",
                    "valor": sum(int(f.get("sesiones") or 0) for f in fases),
                    "label": "Sesiones sugeridas",
                },
                {
                    "clave": "checklist",
                    "icono": "clipboard-document-list",
                    "valor": len(checklist),
                    "label": "Puntos del plan",
                },
                {
                    "clave": "riesgos",
                    "icono": "exclamation-triangle",
                    "valor": len(riesgos),
                    "label": "Riesgos a vigilar",
                },
            ],
            "fases": fases,
            "checklist": checklist,
            "riesgos": riesgos,
            "ventajas": (analisis_base or {}).get("ventajas") or [],
            "desventajas": (analisis_base or {}).get("desventajas") or [],
            "recomendaciones": recomendaciones
            or (analisis_base or {}).get("recomendaciones")
            or [],
            "eventos": [evento_item] if evento_item else [],
        }

    def _plan_preparacion(
        self,
        *,
        discapacidad: str,
        semanas: int,
        evento: Optional[dict],
        objetivo: str,
        recomendaciones: list[str],
    ) -> dict[str, Any]:
        etiqueta = descripcion(canonizar(discapacidad))
        fases = []
        for i in range(1, semanas + 1):
            if i < semanas:
                foco = "construcción de base y técnica"
                intensidad = "media"
            else:
                foco = "afinamiento y taper ligero"
                intensidad = "media-baja"
            fases.append({
                "semana": i,
                "foco": foco,
                "intensidad": intensidad,
                "sesiones_sugeridas": 3 if i < semanas else 2,
                "nota": f"Adapta cada sesión a {etiqueta}; prioriza seguridad sobre volumen.",
            })

        checklist = [
            "Confirma inscripción y logística del evento objetivo.",
            "Registra RPE tras cada sesión de preparación.",
            "Revisa adaptaciones del deporte con tu entrenador.",
            "Duerme 7–9 h y marca al menos un día de descanso semanal.",
        ]
        if evento:
            checklist.insert(
                0,
                f"Meta: {evento.get('nombre')} el {evento.get('fecha')} ({evento.get('deporte')}).",
            )
        riesgos = [
            "Sobreentrenamiento por subir volumen demasiado rápido.",
            "Ignorar dolor articular o fatiga acumulada (RPE ≥ 8).",
        ]
        if recomendaciones:
            checklist.append(recomendaciones[0])

        return {
            "objetivo": objetivo,
            "fases": fases,
            "checklist": checklist,
            "riesgos": riesgos,
            "nota_local": (
                f"Modo competencia activo por {semanas} semana(s) para {etiqueta}. "
                "Mantén técnica limpia y carga progresiva."
            ),
        }

    async def _guardar_modo(self, usuario_id: str, doc: dict[str, Any]) -> None:
        db = get_db()
        if db is None:
            return
        try:
            await db[COL_MODO_COMPETENCIA].update_one(
                {"usuario_id": usuario_id},
                {"$set": doc},
                upsert=True,
            )
        except Exception as exc:
            print(f"No se pudo persistir modo competencia: {exc}")
