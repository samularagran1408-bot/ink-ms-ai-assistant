from app.services.grok_service import GrokService
from app.services.user_service import UserService
import json
import re


class RutinasAgent:
    def __init__(self):
        self.grok = GrokService()
        self.user_service = UserService()

    async def generar_rutina(self, usuario_id: str, tipo: str, objetivo: str, discapacidad: str):
        user_data = await self.user_service.get_user_profile(usuario_id)
        discapacidad_perfil = discapacidad or user_data.get("disability") or "general"
        nombre = user_data.get("fullName") or "Usuario"

        prompt = f"""
        Genera una rutina de ejercicio profesional para un usuario con:
        - Nombre: {nombre}
        - Discapacidad: {discapacidad_perfil}
        - Objetivo: {objetivo}
        - Tipo: {tipo}

        La rutina debe incluir 6-8 ejercicios con: nombre, repeticiones, series,
        tiempo estimado (segundos), adaptaciones específicas a la discapacidad, esfuerzo (1-5), descanso (segundos).

        Entregar SOLO JSON válido (sin markdown):
        {{
            "nombre": "Rutina personalizada",
            "ejercicios": [
                {{
                    "nombre": "Ejercicio 1",
                    "repeticiones": 12,
                    "series": 3,
                    "tiempo_estimado": 45,
                    "adaptaciones": "Descripción de la adaptación",
                    "esfuerzo": 3,
                    "descanso": 60
                }}
            ],
            "objetivo": "Descripción del objetivo",
            "recomendaciones": "Recomendaciones para la ejecución"
        }}
        """

        respuesta = None
        try:
            respuesta = await self.grok.chat(prompt, discapacidad_perfil)
        except Exception as e:
            print(f"Grok no disponible para rutinas: {e}")

        if respuesta:
            try:
                json_match = re.search(r"\{.*\}", respuesta, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    if isinstance(data, dict) and data.get("ejercicios"):
                        data["usuario"] = {
                            "id": user_data.get("id") or usuario_id,
                            "fullName": nombre,
                            "disability": discapacidad_perfil,
                        }
                        return data
            except Exception:
                pass

        return {
            "nombre": f"Rutina {tipo} para {discapacidad_perfil}",
            "ejercicios": [
                {
                    "nombre": "Movilidad articular adaptada",
                    "repeticiones": 10,
                    "series": 3,
                    "tiempo_estimado": 30,
                    "adaptaciones": f"Ajustar rango de movimiento según {discapacidad_perfil}",
                    "esfuerzo": 2,
                    "descanso": 45,
                },
                {
                    "nombre": "Fortalecimiento funcional",
                    "repeticiones": 8,
                    "series": 3,
                    "tiempo_estimado": 40,
                    "adaptaciones": "Usar soporte o asistencia según necesidad",
                    "esfuerzo": 3,
                    "descanso": 60,
                },
                {
                    "nombre": "Estiramiento suave",
                    "repeticiones": 6,
                    "series": 2,
                    "tiempo_estimado": 45,
                    "adaptaciones": "Sin dolor; priorizar comodidad y control",
                    "esfuerzo": 1,
                    "descanso": 30,
                },
            ],
            "objetivo": objetivo,
            "recomendaciones": "Consulta a tu entrenador para una rutina personalizada. Detén el ejercicio si sientes dolor.",
            "usuario": {
                "id": user_data.get("id") or usuario_id,
                "fullName": nombre,
                "disability": discapacidad_perfil,
            },
        }
