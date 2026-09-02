# Crew InkluSport

**Estas mutaciones sandbox no afectan la plataforma real.** El store vive en
`sandbox_data.json`. No hay HTTP a Users `:3002` ni Sports `:3003`.

| `via` | Origen |
|-------|--------|
| `mcp` | Lectura GET al servidor MCP |
| `sandbox` | Store fake |
| `agente` | Motor local (quiz, rutina, perfil) |

## Cinco crews (un dominio cada uno)

| dominio | Agente | Tools |
|---------|--------|--------|
| investigacion | Estadísticas | MCP lectura dashboard/conteos/listados |
| quiz | Preparación quiz | `info_quiz`, `muestra_preguntas_quiz` (local) |
| competencia | Planes | competencia/riesgo local + MCP `listar_eventos_disponibles`, `listar_rutinas_publicadas` |
| automatizado | Sandbox | CRUD fake + `Confirmo` |
| consulta | Asesor individual | MCP perfil/inscripciones/eventos + `recomendar_*` / `generar_rutina` |

Un agente no tiene las tools de otro. `allow_delegation=False`.

```http
POST /api/ai/crew/run
Authorization: Bearer <JWT>

{ "mensaje": "Explica el umbral del quiz de entrenador", "dominio": "quiz" }
```

Demo CLI: `python -m app.crew.crews quiz "¿Cuál es el umbral del organizador?"`

Kickoff investigación: `python -m app.crew.crews`
