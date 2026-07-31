"""Planes de entrenamiento multi-sesión (RF44) con progresión semanal."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.database.mongodb import get_db
from app.database.repositorio import COL_PLANES, obtener_catalogo_ejercicios
from app.motor.rutinas import generar_rutina
from app.nlp.discapacidad import canonizar
from app.services.llm_service import LLMService
from app.services.user_service import UserService

NIVELES = ("principiante", "intermedio", "avanzado")


class PlanesAgent:
    def __init__(self):
        self.user_service = UserService()
        self.llm = LLMService()

    async def generar_plan(
        self,
        usuario_id: str,
        objetivo: str = "general",
        discapacidad: Optional[str] = None,
        nivel: Optional[str] = None,
        semanas: int = 4,
        sesiones_por_semana: int = 3,
        duracion_minutos: int = 35,
        authorization: Optional[str] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        semanas = max(1, min(semanas, 8))
        sesiones_por_semana = max(2, min(sesiones_por_semana, 5))

        perfil = perfil or await self.user_service.get_user_profile(usuario_id, authorization)
        discapacidad_final = canonizar(discapacidad or perfil.get("disability") or "general")
        nivel_base = nivel or "principiante"
        if nivel_base not in NIVELES:
            nivel_base = "principiante"
        nombre = perfil.get("fullName") or "Usuario"
        catalogo = await obtener_catalogo_ejercicios()

        sesiones: list[dict[str, Any]] = []
        idx_nivel = NIVELES.index(nivel_base)
        for semana in range(1, semanas + 1):
            # Progresión suave: sube nivel a mitad de plan si hay margen.
            nivel_semana = NIVELES[min(idx_nivel + (1 if semana > semanas // 2 else 0), 2)]
            for dia in range(1, sesiones_por_semana + 1):
                semilla = hash(f"{usuario_id}-{semana}-{dia}-{objetivo}") % 10_000_000
                # Alterna énfasis: fuerza / resistencia / movilidad
                enfoque = ("fuerza", "resistencia", "movilidad")[(dia - 1) % 3]
                objetivo_sesion = objetivo if objetivo and objetivo != "general" else enfoque
                rutina = generar_rutina(
                    discapacidad=discapacidad_final,
                    objetivo_texto=objetivo_sesion,
                    tipo_texto=enfoque,
                    nivel=nivel_semana,
                    duracion_minutos=duracion_minutos + (5 if semana > 2 else 0),
                    semilla=semilla,
                    catalogo=catalogo,
                )
                sesiones.append({
                    "semana": semana,
                    "sesion": dia,
                    "enfoque": enfoque,
                    "nivel": nivel_semana,
                    "nombre": rutina["nombre"],
                    "duracion_estimada_minutos": rutina["duracion_estimada_minutos"],
                    "total_ejercicios": rutina["total_ejercicios"],
                    "bloques": rutina["bloques"],
                    "material_necesario": rutina["material_necesario"],
                    "recomendaciones": rutina["recomendaciones"][:3],
                })

        plan_id = str(uuid.uuid4())
        plan = {
            "plan_id": plan_id,
            "usuario": {
                "id": perfil.get("id") or usuario_id,
                "fullName": nombre,
                "disability": discapacidad_final,
            },
            "objetivo": objetivo,
            "nivel_inicial": nivel_base,
            "semanas": semanas,
            "sesiones_por_semana": sesiones_por_semana,
            "total_sesiones": len(sesiones),
            "sesiones": sesiones,
            "progresion": (
                f"El plan empieza en {nivel_base} y progresa en volumen/nivel "
                f"a partir de la semana {max(2, semanas // 2 + 1)}."
            ),
            "creado_en": datetime.now(timezone.utc).isoformat(),
            "fuente": "motor_local",
            "rf": "RF44",
        }
        plan["resumen"] = await self._resumen(plan, nombre)
        await self._guardar(plan)
        return plan

    async def obtener_plan(self, plan_id: str) -> Optional[dict[str, Any]]:
        db = get_db()
        if db is None:
            return None
        return await db[COL_PLANES].find_one({"plan_id": plan_id}, {"_id": 0})

    async def _resumen(self, plan: dict, nombre: str) -> str:
        base = (
            f"{nombre}, tu plan de {plan['semanas']} semanas incluye "
            f"{plan['total_sesiones']} sesiones orientadas a {plan['objetivo']}."
        )
        if not self.llm.disponible:
            return base
        prompt = (
            f"Resume en 2 frases un plan de entrenamiento inclusivo para {nombre}: "
            f"{plan['semanas']} semanas, {plan['sesiones_por_semana']} sesiones/semana, "
            f"objetivo {plan['objetivo']}, discapacidad {plan['usuario']['disability']}. "
            "Sin Markdown."
        )
        return await self.llm.texto(prompt, plan["usuario"]["disability"]) or base

    async def _guardar(self, plan: dict) -> None:
        db = get_db()
        if db is None:
            return
        try:
            await db[COL_PLANES].insert_one(dict(plan))
        except Exception as exc:
            print(f"No se pudo guardar el plan: {exc}")
