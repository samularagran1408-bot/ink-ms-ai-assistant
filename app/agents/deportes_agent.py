"""Filtrado inteligente de deportes y recomendación por perfil (RF50/RF51)."""

from __future__ import annotations

from typing import Any, Optional

from app.nlp.discapacidad import canonizar, coincide, descripcion
from app.nlp.texto import normalizar
from app.services.sports_service import SportsService
from app.services.user_service import UserService


class DeportesAgent:
    def __init__(self):
        self.user_service = UserService()
        self.sports_service = SportsService()

    async def filtrar(
        self,
        usuario_id: str,
        limite: int = 10,
        authorization: Optional[str] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        perfil = perfil or await self.user_service.get_user_profile(usuario_id, authorization)
        discapacidad = canonizar(perfil.get("disability") or "general")
        intereses = self._intereses(perfil)
        deportes = await self.sports_service.get_deportes_activos(authorization)

        ranking: list[dict[str, Any]] = []
        for deporte in deportes:
            sid = deporte.get("id")
            ads = (
                await self.sports_service.get_adaptaciones_deporte(sid, authorization)
                if sid is not None
                else []
            )
            match_discapacidad = any(
                coincide(discapacidad, a.get("disabilityName"), a.get("adaptations"))
                for a in ads
            ) or any(
                coincide(discapacidad, d.get("name"), d.get("category"))
                for d in (deporte.get("disabilities") or [])
                if isinstance(d, dict)
            )

            puntaje = 10.0
            motivos = []
            if match_discapacidad and discapacidad != "general":
                puntaje += 50
                motivos.append(f"Compatible con {descripcion(discapacidad)}")
            elif discapacidad == "general":
                puntaje += 20
                motivos.append("Abierto a perfil general")
            else:
                motivos.append("Sin adaptaciones registradas para tu discapacidad")

            nombre = normalizar(str(deporte.get("name") or ""))
            for interes in intereses:
                if interes and interes in nombre:
                    puntaje += 25
                    motivos.append(f"Coincide con tu interés: {interes}")

            dificultad = str(deporte.get("difficulty") or "").lower()
            if "princip" in dificultad or "basic" in dificultad:
                puntaje += 5

            ranking.append({
                "sport_id": sid,
                "nombre": deporte.get("name"),
                "dificultad": deporte.get("difficulty"),
                "material": deporte.get("requiredMaterials"),
                "descripcion": deporte.get("description"),
                "compatible_discapacidad": match_discapacidad or discapacidad == "general",
                "adaptaciones": [
                    {
                        "discapacidad": a.get("disabilityName"),
                        "adaptacion": a.get("adaptations"),
                    }
                    for a in ads
                    if coincide(discapacidad, a.get("disabilityName"))
                ][:3],
                "puntaje": round(puntaje, 2),
                "razon": ". ".join(motivos) + ".",
            })

        ranking.sort(key=lambda x: (not x["compatible_discapacidad"], -x["puntaje"]))
        seleccion = ranking[: max(1, min(limite, 20))]
        return {
            "usuario": {
                "id": perfil.get("id") or usuario_id,
                "fullName": perfil.get("fullName") or "Usuario",
                "disability": discapacidad,
                "intereses_detectados": intereses,
            },
            "deportes": seleccion,
            "total_evaluados": len(ranking),
            "compatibles": sum(1 for d in ranking if d["compatible_discapacidad"]),
            "criterio": (
                "compatibilidad con discapacidad del perfil, intereses/preferencias "
                "y dificultad"
            ),
            "rf": ["RF50", "RF51"],
        }

    def _intereses(self, perfil: dict) -> list[str]:
        candidatos = []
        for clave in (
            "interests", "intereses", "preferredSports", "sportsInterest",
            "hobby", "hobbies", "preferences",
        ):
            valor = perfil.get(clave)
            if isinstance(valor, str) and valor.strip():
                candidatos.extend(normalizar(p) for p in valor.replace(";", ",").split(","))
            elif isinstance(valor, list):
                candidatos.extend(normalizar(str(v)) for v in valor)
        return [c for c in candidatos if c]
