import httpx
import json
from typing import Any, List, Mapping, Optional
from langchain.llms.base import LLM
from langchain.callbacks.manager import CallbackManagerForLLMRun
from app.config import settings

class GrokLLM(LLM):
    """LLM wrapper para Grok de xAI"""

    api_key: str = settings.GROK_API_KEY
    model: str = settings.GROK_MODEL
    api_url: str = settings.GROK_API_URL
    temperature: float = 0.7
    max_tokens: int = 2048

    @property
    def _llm_type(self) -> str:
        return "grok"

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "messages": [
                    {"role": "system", "content": "Eres un asistente especializado en deporte inclusivo y adaptado. Responde de manera clara, empática y profesional."},
                    {"role": "user", "content": prompt}
                ],
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": False
            }

            with httpx.Client(timeout=60.0) as client:
                response = client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]

        except Exception as e:
            return f"Error al procesar la solicitud: {str(e)}"

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }