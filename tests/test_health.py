"""Salud HTTP del asistente (sin Mongo ni LLM).

    python tests/test_health.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import health_check, root  # noqa: E402


def test_health_reporta_servicio_operativo():
    with patch("app.main.estado_mongo", return_value={"connected": False}):
        result = asyncio.run(health_check())

    assert result["status"] == "healthy"
    assert result["service"] == "ink-ms-ai-assistant"
    assert "chatbot" in result["agents"]
    assert "intenciones" in result["motor_local"]


def test_root_enlaza_salud_y_docs():
    result = asyncio.run(root())

    assert result["health"] == "/api/ai/health"
    assert result["docs"] == "/docs"
    assert result["service"] == "ink-ms-ai-assistant"


def _ejecutar_todo() -> int:
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallidas = 0
    for prueba in pruebas:
        try:
            prueba()
            print(f"  OK   {prueba.__name__}")
        except AssertionError as exc:
            fallidas += 1
            print(f"  FALLA {prueba.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            fallidas += 1
            print(f"  ERROR {prueba.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(pruebas) - fallidas}/{len(pruebas)} pruebas correctas")
    return 1 if fallidas else 0


if __name__ == "__main__":
    raise SystemExit(_ejecutar_todo())
