"""Agente de rutinas.

El catálogo de ejercicios es la fuente autorizada: garantiza ejercicios reales,
adaptados y con progresión coherente. El LLM, cuando está disponible, solo añade
una nota personalizada; nunca sustituye la selección de ejercicios.
"""

from typing import Any, Optional

from app.database.repositorio import obtener_catalogo_ejercicios
from app.motor.rutinas import generar_rutina
from app.nlp.discapacidad import canonizar
from app.services.llm_service import LLMService
from app.services.user_service import UserService


class RutinasAgent:
    def __init__(self):
        self.llm = LLMService()
        self.user_service = UserService()

    async def generar_rutina(
        self,
        usuario_id: str,
        tipo: str,
        objetivo: str,
        discapacidad: str,
        nivel: Optional[str] = None,
        duracion_minutos: int = 35,
        semilla: Optional[int] = None,
        authorization: Optional[str] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        perfil = perfil or await self.user_service.get_user_profile(usuario_id, authorization)
        discapacidad_final = discapacidad or perfil.get("disability") or "general"
        nombre = perfil.get("fullName") or "Usuario"

        catalogo = await obtener_catalogo_ejercicios()
        rutina = generar_rutina(
            discapacidad=discapacidad_final,
            objetivo_texto=objetivo,
            tipo_texto=tipo,
            nivel=nivel,
            duracion_minutos=duracion_minutos,
            semilla=semilla,
            catalogo=catalogo,
        )

        rutina["usuario"] = {
            "id": perfil.get("id") or usuario_id,
            "fullName": nombre,
            "disability": canonizar(discapacidad_final),
            "disability_origen": discapacidad_final,
        }
        rutina["nota_personalizada"] = await self._nota_personalizada(rutina, nombre)
        return rutina

    async def _nota_personalizada(self, rutina: dict, nombre: str) -> Optional[str]:
        """Comentario de acompañamiento generado por el LLM, si está disponible."""
        if not self.llm.disponible:
            return None

        listado = ", ".join(e["nombre"] for e in rutina["ejercicios"])
        prompt = (
            f"Escribe en 3 frases una nota de acompañamiento para {nombre}, que va a "
            f"realizar esta sesión: {listado}. Objetivo: {rutina['objetivo']}. "
            f"Nivel: {rutina['nivel']}. No inventes ejercicios distintos a los listados "
            "ni des cifras de series o repeticiones."
        )
        return await self.llm.texto(prompt, rutina["discapacidad"])
