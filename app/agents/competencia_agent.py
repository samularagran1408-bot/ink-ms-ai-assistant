"""Agente de panorama competitivo y modo competencia (RF53).

Filtra eventos al cruce deporte–discapacidad del perfil y gestiona el plan
de preparación (checklist + sesiones de rutina).
"""

import json
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.agents.competencia_progreso import (
    CompetenciaAccionError,
    fases_con_sesiones,
    normalizar_checklist,
    progreso_plan_desde_doc,
    rutinas_inscritas_vista,
    sesiones_hechas_doc,
)
from app.database.mongodb import get_db
from app.nlp.discapacidad import canonizar, coincide, descripcion
from app.nlp.texto import normalizar
from app.services.llm_service import LLMService
from app.services.sports_service import SportsService
from app.services.user_service import UserService

COL_MODO_COMPETENCIA = "modo_competencia"


def progreso_desde_inscripciones(inscritos: list, rutinas: list | None = None) -> dict[str, Any]:
    """Calcula asistencia, confirmados, lista de espera y rutinas, como la tarjeta Progreso del panel."""
    inscritos = inscritos or []
    en_espera = sum(1 for e in inscritos if e.get("waitlistPosition") is not None)
    confirmados = max(0, len(inscritos) - en_espera)
    asistidos = sum(
        1
        for e in inscritos
        if e.get("attended") is True and e.get("waitlistPosition") is None
    )
    tasa = round((asistidos * 100) / confirmados) if confirmados else 0
    return {
        "asistencia_pct": tasa,
        "asistidos": asistidos,
        "confirmados": confirmados,
        "inscripciones": len(inscritos),
        "rutinas": len(rutinas or []),
        "lista_espera": en_espera,
    }


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
        """Inicializa LLM, users y sports."""
        self.llm = LLMService()
        self.user_service = UserService()
        self.sports_service = SportsService()

    def _normalizar(self, texto: str) -> str:
        """Normaliza texto para comparaciones (minúsculas, sin acentos superfluos)."""
        return normalizar(texto)

    def _discapacidad_coincide(self, discapacidad_usuario: str, *candidatos: str) -> bool:
        """Indica si algún candidato describe la misma discapacidad canónica del usuario."""
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
        progreso_panel: Optional[dict] = None,
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
        panel = progreso_panel or {}
        if panel.get("asistencia_pct"):
            ventajas.append(
                f"En tu panel llevas {panel['asistencia_pct']}% de asistencia "
                f"({panel.get('asistidos')}/{panel.get('confirmados')} eventos)."
            )
        if panel.get("rutinas"):
            ventajas.append(
                f"Tienes {panel['rutinas']} rutina(s) activa(s) en el panel; "
                "el modo competencia usa ese avance como base de preparación."
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
        if panel.get("confirmados") and not panel.get("asistidos"):
            desventajas.append(
                "En el panel tienes eventos inscritos pero 0% de asistencia registrada."
            )
        if not panel.get("rutinas"):
            desventajas.append(
                "Aún no estás en ninguna rutina del panel, así que el plan de competencia "
                "no tiene sesiones publicadas asociadas a tu progreso."
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
        if not panel.get("rutinas"):
            recomendaciones.append(
                "Únete a una rutina desde el panel principal para que el modo competencia "
                "se alimente de tu progreso real (asistencia y sesiones)."
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
        """RF53 — analiza el panorama competitivo del atleta autenticado.

        Cruza eventos con deportes que tienen adaptación a su discapacidad,
        calcula estadísticas de cupos/asistencias y pide al LLM (o al heurístico)
        ventajas, desventajas y recomendaciones concretas.
        """
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
        rutinas = await self.sports_service.get_rutinas_usuario(usuario_id, authorization)
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
            "rutinas_panel": len(rutinas or []),
        }
        progreso_panel = progreso_desde_inscripciones(inscritos, rutinas)

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
            progreso_panel=progreso_panel,
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
            "progreso_panel": progreso_panel,
            "rutinas_usuario": rutinas or [],
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
                "progreso_panel": analisis.get("progreso_panel") or {},
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
                    progreso_panel=analisis.get("progreso_panel") or {},
                    rutinas_inscritas=rutinas_inscritas_vista(
                        analisis.get("rutinas_usuario") or []
                    ),
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

        ahora = datetime.now(timezone.utc).isoformat()
        evento_item = self._item_evento(proximo)
        usuario_email = usuario.get("email")
        estado = {
            "usuario_id": usuario_id,
            "email": usuario_email,
            "activo": True,
            "evento_id": (proximo or {}).get("id") or evento_id,
            "evento_snapshot": evento_item,
            "objetivo": objetivo_txt,
            "semanas": semanas,
            "plan": plan,
            "activado_en": ahora,
            "actualizado": ahora,
            "progreso_panel": analisis.get("progreso_panel") or {},
            "sesiones_hechas": [],
        }
        await self._guardar_modo(usuario_id, estado)
        nota = plan.get("nota_local")

        analisis_base = {
            "ventajas": (analisis.get("ventajas") or [])[:3],
            "desventajas": (analisis.get("desventajas") or [])[:3],
            "recomendaciones": (analisis.get("recomendaciones") or [])[:3],
        }
        progreso_panel = analisis.get("progreso_panel") or {}
        plan_prog = progreso_plan_desde_doc(estado)
        inscritos_rutina = rutinas_inscritas_vista(analisis.get("rutinas_usuario") or [])
        return {
            "activo": True,
            "objetivo": objetivo_txt,
            "semanas": semanas,
            "semana_actual": plan_prog.get("semana_actual"),
            "plan_pct": plan_prog.get("plan_pct"),
            "checklist_pct": plan_prog.get("checklist_pct"),
            "sesiones_pct": plan_prog.get("sesiones_pct"),
            "checklist_hechos": plan_prog.get("checklist_hechos"),
            "checklist_total": plan_prog.get("checklist_total"),
            "sesiones_hechas": plan_prog.get("sesiones_hechas"),
            "sesiones_objetivo": plan_prog.get("sesiones_objetivo"),
            "evento_objetivo": proximo,
            "plan": plan,
            "checklist": plan_prog.get("checklist") or [],
            "riesgos": plan.get("riesgos") or [],
            "nota": nota,
            "analisis_base": analisis_base,
            "usuario": usuario,
            "progreso_panel": progreso_panel,
            "rutinas_inscritas": inscritos_rutina,
            "rf": "RF53",
            "vista": self._vista_modo(
                activo=True,
                objetivo=objetivo_txt,
                semanas=semanas,
                evento=proximo,
                plan=plan,
                nota=nota,
                analisis_base=analisis_base,
                progreso_panel=progreso_panel,
                progreso_plan=plan_prog,
                rutinas_inscritas=inscritos_rutina,
            ),
        }

    def _item_evento(self, evento: Optional[dict]) -> Optional[dict[str, Any]]:
        """Normaliza un evento a {titulo, subtitulo, meta, id} para tarjetas de UI."""
        if not isinstance(evento, dict) or not evento:
            return None
        if evento.get("titulo") and ("meta" in evento or "subtitulo" in evento):
            return {
                "titulo": evento.get("titulo") or "Evento",
                "subtitulo": evento.get("subtitulo") or "",
                "meta": list(evento.get("meta") or []),
                "id": str(evento.get("id") or evento.get("eventId") or ""),
            }
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
        panel = analisis.get("progreso_panel") or {}
        return {
            "tipo": "analisis",
            "activo": False,
            "titulo": "Panorama competitivo",
            "perfil": {
                "nombre": usuario.get("fullName") or "Usuario",
                "discapacidad": usuario.get("disability") or "—",
            },
            "progreso_panel": panel,
            "kpis": [
                {
                    "clave": "asistencia",
                    "icono": "chart-bar",
                    "valor": f"{panel.get('asistencia_pct') or 0}%",
                    "label": "Asistencia del panel",
                },
                {
                    "clave": "rutinas",
                    "icono": "heart",
                    "valor": panel.get("rutinas") or 0,
                    "label": "Rutinas del panel",
                },
                {
                    "clave": "compatibles",
                    "icono": "trophy",
                    "valor": stats.get("eventos_compatibles_discapacidad") or 0,
                    "label": "Eventos compatibles",
                },
                {
                    "clave": "inscripciones",
                    "icono": "user",
                    "valor": stats.get("inscripciones_usuario") or panel.get("inscripciones") or 0,
                    "label": "Tus inscripciones",
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
        progreso_panel: Optional[dict[str, Any]] = None,
        progreso_plan: Optional[dict[str, Any]] = None,
        rutinas_inscritas: Optional[list[dict[str, str]]] = None,
    ) -> dict[str, Any]:
        """Plan de competencia listo para pintar, sin serializar JSON al usuario."""
        panel = progreso_panel or {}
        plan_prog = progreso_plan or {}
        inscritos = rutinas_inscritas or []
        if not activo:
            return {
                "tipo": "modo",
                "activo": False,
                "titulo": "Modo competencia desactivado",
                "nota": nota,
                "recomendaciones": recomendaciones or [],
                "kpis": self._kpis_panel(panel),
                "ventajas": [],
                "desventajas": [],
                "eventos": [],
                "fases": [],
                "checklist": [],
                "riesgos": [],
                "objetivo": None,
                "semanas": semanas,
                "evento_objetivo": None,
                "progreso_panel": panel,
                "semana_actual": 0,
                "plan_pct": 0,
                "checklist_pct": 0,
                "sesiones_pct": 0,
                "rutinas_inscritas": inscritos,
            }

        evento_item = self._item_evento(evento)
        semana_actual = int(plan_prog.get("semana_actual") or 1)
        plan_pct = int(plan_prog["plan_pct"]) if "plan_pct" in plan_prog else 0
        checklist = plan_prog.get("checklist") or normalizar_checklist(plan)
        fases = fases_con_sesiones(plan, int(plan_prog.get("sesiones_hechas") or 0), semana_actual)
        riesgos = (plan or {}).get("riesgos") or []
        check_hechos = int(plan_prog.get("checklist_hechos") or 0)
        check_total = int(plan_prog.get("checklist_total") or len(checklist))
        ses_hechas = int(plan_prog.get("sesiones_hechas") or 0)
        ses_obj = int(plan_prog.get("sesiones_objetivo") or 0)
        kpis = [
            {
                "clave": "asistencia",
                "icono": "chart-bar",
                "valor": f"{panel.get('asistencia_pct') or 0}%",
                "label": "Asistencia del panel",
            },
            {
                "clave": "plan",
                "icono": "trophy",
                "valor": f"{plan_pct}%",
                "label": f"Plan (sem. {semana_actual}/{semanas})",
            },
            {
                "clave": "checklist",
                "icono": "clipboard-document-list",
                "valor": f"{check_hechos}/{check_total}",
                "label": "Lista del plan",
            },
            {
                "clave": "sesiones",
                "icono": "heart",
                "valor": f"{ses_hechas}/{ses_obj}",
                "label": "Sesiones de rutina",
            },
        ]
        return {
            "tipo": "modo",
            "activo": True,
            "titulo": "Modo competencia activo",
            "objetivo": objetivo,
            "semanas": semanas,
            "semana_actual": semana_actual,
            "plan_pct": plan_pct,
            "checklist_pct": int(plan_prog.get("checklist_pct") or 0),
            "sesiones_pct": int(plan_prog.get("sesiones_pct") or 0),
            "checklist_hechos": check_hechos,
            "checklist_total": check_total,
            "sesiones_hechas": ses_hechas,
            "sesiones_objetivo": ses_obj,
            "nota": nota,
            "evento_objetivo": evento_item,
            "progreso_panel": panel,
            "kpis": kpis,
            "fases": fases,
            "checklist": checklist,
            "riesgos": riesgos,
            "rutinas_inscritas": inscritos,
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
        """Arma fases semanales, checklist y riesgos del plan de preparación competitiva."""
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
            {
                "id": "c_logistica",
                "texto": "Confirma inscripción y logística del evento objetivo.",
                "hecho": False,
            },
            {
                "id": "c_rpe",
                "texto": "Registra RPE tras cada sesión de preparación.",
                "hecho": False,
            },
            {
                "id": "c_adaptaciones",
                "texto": "Revisa adaptaciones del deporte con tu entrenador.",
                "hecho": False,
            },
            {
                "id": "c_descanso",
                "texto": "Duerme 7–9 h y marca al menos un día de descanso semanal.",
                "hecho": False,
            },
        ]
        if evento:
            checklist.insert(
                0,
                {
                    "id": "c_meta",
                    "texto": (
                        f"Meta: {evento.get('nombre')} el {evento.get('fecha')} "
                        f"({evento.get('deporte')})."
                    ),
                    "hecho": False,
                },
            )
        riesgos = [
            "Sobreentrenamiento por subir volumen demasiado rápido.",
            "Ignorar dolor articular o fatiga acumulada (RPE ≥ 8).",
        ]
        if recomendaciones:
            checklist.append(
                {
                    "id": "c_reco",
                    "texto": str(recomendaciones[0]),
                    "hecho": False,
                }
            )

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

    def _kpis_panel(self, panel: dict[str, Any]) -> list[dict[str, Any]]:
        """KPIs de asistencia, rutinas, confirmados y lista de espera para la vista inactiva."""
        return [
            {
                "clave": "asistencia",
                "icono": "chart-bar",
                "valor": f"{panel.get('asistencia_pct') or 0}%",
                "label": "Asistencia del panel",
            },
            {
                "clave": "rutinas",
                "icono": "heart",
                "valor": panel.get("rutinas") or 0,
                "label": "Rutinas del panel",
            },
            {
                "clave": "confirmados",
                "icono": "calendar-days",
                "valor": panel.get("confirmados") or 0,
                "label": "Eventos confirmados",
            },
            {
                "clave": "espera",
                "icono": "user",
                "valor": panel.get("lista_espera") or 0,
                "label": "Lista de espera",
            },
        ]

    async def obtener_modo(
        self, usuario_id: str, authorization: Optional[str] = None
    ) -> dict[str, Any]:
        """Estado persistido del modo competencia + progreso del panel principal."""
        doc = await self._leer_modo(usuario_id)
        progreso, rutinas = await self._panel_y_rutinas(usuario_id, authorization)
        inscritos_rutina = rutinas_inscritas_vista(rutinas)
        activo = bool(doc.get("activo"))
        plan = doc.get("plan") if activo else {}
        plan_prog = progreso_plan_desde_doc(doc) if activo else {}
        evento = doc.get("evento_snapshot") if activo else None
        objetivo = doc.get("objetivo") if activo else None
        semanas = int(doc.get("semanas") or 3)
        return {
            "activo": activo,
            "objetivo": objetivo,
            "semanas": semanas if activo else None,
            "semana_actual": plan_prog.get("semana_actual") if activo else 0,
            "plan_pct": plan_prog.get("plan_pct") if activo else 0,
            "checklist_pct": plan_prog.get("checklist_pct") if activo else 0,
            "sesiones_pct": plan_prog.get("sesiones_pct") if activo else 0,
            "checklist_hechos": plan_prog.get("checklist_hechos") if activo else 0,
            "checklist_total": plan_prog.get("checklist_total") if activo else 0,
            "sesiones_hechas": plan_prog.get("sesiones_hechas") if activo else 0,
            "sesiones_objetivo": plan_prog.get("sesiones_objetivo") if activo else 0,
            "checklist": plan_prog.get("checklist") if activo else [],
            "evento_objetivo": evento,
            "plan": plan or {},
            "progreso_panel": progreso,
            "rutinas_inscritas": inscritos_rutina,
            "activado_en": doc.get("activado_en") if activo else None,
            "rf": "RF53",
            "vista": self._vista_modo(
                activo=activo,
                objetivo=objetivo,
                semanas=semanas,
                evento=evento if isinstance(evento, dict) else None,
                plan=plan if isinstance(plan, dict) else {},
                nota=None if activo else "Modo competencia desactivado.",
                analisis_base={},
                progreso_panel=progreso,
                progreso_plan=plan_prog,
                rutinas_inscritas=inscritos_rutina,
            ),
        }

    async def marcar_checklist(
        self,
        usuario_id: str,
        item_id: str,
        hecho: bool,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Marca o desmarca un ítem de la lista del plan activo."""
        doc = await self._leer_modo(usuario_id)
        if not doc.get("activo"):
            raise CompetenciaAccionError(
                409, "Activa el modo competencia para marcar la lista del plan."
            )
        plan = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
        items = normalizar_checklist(plan)
        clave = str(item_id or "").strip()
        encontrado = False
        for item in items:
            if item.get("id") == clave:
                item["hecho"] = bool(hecho)
                encontrado = True
                break
        if not encontrado:
            raise CompetenciaAccionError(404, "No encontré ese punto de la lista.")
        plan["checklist"] = items
        doc["plan"] = plan
        doc["actualizado"] = datetime.now(timezone.utc).isoformat()
        await self._guardar_modo(usuario_id, doc)
        return await self.obtener_modo(usuario_id, authorization)

    async def registrar_sesion(
        self,
        usuario_id: str,
        routine_id: str,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Registra una sesión de una rutina inscrita para avanzar el plan."""
        doc = await self._leer_modo(usuario_id)
        if not doc.get("activo"):
            raise CompetenciaAccionError(
                409, "Activa el modo competencia para registrar sesiones del plan."
            )
        rid = str(routine_id or "").strip()
        if not rid:
            raise CompetenciaAccionError(400, "Indica la rutina de la sesión.")

        _, rutinas = await self._panel_y_rutinas(usuario_id, authorization)
        match = next(
            (
                r
                for r in rutinas
                if str(r.get("routineId") or r.get("id") or "") == rid
                and str(r.get("status") or "active").lower() != "cancelled"
            ),
            None,
        )
        if match is None:
            raise CompetenciaAccionError(
                409, "Únete a esa rutina en el panel para poder registrar la sesión."
            )

        sesiones = sesiones_hechas_doc(doc)
        hoy = datetime.now(timezone.utc).date().isoformat()
        if any(
            str(s.get("routine_id") or "") == rid and str(s.get("fecha") or "")[:10] == hoy
            for s in sesiones
        ):
            raise CompetenciaAccionError(
                409, "Ya registraste una sesión de esta rutina hoy."
            )

        sesiones.append(
            {
                "id": str(uuid4()),
                "routine_id": rid,
                "routine_name": match.get("routineName") or match.get("name") or "Rutina",
                "fecha": datetime.now(timezone.utc).isoformat(),
            }
        )
        doc["sesiones_hechas"] = sesiones
        doc["actualizado"] = datetime.now(timezone.utc).isoformat()
        await self._guardar_modo(usuario_id, doc)
        return await self.obtener_modo(usuario_id, authorization)

    async def _panel_y_rutinas(
        self, usuario_id: str, authorization: Optional[str] = None
    ) -> tuple[dict[str, Any], list]:
        """Cifras de progreso del panel (asistencia/rutinas) y listado de rutinas inscritas."""
        inscritos = await self.sports_service.get_eventos_usuario(usuario_id, authorization)
        rutinas = await self.sports_service.get_rutinas_usuario(usuario_id, authorization)
        return progreso_desde_inscripciones(inscritos, rutinas), rutinas or []

    async def _leer_modo(self, usuario_id: str) -> dict[str, Any]:
        """Carga el documento de modo competencia; `{activo: False}` si no hay persistencia."""
        db = get_db()
        if db is None:
            return {"usuario_id": usuario_id, "activo": False}
        try:
            doc = await db[COL_MODO_COMPETENCIA].find_one(
                {
                    "$or": [
                        {"usuario_id": usuario_id},
                        {"email": usuario_id},
                    ]
                },
                {"_id": 0},
            )
            return doc or {"usuario_id": usuario_id, "activo": False}
        except Exception:
            return {"usuario_id": usuario_id, "activo": False}

    async def _guardar_modo(self, usuario_id: str, doc: dict[str, Any]) -> None:
        """Persiste (upsert) el estado del modo competencia en Mongo."""
        db = get_db()
        if db is None:
            raise CompetenciaAccionError(
                503, "No hay persistencia: no se pudo guardar el modo competencia."
            )
        try:
            clave = {"usuario_id": usuario_id}
            if doc.get("email"):
                existente = await db[COL_MODO_COMPETENCIA].find_one(
                    {"$or": [{"usuario_id": usuario_id}, {"email": doc.get("email")}]},
                    {"usuario_id": 1},
                )
                if existente and existente.get("usuario_id"):
                    clave = {"usuario_id": existente["usuario_id"]}
            await db[COL_MODO_COMPETENCIA].update_one(
                clave,
                {"$set": doc},
                upsert=True,
            )
        except CompetenciaAccionError:
            raise
        except Exception as exc:
            raise CompetenciaAccionError(
                503, "No se pudo guardar el modo competencia."
            ) from exc
