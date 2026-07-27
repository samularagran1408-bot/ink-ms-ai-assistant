import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.grok_service import GrokService
from app.services.user_service import UserService
from app.services.sports_service import SportsService
from app.database.mongodb import get_db


# Umbrales alineados con ink-ms-users (UserService)
UMBRAL_ORGANIZADOR = 70.0
UMBRAL_ENTRENADOR = 75.0

# Fallback en memoria si Mongo no está disponible
_QUIZ_STORE: dict[str, dict[str, Any]] = {}


ORGANIZADOR_FALLBACK = [
    {
        "id": "o1",
        "enunciado": "Al crear un evento en POST /api/events, ¿qué campo es obligatorio y debe referirse a un deporte existente?",
        "opciones": [
            {"id": "a", "texto": "createdBy"},
            {"id": "b", "texto": "sportId"},
            {"id": "c", "texto": "availableCapacity"},
            {"id": "d", "texto": "status"},
        ],
        "correcta": "b",
        "tema": "event_request",
        "explicacion": "EventRequest exige sportId válido de ink-ms-sports.",
    },
    {
        "id": "o2",
        "enunciado": "Para crear eventos, el rol JWT correcto (tras normalización en sports) es:",
        "opciones": [
            {"id": "a", "texto": "USER"},
            {"id": "b", "texto": "COACH"},
            {"id": "c", "texto": "ORGANIZER (ORGANIZADOR)"},
            {"id": "d", "texto": "GUEST"},
        ],
        "correcta": "c",
        "tema": "roles",
        "explicacion": "Solo ADMIN u ORGANIZER pueden crear eventos.",
    },
    {
        "id": "o3",
        "enunciado": "La fecha del evento (eventDate) debería ser:",
        "opciones": [
            {"id": "a", "texto": "Una fecha pasada para historial"},
            {"id": "b", "texto": "Una fecha futura válida"},
            {"id": "c", "texto": "Opcional siempre"},
            {"id": "d", "texto": "Solo el año"},
        ],
        "correcta": "b",
        "tema": "event_request",
        "explicacion": "eventDate usa validación @Future en EventRequest.",
    },
    {
        "id": "o4",
        "enunciado": "maxCapacity al crear un evento debe ser:",
        "opciones": [
            {"id": "a", "texto": "Negativo para lista de espera"},
            {"id": "b", "texto": "Cero"},
            {"id": "c", "texto": "Un entero positivo"},
            {"id": "d", "texto": "Un porcentaje"},
        ],
        "correcta": "c",
        "tema": "event_request",
        "explicacion": "maxCapacity es @Positive; availableCapacity inicia igual.",
    },
    {
        "id": "o5",
        "enunciado": "Antes de publicar un evento inclusivo, ¿qué deberías revisar en el catálogo?",
        "opciones": [
            {"id": "a", "texto": "Solo el color del logo"},
            {"id": "b", "texto": "Deportes activos y adaptaciones deporte-discapacidad"},
            {"id": "c", "texto": "Únicamente el precio de la entrada"},
            {"id": "d", "texto": "Nada; el sistema lo hace solo"},
        ],
        "correcta": "b",
        "tema": "inclusion",
        "explicacion": "GET /api/sports/active y /api/sport-disabilities/sport/{id}.",
    },
    {
        "id": "o6",
        "enunciado": "Un evento bien descrito para inclusión debe incluir principalmente:",
        "opciones": [
            {"id": "a", "texto": "Solo el nombre del organizador"},
            {"id": "b", "texto": "Ubicación accesible, horario y descripción clara de adaptaciones"},
            {"id": "c", "texto": "Únicamente el sportId"},
            {"id": "d", "texto": "Contraseñas de inscritos"},
        ],
        "correcta": "b",
        "tema": "inclusion",
        "explicacion": "location, eventTime y description orientan a participantes.",
    },
    {
        "id": "o7",
        "enunciado": "El cupo disponible (availableCapacity) al crear el evento:",
        "opciones": [
            {"id": "a", "texto": "Se envía manualmente en el request"},
            {"id": "b", "texto": "Se inicializa automáticamente con maxCapacity"},
            {"id": "c", "texto": "Siempre es ilimitado"},
            {"id": "d", "texto": "Depende del clima"},
        ],
        "correcta": "b",
        "tema": "event_service",
        "explicacion": "EventService asigna availableCapacity = maxCapacity.",
    },
    {
        "id": "o8",
        "enunciado": "Para demostrar aptitud como organizador verificado, además del quiz se exige:",
        "opciones": [
            {"id": "a", "texto": "Solo tener Instagram"},
            {"id": "b", "texto": "Eventos asistidos, evento de prueba, email/teléfono verificados y días en plataforma"},
            {"id": "c", "texto": "Únicamente pagar una membresía"},
            {"id": "d", "texto": "Nada más que el quiz"},
        ],
        "correcta": "b",
        "tema": "verificacion",
        "explicacion": "verifyOrganizer valida varios requisitos además de organizerQuizPassed.",
    },
]

ENTRENADOR_FALLBACK = [
    {
        "id": "t1",
        "enunciado": "Para registrar una adaptación deporte-discapacidad se usa:",
        "opciones": [
            {"id": "a", "texto": "POST /api/events"},
            {"id": "b", "texto": "POST /api/sport-disabilities"},
            {"id": "c", "texto": "GET /api/auth/login"},
            {"id": "d", "texto": "DELETE /api/users"},
        ],
        "correcta": "b",
        "tema": "sport_disability",
        "explicacion": "SportDisabilityController expone POST /api/sport-disabilities.",
    },
    {
        "id": "t2",
        "enunciado": "SportDisabilityRequest requiere principalmente:",
        "opciones": [
            {"id": "a", "texto": "sportId, disabilityId y texto de adaptations"},
            {"id": "b", "texto": "Solo el nombre del usuario"},
            {"id": "c", "texto": "Un QR code"},
            {"id": "d", "texto": "La fecha del evento"},
        ],
        "correcta": "a",
        "tema": "sport_disability",
        "explicacion": "Campos: sportId, disabilityId, adaptations.",
    },
    {
        "id": "t3",
        "enunciado": "Categorías típicas de discapacidad en el catálogo incluyen:",
        "opciones": [
            {"id": "a", "texto": "visual, fisica, auditiva, intelectual, multiple"},
            {"id": "b", "texto": "solo amateur y pro"},
            {"id": "c", "texto": "rojo y azul"},
            {"id": "d", "texto": "local y remoto"},
        ],
        "correcta": "a",
        "tema": "disabilities",
        "explicacion": "Disability.category usa esas categorías.",
    },
    {
        "id": "t4",
        "enunciado": "Una buena adaptación para discapacidad visual en un deporte debería:",
        "opciones": [
            {"id": "a", "texto": "Ignorar señales sonoras"},
            {"id": "b", "texto": "Incluir guías auditivas/táctiles y orientación clara"},
            {"id": "c", "texto": "Eliminar a los participantes"},
            {"id": "d", "texto": "Usar solo colores sin contraste"},
        ],
        "correcta": "b",
        "tema": "adaptaciones",
        "explicacion": "El campo adaptations describe medidas concretas de inclusión.",
    },
    {
        "id": "t5",
        "enunciado": "Al crear/actualizar un deporte (POST/PUT /api/sports), difficulty suele ser:",
        "opciones": [
            {"id": "a", "texto": "bajo, medio o alto"},
            {"id": "b", "texto": "1 a 1000 libre"},
            {"id": "c", "texto": "Solo 'extremo'"},
            {"id": "d", "texto": "No existe ese campo"},
        ],
        "correcta": "a",
        "tema": "sports",
        "explicacion": "SportRequest.difficulty: bajo|medio|alto.",
    },
    {
        "id": "t6",
        "enunciado": "¿Quién suele estar autorizado a gestionar discapacidades/adaptaciones (roles sports)?",
        "opciones": [
            {"id": "a", "texto": "Cualquier anónimo"},
            {"id": "b", "texto": "ADMIN o COACH (ENTRENADOR)"},
            {"id": "c", "texto": "Solo el gateway"},
            {"id": "d", "texto": "Únicamente el servicio de reportes"},
        ],
        "correcta": "b",
        "tema": "roles",
        "explicacion": "Escritura en disabilities/sports requiere ADMIN o COACH.",
    },
    {
        "id": "t7",
        "enunciado": "Consultar adaptaciones de un deporte concreto:",
        "opciones": [
            {"id": "a", "texto": "GET /api/sport-disabilities/sport/{sportId}"},
            {"id": "b", "texto": "GET /api/ai/chat"},
            {"id": "c", "texto": "POST /api/registrations"},
            {"id": "d", "texto": "GET /api/admin/users"},
        ],
        "correcta": "a",
        "tema": "sport_disability",
        "explicacion": "Endpoint de lectura por deporte.",
    },
    {
        "id": "t8",
        "enunciado": "Para aprobación de ENTRENADOR verificado, además del quiz (≥75) se requiere:",
        "opciones": [
            {"id": "a", "texto": "certificación, experiencia ≥6 meses, eventos como entrenador e identidad"},
            {"id": "b", "texto": "Solo un like en redes"},
            {"id": "c", "texto": "Crear 100 eventos en un día"},
            {"id": "d", "texto": "Nada más"},
        ],
        "correcta": "a",
        "tema": "verificacion",
        "explicacion": "verifyTrainer valida certificationFile, experienceMonths, eventsAsTrainer, identityDocument.",
    },
]


class QuizAgent:
    def __init__(self):
        self.grok = GrokService()
        self.user_service = UserService()
        self.sports_service = SportsService()

    async def _contexto_catalogo(self) -> dict[str, Any]:
        deportes = await self.sports_service.get_deportes_activos()
        discapacidades = await self.sports_service.get_discapacidades_activas()
        eventos = await self.sports_service.get_eventos_activos()

        adaptaciones_muestra = []
        for deporte in deportes[:5]:
            sid = deporte.get("id")
            if sid is None:
                continue
            ads = await self.sports_service.get_adaptaciones_deporte(sid)
            for a in ads[:3]:
                adaptaciones_muestra.append({
                    "sportId": sid,
                    "sportName": deporte.get("name") or a.get("sportName"),
                    "disabilityName": a.get("disabilityName"),
                    "adaptations": a.get("adaptations"),
                })

        return {
            "deportes": [
                {"id": d.get("id"), "name": d.get("name"), "difficulty": d.get("difficulty")}
                for d in deportes[:12]
            ],
            "discapacidades": [
                {"id": d.get("id"), "name": d.get("name"), "category": d.get("category")}
                for d in discapacidades[:12]
            ],
            "eventos_ejemplo": [
                {"name": e.get("name"), "sportName": e.get("sportName"), "status": e.get("status")}
                for e in eventos[:8]
            ],
            "adaptaciones_ejemplo": adaptaciones_muestra[:10],
        }

    def _public_preguntas(self, preguntas: list[dict]) -> list[dict]:
        out = []
        for p in preguntas:
            out.append({
                "id": p["id"],
                "enunciado": p["enunciado"],
                "opciones": p["opciones"],
                "tema": p.get("tema", "general"),
            })
        return out

    async def _guardar_quiz(self, doc: dict[str, Any]) -> None:
        _QUIZ_STORE[doc["quiz_id"]] = doc
        db = get_db()
        if db is not None:
            try:
                await db.quizzes_verificacion.replace_one(
                    {"quiz_id": doc["quiz_id"]},
                    doc,
                    upsert=True,
                )
            except Exception as e:
                print(f"Error guardando quiz en Mongo: {e}")

    async def _cargar_quiz(self, quiz_id: str) -> Optional[dict[str, Any]]:
        if quiz_id in _QUIZ_STORE:
            return _QUIZ_STORE[quiz_id]
        db = get_db()
        if db is not None:
            try:
                doc = await db.quizzes_verificacion.find_one({"quiz_id": quiz_id})
                if doc:
                    doc.pop("_id", None)
                    _QUIZ_STORE[quiz_id] = doc
                    return doc
            except Exception as e:
                print(f"Error cargando quiz de Mongo: {e}")
        return None

    async def _generar_con_llm(
        self,
        rol: str,
        num_preguntas: int,
        dificultad: str,
        contexto: dict[str, Any],
        perfil: dict[str, Any],
    ) -> list[dict]:
        if rol == "ORGANIZADOR":
            foco = (
                "Creación de eventos (POST /api/events, EventRequest: sportId, name, description, "
                "eventDate futura, eventTime, location, maxCapacity positivo, createdBy), "
                "roles ORGANIZADOR/ORGANIZER, cupos, inclusión y verificación de organizador."
            )
        else:
            foco = (
                "Adaptaciones (POST /api/sport-disabilities: sportId, disabilityId, adaptations), "
                "catálogo /api/sports y /api/disabilities, categorías de discapacidad, "
                "buenas prácticas inclusivas y verificación de entrenador (COACH)."
            )

        prompt = f"""
Genera un quiz de aptitud para el rol {rol} en InkluSport (deporte inclusivo).
Dificultad: {dificultad}. Exactamente {num_preguntas} preguntas de opción múltiple.
Enfoque: {foco}

Contexto real del sistema (úsalo en algunas preguntas):
{json.dumps(contexto, ensure_ascii=False, default=str)}

Usuario: {perfil.get('fullName', 'Candidato')} | discapacidad perfil: {perfil.get('disability', 'N/A')}

Entregar SOLO JSON válido (sin markdown):
{{
  "preguntas": [
    {{
      "id": "q1",
      "enunciado": "pregunta",
      "opciones": [
        {{"id": "a", "texto": "..."}},
        {{"id": "b", "texto": "..."}},
        {{"id": "c", "texto": "..."}},
        {{"id": "d", "texto": "..."}}
      ],
      "correcta": "a",
      "tema": "event_request|sport_disability|roles|inclusion|verificacion",
      "explicacion": "breve"
    }}
  ]
}}
Reglas: 4 opciones a-d; una sola correcta; español; práctico sobre APIs y buenas prácticas inclusivas.
"""
        try:
            raw = await self.grok.chat(prompt, perfil.get("disability") or "general")
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return []
            data = json.loads(match.group())
            preguntas = data.get("preguntas") or []
            validas = []
            for i, p in enumerate(preguntas):
                if not isinstance(p, dict):
                    continue
                opciones = p.get("opciones") or []
                if len(opciones) < 2 or not p.get("correcta") or not p.get("enunciado"):
                    continue
                pid = str(p.get("id") or f"q{i+1}")
                validas.append({
                    "id": pid,
                    "enunciado": p["enunciado"],
                    "opciones": [
                        {"id": str(o.get("id", "")).lower(), "texto": o.get("texto", "")}
                        for o in opciones
                        if isinstance(o, dict)
                    ],
                    "correcta": str(p["correcta"]).lower(),
                    "tema": p.get("tema") or "general",
                    "explicacion": p.get("explicacion") or "",
                })
            return validas[:num_preguntas]
        except Exception as e:
            print(f"LLM quiz falló: {e}")
            return []

    def _fallback(self, rol: str, num_preguntas: int) -> list[dict]:
        bank = ORGANIZADOR_FALLBACK if rol == "ORGANIZADOR" else ENTRENADOR_FALLBACK
        return [dict(p) for p in bank[:num_preguntas]]

    async def generar(self, rol: str, usuario_id: str, num_preguntas: int = 8, dificultad: str = "media"):
        rol = rol.upper()
        if rol not in ("ORGANIZADOR", "ENTRENADOR"):
            raise ValueError("rol debe ser ORGANIZADOR o ENTRENADOR")

        umbral = UMBRAL_ORGANIZADOR if rol == "ORGANIZADOR" else UMBRAL_ENTRENADOR
        perfil = await self.user_service.get_user_profile(usuario_id)
        contexto = await self._contexto_catalogo()

        preguntas = await self._generar_con_llm(rol, num_preguntas, dificultad, contexto, perfil)
        if len(preguntas) < max(5, num_preguntas // 2):
            preguntas = self._fallback(rol, num_preguntas)

        quiz_id = str(uuid.uuid4())
        doc = {
            "quiz_id": quiz_id,
            "rol": rol,
            "usuario_id": usuario_id,
            "umbral_aprobacion": umbral,
            "dificultad": dificultad,
            "preguntas": preguntas,
            "creado_en": datetime.now(timezone.utc).isoformat(),
            "estado": "activo",
        }
        await self._guardar_quiz(doc)

        return {
            "quiz_id": quiz_id,
            "rol": rol,
            "umbral_aprobacion": umbral,
            "num_preguntas": len(preguntas),
            "preguntas": self._public_preguntas(preguntas),
            "contexto": {
                "deportes_disponibles": len(contexto.get("deportes") or []),
                "discapacidades_disponibles": len(contexto.get("discapacidades") or []),
                "eventos_referencia": len(contexto.get("eventos_ejemplo") or []),
            },
            "mensaje": (
                f"Quiz de aptitud para {rol}. Responde con POST /api/ai/quiz/"
                f"{'organizer' if rol == 'ORGANIZADOR' else 'trainer'}/evaluar. "
                f"Umbral de aprobación: {umbral}%."
            ),
        }

    async def evaluar(
        self,
        rol: str,
        usuario_id: str,
        quiz_id: str,
        respuestas: list[dict],
        registrar_en_users: bool = True,
        authorization: Optional[str] = None,
    ):
        rol = rol.upper()
        umbral = UMBRAL_ORGANIZADOR if rol == "ORGANIZADOR" else UMBRAL_ENTRENADOR

        doc = await self._cargar_quiz(quiz_id)
        if not doc:
            raise ValueError("Quiz no encontrado o expirado. Genera uno nuevo.")
        if doc.get("rol") != rol:
            raise ValueError(f"Este quiz es de rol {doc.get('rol')}, no {rol}.")
        if doc.get("usuario_id") and doc["usuario_id"] != usuario_id:
            raise ValueError("El quiz no pertenece a este usuario.")

        mapa_resp = {
            str(r.get("pregunta_id")): str(r.get("opcion_id", "")).lower()
            for r in respuestas
            if isinstance(r, dict)
        }

        detalle = []
        correctas = 0
        preguntas = doc.get("preguntas") or []
        for p in preguntas:
            pid = p["id"]
            elegida = mapa_resp.get(pid)
            ok = elegida == str(p.get("correcta", "")).lower()
            if ok:
                correctas += 1
            detalle.append({
                "pregunta_id": pid,
                "correcta": ok,
                "opcion_elegida": elegida,
                "opcion_correcta": p.get("correcta"),
                "explicacion": p.get("explicacion"),
                "tema": p.get("tema"),
            })

        total = len(preguntas) or 1
        score = round((correctas / total) * 100.0, 2)
        aprobado = score >= umbral

        score_ok = False
        if registrar_en_users:
            if rol == "ORGANIZADOR":
                score_ok = await self.user_service.save_organizer_quiz_score(
                    usuario_id, score, authorization
                )
            else:
                score_ok = await self.user_service.save_trainer_quiz_score(
                    usuario_id, score, authorization
                )

        doc["estado"] = "evaluado"
        doc["score"] = score
        doc["evaluado_en"] = datetime.now(timezone.utc).isoformat()
        await self._guardar_quiz(doc)

        if aprobado:
            siguiente = (
                f"Quiz aprobado. Completa el resto de requisitos y llama "
                f"POST /api/users/verify/{'organizer' if rol == 'ORGANIZADOR' else 'trainer'}/{usuario_id}"
            )
        else:
            siguiente = (
                f"No alcanzó el umbral ({umbral}%). Genera un nuevo quiz y vuelve a intentarlo."
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
            "score_registrado_en_users": score_ok,
            "siguiente_paso": siguiente,
        }
