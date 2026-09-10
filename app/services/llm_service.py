"""Cliente LLM opcional, compatible con APIs estilo OpenAI.

Soporta Ollama (servidor local, sin clave) y proveedores en la nube: OpenAI,
xAI (Grok), OpenRouter, DeepSeek, Mistral, Together y Groq. Se elige con
LLM_PROVIDER o se deduce del prefijo de LLM_API_KEY.

El servicio completo funciona sin LLM: los agentes usan su motor local y, cuando
el proveedor responde, lo aprovechan para redactar respuestas más ricas.

Incluye un cortacircuitos compartido: un fallo duro (401/403/sin créditos)
pausa las llamadas `LLM_COOLDOWN_SEGUNDOS`. Timeouts y 429 reintentan el
mismo modelo y luego el siguiente, sin apagar el chat para todos.
"""

import asyncio
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
    finish_reason: Optional[str] = None

    @property
    def tiene_tools(self) -> bool:
        """True si el modelo pidió una o más llamadas a herramientas."""
        return bool(self.tool_calls)

    @property
    def truncado(self) -> bool:
        """True si el proveedor cortó por límite de tokens."""
        reason = (self.finish_reason or "").lower()
        return reason in {"length", "max_tokens"}


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

def _es_modelo_free(modelo: str) -> bool:
    """True si el slug consume la cuota diaria :free de OpenRouter."""
    m = (modelo or "").strip()
    return m.endswith(":free") or m in {"openrouter/free", "free"}


# :free vigentes (rotan; 404 = ya no son free). Tras agotar cupo diario se
# prueba un modelo de pago muy barato: la cuota :free es compartida.
_FALLBACKS_OPENROUTER = (
    "google/gemma-4-26b-a4b-it:free",
    "liquid/lfm-2.5-2.6b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "inclusionai/ling-3.0-flash-fin:free",
    "nex-agi/nex-n2.5-mini:free",
)
_FALLBACKS_OPENROUTER_PAGO = (
    "openai/gpt-oss-20b",
    "qwen/qwen3.7-flash",
)


def _es_url_local(url: str) -> bool:
    """True si la URL apunta a Ollama u otro anfitrión local (sin clave)."""
    return bool(url) and any(a in url for a in _ANFITRIONES_LOCALES)


def _es_modelo_reintentable(status: int, cuerpo: str) -> bool:
    """True si conviene probar el siguiente modelo (429, modelo inválido, 5xx)."""
    if _es_rate_limit(status, cuerpo):
        return True
    if status in {400, 404, 408, 422, 502, 503, 524}:
        return True
    bajo = (cuerpo or "").lower()
    return any(
        t in bajo
        for t in ("not found", "no endpoints", "is not a valid", "unknown model")
    )


def _es_rate_limit(status: int, cuerpo: str) -> bool:
    """Detecta HTTP 429 o mensajes de rate-limit en el cuerpo de error."""
    if status == 429:
        return True
    bajo = (cuerpo or "").lower()
    return "rate-limited" in bajo or "rate limit" in bajo


def _es_cuota_free_diaria(status: int, cuerpo: str) -> bool:
    """True si OpenRouter cortó todos los :free (cupo diario/minuto, no un modelo)."""
    if not _es_rate_limit(status, cuerpo):
        return False
    bajo = (cuerpo or "").lower()
    return any(
        t in bajo
        for t in (
            "free-models-per-day",
            "free-models-per-min",
            "free_tier",
            "openrouter_free_tier",
        )
    )


def _segundos_hasta_reset_cuota(cuerpo: str) -> int:
    """Lee X-RateLimit-Reset del JSON de OpenRouter; si no, 1 h (máx. 24 h)."""
    match = re.search(r"X-RateLimit-Reset\"\s*:\s*\"?(\d+)", cuerpo or "")
    if match:
        crudo = int(match.group(1))
        reset_epoch = crudo / 1000.0 if crudo > 10_000_000_000 else float(crudo)
        restante = int(reset_epoch - time.time())
        return max(60, min(restante, 86_400))
    return 3600


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


def _es_fallo_duro(status: int, cuerpo: str) -> bool:
    """Clave inválida o cuenta sin créditos: no tiene sentido probar otro :free."""
    if status in {401, 403}:
        return True
    if status == 402:
        return not _es_cuota_free_diaria(status, cuerpo)
    bajo = (cuerpo or "").lower()
    return "invalid api key" in bajo or "incorrect api key" in bajo


def _es_error_red(exc: BaseException) -> bool:
    """Timeouts y cortes de red: conviene reintentar u otro modelo."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    nombre = type(exc).__name__.lower()
    return any(t in nombre for t in ("timeout", "connect", "network", "read"))


def _unir_continuacion(base: str, extra: str) -> str:
    """Pega un trozo cortado por max_tokens con su continuación, sin duplicar."""
    a = (base or "").rstrip()
    b = (extra or "").lstrip()
    if not b:
        return a
    if not a:
        return b
    tope = min(len(a), len(b), 120)
    for n in range(tope, 7, -1):
        if a.endswith(b[:n]):
            return a + b[n:]
    if a[-1].isalnum() and b[0].islower():
        return a + b
    if a[-1] in " \n" or b[0] in " \n.,;:!?)":
        return a + b
    return f"{a} {b}"


async def _esperar_reintento(intento: int) -> None:
    """Backoff corto (0.4s, 0.8s, … tope 2s) para no inflar la espera del usuario."""
    espera = min(2.0, 0.4 * (2 ** max(0, intento)))
    await asyncio.sleep(espera)


class LLMService:
    """Cliente de chat/completions (OpenAI-compatible) con cortacircuitos y fallbacks."""

    # Estado compartido por todas las instancias (una por agente)
    _bloqueado_hasta: float = 0.0
    _free_cuota_hasta: float = 0.0
    _ultimo_error: Optional[str] = None
    _ultimo_exito: Optional[float] = None
    _llamadas_ok: int = 0
    _llamadas_fallidas: int = 0
    _en_curso: int = 0
    _sema: asyncio.Semaphore | None = None

    @classmethod
    def _semaforo(cls) -> asyncio.Semaphore:
        """Semáforo global: limita llamadas concurrentes al proveedor."""
        if cls._sema is None:
            cls._sema = asyncio.Semaphore(max(1, settings.LLM_MAX_CONCURRENT))
        return cls._sema

    def __init__(self):
        """Lee clave, modelo, URL y timeout de settings y resuelve el proveedor."""
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
        """True si el LLM está habilitado y tiene clave (nube) o URL+modelo (local)."""
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
    def _registrar_fallo(cls, error: str, *, transitorio: bool = False) -> None:
        """Anota el error. El cooldown largo solo aplica a fallos duros."""
        cls._ultimo_error = error[:300]
        cls._llamadas_fallidas += 1
        espera = (
            settings.LLM_COOLDOWN_TRANSITORIO_SEGUNDOS
            if transitorio
            else settings.LLM_COOLDOWN_SEGUNDOS
        )
        cls._bloqueado_hasta = time.monotonic() + max(0, espera)

    @classmethod
    def _registrar_exito(cls) -> None:
        """Limpia el cooldown y cuenta una llamada correcta al proveedor."""
        cls._ultimo_error = None
        cls._llamadas_ok += 1
        cls._ultimo_exito = time.time()
        cls._bloqueado_hasta = 0.0

    async def chat(
        self,
        prompt: str,
        disability_type: str = "general",
        sistema_extra: str = "",
        temperatura: Optional[float] = None,
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
        """Modelo configurado primero; en OpenRouter, :free vigentes y pago barato."""
        primario = self.model
        if self.proveedor != "openrouter" or not primario:
            return [primario] if primario else []
        sin_free = time.time() < LLMService._free_cuota_hasta
        orden: list[str] = []
        for modelo in (primario, *_FALLBACKS_OPENROUTER, *_FALLBACKS_OPENROUTER_PAGO):
            if not modelo or modelo in orden:
                continue
            if sin_free and _es_modelo_free(modelo):
                continue
            orden.append(modelo)
        return orden

    @staticmethod
    def _temperatura(valor: Optional[float]) -> float:
        """Usa ``LLM_TEMPERATURE`` (~0.2) si el llamador no fija otra."""
        if valor is None:
            return settings.LLM_TEMPERATURE
        return max(0.0, min(2.0, float(valor)))

    def _validar_listo(self, *, ignorar_pausa: bool = False) -> None:
        """Lanza RuntimeError si el LLM está deshabilitado, mal configurado o en pausa."""
        if not self.habilitado:
            raise RuntimeError("LLM deshabilitado (LLM_ENABLED=false)")
        if self.requiere_clave and not self.api_key:
            raise RuntimeError("LLM sin clave configurada (LLM_API_KEY)")
        if not self.api_url or not self.model:
            raise RuntimeError("LLM sin URL o modelo configurados")
        if not ignorar_pausa and time.monotonic() < LLMService._bloqueado_hasta:
            restante = int(LLMService._bloqueado_hasta - time.monotonic())
            raise RuntimeError(
                f"LLM en pausa {restante}s tras un fallo previo: {LLMService._ultimo_error}"
            )

    @staticmethod
    def _parsear_mensaje(mensaje: dict[str, Any]) -> ChatCompletionResult:
        """Normaliza el ``message`` de /chat/completions a texto y tool_calls."""
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

    @staticmethod
    def _parsear_choice(cuerpo: dict[str, Any]) -> ChatCompletionResult:
        """Lee ``choices[0]`` (texto, tools y finish_reason)."""
        choices = cuerpo.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise ValueError("respuesta sin choices")
        choice = choices[0]
        mensaje = choice.get("message") or {}
        if not isinstance(mensaje, dict):
            mensaje = {}
        resultado = LLMService._parsear_mensaje(mensaje)
        reason = choice.get("finish_reason") or choice.get("native_finish_reason")
        resultado.finish_reason = str(reason) if reason else None
        return resultado

    async def completar(
        self,
        mensajes: list[dict[str, Any]],
        *,
        temperatura: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        ignorar_pausa: bool = False,
    ) -> ChatCompletionResult:
        """Llama al proveedor (POST a la URL de /v1/chat/completions) y devuelve texto y/o tool_calls.

        Prueba el modelo configurado y, en OpenRouter, fallbacks si hay rate-limit
        o el modelo no existe. Reintenta timeouts/429 en el mismo modelo. Si el
        texto llega cortado (``finish_reason=length``), pide continuación.
        El llamador recibe un ``ChatCompletionResult``; si todos los modelos
        fallan, se activa el cortacircuitos y se lanza ``RuntimeError``.
        """
        self._validar_listo(ignorar_pausa=ignorar_pausa)
        headers = self._headers()
        modelos = self._modelos_a_probar()
        usar_tools = bool(tools)
        sema = self._semaforo()
        espera = max(0.5, float(settings.LLM_QUEUE_WAIT_SEGUNDOS))
        try:
            await asyncio.wait_for(sema.acquire(), timeout=espera)
        except TimeoutError as exc:
            raise RuntimeError(
                "LLM ocupado: demasiadas consultas a la vez"
            ) from exc
        LLMService._en_curso += 1
        try:
            return await self._completar_http(
                mensajes,
                headers,
                modelos,
                usar_tools,
                tools,
                tool_choice,
                self._temperatura(temperatura),
                max_tokens,
            )
        finally:
            LLMService._en_curso = max(0, LLMService._en_curso - 1)
            sema.release()

    async def _completar_http(
        self,
        mensajes: list[dict[str, Any]],
        headers: dict[str, str],
        modelos: list[str],
        usar_tools: bool,
        tools: Optional[list[dict[str, Any]]],
        tool_choice: Optional[str],
        temperatura: float,
        max_tokens: Optional[int],
    ) -> ChatCompletionResult:
        """POST al proveedor. El llamador ya tiene el cupo del semáforo."""
        ultimo_error = ""
        transitorio = True
        tokens = max_tokens or settings.LLM_MAX_TOKENS
        reintentos = max(0, settings.LLM_REINTENTOS_POR_MODELO)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i, modelo in enumerate(modelos):
                if _es_modelo_free(modelo) and time.time() < LLMService._free_cuota_hasta:
                    continue
                hay_mas = any(
                    m != modelo
                    and not (
                        _es_modelo_free(m) and time.time() < LLMService._free_cuota_hasta
                    )
                    for m in modelos[i + 1 :]
                )
                payload: dict[str, Any] = {
                    "messages": mensajes,
                    "model": modelo,
                    "temperature": temperatura,
                    "max_tokens": tokens,
                }
                if usar_tools:
                    payload["tools"] = tools
                    payload["tool_choice"] = tool_choice or "auto"

                for intento in range(reintentos + 1):
                    try:
                        respuesta = await client.post(
                            self.api_url, headers=headers, json=payload
                        )
                    except Exception as exc:
                        ultimo_error = f"{type(exc).__name__}: {exc}"
                        transitorio = True
                        if _es_error_red(exc) and intento < reintentos:
                            print(
                                f"LLM {modelo} {ultimo_error[:80]}; "
                                f"reintento {intento + 1}/{reintentos}..."
                            )
                            await _esperar_reintento(intento)
                            continue
                        if _es_error_red(exc) and hay_mas:
                            print(
                                f"LLM {modelo} {ultimo_error[:80]}; "
                                "probando alternativa..."
                            )
                            break
                        self._registrar_fallo(ultimo_error, transitorio=True)
                        raise RuntimeError(f"LLM inaccesible: {exc}") from exc

                    if respuesta.status_code < 400:
                        try:
                            resultado = self._parsear_choice(respuesta.json())
                        except Exception as exc:
                            ultimo_error = f"Respuesta inesperada: {exc}"
                            transitorio = True
                            if hay_mas:
                                print(f"LLM {modelo} {ultimo_error[:80]}; alternativa...")
                                break
                            self._registrar_fallo(ultimo_error, transitorio=True)
                            raise RuntimeError(
                                f"Respuesta del LLM no interpretable: {exc}"
                            ) from exc
                        if not (resultado.content or "").strip() and not resultado.tiene_tools:
                            ultimo_error = f"{modelo}: respuesta vacía"
                            if intento < reintentos:
                                await _esperar_reintento(intento)
                                continue
                            if hay_mas:
                                print(f"LLM {ultimo_error}; probando alternativa...")
                                break
                            self._registrar_fallo(ultimo_error, transitorio=True)
                            raise RuntimeError(f"LLM {ultimo_error}")
                        if resultado.truncado and not resultado.tiene_tools:
                            resultado = await self._continuar_si_truncado(
                                client, headers, payload, resultado
                            )
                        resultado.modelo_usado = modelo
                        self._registrar_exito()
                        if modelo != self.model:
                            print(f"LLM: {self.model} falló; respondió {modelo}")
                        return resultado

                    detalle = respuesta.text[:800]
                    ultimo_error = f"HTTP {respuesta.status_code}: {detalle[:300]}"
                    if usar_tools and _es_tools_no_soportado(
                        respuesta.status_code, detalle
                    ):
                        raise RuntimeError(f"LLM sin soporte de tools: {ultimo_error}")
                    if _es_cuota_free_diaria(respuesta.status_code, detalle):
                        espera = _segundos_hasta_reset_cuota(detalle)
                        LLMService._free_cuota_hasta = time.time() + espera
                        transitorio = True
                        print(
                            f"LLM cuota :free agotada ~{espera}s; "
                            "sigo con modelo de pago barato si hay..."
                        )
                        break
                    if _es_fallo_duro(respuesta.status_code, detalle):
                        transitorio = False
                        self._registrar_fallo(ultimo_error, transitorio=False)
                        raise RuntimeError(f"LLM {ultimo_error}")
                    if (
                        _es_modelo_reintentable(respuesta.status_code, detalle)
                        and intento < reintentos
                    ):
                        print(
                            f"LLM {modelo} {ultimo_error[:80]}; "
                            f"reintento {intento + 1}/{reintentos}..."
                        )
                        await _esperar_reintento(intento)
                        continue
                    if (
                        _es_modelo_reintentable(respuesta.status_code, detalle)
                        and hay_mas
                    ):
                        print(f"LLM {modelo} {ultimo_error[:80]}; probando alternativa...")
                        break
                    self._registrar_fallo(ultimo_error, transitorio=transitorio)
                    raise RuntimeError(f"LLM {ultimo_error}")

        self._registrar_fallo(ultimo_error or "sin modelos", transitorio=transitorio)
        raise RuntimeError(f"LLM {ultimo_error or 'sin respuesta'}")

    async def _continuar_si_truncado(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
        resultado: ChatCompletionResult,
    ) -> ChatCompletionResult:
        """Si el modelo cortó por tokens, pide el resto y lo pega."""
        max_cont = max(0, settings.LLM_CONTINUACIONES_TRUNCADO)
        acumulado = (resultado.content or "").rstrip()
        mensajes_base = list(payload.get("messages") or [])
        usados = 0
        while resultado.truncado and usados < max_cont and acumulado:
            usados += 1
            cont_payload = dict(payload)
            cont_payload["messages"] = mensajes_base + [
                {"role": "assistant", "content": acumulado},
                {
                    "role": "user",
                    "content": (
                        "Continúa exactamente desde el carácter donde te quedaste. "
                        "No repitas lo ya escrito. Termina las frases."
                    ),
                },
            ]
            try:
                resp = await client.post(
                    self.api_url, headers=headers, json=cont_payload
                )
            except Exception as exc:
                print(f"LLM continuación falló: {type(exc).__name__}: {exc}")
                break
            if resp.status_code >= 400:
                print(f"LLM continuación HTTP {resp.status_code}")
                break
            try:
                extra = self._parsear_choice(resp.json())
            except Exception as exc:
                print(f"LLM continuación ilegible: {exc}")
                break
            if not (extra.content or "").strip():
                break
            acumulado = _unir_continuacion(acumulado, extra.content or "")
            resultado.content = acumulado
            resultado.finish_reason = extra.finish_reason
            reason = (extra.finish_reason or "").lower()
            if reason not in {"length", "max_tokens"}:
                break
        return resultado

    async def chat_mensajes(
        self,
        mensajes: list[dict[str, Any]],
        temperatura: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        ignorar_pausa: bool = False,
    ) -> str:
        """Consulta al LLM; si hay tools, ignora tool_calls y solo devuelve texto."""
        resultado = await self.completar(
            mensajes,
            temperatura=temperatura,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            ignorar_pausa=ignorar_pausa,
        )
        if resultado.content:
            return resultado.content
        if resultado.tiene_tools:
            raise RuntimeError(
                "El modelo devolvió tool_calls sin texto; usa completar() en el orquestador"
            )
        return ""

    def _headers(self) -> dict[str, str]:
        """Cabeceras JSON + Bearer; OpenRouter añade Referer y X-Title del producto."""
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
        temperatura: Optional[float] = None,
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
        temperatura: Optional[float] = None,
        max_tokens: Optional[int] = None,
        ignorar_pausa: bool = False,
    ) -> Optional[str]:
        """Como ``chat_mensajes`` pero devuelve None si el LLM no está configurado o falla.

        ``ignorar_pausa=True`` reintenta aunque el cortacircuitos esté activo
        (chat abierto: el usuario espera una respuesta, no un menú).
        """
        if not self.is_configured:
            return None
        if not ignorar_pausa and not self.disponible:
            return None
        try:
            respuesta = await self.chat_mensajes(
                mensajes, temperatura, max_tokens, ignorar_pausa=ignorar_pausa
            )
        except Exception as exc:
            print(f"LLM no disponible: {exc}")
            return None
        return _limpiar(respuesta)

    async def json_dict(
        self, prompt: str, disability_type: str = "general", sistema_extra: str = ""
    ) -> Optional[dict[str, Any]]:
        """Pide una respuesta JSON y la devuelve como dict, o None si falla."""
        crudo = await self.texto(prompt, disability_type, sistema_extra)
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
        """Snapshot de configuración, cooldown y si el LLM está operativo o en motor local."""
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
            "temperatura": settings.LLM_TEMPERATURE,
            "timeout_segundos": instancia.timeout,
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
            "concurrencia": {
                "max": settings.LLM_MAX_CONCURRENT,
                "en_curso": cls._en_curso,
                "cola_espera_segundos": settings.LLM_QUEUE_WAIT_SEGUNDOS,
                "chat_inflight_por_usuario": settings.CHAT_MAX_INFLIGHT_PER_USER,
            },
        }


def system_prompt(disability_type: str = "general", sistema_extra: str = "") -> str:
    """System prompt de InkluSport adaptado al tipo de discapacidad del usuario.

    ``sistema_extra`` se concatena al final (instrucciones del agente concreto).
    """
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
        "- No uses asteriscos ni almohadillas (lectores de pantalla).\n"
        "- Separa las ideas: un dato por línea, viñetas con '- ' y una línea "
        "en blanco entre el titular y la lista. No amontones todo en un párrafo.\n"
        "- No pegues JSON ni bloques de código: resume con frases y viñetas.\n"
        "- Nunca pidas el email, correo o ID del usuario autenticado: ya está en sesión.\n"
        "- No inventes eventos, deportes ni datos: usa solo la información que te den "
        "las herramientas o el contexto de plataforma.\n"
        "- Si falta información, dilo y ofrece el siguiente paso concreto.\n"
        "- Mantén continuidad con el historial de la conversación.\n"
        "- Suena a chatbot real: evita plantillas repetidas y no digas que no entiendes "
        "si puedes aportar una respuesta útil.\n"
        "- No inventes límites de uso, cuotas ni tiempos de espera del chat. "
        "Si hay un tope, el sistema lo avisará aparte.\n"
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
    limpio = limpio.strip()
    if "\n" in limpio:
        return limpio
    partes = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9])", limpio)
    if len(partes) >= 3:
        return "\n\n".join(p.strip() for p in partes if p.strip())
    return limpio
