"""CrewAI de InkluSport: sandbox, tools y agentes.

Las mutaciones de este paquete NO tocan Users :3002 ni Sports :3003.
En Docker no debe haber prompts interactivos (traces / telemetría).
"""

from __future__ import annotations

import os

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
