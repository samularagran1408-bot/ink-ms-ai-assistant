"""Agente de quices de aptitud para organizadores y entrenadores.

Genera quizzes distintos por muestreo del banco local (sin esperar al LLM).
"""

import asyncio
import random
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from app.database.mongodb import get_db
from app.database.repositorio import COL_QUIZZES, obtener_banco_quiz
from app.services.sports_service import SportsService
from app.services.user_service import UserService

UMBRALES = {"ORGANIZADOR": 70.0, "ENTRENADOR": 75.0}
ROLES_VALIDOS = tuple(UMBRALES)
LETRAS = ("a", "b", "c", "d", "e", "f")

# Respaldo en memoria para poder evaluar aunque Mongo no esté disponible
_QUIZ_STORE: dict[str, dict[str, Any]] = {}

_REPARTO_DIFICULTAD = {
    "baja": {"facil": 0.6, "media": 0.35, "dificil": 0.05},
    "media": {"facil": 0.3, "media": 0.5, "dificil": 0.2},
    "alta": {"facil": 0.1, "media": 0.45, "dificil": 0.45},
}


class QuizAgent:
    """Orquesta generación, evaluación y persistencia de quices de aptitud."""

    def __init__(self):
        """Inicializa clientes de users y sports (el banco arma el quiz)."""
        self.user_service = UserService()
        self.sports_service = SportsService()

    # ---------------------------------------------------------------- generación

    async def generar(
        self,
        rol: str,
        usuario_id: str,
        num_preguntas: int = 8,
        dificultad: str = "media",
        semilla: Optional[int] = None,
        authorization: Optional[str] = None,
        discipline_sport_ids: Optional[list[int]] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Genera un quiz personalizado por disciplinas tras validar el prep en users.

        Exige rol ORGANIZADOR/ENTRENADOR, cuenta activa, intentos restantes y al
        menos una disciplina. Muestrea el banco local, baraja opciones y oculta
        la respuesta correcta. Sin round-trip al LLM.
        """
        rol = (rol or "").upper()
        if rol not in ROLES_VALIDOS:
            raise ValueError("El rol debe ser ORGANIZADOR o ENTRENADOR")

        umbral = UMBRALES[rol]
        perfil = perfil or {}
        prep_coro = self.user_service.get_quiz_prep_status(rol, usuario_id, authorization)
        banco_coro = obtener_banco_quiz(rol)
        if perfil:
            prep, banco = await asyncio.gather(prep_coro, banco_coro)
        else:
            perfil, prep, banco = await asyncio.gather(
                self.user_service.get_user_profile(usuario_id, authorization),
                prep_coro,
                banco_coro,
            )
        self._assert_puede_generar(perfil, prep)

        disciplina_ids = self._resolver_disciplinas(discipline_sport_ids, prep, perfil)
        if not disciplina_ids:
            raise ValueError(
                "Debes registrar al menos una disciplina en "
                "POST /api/users/verify/quiz/prep/{role}/{userId} antes de generar el quiz."
            )

        disciplinas = self._nombres_disciplinas(disciplina_ids, {"deportes": []})
        azar = random.Random(semilla)

        banco = self._priorizar_por_disciplinas(banco or [], disciplinas)
        preguntas = self._muestrear(banco, num_preguntas, dificultad, azar)

        preguntas = [self._barajar_opciones(p, azar) for p in preguntas]
        azar.shuffle(preguntas)
        for indice, pregunta in enumerate(preguntas, start=1):
            pregunta["numero"] = indice

        quiz_id = str(uuid.uuid4())
        documento = {
            "quiz_id": quiz_id,
            "rol": rol,
            "usuario_id": usuario_id,
            "umbral_aprobacion": umbral,
            "dificultad": dificultad,
            "disciplinas": disciplinas,
            "discipline_sport_ids": disciplina_ids,
            "preguntas": preguntas,
            "creado_en": datetime.now(timezone.utc).isoformat(),
            "estado": "activo",
        }
        await self._guardar_quiz(documento, bloquear=False)

        return {
            "quiz_id": quiz_id,
            "rol": rol,
            "umbral_aprobacion": umbral,
            "num_preguntas": len(preguntas),
            "preguntas": self._preguntas_publicas(preguntas),
            "contexto": {
                "preguntas_en_banco": len(banco),
                "preguntas_generadas_por_llm": 0,
                "temas": sorted({p.get("tema", "general") for p in preguntas}),
                "disciplinas": disciplinas,
                "intentos_restantes": prep.get("attemptsRemaining"),
                "deportes_disponibles": 0,
                "discapacidades_disponibles": 0,
                "eventos_referencia": 0,
            },
            "mensaje": (
                f"Quiz de aptitud para {rol} centrado en: {', '.join(disciplinas) or 'plataforma'}. "
                f"Umbral de aprobación: {umbral}%."
            ),
        }

    @staticmethod
    def _assert_puede_generar(perfil: dict, prep: dict) -> None:
        """Valida cuenta activa, intentos restantes y datos de prep antes de generar."""
        if perfil and perfil.get("isActive") is False:
            raise ValueError("No se pudo completar el acceso.")
        if prep.get("quizPassed"):
            raise ValueError("El quiz ya fue aprobado para este rol.")
        remaining = prep.get("attemptsRemaining")
        if remaining is not None and int(remaining) <= 0:
            raise ValueError("Has agotado los intentos de verificación.")
        if prep and prep.get("canStartQuiz") is False and not prep.get("quizPassed"):
            years = prep.get("experienceYears") or 0
            disciplinas = prep.get("disciplineSportIds") or []
            if not years or not disciplinas:
                raise ValueError(
                    "Completa el paso previo (años de experiencia y disciplinas) "
                    "antes de generar el quiz."
                )

    @staticmethod
    def _resolver_disciplinas(
        request_ids: Optional[list[int]], prep: dict, perfil: dict
    ) -> list[int]:
        """Obtiene IDs de disciplinas desde el request, el prep o el perfil del usuario."""
        candidatos: list[Any] = []
        if request_ids:
            candidatos = list(request_ids)
        elif prep.get("disciplineSportIds"):
            candidatos = list(prep.get("disciplineSportIds") or [])
        elif perfil.get("disciplineSportIds"):
            candidatos = list(perfil.get("disciplineSportIds") or [])
        elif perfil.get("quizDisciplines"):
            raw = str(perfil.get("quizDisciplines") or "")
            candidatos = [p.strip() for p in raw.split(",") if p.strip()]

        ids: list[int] = []
        for item in candidatos:
            try:
                valor = int(item)
            except (TypeError, ValueError):
                continue
            if valor > 0 and valor not in ids:
                ids.append(valor)
        return ids

    @staticmethod
    def _nombres_disciplinas(ids: list[int], contexto: dict) -> list[str]:
        """Traduce sport IDs a nombres usando el catálogo de deportes del contexto."""
        por_id = {
            int(d["id"]): str(d.get("nombre") or d.get("name") or "")
            for d in (contexto.get("deportes") or [])
            if d.get("id") is not None
        }
        nombres = [por_id[i] for i in ids if i in por_id and por_id[i]]
        return nombres or [f"deporte-{i}" for i in ids]

    @staticmethod
    def _priorizar_por_disciplinas(banco: list[dict], disciplinas: list[str]) -> list[dict]:
        """Ordena el banco priorizando preguntas alineadas a las disciplinas del usuario."""
        if not banco or not disciplinas:
            return banco
        claves = [d.lower() for d in disciplinas if d]

        def score(pregunta: dict) -> int:
            """Cuenta coincidencias de disciplinas en enunciado/tema y suma bonus de temas clave."""
            texto = " ".join([
                str(pregunta.get("enunciado") or ""),
                str(pregunta.get("tema") or ""),
                " ".join(str(o) for o in (pregunta.get("opciones") or [])),
            ]).lower()
            aciertos = sum(1 for c in claves if c and c in texto)
            if pregunta.get("tema") in {
                "eventos", "cupos", "roles", "verificacion", "adaptaciones",
                "catalogo", "asistencia", "seguridad", "inclusion",
            }:
                aciertos += 1
            return aciertos

        ordenadas = sorted(banco, key=score, reverse=True)
        relevantes = [p for p in ordenadas if score(p) > 0]
        return relevantes or ordenadas

    def _muestrear(
        self, banco: list[dict], cantidad: int, dificultad: str, azar: random.Random
    ) -> list[dict]:
        """Muestra equilibrada por dificultad y con temas lo más variados posible."""
        if not banco:
            return []

        proporciones = _REPARTO_DIFICULTAD.get(
            (dificultad or "media").lower(), _REPARTO_DIFICULTAD["media"]
        )
        por_dificultad: dict[str, list[dict]] = defaultdict(list)
        for pregunta in banco:
            por_dificultad[pregunta.get("dificultad", "media")].append(pregunta)
        for lista in por_dificultad.values():
            azar.shuffle(lista)

        seleccion: list[dict] = []
        for nivel, proporcion in proporciones.items():
            objetivo = round(cantidad * proporcion)
            seleccion.extend(por_dificultad.get(nivel, [])[:objetivo])

        if len(seleccion) < cantidad:
            restantes = [p for p in banco if p not in seleccion]
            azar.shuffle(restantes)
            seleccion.extend(restantes[: cantidad - len(seleccion)])

        return self._diversificar_temas(seleccion[:cantidad], azar)

    @staticmethod
    def _diversificar_temas(preguntas: list[dict], azar: random.Random) -> list[dict]:
        """Reordena para que no queden juntas varias preguntas del mismo tema."""
        por_tema: dict[str, list[dict]] = defaultdict(list)
        for pregunta in preguntas:
            por_tema[pregunta.get("tema", "general")].append(pregunta)

        temas = list(por_tema)
        azar.shuffle(temas)
        ordenadas: list[dict] = []
        while any(por_tema[t] for t in temas):
            for tema in temas:
                if por_tema[tema]:
                    ordenadas.append(por_tema[tema].pop())
        return ordenadas

    @staticmethod
    def _barajar_opciones(pregunta: dict, azar: random.Random) -> dict[str, Any]:
        """Asigna letras a las opciones en orden aleatorio y recalcula la correcta."""
        textos = list(pregunta["opciones"])
        indice_correcto = pregunta.get("correcta_indice", 0)
        emparejadas = list(enumerate(textos))
        azar.shuffle(emparejadas)

        opciones = []
        correcta = LETRAS[0]
        for posicion, (original, texto) in enumerate(emparejadas):
            letra = LETRAS[posicion]
            opciones.append({"id": letra, "texto": texto})
            if original == indice_correcto:
                correcta = letra

        return {
            "id": pregunta["id"],
            "enunciado": pregunta["enunciado"],
            "opciones": opciones,
            "correcta": correcta,
            "tema": pregunta.get("tema", "general"),
            "dificultad": pregunta.get("dificultad", "media"),
            "explicacion": pregunta.get("explicacion", ""),
            "origen": pregunta.get("origen", "banco"),
        }

    @staticmethod
    def _preguntas_publicas(preguntas: list[dict]) -> list[dict]:
        """Versión pública sin la respuesta correcta ni la explicación, para el cliente."""
        return [
            {
                "id": p["id"],
                "enunciado": p["enunciado"],
                "opciones": p["opciones"],
                "tema": p.get("tema", "general"),
            }
            for p in preguntas
        ]

    # ---------------------------------------------------------------- evaluación

    async def evaluar(
        self,
        rol: str,
        usuario_id: str,
        quiz_id: str,
        respuestas: list[dict],
        registrar_en_users: bool = True,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Evalúa respuestas, registra el score en users y calcula intentos restantes.

        Rechaza quizzes de otro rol/usuario o ya evaluados. Devuelve detalle por
        pregunta, temas a reforzar y el siguiente paso según aprobado o no.
        """
        rol = (rol or "").upper()
        if rol not in ROLES_VALIDOS:
            raise ValueError("El rol debe ser ORGANIZADOR o ENTRENADOR")
        umbral = UMBRALES[rol]

        documento = await self._cargar_quiz(quiz_id)
        if not documento:
            raise ValueError("Quiz no encontrado o expirado. Genera uno nuevo.")
        if documento.get("rol") != rol:
            raise ValueError(f"Este quiz es del rol {documento.get('rol')}, no {rol}.")
        if documento.get("usuario_id") and documento["usuario_id"] != usuario_id:
            raise ValueError("El quiz no pertenece a este usuario.")
        if documento.get("estado") == "evaluado":
            raise ValueError("Este quiz ya fue evaluado. Genera uno nuevo para reintentar.")

        elegidas = {
            str(r.get("pregunta_id")): str(r.get("opcion_id", "")).lower()
            for r in respuestas
            if isinstance(r, dict)
        }

        preguntas = documento.get("preguntas") or []
        detalle = []
        correctas = 0
        for pregunta in preguntas:
            elegida = elegidas.get(pregunta["id"])
            acierto = elegida == str(pregunta.get("correcta", "")).lower()
            correctas += int(acierto)
            detalle.append({
                "pregunta_id": pregunta["id"],
                "correcta": acierto,
                "opcion_elegida": elegida,
                "opcion_correcta": pregunta.get("correcta"),
                "explicacion": pregunta.get("explicacion"),
                "tema": pregunta.get("tema"),
            })

        total = len(preguntas) or 1
        score = round((correctas / total) * 100.0, 2)
        aprobado = score >= umbral

        registrado = False
        if registrar_en_users:
            guardar = (
                self.user_service.save_organizer_quiz_score
                if rol == "ORGANIZADOR"
                else self.user_service.save_trainer_quiz_score
            )
            registrado = await guardar(usuario_id, score, authorization)

        prep = await self.user_service.get_quiz_prep_status(rol, usuario_id, authorization)
        intentos_restantes = prep.get("attemptsRemaining")

        documento["estado"] = "evaluado"
        documento["score"] = score
        documento["evaluado_en"] = datetime.now(timezone.utc).isoformat()
        await self._guardar_quiz(documento)

        if aprobado:
            siguiente = (
                f"Quiz aprobado con {score}%. Ya puedes gestionar "
                f"{'eventos e inscritos' if rol == 'ORGANIZADOR' else 'rutinas y atletas'}."
            )
        elif intentos_restantes is not None and int(intentos_restantes) <= 0:
            siguiente = "Has agotado los intentos de verificación."
        else:
            resto = f" Te quedan {intentos_restantes} intento(s)." if intentos_restantes is not None else ""
            siguiente = (
                f"Obtuviste {score}% y el umbral es {umbral}%. "
                f"Revisa las explicaciones y genera un nuevo quiz.{resto}"
            )

        return {
            "quiz_id": quiz_id,
            "rol": rol,
            "usuario_id": usuario_id,
            "score": score,
            "correctas": correctas,
            "total": total,
            "aprobado": aprobado,
            "umbral_aprobacion": umbral,
            "detalle": detalle,
            "temas_a_reforzar": sorted({
                d["tema"] for d in detalle if not d["correcta"] and d.get("tema")
            }),
            "score_registrado_en_users": registrado,
            "siguiente_paso": siguiente,
        }

    # -------------------------------------------------------------- persistencia

    async def _guardar_quiz(self, documento: dict[str, Any], bloquear: bool = True) -> None:
        """Persiste el quiz en memoria; Mongo no bloquea la respuesta al usuario."""
        _QUIZ_STORE[documento["quiz_id"]] = documento
        if bloquear:
            await self._persistir_quiz_mongo(documento)
            return
        try:
            asyncio.get_running_loop().create_task(self._persistir_quiz_mongo(documento))
        except RuntimeError:
            await self._persistir_quiz_mongo(documento)

    async def _persistir_quiz_mongo(self, documento: dict[str, Any]) -> None:
        """Upsert en Mongo; ignora el fallo si la base no está disponible."""
        db = get_db()
        if db is None:
            return
        try:
            await db[COL_QUIZZES].replace_one(
                {"quiz_id": documento["quiz_id"]}, documento, upsert=True
            )
        except Exception as exc:
            print(f"Error guardando el quiz en MongoDB: {exc}")

    async def _cargar_quiz(self, quiz_id: str) -> Optional[dict[str, Any]]:
        """Recupera un quiz por id desde memoria o MongoDB."""
        if quiz_id in _QUIZ_STORE:
            return _QUIZ_STORE[quiz_id]
        db = get_db()
        if db is None:
            return None
        try:
            documento = await db[COL_QUIZZES].find_one({"quiz_id": quiz_id}, {"_id": 0})
        except Exception as exc:
            print(f"Error cargando el quiz de MongoDB: {exc}")
            return None
        if documento:
            _QUIZ_STORE[quiz_id] = documento
        return documento
