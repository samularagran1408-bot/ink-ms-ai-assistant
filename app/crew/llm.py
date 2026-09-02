"""LLM de CrewAI a partir de app.config / LLMService (mismo .env).

No hardcodea gpt-4o-mini. No copia claves: lee LLM_API_KEY.
"""

from __future__ import annotations

import os
from typing import Optional

from crewai import LLM

from app.services.llm_service import LLMService

# `openrouter/free` no es un slug de LiteLLM. Varios :free van a 429;
# el crew prueba esta lista en orden (igual espíritu que LLMService).
_FALLBACKS_OPENROUTER_CREW = (
    "openrouter/inclusionai/ling-3.0-flash-fin:free",
    "openrouter/liquid/lfm-2.5-2.6b:free",
    "openrouter/minimax/minimax-m2.7:free",
    "openrouter/google/gemma-4-26b-a4b-it:free",
    "openrouter/z-ai/glm-5.2:free",
)


def _base_openai(url: str) -> str:
    """Quita /chat/completions para dejar el api_base estilo OpenAI."""
    u = (url or "").rstrip("/")
    if u.endswith("/chat/completions"):
        u = u[: -len("/chat/completions")]
    return u


def _es_modelo_libre(modelo: str) -> bool:
    """True si el .env pide el router free o un slug :free de OpenRouter."""
    m = (modelo or "").strip()
    return m in ("openrouter/free", "free") or m.endswith(":free")


def candidatos_llm() -> list[Optional[str]]:
    """Modelos a probar. ``None`` = el que resuelve ``llm_crew()`` sin override."""
    svc = LLMService()
    if svc.proveedor != "openrouter" or not _es_modelo_libre(svc.model):
        return [None]
    return list(_FALLBACKS_OPENROUTER_CREW)


def llm_saturado(exc: BaseException) -> bool:
    """True si OpenRouter/LiteLLM rechazó el modelo (429, sin endpoint, no-free)."""
    texto = str(exc).lower()
    return any(
        t in texto
        for t in (
            "429",
            "rate-limited",
            "rate limit",
            "no endpoints found",
            "unavailable for free",
        )
    )


def llm_crew(modelo: Optional[str] = None) -> LLM:
    """Construye crewai.LLM() con el proveedor ya resuelto por LLMService."""
    svc = LLMService()
    if not svc.is_configured:
        raise RuntimeError(
            "LLM no configurado. Revisa LLM_ENABLED, LLM_API_KEY y LLM_MODEL "
            "en ink-ms-ai-assistant/.env (no uses las keys del taller CREWAI1)."
        )

    proveedor = svc.proveedor
    elegido = (modelo or svc.model or "").strip()
    clave = svc.api_key
    base = _base_openai(svc.api_url)

    if clave and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = clave

    extra: dict = {}
    if proveedor == "openrouter":
        if clave:
            os.environ["OPENROUTER_API_KEY"] = clave
        extra["extra_headers"] = {
            "HTTP-Referer": "https://inklusport.inklusport.uk",
            "X-Title": "InkluSport AI Assistant",
        }
        if modelo:
            elegido = modelo if modelo.startswith("openrouter/") else f"openrouter/{modelo}"
        elif _es_modelo_libre(elegido) and not elegido.endswith(":free"):
            elegido = _FALLBACKS_OPENROUTER_CREW[0]
        elif not elegido.startswith("openrouter/"):
            elegido = f"openrouter/{elegido}"
        print(f" [LLM] modelo={elegido}", flush=True)
        return LLM(
            model=elegido,
            api_key=clave or None,
            base_url=base or "https://openrouter.ai/api/v1",
            timeout=svc.timeout,
            **extra,
        )

    if proveedor == "groq":
        if clave:
            os.environ["GROQ_API_KEY"] = clave
        if not elegido.startswith("groq/"):
            elegido = f"groq/{elegido}"
        print(f" [LLM] modelo={elegido}", flush=True)
        return LLM(model=elegido, api_key=clave or None, timeout=svc.timeout)

    if proveedor == "xai":
        if clave:
            os.environ["XAI_API_KEY"] = clave
        if not elegido.startswith("xai/"):
            elegido = f"xai/{elegido}"
        print(f" [LLM] modelo={elegido}", flush=True)
        return LLM(model=elegido, api_key=clave or None, timeout=svc.timeout)

    if proveedor == "ollama":
        if not elegido.startswith("ollama/"):
            elegido = f"ollama/{elegido}"
        ollama_base = base.replace("/v1", "") if base else "http://127.0.0.1:11434"
        print(f" [LLM] modelo={elegido}", flush=True)
        return LLM(model=elegido, base_url=ollama_base, timeout=svc.timeout)

    print(f" [LLM] modelo={elegido}", flush=True)
    return LLM(
        model=elegido,
        api_key=clave or None,
        base_url=base or None,
        timeout=svc.timeout,
    )
