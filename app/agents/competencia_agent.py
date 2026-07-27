from app.services.grok_service import GrokService
from app.services.user_service import UserService
from app.services.sports_service import SportsService
import json
import re
import unicodedata


class CompetenciaAgent:
    """
    Analiza el contexto competitivo del usuario.
    En `eventos` solo incluye eventos cuyo deporte tiene adaptación
    a la discapacidad del perfil (sport-disabilities / catálogo sports).
    """

    def __init__(self):
        self.grok = GrokService()
        self.user_service = UserService()
        self.sports_service = SportsService()

    def _normalizar(self, texto: str) -> str:
        t = (texto or "").strip().lower()
        t = "".join(
            c for c in unicodedata.normalize("NFD", t)
            if unicodedata.category(c) != "Mn"
        )
        return t

    def _discapacidad_coincide(self, discapacidad_usuario: str, *candidatos: str) -> bool:
        u = self._normalizar(discapacidad_usuario)
        if not u or u in ("general", "ninguna", "n/a"):
            return True  # sin discapacidad específica → no filtrar por este criterio

        # sinonimos cortos
        aliases = {
            "fisica": ["fisica", "fisico", "motriz", "movilidad", "silla"],
            "visual": ["visual", "ciego", "ceguera", "vision"],
            "auditiva": ["auditiva", "auditivo", "sordo", "audicion"],
            "intelectual": ["intelectual", "cognitiva", "cognitivo"],
            "multiple": ["multiple", "multidiscapacidad"],
        }
        for key, words in aliases.items():
            if key in u or any(w in u for w in words):
                u_tokens = set(words + [key, u])
                break
        else:
            u_tokens = set(p for p in u.split() if len(p) > 2) | {u}

        for cand in candidatos:
            d = self._normalizar(cand)
            if not d:
                continue
            if u in d or d in u:
                return True
            if any(tok in d for tok in u_tokens if len(tok) > 2):
                return True
        return False

    async def _sport_ids_compatibles(self, discapacidad: str) -> tuple[set, dict]:
        """
        Devuelve sportIds compatibles con la discapacidad y mapa de adaptaciones.
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

        return compatibles, adaptaciones_por_sport

    async def analizar_rendimiento(self, usuario_id: str):
        user_data = await self.user_service.get_user_profile(usuario_id)
        discapacidad = user_data.get("disability") or "general"
        nombre = user_data.get("fullName") or "Usuario"
        email = user_data.get("email")

        eventos_sistema = await self.sports_service.get_eventos()
        sport_ids_ok, adaptaciones_por_sport = await self._sport_ids_compatibles(discapacidad)

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

        estadisticas = {
            "eventos_en_sistema": len(eventos_sistema),
            "eventos_compatibles_discapacidad": len(eventos_filtrados),
            "eventos_activos_o_disponibles": len(eventos_activos),
            "deportes_compatibles": len(sport_ids_ok),
            "cupos_totales": cupos_totales,
            "cupos_disponibles": cupos_disponibles,
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
        try:
            respuesta = await self.grok.chat(prompt, discapacidad)
            json_match = re.search(r"\{.*\}", respuesta, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if isinstance(data, dict):
                    ventajas = data.get("ventajas") or []
                    desventajas = data.get("desventajas") or []
                    recomendaciones = data.get("recomendaciones") or []
        except Exception as e:
            print(f"Grok no disponible para competencia: {e}")

        if not ventajas:
            if resumen_eventos:
                ventajas = [
                    f"{len(resumen_eventos)} evento(s) con deporte adaptado a '{discapacidad}'",
                    f"{len(sport_ids_ok)} deporte(s) compatibles en el catálogo",
                ]
            else:
                ventajas = [f"Perfil con discapacidad '{discapacidad}' registrado"]

        if not desventajas:
            if not resumen_eventos:
                desventajas = [
                    f"No hay eventos cuyo deporte tenga adaptación registrada para '{discapacidad}'. "
                    "Revisa /api/sport-disabilities y crea eventos con esos sportId."
                ]
            elif not inscritos:
                desventajas = ["Aún no estás inscrito en los eventos compatibles"]

        if not recomendaciones:
            if resumen_eventos:
                recomendaciones = [
                    f"Considera el evento '{resumen_eventos[0]['nombre']}' ({resumen_eventos[0].get('deporte')})",
                    "Revisa las adaptaciones listadas en cada evento antes de inscribirte",
                ]
            else:
                recomendaciones = [
                    "Pide a un entrenador que registre adaptaciones deporte-discapacidad en /api/sport-disabilities",
                    "Luego crea eventos en /api/events con esos sportId",
                ]

        return {
            "estadisticas": estadisticas,
            "ventajas": ventajas,
            "desventajas": desventajas,
            "recomendaciones": recomendaciones,
            "eventos": resumen_eventos,
            "filtro": {
                "discapacidad_perfil": discapacidad,
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
