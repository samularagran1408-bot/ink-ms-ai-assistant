"""Caché en memoria con vencimiento, para no repetir la misma llamada HTTP.

Cada petición al asistente valida el JWT y carga el perfil antes de hacer nada.
Guardar esas respuestas unos segundos ahorra dos saltos de red por petición sin
que el usuario note datos viejos.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Optional


class CacheTTL:
    """Diccionario con vencimiento por clave y tope de tamaño."""

    def __init__(self, ttl_segundos: float, max_items: int = 512):
        """Fija cuánto vive cada entrada y cuántas se guardan como máximo."""
        self.ttl = max(0.0, float(ttl_segundos))
        self.max_items = max(1, int(max_items))
        self._datos: dict[str, tuple[float, Any]] = {}

    def get(self, clave: str) -> Optional[Any]:
        """Valor vigente de `clave`, o None si no está o ya venció."""
        if not clave or self.ttl <= 0:
            return None
        entrada = self._datos.get(clave)
        if not entrada:
            return None
        vence, valor = entrada
        if vence <= time.monotonic():
            self._datos.pop(clave, None)
            return None
        return valor

    def set(self, clave: str, valor: Any) -> Any:
        """Guarda `valor` bajo `clave` y lo devuelve tal cual."""
        if not clave or self.ttl <= 0:
            return valor
        if len(self._datos) >= self.max_items:
            self._purgar()
        self._datos[clave] = (time.monotonic() + self.ttl, valor)
        return valor

    def invalidar(self, clave: Optional[str] = None) -> None:
        """Borra una clave concreta o toda la caché si no se indica ninguna."""
        if clave is None:
            self._datos.clear()
        else:
            self._datos.pop(clave, None)

    def _purgar(self) -> None:
        """Quita lo vencido; si aún está lleno, descarta lo más próximo a vencer."""
        ahora = time.monotonic()
        for clave in [k for k, (vence, _) in self._datos.items() if vence <= ahora]:
            self._datos.pop(clave, None)
        if len(self._datos) < self.max_items:
            return
        sobrantes = sorted(self._datos.items(), key=lambda item: item[1][0])
        for clave, _ in sobrantes[: max(1, len(sobrantes) // 4)]:
            self._datos.pop(clave, None)


def clave_token(token: Optional[str]) -> str:
    """Huella corta del JWT: sirve de clave sin guardar el token en memoria."""
    if not token:
        return ""
    limpio = token.strip()
    if limpio.startswith("Bearer "):
        limpio = limpio[7:].strip()
    if not limpio:
        return ""
    return hashlib.sha256(limpio.encode("utf-8")).hexdigest()[:32]
