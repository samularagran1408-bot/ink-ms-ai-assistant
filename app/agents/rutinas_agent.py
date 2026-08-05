"""Agente de rutinas.

El catálogo de ejercicios es la fuente autorizada: garantiza ejercicios reales,
adaptados y con progresión coherente. El LLM, cuando está disponible, solo añade
una nota personalizada; nunca sustituye la selección de ejercicios.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Deque, Optional

from app.database.repositorio import obtener_catalogo_ejercicios
from app.motor.rutinas import generar_rutina
from app.nlp.discapacidad import canonizar
from app.services.llm_service import LLMService
from app.services.user_service import UserService

# Últimos ids de ejercicios por usuario para no devolver la misma sesión seguida
_RECIENTES: dict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=24))


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

        # Sin semilla explícita: entropía por petición (hora + usuario) para variar.
        # Con semilla fija el cliente sigue pudiendo reproducir resultados.
        semilla_efectiva = semilla
        if semilla_efectiva is None:
            semilla_efectiva = (
                abs(hash(f"{usuario_id}:{objetivo}:{tipo}:{time.time_ns()}")) % 10_000_000
            )

        catalogo = await obtener_catalogo_ejercicios()
        excluir = set(_RECIENTES.get(usuario_id) or [])
        rutina = generar_rutina(
            discapacidad=discapacidad_final,
            objetivo_texto=objetivo,
            tipo_texto=tipo,
            nivel=nivel,
            duracion_minutos=duracion_minutos,
            semilla=semilla_efectiva,
            catalogo=catalogo,
            excluir_ids=excluir,
        )

        for eid in (e.get("id") for e in rutina.get("ejercicios") or []):
            if eid:
                _RECIENTES[usuario_id].append(str(eid))

        rutina["usuario"] = {
            "id": perfil.get("id") or usuario_id,
            "fullName": nombre,
            "disability": canonizar(discapacidad_final),
            "disability_origen": discapacidad_final,
        }
        if rutina.get("interpretacion") is not None:
            rutina["interpretacion"]["semilla_efectiva"] = semilla_efectiva
            rutina["interpretacion"]["semilla_cliente"] = semilla
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
            "ni des cifras de series o repeticiones. Varía el tono; no uses siempre "
            "las mismas frases de ánimo."
        )
        return await self.llm.texto(prompt, rutina["discapacidad"], temperatura=0.85)
