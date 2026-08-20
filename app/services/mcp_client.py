"""Cliente del servidor MCP de Inklusport (Streamable HTTP)."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.config import settings

_MCP_TIMEOUT = 30.0


def _openai_tool(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or tool.name,
            "parameters": schema,
        },
    }


def _texto_resultado(resultado: Any) -> str:
    parts: list[str] = []
    for bloque in getattr(resultado, "content", None) or []:
        texto = getattr(bloque, "text", None)
        if texto:
            parts.append(str(texto))
    if parts:
        return "\n".join(parts)
    structured = getattr(resultado, "structured_content", None) or getattr(
        resultado, "structuredContent", None
    )
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, default=str)
    return json.dumps({"success": False, "error": "respuesta MCP vacía"}, ensure_ascii=False)


def _parsear_json(texto: str) -> Any:
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return {"raw": texto}


def _headers_auth(authorization: Optional[str]) -> dict[str, str]:
    if not authorization:
        return {}
    valor = (
        authorization
        if authorization.startswith("Bearer ")
        else f"Bearer {authorization}"
    )
    return {"Authorization": valor}


def _unpack_streams(streams: Any) -> tuple[Any, Any]:
    if hasattr(streams, "read") and hasattr(streams, "write"):
        return streams.read, streams.write
    if isinstance(streams, (tuple, list)) and len(streams) >= 2:
        return streams[0], streams[1]
    raise TypeError(f"streams MCP inesperados: {type(streams)}")


def _http_client(headers: dict[str, str]):
    try:
        from mcp.shared._httpx_utils import create_mcp_http_client

        return create_mcp_http_client(headers or None)
    except Exception:
        pass
    try:
        from mcp.client.streamable_http import create_mcp_http_client as factory

        return factory(headers or None)
    except Exception:
        pass
    try:
        import httpx2 as http_lib
    except ImportError:
        import httpx as http_lib

    timeout = http_lib.Timeout(_MCP_TIMEOUT, read=300.0)
    return http_lib.AsyncClient(
        headers=headers or None,
        timeout=timeout,
        follow_redirects=True,
    )


async def _con_sesion(authorization: Optional[str], operacion):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = _headers_auth(authorization)
    async with _http_client(headers) as http:
        async with streamable_http_client(
            settings.MCP_URL, http_client=http
        ) as streams:
            read_stream, write_stream = _unpack_streams(streams)
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await operacion(session)


async def listar_tools_openai(authorization: Optional[str] = None) -> list[dict[str, Any]]:
    """Lista tools MCP en formato OpenAI. Vacío si el servidor no responde."""
    if not settings.MCP_ENABLED or not settings.MCP_URL:
        return []
    try:
        from mcp.client.session import ClientSession  # noqa: F401
        from mcp.client.streamable_http import streamable_http_client  # noqa: F401
    except ImportError:
        print("MCP SDK no instalado; el chat usará tools locales.")
        return []

    async def _listar(session):
        respuesta = await session.list_tools()
        return [_openai_tool(t) for t in (respuesta.tools or [])]

    try:
        return await _con_sesion(authorization, _listar)
    except Exception as exc:
        print(f"MCP no alcanzable ({settings.MCP_URL}): {exc}")
        return []


async def llamar_tool(
    nombre: str,
    argumentos: dict[str, Any],
    authorization: Optional[str] = None,
) -> dict[str, Any]:
    """Ejecuta una tool MCP y devuelve un dict (success/via/data o error)."""
    if not settings.MCP_ENABLED or not settings.MCP_URL:
        return {"success": False, "error": "MCP deshabilitado", "via": "asistente"}
    try:
        from mcp.client.session import ClientSession  # noqa: F401
        from mcp.client.streamable_http import streamable_http_client  # noqa: F401
    except ImportError:
        return {"success": False, "error": "SDK MCP no instalado", "via": "asistente"}

    async def _llamar(session):
        resultado = await session.call_tool(nombre, argumentos or {})
        texto = _texto_resultado(resultado)
        datos = _parsear_json(texto)
        if isinstance(datos, dict):
            return datos
        return {"success": True, "via": "mcp", "data": datos}

    try:
        return await _con_sesion(authorization, _llamar)
    except Exception as exc:
        return {
            "success": False,
            "via": "mcp",
            "error": f"Error llamando MCP '{nombre}': {exc}",
        }
