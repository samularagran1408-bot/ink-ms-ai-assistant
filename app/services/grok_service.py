import httpx
from app.config import settings


class GrokService:
    """Cliente LLM compatible con xAI (Grok) y Groq (claves gsk_)."""

    def __init__(self):
        self.api_key = (settings.GROK_API_KEY or "").strip()
        self.model = settings.GROK_MODEL
        self.api_url = settings.GROK_API_URL
        self._apply_provider_defaults()

    def _apply_provider_defaults(self):
        """Si la clave es de Groq (gsk_), usa su API/modelo válidos."""
        if self.api_key.startswith("gsk_"):
            if "x.ai" in (self.api_url or "") or not self.api_url:
                self.api_url = "https://api.groq.com/openai/v1/chat/completions"
            # Modelos tipo grok-* no existen en Groq
            if not self.model or self.model.startswith("grok"):
                self.model = "llama-3.3-70b-versatile"
        else:
            if not self.api_url:
                self.api_url = "https://api.x.ai/v1/chat/completions"
            if not self.model or self.model in ("grok-1", "grok-beta"):
                self.model = "grok-4.5"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def chat(self, prompt: str, disability_type: str = "visual") -> str:
        disability_context = {
            "visual": "Responde con descripciones claras. Evita referencias visuales como 'mira', 'observa'.",
            "auditiva": "Usa lenguaje claro y directo. Evita referencias sonoras.",
            "cognitiva": "Usa frases cortas, lenguaje simple. Organiza la información en pasos.",
            "motriz": "Enfócate en adaptaciones físicas y accesibilidad.",
            "multiple": "Combina todas las adaptaciones según sea necesario.",
            "general": "Sé inclusivo y claro para cualquier tipo de discapacidad.",
        }

        if not self.is_configured:
            raise RuntimeError("GROK_API_KEY no configurada")

        system_prompt = f"""Eres el asistente virtual de InkluSport, una plataforma de deporte inclusivo.
El usuario tiene discapacidad: {disability_type}
Instrucciones:
1. Sé empático, claro y profesional.
2. Adapta tu respuesta a su discapacidad.
3. Si no sabes algo, indícalo amablemente.
4. Responde en español.
Contexto: {disability_context.get(disability_type, disability_context["general"])}
"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "model": self.model,
            "temperature": 0.7,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.api_url, headers=headers, json=payload)
            if response.status_code >= 400:
                detail = response.text[:400]
                raise RuntimeError(f"LLM HTTP {response.status_code}: {detail}")
            data = response.json()
            return data["choices"][0]["message"]["content"]
