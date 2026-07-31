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
from typing import Any, Optional

import httpx

from app.config import settings

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
        "modelo": "grok-4.5",
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
        # Gratuito, instruction-tuned y con buen español. La lista de modelos
        # gratuitos cambia con el tiempo: se puede sustituir con LLM_MODEL.
        "modelo": "google/gemma-4-31b-it:free",
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


def _es_url_local(url: str) -> bool:
    return bool(url) and any(a in url for a in _ANFITRIONES_LOCALES)


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

    async def chat_mensajes(
        self,
        mensajes: list[dict[str, str]],
        temperatura: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Consulta al LLM con una lista completa de mensajes (historial + system)."""
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

        payload = {
            "messages": mensajes,
            "model": self.model,
            "temperature": temperatura,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        }
        headers = self._headers()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                respuesta = await client.post(self.api_url, headers=headers, json=payload)
        except Exception as exc:
            self._registrar_fallo(f"{type(exc).__name__}: {exc}")
            raise RuntimeError(f"LLM inaccesible: {exc}") from exc

        if respuesta.status_code >= 400:
            detalle = respuesta.text[:300]
            self._registrar_fallo(f"HTTP {respuesta.status_code}: {detalle}")
            raise RuntimeError(f"LLM HTTP {respuesta.status_code}: {detalle}")

        try:
            contenido = respuesta.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            self._registrar_fallo(f"Respuesta inesperada: {exc}")
            raise RuntimeError(f"Respuesta del LLM no interpretable: {exc}") from exc

        self._registrar_exito()
        return contenido

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
        mensajes: list[dict[str, str]],
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
        """Fuerza la carga del modelo en memoria para que la primera consulta real
        del usuario no pague el arranque en frío (relevante en Ollama sobre CPU)."""
        if not self.is_configured:
            return False
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
        # el proveedor responda. Se distingue para que el diagnóstico no prometa un
        # LLM que en realidad está inaccesible.
        if cls._llamadas_ok:
            contactado = cls._ultimo_error is None
        elif cls._llamadas_fallidas:
            contactado = False
        else:
            contactado = None

        operativo = instancia.disponible and contactado is not False
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
