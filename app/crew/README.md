# Crew InkluSport

**Estas mutaciones sandbox no afectan la plataforma real.** El store vive en
`sandbox_data.json`. No hay HTTP a Users `:3002` ni Sports `:3003`.

| `via` | Origen |
|-------|--------|
| `mcp` | Lectura GET al servidor MCP |
| `sandbox` | Store fake |
| `agente` | Motor local (quiz, rutina, perfil) |

**Escritura:** crew = `sandbox`. Chat = MCP real (`POST /api/ai/chat` + Confirmo).
El chat **orquesta CrewAI** en consulta, quiz, plan e investigación
(`CHAT_ORQUESTA_CREW=true`). Altas reales no pasan por crew.

## Cinco crews (un dominio cada uno)

| dominio | Agente | Tools |
|---------|--------|--------|
| investigacion | Estadísticas | MCP lectura dashboard/conteos/listados |
| quiz | Preparación quiz | `info_quiz`, `muestra_preguntas_quiz` (local) |
| competencia | Planes | competencia/riesgo local + MCP `listar_eventos_disponibles`, `listar_rutinas_publicadas` |
| automatizado | Sandbox | CRUD fake + `Confirmo` |
| consulta | Asesor individual | MCP perfil/inscripciones/`listar_eventos`/`listar_eventos_disponibles` + `recomendar_*` / `generar_rutina` |

Un agente no tiene las tools de otro. `allow_delegation=False`.

## Contrato para el front

```http
GET /api/ai/crew/dominios
Authorization: Bearer <JWT>
```

Catálogo del selector **según el rol** (atleta ≠ admin).

| Rol | Dominios |
|-----|----------|
| USUARIO | consulta, competencia |
| ENTRENADOR | quiz, competencia, consulta, automatizado |
| ORGANIZADOR | quiz, automatizado, consulta, investigacion |
| ADMIN | los cinco |

```http
POST /api/ai/crew/run
Authorization: Bearer <JWT>

{ "mensaje": "Explica el umbral del quiz de entrenador", "dominio": "auto" }
```

`dominio` puede omitirse (`auto`). El asistente clasifica con las intenciones del chat.

Respuesta:

```json
{
  "dominio": "quiz",
  "dominio_origen": "auto",
  "intencion": "quiz",
  "confianza": 0.81,
  "fuente": "crew",
  "informe": {
    "resumen": "...",
    "tools_usadas": ["info_quiz"],
    "via_mcp": false,
    "via_sandbox": false,
    "fuente_tools": "agente",
    "hallazgos": "..."
  }
}
```

| HTTP | Cuándo |
|------|--------|
| 401 | Sin JWT o token inválido |
| 403 | El rol no puede usar ese dominio |
| 422 `usar_chat: true` | Saludo/ayuda → `POST /api/ai/chat` |
| 422 con `dominios` | Mensaje ambiguo: pinta el selector |
| 503 | OpenRouter `:free` saturado |
| 504 | Kickoff > `CREW_TIMEOUT_SEGUNDOS` (180) |

«Confirmo» solo, sin dominio, va a `automatizado` **si el rol lo permite**.
El front reenvía el mismo `dominio` y, si `pendiente_confirmacion`, muestra
el botón de confirmar.

Saludos **no** son crew.

Demo CLI: `python -m app.crew.enrutar`

Kickoff: `python -m app.crew.crews quiz "¿Cuál es el umbral del organizador?"`
