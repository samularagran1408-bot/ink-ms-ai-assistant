"""Agente de rutinas.

El catálogo de ejercicios es la fuente autorizada: garantiza ejercicios reales,
adaptados y con progresión coherente. La nota de acompañamiento es local para
no bloquear la respuesta esperando al LLM.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Deque, Optional

from app.database.repositorio import obtener_catalogo_ejercicios
from app.motor.rutinas import generar_rutina
from app.nlp.discapacidad import canonizar
from app.services.user_service import UserService

# Últimos ids de ejercicios por usuario para no devolver la misma sesión seguida
_RECIENTES: dict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=24))


class RutinasAgent:
    """Genera sesiones a partir del catálogo de ejercicios adaptados (RF41)."""

    def __init__(self):
        """Inicializa el cliente de users (el catálogo arma la sesión)."""
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
        """Arma una rutina del catálogo adaptada a discapacidad, objetivo y nivel.

        Sin `semilla` varía los ejercicios (evita repetir los 24 últimos del usuario).
        `nota_personalizada` es local: no espera al proveedor LLM.
        """
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
        rutina["nota_personalizada"] = self._nota_personalizada(rutina, nombre)
        return rutina

    def _nota_personalizada(self, rutina: dict, nombre: str) -> str:
        """Nota de acompañamiento local (sin round-trip al LLM)."""
        pedido = rutina.get("objetivo_pedido") or rutina.get("objetivo") or "tu objetivo"
        minutos = rutina.get("duracion_estimada_minutos") or 35
        nivel = rutina.get("nivel") or "principiante"
        return (
            f"{nombre}, sesión de {minutos} min en nivel {nivel}, "
            f"orientada a {pedido}. Sigue las consignas y detente si aparece dolor."
        )
