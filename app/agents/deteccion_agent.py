"""Sugerencia de configuración de discapacidad desde texto (RF52). Requiere confirmación."""

from __future__ import annotations

from typing import Any

from app.nlp.discapacidad import CANONICAS, canonizar, descripcion
from app.nlp.texto import normalizar


class DeteccionAgent:
    def sugerir(self, texto: str) -> dict[str, Any]:
        limpio = normalizar(texto or "")
        if not limpio:
            return {
                "sugerida": "general",
                "confianza": 0.0,
                "descripcion": descripcion("general"),
                "requiere_confirmacion": True,
                "mensaje": "No hay texto suficiente para sugerir una configuración.",
                "rf": "RF52",
            }

        clave = canonizar(limpio)
        # Confianza por densidad de alias
        confianza = 0.35
        if clave != "general":
            confianza = 0.72
            if any(p in limpio for p in ("silla de ruedas", "ciego", "sordo", "sindrome de down")):
                confianza = 0.9

        return {
            "sugerida": clave,
            "confianza": confianza,
            "descripcion": descripcion(clave),
            "opciones": [
                {"clave": c, "descripcion": descripcion(c)}
                for c in CANONICAS
                if c != "general"
            ],
            "requiere_confirmacion": True,
            "mensaje": (
                f"Por lo que describes, podría encajar una configuración para "
                f"{descripcion(clave)}. Confirma antes de guardarla en tu perfil; "
                "no se aplica automáticamente."
            ),
            "rf": "RF52",
        }
