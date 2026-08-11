"""Cliente LLM opcional, compatible con APIs estilo OpenAI.

Soporta Ollama (servidor local, sin clave) y proveedores en la nube: OpenAI,
xAI (Grok), OpenRouter, DeepSeek, Mistral, Together y Groq. Se elige con
LLM_PROVIDER o se deduce del prefijo de LLM_API_KEY.

El servicio completo funciona sin LLM: los agentes usan su motor local y, cuando
el proveedor responde, lo aprovechan para redactar respuestas más ricas.

Incluye un cortacircuitos compartido: si el proveedor falla, se deja de
intentar durante `LLM_COOLDOWN_SEGUNDOS`, de modo que un proveedor inaccesible
no añade latencia a cada petición.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.config import settings


@dataclass
class ChatCompletionResult:
    """Respuesta de /chat/completions (texto y/o tool_calls)."""

    content: Optional[str] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    modelo_usado: Optional[str] = None

    @property
    def tiene_tools(self) -> bool:
        return bool(self.tool_calls)

CONTEXTO_DISCAPACIDAD = {
    "visual": "Describe todo verbalmente. Evita referencias como 'mira' u 'observa'.",
    "auditiva": "Usa lenguaje claro y directo. Evita referencias a sonidos.",
    "cognitiva": "Usa frases cortas y lenguaje simple. Organiza la información en pasos.",
    "intelectual": "Usa frases cortas, una idea por frase, y repite lo importante.",
    "motriz": "Enfócate en adaptaciones físicas, apoyos y accesibilidad.",
    "multiple": "Combina apoyos verbales, visuales y de simplificación.",
    "general": "Sé claro, inclusivo y concreto.",
}

# Proveedores soportados. Todos hablan el dialecto /v1/chat/completions de OpenAI,
# así que solo cambian la URL, el modelo por defecto y si piden clave.
PERFILES: dict[str, dict[str, Any]] = {
    "ollama": {
        "nombre": "ollama",
        "dominio": "11434",
        "url": "http://ollama:11434/v1/chat/completions",
        "modelo": "qwen2.5:3b",
        "modelo_valido": lambda m: True,
    },
    "groq": {
        "nombre": "groq",
        "dominio": "groq.com",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "modelo": "llama-3.3-70b-versatile",
        "modelo_valido": lambda m: not m.startswith(("grok", "gpt")),
    },
    "xai": {
        "nombre": "xai",
        "dominio": "x.ai",
        "url": "https://api.x.ai/v1/chat/completions",
        # 4.3: mejor ratio calidad/precio para chat de producto; 4.5 solo si se fuerza.
        "modelo": "grok-4.3",
        "modelo_valido": lambda m: m.startswith("grok"),
    },
    "openai": {
        "nombre": "openai",
        "dominio": "openai.com",
        "url": "https://api.openai.com/v1/chat/completions",
        "modelo": "gpt-4o-mini",
        "modelo_valido": lambda m: m.startswith(("gpt", "o1", "o3", "o4")),
    },
    # Pasarela hacia muchos modelos, con opciones gratuitas (sufijo ":free").
    "openrouter": {
        "nombre": "openrouter",
        "dominio": "openrouter.ai",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        # Enruta entre modelos :free; evita clavar uno saturado (p. ej. Gemma 429).
        "modelo": "openrouter/free",
        # Aquí los modelos se nombran "proveedor/modelo".
        "modelo_valido": lambda m: "/" in m,
    },
    "deepseek": {
        "nombre": "deepseek",
        "dominio": "deepseek.com",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "modelo": "deepseek-chat",
        "modelo_valido": lambda m: m.startswith("deepseek"),
    },
    "mistral": {
        "nombre": "mistral",
        "dominio": "mistral.ai",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "modelo": "mistral-small-latest",
        "modelo_valido": lambda m: m.startswith(("mistral", "open-mistral", "ministral")),
    },
    "together": {
        "nombre": "together",
        "dominio": "together.xyz",
        "url": "https://api.together.xyz/v1/chat/completions",
        "modelo": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        "modelo_valido": lambda m: "/" in m,
    },
}

# El orden importa: "sk-or-" (OpenRouter) debe comprobarse antes que "sk-" (OpenAI).
# Los proveedores cuya clave no tiene prefijo distintivo (Mistral, Together,
# DeepSeek) se seleccionan con LLM_PROVIDER.
_POR_PREFIJO_CLAVE = {
    "sk-or-": "openrouter",
    "gsk_": "groq",
    "xai-": "xai",
    "sk-": "openai",
}

# Proveedores que no piden cabecera Authorization
_SIN_CLAVE = ("ollama",)

_ANFITRIONES_LOCALES = ("ollama", "localhost", "127.0.0.1", "host.docker.internal", ":11434")

# Si el modelo free elegido está saturado upstream (429), se prueba esta lista.
# `openrouter/free` ya reparte entre free; los demás son respaldo explícito.
_FALLBACKS_OPENROUTER = (
    "openrouter/free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "inclusionai/ling-3.0-flash:free",
)


def _es_url_local(url: str) -> bool:
    return bool(url) and any(a in url for a in _ANFITRIONES_LOCALES)


def _es_rate_limit(status: int, cuerpo: str) -> bool:
    if status == 429:
        return True
    bajo = (cuerpo or "").lower()
    return "rate-limited" in bajo or "rate limit" in bajo


def _es_tools_no_soportado(status: int, cuerpo: str) -> bool:
    """Algunos modelos free rechazan el campo tools con 400/404."""
    if status not in (400, 404, 422):
        return False
    bajo = (cuerpo or "").lower()
    return any(
        t in bajo
        for t in (
            "tool",
            "function calling",
            "functions are not supported",
            "does not support",
            "unsupported",
        )
    )


class LLMService:
    # Estado compartido por todas las instancias (una por agente)
    _bloqueado_hasta: float = 0.0
    _ultimo_error: Optional[str] = None
    _ultimo_exito: Optional[float] = None
    _llamadas_ok: int = 0
    _llamadas_fallidas: int = 0

    def __init__(self):
        self.api_key = (settings.LLM_API_KEY or "").strip()
        self.model = (settings.LLM_MODEL or "").strip()
        self.api_url = (settings.LLM_API_URL or "").strip()
        self.habilitado = settings.LLM_ENABLED
        self.timeout = settings.LLM_TIMEOUT
        self._ajustar_proveedor()

    def _ajustar_proveedor(self) -> None:
        """Resuelve proveedor, URL y modelo de forma coherente entre sí."""
        forzado = (settings.LLM_PROVIDER or "auto").lower()
        perfil = PERFILES.get(forzado) if forzado != "auto" else None

        if perfil is None:
            for prefijo, nombre in _POR_PREFIJO_CLAVE.items():
                if self.api_key.startswith(prefijo):
                    perfil = PERFILES[nombre]
                    break

        # Sin clave y con URL a un servidor local: es un Ollama (u otro
        # servidor compatible) que no pide autenticación.
        if perfil is None and _es_url_local(self.api_url):
            perfil = PERFILES["ollama"]

        if perfil is None:
            self.proveedor = "personalizado" if self.api_key else "sin_configurar"
            return

        self.proveedor = perfil["nombre"]
        if not self.api_url or perfil["dominio"] not in self.api_url:
            self.api_url = perfil["url"]
        if not self.model or not perfil["modelo_valido"](self.model):
            self.model = perfil["modelo"]

    @property
    def requiere_clave(self) -> bool:
        """Los servidores locales no autentican; los proveedores en la nube sí."""
        return self.proveedor not in _SIN_CLAVE

    @property
    def is_configured(self) -> bool:
        if not self.habilitado:
            return False
        if self.requiere_clave:
            return bool(self.api_key)
        return bool(self.api_url and self.model)

    @property
    def disponible(self) -> bool:
        """Configurado y sin cortacircuitos activo."""
        return self.is_configured and time.monotonic() >= LLMService._bloqueado_hasta

    @classmethod
    def _registrar_fallo(cls, error: str) -> None:
        cls._ultimo_error = error[:300]
        cls._llamadas_fallidas += 1
        cls._bloqueado_hasta = time.monotonic() + settings.LLM_COOLDOWN_SEGUNDOS

    @classmethod
    def _registrar_exito(cls) -> None:
        cls._ultimo_error = None
        cls._llamadas_ok += 1
        cls._ultimo_exito = time.time()
        cls._bloqueado_hasta = 0.0

    async def chat(
        self,
        prompt: str,
        disability_type: str = "general",
        sistema_extra: str = "",
        temperatura: float = 0.7,
    ) -> str:
        """Consulta al proveedor. Lanza excepción si no está disponible o falla."""
        return await self.chat_mensajes(
            [
                {"role": "system", "content": system_prompt(disability_type, sistema_extra)},
                {"role": "user", "content": prompt},
            ],
            temperatura=temperatura,
        )

    def _modelos_a_probar(self) -> list[str]:
        """Modelo configurado primero; en OpenRouter, fallbacks si hay 429 upstream."""
        primario = self.model
        if self.proveedor != "openrouter" or not primario:
            return [primario] if primario else []
        extras = [m for m in _FALLBACKS_OPENROUTER if m != primario]
        return [primario, *extras]

    def _validar_listo(self) -> None:
        if not self.habilitado:
            raise RuntimeError("LLM deshabilitado (LLM_ENABLED=false)")
        if self.requiere_clave and not self.api_key:
            raise RuntimeError("LLM sin clave configurada (LLM_API_KEY)")
        if not self.api_url or not self.model:
            raise RuntimeError("LLM sin URL o modelo configurados")
        if time.monotonic() < LLMService._bloqueado_hasta:
            restante = int(LLMService._bloqueado_hasta - time.monotonic())
            raise RuntimeError(
                f"LLM en pausa {restante}s tras un fallo previo: {LLMService._ultimo_error}"
            )

    @staticmethod
    def _parsear_mensaje(mensaje: dict[str, Any]) -> ChatCompletionResult:
        contenido = mensaje.get("content")
        if isinstance(contenido, list):
            # Algunos proveedores devuelven content como lista de bloques
            partes = []
            for bloque in contenido:
                if isinstance(bloque, dict) and bloque.get("type") == "text":
                    partes.append(str(bloque.get("text") or ""))
                elif isinstance(bloque, str):
                    partes.append(bloque)
            contenido = "\n".join(p for p in partes if p) or None
        elif contenido is not None:
            contenido = str(contenido)

        tool_calls_raw = mensaje.get("tool_calls") or []
        tool_calls: list[dict[str, Any]] = []
        for tc in tool_calls_raw:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            tool_calls.append(
                {
                    "id": tc.get("id") or f"call_{len(tool_calls)}",
                    "type": tc.get("type") or "function",
                    "function": {
                        "name": (fn.get("name") or "").strip(),
                        "arguments": fn.get("arguments") or "{}",
                    },
                }
            )
        return ChatCompletionResult(content=contenido, tool_calls=tool_calls)

    async def completar(
        self,
        mensajes: list[dict[str, Any]],
        *,
        temperatura: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> ChatCompletionResult:
        """Llama al proveedor y devuelve texto y/o tool_calls."""
        self._validar_listo()
        headers = self._headers()
        ultimo_error = ""
        modelos = self._modelos_a_probar()
        usar_tools = bool(tools)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i, modelo in enumerate(modelos):
                payload: dict[str, Any] = {
                    "messages": mensajes,
                    "model": modelo,
                    "temperature": temperatura,
                    "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
                }
                if usar_tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = tool_choice or "auto"

                try:
                    respuesta = await client.post(
                        self.api_url, headers=headers, json=payload
                    )
                except Exception as exc:
                    self._registrar_fallo(f"{type(exc).__name__}: {exc}")
                    raise RuntimeError(f"LLM inaccesible: {exc}") from exc

                if respuesta.status_code < 400:
                    try:
                        mensaje = respuesta.json()["choices"][0]["message"]
                        resultado = self._parsear_mensaje(mensaje)
                    except Exception as exc:
                        self._registrar_fallo(f"Respuesta inesperada: {exc}")
                        raise RuntimeError(
                            f"Respuesta del LLM no interpretable: {exc}"
                        ) from exc
                    resultado.modelo_usado = modelo
                    self._registrar_exito()
                    if modelo != self.model:
                        print(f"LLM: {self.model} falló; respondió {modelo}")
                    return resultado

                detalle = respuesta.text[:300]
                ultimo_error = f"HTTP {respuesta.status_code}: {detalle}"
                # Modelo sin soporte de tools: no activar cortacircuitos global
                # (el chat puede seguir usando LLM sin tools / motor local).
                if usar_tools and _es_tools_no_soportado(respuesta.status_code, detalle):
                    raise RuntimeError(f"LLM sin soporte de tools: {ultimo_error}")
                if (
                    _es_rate_limit(respuesta.status_code, detalle)
                    and i < len(modelos) - 1
                ):
                    print(f"LLM {modelo} rate-limited; probando alternativa...")
                    continue
                self._registrar_fallo(ultimo_error)
                raise RuntimeError(f"LLM {ultimo_error}")

        self._registrar_fallo(ultimo_error or "sin modelos")
        raise RuntimeError(f"LLM {ultimo_error or 'sin respuesta'}")

    async def chat_mensajes(
        self,
        mensajes: list[dict[str, Any]],
        temperatura: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> str:
        """Consulta al LLM; si hay tools, ignora tool_calls y solo devuelve texto."""
        resultado = await self.completar(
            mensajes,
            temperatura=temperatura,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        if resultado.content:
            return resultado.content
        if resultado.tiene_tools:
            raise RuntimeError(
                "El modelo devolvió tool_calls sin texto; usa completar() en el orquestador"
            )
        return ""

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.proveedor == "openrouter":
            headers["HTTP-Referer"] = "https://inklusport.inklusport.uk"
            headers["X-Title"] = "InkluSport AI Assistant"
        return headers

    async def texto(
        self,
        prompt: str,
        disability_type: str = "general",
        sistema_extra: str = "",
        temperatura: float = 0.7,
    ) -> Optional[str]:
        """Como `chat` pero devuelve None en vez de lanzar excepción."""
        if not self.disponible:
            return None
        try:
            respuesta = await self.chat(prompt, disability_type, sistema_extra, temperatura)
        except Exception as exc:
            print(f"LLM no disponible: {exc}")
            return None
        return _limpiar(respuesta)

    async def texto_mensajes(
        self,
        mensajes: list[dict[str, Any]],
        temperatura: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        if not self.disponible:
            return None
        try:
            respuesta = await self.chat_mensajes(mensajes, temperatura, max_tokens)
        except Exception as exc:
            print(f"LLM no disponible: {exc}")
            return None
        return _limpiar(respuesta)

    async def json_dict(
        self, prompt: str, disability_type: str = "general", sistema_extra: str = ""
    ) -> Optional[dict[str, Any]]:
        """Pide una respuesta JSON y la devuelve como dict, o None si falla."""
        crudo = await self.texto(prompt, disability_type, sistema_extra, temperatura=0.3)
        if not crudo:
            return None
        bloque = re.search(r"\{.*\}", crudo, re.DOTALL)
        if not bloque:
            return None
        try:
            datos = json.loads(bloque.group())
        except json.JSONDecodeError as exc:
            print(f"JSON del LLM inválido: {exc}")
            return None
        return datos if isinstance(datos, dict) else None

    async def precalentar(self) -> bool:
        """Fuerza la carga del modelo en memoria (útil en Ollama/CPU).

        En proveedores cloud (OpenRouter, etc.) se omite: quema cuota free y un
        429 al arranque deja el cortacircuitos activo sin beneficio.
        """
        if not self.is_configured:
            return False
        if self.requiere_clave:
            print(
                f"LLM cloud ({self.proveedor}): sin precalentar; "
                "la primera petición real validará el proveedor"
            )
            return True
        try:
            await self.chat("Responde solo: ok", "general", temperatura=0.0)
        except Exception as exc:
            print(f"LLM no respondió al precalentar: {exc}")
            return False
        return True

    @classmethod
    def estado(cls) -> dict[str, Any]:
        instancia = cls()
        pausa = max(0, int(cls._bloqueado_hasta - time.monotonic()))

        # "configurado" sólo dice que hay URL, modelo y clave si hace falta; no que
        # el proveedor responda. Tras el cooldown se permite reintentar aunque el
        # último contacto haya fallado (p. ej. 429 temporal de un modelo free).
        if cls._llamadas_ok and cls._ultimo_error is None:
            contactado: Optional[bool] = True
        elif pausa > 0:
            contactado = False
        elif cls._llamadas_fallidas:
            # Cooldown ya pasó: listo para reintentar en la próxima petición.
            contactado = None
        else:
            contactado = None

        operativo = instancia.disponible and pausa == 0
        return {
            "habilitado": instancia.habilitado,
            "proveedor": instancia.proveedor,
            "requiere_clave": instancia.requiere_clave,
            "clave_configurada": bool(instancia.api_key),
            "url": instancia.api_url or None,
            "modelo": instancia.model or None,
            "configurado": instancia.is_configured,
            "contactado": contactado,
            "disponible": operativo,
            "en_pausa_segundos": pausa,
            "llamadas_ok": cls._llamadas_ok,
            "llamadas_fallidas": cls._llamadas_fallidas,
            "ultimo_error": cls._ultimo_error,
            "modo": "llm+motor_local" if operativo else "motor_local",
            "tool_calling": {
                "habilitado": settings.LLM_TOOL_CALLING_ENABLED,
                "max_rondas": settings.LLM_TOOL_MAX_RONDAS,
            },
        }


def system_prompt(disability_type: str = "general", sistema_extra: str = "") -> str:
    contexto = CONTEXTO_DISCAPACIDAD.get(
        (disability_type or "general").lower(), CONTEXTO_DISCAPACIDAD["general"]
    )
    base = (
        "Eres el agente profesional de InkluSport, la plataforma de deporte inclusivo "
        "accesible en inklusport.inklusport.uk.\n"
        "Tu rol: orientar a deportistas, entrenadores y organizadores sobre entrenamiento "
        "adaptado, eventos, adaptaciones y verificación de aptitud.\n"
        f"Perfil de discapacidad del usuario: {disability_type}.\n"
        "Reglas:\n"
        "- Responde siempre en español, claro, empático y profesional.\n"
        "- No uses Markdown ni asteriscos (lectores de pantalla).\n"
        "- No inventes eventos, deportes ni datos: usa solo la información que te den "
        "las herramientas o el contexto de plataforma.\n"
        "- Si falta información, dilo y ofrece el siguiente paso concreto.\n"
        "- Mantén continuidad con el historial de la conversación.\n"
        "- Suena a chatbot real: evita plantillas repetidas y no digas que no entiendes "
        "si puedes aportar una respuesta útil.\n"
        f"- Adaptación requerida: {contexto}"
    )
    if sistema_extra:
        return f"{base}\n{sistema_extra}"
    return base


def _limpiar(texto: str) -> str:
    """Quita el Markdown que algunos modelos pequeños insertan pese al system prompt.

    Las respuestas se leen con lectores de pantalla, donde los asteriscos y las
    almohadillas se verbalizan y estorban.
    """
    limpio = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", texto)
    limpio = re.sub(r"^#{1,6}\s*", "", limpio, flags=re.MULTILINE)
    limpio = re.sub(r"^\s*[-*]\s+", "- ", limpio, flags=re.MULTILINE)
    return limpio.strip()
