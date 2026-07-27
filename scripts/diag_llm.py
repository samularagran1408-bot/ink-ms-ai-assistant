"""Diagnóstico del proveedor de LLM.

Comprueba si hay salida a internet y si los endpoints de los proveedores
soportados responden con la clave configurada. No imprime la clave ni fragmentos
de ella, solo si está presente y el resultado HTTP de cada comprobación.

Uso:
    python scripts/diag_llm.py
"""

import json
import os
import urllib.error
import urllib.request

PROVEEDORES = {
    "gsk_": ("Groq", "https://api.groq.com/openai/v1/models"),
    "xai-": ("xAI (Grok)", "https://api.x.ai/v1/models"),
    "sk-": ("OpenAI", "https://api.openai.com/v1/models"),
}


def cargar_env(ruta: str) -> dict[str, str]:
    valores: dict[str, str] = {}
    if not os.path.exists(ruta):
        return valores
    with open(ruta, encoding="utf-8") as fichero:
        for linea in fichero:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            valores[clave.strip()] = valor.strip()
    return valores


def _es_local(url: str) -> bool:
    return bool(url) and any(
        a in url for a in ("ollama", "localhost", "127.0.0.1", ":11434")
    )


def _mensaje_error(detalle: str) -> str:
    """Extrae el mensaje de un error del proveedor, que no siempre es JSON.

    Algunos bloqueos de red devuelven HTML o texto plano, y otros un JSON cuyo
    campo `error` es una cadena en lugar de un objeto.
    """
    try:
        datos = json.loads(detalle)
    except json.JSONDecodeError:
        return detalle
    if isinstance(datos, dict):
        error = datos.get("error", detalle)
        if isinstance(error, dict):
            return str(error.get("message", detalle))
        return str(error)
    return detalle


def probar(etiqueta: str, url: str, clave: str = "", cuerpo: bytes | None = None) -> bool:
    cabeceras = {"Content-Type": "application/json"}
    if clave:
        cabeceras["Authorization"] = f"Bearer {clave}"
    peticion = urllib.request.Request(url, data=cuerpo, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            print(f"  [{etiqueta}] HTTP {respuesta.status} OK")
            return True
    except urllib.error.HTTPError as error:
        detalle = error.read().decode(errors="replace")
        print(f"  [{etiqueta}] HTTP {error.code}: {_mensaje_error(detalle)[:180]}")
    except Exception as error:  # noqa: BLE001
        print(f"  [{etiqueta}] sin respuesta: {type(error).__name__}: {error}")
    return False


def main() -> None:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entorno = cargar_env(os.path.join(base, ".env"))

    def leer(*nombres: str) -> str:
        for nombre in nombres:
            if entorno.get(nombre):
                return entorno[nombre]
        return ""

    clave = leer("LLM_API_KEY", "GROK_API_KEY")
    url = leer("LLM_API_URL", "GROK_API_URL")
    modelo = leer("LLM_MODEL", "GROK_MODEL")
    habilitado = leer("LLM_ENABLED").lower() not in ("false", "0", "no")
    declarado = leer("LLM_PROVIDER").lower()

    prefijo = next((p for p in PROVEEDORES if clave.startswith(p)), None)
    if declarado == "ollama" or (not clave and _es_local(url)):
        proveedor = "Ollama (local, sin clave)"
    elif prefijo:
        proveedor = PROVEEDORES[prefijo][0]
    else:
        proveedor = "desconocido"

    print("Configuración")
    print(f"  LLM_ENABLED: {'si' if habilitado else 'no'}")
    print(f"  proveedor: {proveedor}")
    print(f"  clave configurada: {'si' if clave else 'no (no hace falta en local)'}")
    print(f"  url: {url or '(vacia)'}")
    print(f"  modelo: {modelo or '(vacio)'}")

    if proveedor.startswith("Ollama"):
        print("\nServidor local")
        base = url.split("/v1/")[0] if "/v1/" in url else url
        if probar("modelos instalados", f"{base}/api/tags"):
            print(f"  El servidor responde. Comprueba que '{modelo}' aparezca en la lista.")
        else:
            print("  No responde. Levanta el contenedor con: docker compose up -d ollama")
        if url and modelo:
            print("\nLlamada real de chat")
            cuerpo = json.dumps(
                {"model": modelo, "messages": [{"role": "user", "content": "di hola"}]}
            ).encode()
            probar("chat completions", url, "", cuerpo)
        return

    print("\nConectividad")
    if not probar("internet", "https://example.com"):
        print("\n  Sin salida a internet: el asistente seguirá funcionando con el motor local.")
        return

    print("\nEndpoints de los proveedores soportados")
    for prefijo_proveedor, (nombre, endpoint) in PROVEEDORES.items():
        etiqueta = f"{nombre}{' (clave configurada)' if clave.startswith(prefijo_proveedor) else ''}"
        probar(etiqueta, endpoint, clave if clave.startswith(prefijo_proveedor) else "")

    if clave and url and modelo:
        print("\nLlamada real de chat con la configuración actual")
        cuerpo = json.dumps(
            {"model": modelo, "messages": [{"role": "user", "content": "di hola"}]}
        ).encode()
        if probar("chat completions", url, clave, cuerpo):
            print("\n  El proveedor responde: pon LLM_ENABLED=true para aprovecharlo.")
        else:
            print(
                "\n  El proveedor no responde. Con LLM_ENABLED=false el asistente funciona "
                "igual usando el motor local."
            )


if __name__ == "__main__":
    main()
