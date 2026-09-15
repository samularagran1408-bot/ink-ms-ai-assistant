"""Cliente HTTP compartido para hablar con el resto de microservicios.

Abrir un ``httpx.AsyncClient`` por llamada obliga a negociar una conexión TCP
nueva cada vez. Con un único cliente el pool reutiliza conexiones vivas, así
que cada salto interno (auth, users, sports, reports) deja de pagar el
handshake y el tiempo por petición baja a la latencia real del servicio.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

# Suficientes conexiones para los picos del chat sin dejar sockets abiertos de más.
_LIMITES = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30.0,
)

# Por defecto: conectar rápido y no quedarse colgado leyendo.
TIEMPO_POR_DEFECTO = httpx.Timeout(5.0, connect=1.5)

_cliente: Optional[httpx.AsyncClient] = None
_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    """Devuelve el cliente compartido, creándolo la primera vez que se usa."""
    global _cliente
    if _cliente is not None and not _cliente.is_closed:
        return _cliente
    async with _lock:
        if _cliente is None or _cliente.is_closed:
            _cliente = httpx.AsyncClient(limits=_LIMITES, timeout=TIEMPO_POR_DEFECTO)
    return _cliente


async def cerrar_cliente() -> None:
    """Cierra el cliente compartido al apagar el servicio."""
    global _cliente
    if _cliente is not None and not _cliente.is_closed:
        try:
            await _cliente.aclose()
        except Exception:
            pass
    _cliente = None


async def get_json(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, Any]] = None,
    timeout: float = 3.0,
    default: Any = None,
) -> Any:
    """GET que devuelve el JSON de un 200 o ``default`` ante error/timeout."""
    try:
        cliente = await get_client()
        respuesta = await cliente.get(
            url,
            headers=headers or None,
            params=params or None,
            timeout=httpx.Timeout(timeout, connect=min(1.5, timeout)),
        )
        if respuesta.status_code == 200:
            return respuesta.json()
    except Exception as exc:
        print(f"Error GET {url}: {type(exc).__name__}: {exc}")
    return default
