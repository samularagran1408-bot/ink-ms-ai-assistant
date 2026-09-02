"""Checklist de demo CrewAI contra el gateway local (sin Postman).

  python scripts/demo_crew_checklist.py

Usa email/password de postman/Inklusport.local.postman_environment.json
o CREW_DEMO_EMAIL / CREW_DEMO_PASSWORD. No imprime el token ni la clave.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
ENV_POSTMAN = ROOT / "postman" / "Inklusport.local.postman_environment.json"
BASE = os.getenv("CREW_DEMO_BASE", "http://localhost:8080")


def _credenciales() -> tuple[str, str]:
    email = os.getenv("CREW_DEMO_EMAIL", "").strip()
    password = os.getenv("CREW_DEMO_PASSWORD", "")
    if email and password:
        return email, password
    datos = json.loads(ENV_POSTMAN.read_text(encoding="utf-8"))
    vals = {v["key"]: v.get("value") or "" for v in datos.get("values", [])}
    return str(vals.get("email") or ""), str(vals.get("password") or "")


def _ok(nombre: str, condicion: bool, detalle: str = "") -> None:
    marca = "OK" if condicion else "FALLA"
    extra = f" -- {detalle}" if detalle else ""
    print(f"  {marca}  {nombre}{extra}")
    if not condicion:
        raise SystemExit(1)


def main() -> None:
    email, password = _credenciales()
    _ok("credenciales", bool(email and password), "hay usuario de demo")

    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        login = c.post("/api/auth/login", json={"email": email, "password": password})
        _ok("login", login.status_code == 200, f"HTTP {login.status_code}")
        token = login.json().get("token") or login.json().get("accessToken")
        _ok("jwt", bool(token))
        c.headers["Authorization"] = f"Bearer {token}"

        salud = c.get("/api/ai/health")
        writes = (salud.json().get("crew") or {}).get("writes") or {}
        _ok("health", salud.status_code == 200)
        _ok("writes.crew=sandbox", writes.get("crew") == "sandbox", str(writes.get("crew")))
        _ok("writes.chat=mcp", writes.get("chat") == "mcp", str(writes.get("chat")))

        sin = httpx.get(f"{BASE}/api/ai/crew/dominios", timeout=15.0)
        _ok("dominios sin JWT = 401", sin.status_code == 401, f"HTTP {sin.status_code}")

        cat = c.get("/api/ai/crew/dominios")
        _ok("dominios con JWT", cat.status_code == 200, f"HTTP {cat.status_code}")
        cuerpo = cat.json()
        rol = cuerpo.get("rol") or ""
        ids = [d.get("id") for d in cuerpo.get("dominios") or []]
        _ok("writes en catálogo", (cuerpo.get("writes") or {}).get("crew") == "sandbox")
        print(f"      rol={rol} dominios={ids}")

        hola = c.post("/api/ai/crew/run", json={"mensaje": "Hola", "dominio": "auto"})
        detalle = hola.json() if hola.headers.get("content-type", "").startswith("application/json") else {}
        usar_chat = (detalle.get("detail") or {}).get("usar_chat") if isinstance(detalle.get("detail"), dict) else False
        _ok("Hola = 422 chat", hola.status_code == 422 and bool(usar_chat), f"HTTP {hola.status_code}")

        if rol == "USUARIO":
            prohibido = c.post(
                "/api/ai/crew/run",
                json={"mensaje": "¿Cuántos usuarios hay?", "dominio": "auto"},
            )
            _ok("atleta investigacion = 403", prohibido.status_code == 403, f"HTTP {prohibido.status_code}")
        else:
            print(f"      (403 de atleta omitido: sesión es {rol or '?'})")

    kickoff = os.getenv("CREW_DEMO_KICKOFF", "1") != "0"
    if not kickoff:
        print("\nChecklist rápido listo. Kickoff omitido (CREW_DEMO_KICKOFF=0).")
        return

    print("\nKickoffs (hasta ~3 min; 503 si OpenRouter free esta saturado)...")
    with httpx.Client(base_url=BASE, timeout=200.0) as c:
        login = c.post("/api/auth/login", json={"email": email, "password": password})
        token = login.json().get("token") or login.json().get("accessToken")
        c.headers["Authorization"] = f"Bearer {token}"

        cat2 = c.get("/api/ai/crew/dominios").json()
        ids_rol = [d.get("id") for d in cat2.get("dominios") or []]
        pruebas = []
        if "quiz" in ids_rol:
            pruebas.append(("quiz", "¿Cuál es el umbral del quiz de organizador?", "quiz"))
        if "consulta" in ids_rol:
            pruebas.append(("consulta", "Recomiéndame eventos", "consulta"))
        if "automatizado" in ids_rol:
            pruebas.append(
                (
                    "sandbox",
                    "Crea un evento Copa sandbox el 2026-09-15",
                    "automatizado",
                )
            )
        if not pruebas:
            print("      sin dominios para kickoff")
            return

        for nombre, mensaje, dominio in pruebas:
            resp = c.post("/api/ai/crew/run", json={"mensaje": mensaje, "dominio": dominio})
            _ok(f"{nombre} kickoff", resp.status_code in (200, 503), f"HTTP {resp.status_code}")
            if resp.status_code != 200:
                continue
            inf = resp.json().get("informe") or {}
            print(
                f"      via_mcp={inf.get('via_mcp')} via_sandbox={inf.get('via_sandbox')} "
                f"pendiente={inf.get('pendiente_confirmacion')} fuente={inf.get('fuente_tools')}"
            )

    print("\nChecklist de demo terminado.")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as exc:
        print(f"FALLA red: {exc}")
        sys.exit(1)
