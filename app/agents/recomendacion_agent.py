from app.services.grok_service import GrokService
from app.services.user_service import UserService
from app.services.sports_service import SportsService
import json
import re


class RecomendacionAgent:
    def __init__(self):
        self.grok = GrokService()
        self.user_service = UserService()
        self.sports_service = SportsService()

    def _normalizar(self, texto: str) -> str:
        return (texto or "").strip().lower()

    def _discapacidad_coincide(self, discapacidad_usuario: str, disability_name: str) -> bool:
        u = self._normalizar(discapacidad_usuario)
        d = self._normalizar(disability_name)
        if not u or not d:
            return False
        return u in d or d in u or any(p in d for p in u.split() if len(p) > 3)

    async def recomendar_eventos(self, usuario_id: str):
        user_data = await self.user_service.get_user_profile(usuario_id)
        discapacidad = user_data.get("disability") or "general"
        nombre = user_data.get("fullName") or "Usuario"

        eventos = await self.sports_service.get_eventos_activos()
        discapacidades_catalogo = await self.sports_service.get_discapacidades_activas()

        # Filtrar eventos por adaptaciones deporte-discapacidad (ink-ms-sports)
        candidatos = []
        for evento in eventos:
            sport_id = evento.get("sportId")
            adaptaciones = []
            match_discapacidad = False
            if sport_id is not None:
                adaptaciones = await self.sports_service.get_adaptaciones_deporte(sport_id)
                match_discapacidad = any(
                    self._discapacidad_coincide(discapacidad, a.get("disabilityName", ""))
                    for a in adaptaciones
                )

            candidatos.append({
                "id": evento.get("id"),
                "nombre": evento.get("name"),
                "descripcion": evento.get("description"),
                "deporte": evento.get("sportName"),
                "sportId": sport_id,
                "fecha": evento.get("eventDate"),
                "hora": evento.get("eventTime"),
                "ubicacion": evento.get("location"),
                "cupos": evento.get("availableCapacity"),
                "status": evento.get("status"),
                "compatible_discapacidad": match_discapacidad,
                "adaptaciones": [
                    {
                        "discapacidad": a.get("disabilityName"),
                        "adaptacion": a.get("adaptations"),
                    }
                    for a in adaptaciones
                    if self._discapacidad_coincide(discapacidad, a.get("disabilityName", ""))
                ] if match_discapacidad else [],
            })

        # Priorizar compatibles; si no hay, usar todos los activos
        priorizados = [c for c in candidatos if c["compatible_discapacidad"]] or candidatos
        muestra = priorizados[:12]

        catalogo_nombres = [d.get("name") for d in discapacidades_catalogo if d.get("name")]

        prompt = f"""
        Recomienda eventos de InkluSport para un usuario.
        - Nombre: {nombre}
        - Discapacidad del perfil (ink-ms-users): {discapacidad}
        - Catálogo de discapacidades del sistema: {catalogo_nombres}
        - Eventos candidatos (creados en ink-ms-sports): {json.dumps(muestra, ensure_ascii=False, default=str)}

        Recomienda hasta 3 eventos más adecuados. Usa el nombre real del evento.
        Explica la razón considerando discapacidad y adaptaciones.

        Entregar SOLO JSON válido (sin markdown):
        {{
            "recomendaciones": [
                {{
                    "evento_id": "id",
                    "evento": "Nombre del evento",
                    "deporte": "Deporte",
                    "razon": "Razón",
                    "adaptaciones": "Adaptaciones relevantes"
                }}
            ],
            "mensaje": "Mensaje personalizado"
        }}
        """

        respuesta = None
        try:
            respuesta = await self.grok.chat(prompt, discapacidad)
        except Exception as e:
            print(f"Grok no disponible para recomendación: {e}")

        if respuesta:
            try:
                json_match = re.search(r"\{.*\}", respuesta, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    if isinstance(data, dict) and data.get("recomendaciones"):
                        data["usuario"] = {
                            "id": user_data.get("id") or usuario_id,
                            "fullName": nombre,
                            "disability": discapacidad,
                        }
                        data["total_eventos_disponibles"] = len(eventos)
                        return data
            except Exception:
                pass

        # Fallback determinista sin Grok
        top = priorizados[:3]
        recomendaciones = []
        for c in top:
            razon = (
                f"Compatible con tu discapacidad ({discapacidad})"
                if c["compatible_discapacidad"]
                else "Evento activo disponible en la plataforma"
            )
            adapt = "; ".join(
                a.get("adaptacion", "") for a in c.get("adaptaciones", []) if a.get("adaptacion")
            )
            recomendaciones.append({
                "evento_id": c.get("id"),
                "evento": c.get("nombre") or "Evento",
                "deporte": c.get("deporte"),
                "razon": razon,
                "adaptaciones": adapt or None,
                "fecha": c.get("fecha"),
                "ubicacion": c.get("ubicacion"),
            })

        if not recomendaciones:
            return {
                "recomendaciones": [],
                "mensaje": "Por ahora no hay eventos activos. Vuelve pronto; se crean en ink-ms-sports.",
                "usuario": {
                    "id": user_data.get("id") or usuario_id,
                    "fullName": nombre,
                    "disability": discapacidad,
                },
                "total_eventos_disponibles": 0,
            }

        return {
            "recomendaciones": recomendaciones,
            "mensaje": f"Encontramos {len(recomendaciones)} evento(s) relevantes para {nombre}.",
            "usuario": {
                "id": user_data.get("id") or usuario_id,
                "fullName": nombre,
                "disability": discapacidad,
            },
            "total_eventos_disponibles": len(eventos),
        }
