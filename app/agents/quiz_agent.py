"""
/**
 * Agente de quices de aptitud para organizadores y entrenadores.
 * Genera quizzes distintos por muestreo del banco, disciplinas y (opcional) LLM.
 */
"""

import json
import random
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from app.database.mongodb import get_db
from app.database.repositorio import COL_QUIZZES, obtener_banco_quiz
from app.services.llm_service import LLMService
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
    """
    /**
     * Orquesta generación, evaluación y persistencia de quices de aptitud.
     */
    """

    def __init__(self):
        """
        /**
         * Inicializa dependencias de LLM, users y sports.
         */
        """
        self.llm = LLMService()
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
    ) -> dict[str, Any]:
        """
        /**
         * Genera un quiz personalizado por disciplinas tras validar el prep en users.
         */
        """
        rol = (rol or "").upper()
        if rol not in ROLES_VALIDOS:
            raise ValueError("El rol debe ser ORGANIZADOR o ENTRENADOR")

        umbral = UMBRALES[rol]
        perfil = await self.user_service.get_user_profile(usuario_id, authorization)
        prep = await self.user_service.get_quiz_prep_status(rol, usuario_id, authorization)
        self._assert_puede_generar(perfil, prep)

        disciplina_ids = self._resolver_disciplinas(discipline_sport_ids, prep, perfil)
        if not disciplina_ids:
            raise ValueError(
                "Debes registrar al menos una disciplina en "
                "POST /api/users/verify/quiz/prep/{role}/{userId} antes de generar el quiz."
            )

        contexto = await self._contexto_catalogo(authorization)
        disciplinas = self._nombres_disciplinas(disciplina_ids, contexto)
        azar = random.Random(semilla)

        banco = await obtener_banco_quiz(rol)
        banco = self._priorizar_por_disciplinas(banco, disciplinas)
        preguntas = self._muestrear(banco, num_preguntas, dificultad, azar)

        generadas = await self._preguntas_llm(rol, contexto, perfil, disciplinas, azar)
        if generadas:
            preguntas = self._mezclar_fuentes(preguntas, generadas, num_preguntas, azar)

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
        await self._guardar_quiz(documento)

        return {
            "quiz_id": quiz_id,
            "rol": rol,
            "umbral_aprobacion": umbral,
            "num_preguntas": len(preguntas),
            "preguntas": self._preguntas_publicas(preguntas),
            "contexto": {
                "preguntas_en_banco": len(banco),
                "preguntas_generadas_por_llm": sum(
                    1 for p in preguntas if p.get("origen") == "llm"
                ),
                "temas": sorted({p.get("tema", "general") for p in preguntas}),
                "disciplinas": disciplinas,
                "intentos_restantes": prep.get("attemptsRemaining"),
                "deportes_disponibles": len(contexto.get("deportes") or []),
                "discapacidades_disponibles": len(contexto.get("discapacidades") or []),
                "eventos_referencia": len(contexto.get("eventos_ejemplo") or []),
            },
            "mensaje": (
                f"Quiz de aptitud para {rol} centrado en: {', '.join(disciplinas) or 'plataforma'}. "
                f"Umbral de aprobación: {umbral}%."
            ),
        }

    @staticmethod
    def _assert_puede_generar(perfil: dict, prep: dict) -> None:
        """
        /**
         * Valida cuenta activa, intentos restantes y datos de prep antes de generar.
         */
        """
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
        """
        /**
         * Obtiene IDs de disciplinas desde el request, el prep o el perfil del usuario.
         */
        """
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
        """
        /**
         * Traduce sport IDs a nombres usando el catálogo de deportes del contexto.
         */
        """
        por_id = {
            int(d["id"]): str(d.get("nombre") or d.get("name") or "")
            for d in (contexto.get("deportes") or [])
            if d.get("id") is not None
        }
        nombres = [por_id[i] for i in ids if i in por_id and por_id[i]]
        return nombres or [f"deporte-{i}" for i in ids]

    @staticmethod
    def _priorizar_por_disciplinas(banco: list[dict], disciplinas: list[str]) -> list[dict]:
        """
        /**
         * Ordena el banco priorizando preguntas alineadas a las disciplinas del usuario.
         */
        """
        if not banco or not disciplinas:
            return banco
        claves = [d.lower() for d in disciplinas if d]

        def score(pregunta: dict) -> int:
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
        """
        /**
         * Muestra equilibrada por dificultad y con temas lo más variados posible.
         */
        """
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
        """
        /**
         * Reordena para que no queden juntas varias preguntas del mismo tema.
         */
        """
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
    def _mezclar_fuentes(
        banco: list[dict], generadas: list[dict], cantidad: int, azar: random.Random
    ) -> list[dict]:
        """
        /**
         * Reserva hasta un tercio del quiz a preguntas del LLM.
         */
        """
        cupo_llm = min(len(generadas), max(1, cantidad // 3))
        elegidas = azar.sample(generadas, cupo_llm)
        return (banco[: cantidad - cupo_llm]) + elegidas

    @staticmethod
    def _barajar_opciones(pregunta: dict, azar: random.Random) -> dict[str, Any]:
        """
        /**
         * Asigna letras a las opciones en orden aleatorio y recalcula la correcta.
         */
        """
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
        """
        /**
         * Versión pública sin la respuesta correcta para enviar al cliente.
         */
        """
        return [
            {
                "id": p["id"],
                "enunciado": p["enunciado"],
                "opciones": p["opciones"],
                "tema": p.get("tema", "general"),
            }
            for p in preguntas
        ]

    # ---------------------------------------------------------------------- LLM

    async def _preguntas_llm(
        self,
        rol: str,
        contexto: dict,
        perfil: dict,
        disciplinas: list[str],
        azar: random.Random,
    ) -> list[dict]:
        """
        /**
         * Pide al LLM preguntas acotadas a las disciplinas del usuario (opcional).
         */
        """
        if not self.llm.disponible:
            return []

        disciplinas_txt = ", ".join(disciplinas) if disciplinas else "deportes inclusivos"
        if rol == "ORGANIZADOR":
            foco = (
                f"creación y gestión de eventos inclusivos en estas disciplinas: {disciplinas_txt}. "
                "Campos obligatorios, fechas futuras, cupos, lista de espera, estados del evento "
                "y adaptaciones reales de esos deportes"
            )
        else:
            foco = (
                f"adaptaciones y planificación segura para estas disciplinas: {disciplinas_txt}. "
                "Catálogo deporte-discapacidad, material y riesgos típicos de esas modalidades"
            )

        # Recorta el contexto a las disciplinas del usuario para reducir alucinaciones
        deportes_filtrados = [
            d for d in (contexto.get("deportes") or [])
            if str(d.get("nombre") or "").lower() in {x.lower() for x in disciplinas}
        ] or (contexto.get("deportes") or [])[:6]
        adaptaciones_filtradas = [
            a for a in (contexto.get("adaptaciones_ejemplo") or [])
            if str(a.get("deporte") or "").lower() in {x.lower() for x in disciplinas}
        ] or (contexto.get("adaptaciones_ejemplo") or [])[:6]
        contexto_acotado = {
            "disciplinas_usuario": disciplinas,
            "deportes": deportes_filtrados,
            "adaptaciones_ejemplo": adaptaciones_filtradas,
            "discapacidades": (contexto.get("discapacidades") or [])[:8],
        }

        prompt = f"""
Genera 4 preguntas de opción múltiple en español para evaluar aptitud del rol {rol}
en InkluSport (plataforma de deporte inclusivo). Enfoque: {foco}.

Usa SOLO hechos coherentes con este contexto (no inventes deportes ajenos):
{json.dumps(contexto_acotado, ensure_ascii=False, default=str)}

Devuelve SOLO JSON válido, sin markdown:
{{"preguntas": [{{"enunciado": "...", "opciones": ["...", "...", "...", "..."],
 "correcta_indice": 0, "tema": "eventos", "explicacion": "...", "dificultad": "media"}}]}}

Reglas: exactamente 4 opciones por pregunta, una sola correcta,
`correcta_indice` es la posición (0-3) de la opción correcta.
No menciones deportes fuera de: {disciplinas_txt}.
"""
        datos = await self.llm.json_dict(prompt, perfil.get("disability") or "general")
        if not datos:
            return []

        validas = []
        for posicion, cruda in enumerate(datos.get("preguntas") or []):
            pregunta = self._validar_pregunta_llm(cruda, posicion, azar)
            if pregunta:
                validas.append(pregunta)
        return validas

    @staticmethod
    def _validar_pregunta_llm(
        cruda: Any, posicion: int, azar: random.Random
    ) -> Optional[dict]:
        """
        /**
         * Valida y normaliza una pregunta cruda del LLM; descarta formatos inválidos.
         */
        """
        if not isinstance(cruda, dict):
            return None
        enunciado = str(cruda.get("enunciado") or "").strip()
        opciones = cruda.get("opciones") or []

        # Se acepta también el formato con objetos {"id": "a", "texto": "..."}
        if opciones and isinstance(opciones[0], dict):
            letras = [str(o.get("id", "")).lower() for o in opciones]
            opciones = [str(o.get("texto", "")).strip() for o in opciones]
            correcta = str(cruda.get("correcta", "")).lower()
            indice = letras.index(correcta) if correcta in letras else 0
        else:
            opciones = [str(o).strip() for o in opciones]
            try:
                indice = int(cruda.get("correcta_indice", 0))
            except (TypeError, ValueError):
                return None

        if not enunciado or len(opciones) < 3 or not all(opciones):
            return None
        if not 0 <= indice < len(opciones):
            return None

        return {
            "id": f"g{azar.randrange(1000, 9999)}{posicion}",
            "enunciado": enunciado,
            "opciones": opciones,
            "correcta_indice": indice,
            "tema": str(cruda.get("tema") or "general"),
            "dificultad": str(cruda.get("dificultad") or "media"),
            "explicacion": str(cruda.get("explicacion") or ""),
            "origen": "llm",
        }

    async def _contexto_catalogo(self, authorization: Optional[str]) -> dict[str, Any]:
        """
        /**
         * Construye contexto real (deportes, discapacidades, adaptaciones, eventos).
         */
        """
        deportes = await self.sports_service.get_deportes_activos(authorization)
        discapacidades = await self.sports_service.get_discapacidades_activas(authorization)
        eventos = await self.sports_service.get_eventos_activos(authorization)

        adaptaciones = []
        for deporte in deportes[:5]:
            sport_id = deporte.get("id")
            if sport_id is None:
                continue
            for adaptacion in (
                await self.sports_service.get_adaptaciones_deporte(sport_id, authorization)
            )[:3]:
                adaptaciones.append({
                    "deporte": deporte.get("name") or adaptacion.get("sportName"),
                    "discapacidad": adaptacion.get("disabilityName"),
                    "adaptacion": adaptacion.get("adaptations"),
                })

        return {
            "deportes": [
                {"id": d.get("id"), "nombre": d.get("name"), "dificultad": d.get("difficulty")}
                for d in deportes[:12]
            ],
            "discapacidades": [
                {"nombre": d.get("name"), "categoria": d.get("category")}
                for d in discapacidades[:12]
            ],
            "eventos_ejemplo": [
                {"nombre": e.get("name"), "deporte": e.get("sportName"), "estado": e.get("status")}
                for e in eventos[:8]
            ],
            "adaptaciones_ejemplo": adaptaciones[:10],
        }

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
        """
        /**
         * Evalúa respuestas, registra score en users y calcula intentos restantes.
         */
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

    async def _guardar_quiz(self, documento: dict[str, Any]) -> None:
        """
        /**
         * Persiste el quiz en memoria y, si hay Mongo, en la colección de quizzes.
         */
        """
        _QUIZ_STORE[documento["quiz_id"]] = documento
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
        """
        /**
         * Recupera un quiz por id desde memoria o MongoDB.
         */
        """
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
