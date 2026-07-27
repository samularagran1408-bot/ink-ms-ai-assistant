# API de ink-ms-ai-assistant

Microservicio de IA de InkluSport (FastAPI, Python 3.11).

- Puerto: **3008**
- Base URL directa: `http://localhost:3008`
- Documentación interactiva: `http://localhost:3008/docs`

## Idea principal: funciona con o sin LLM

El servicio tiene un **motor local** que clasifica intenciones, selecciona
ejercicios del catálogo, puntúa eventos y arma quices. Todo eso funciona sin
salir a internet.

Si además configuras un proveedor de LLM, se usa para enriquecer las respuestas
(mensajes más naturales, notas personalizadas y preguntas extra en los quices).
Si el proveedor falla, el servicio no se degrada: sigue respondiendo con el
motor local y deja de intentar salir durante `LLM_COOLDOWN_SEGUNDOS` para no
añadir latencia a cada petición.

| Situación | Chat | Rutinas | Eventos | Quices |
|-----------|------|---------|---------|--------|
| Sin LLM y sin MongoDB | funciona | funciona | funciona | funciona (sin guardar historial) |
| Sin LLM, con MongoDB | funciona + historial | funciona | funciona | funciona |
| Con LLM | responde también fuera del catálogo de intenciones | añade nota personalizada | redacta el cierre | añade preguntas generadas |

La recomendación de eventos es lo único que necesita otro microservicio:
**ink-ms-sports** con eventos publicados.

## Puesta en marcha

En local:

```bash
cd ink-ms-ai-assistant
pip install -r requirements.txt
uvicorn app.main:app --reload --port 3008
```

Con Docker, desde la raíz del monorepo:

```bash
docker compose up -d mongodb sports-service users-service auth-service ai-service
```

## Configuración

Copia `.env.example` a `.env`. En Docker, `docker-compose.yml` sobrescribe las
URLs con los nombres de los contenedores.

| Variable | Por defecto | Para qué sirve |
|----------|-------------|----------------|
| `MONGODB_URI` | `mongodb://localhost:27017/` | Base de conocimiento, catálogos, conversaciones y quices |
| `MONGODB_DB` | `inclusport_training_ia` | Nombre de la base de datos |
| `MONGODB_URI_ALTERNATIVAS` | localhost 27017 y 27018 | URIs que se prueban si la principal falla |
| `AUTH_SERVICE_URL` | `http://localhost:3001` | Validación de token |
| `USERS_SERVICE_URL` | `http://localhost:3002` | Perfil del usuario y registro de puntajes |
| `SPORTS_SERVICE_URL` | `http://localhost:3003` | Eventos, deportes y adaptaciones |
| `LLM_ENABLED` | `true` | Ponlo en `false` para trabajar solo con el motor local |
| `LLM_PROVIDER` | `openrouter` | Proveedor explícito, o `auto` para deducirlo de la clave |
| `LLM_API_KEY` | vacío | Clave del proveedor. Vacía en los proveedores locales |
| `LLM_MODEL` / `LLM_API_URL` | según el proveedor | Se autocompletan si no concuerdan con el proveedor |
| `LLM_TIMEOUT` | `120` | Segundos de espera por respuesta |
| `LLM_COOLDOWN_SEGUNDOS` | `60` | Pausa tras un fallo del proveedor |

### El LLM es opcional

Todos los endpoints funcionan sin LLM: el motor local cubre el dominio deportivo
(intenciones, rutinas, eventos, análisis de competencia y quices). El LLM sólo
añade una cosa: que el chat conteste preguntas ajenas al deporte en lugar de
redirigir al usuario. Cuando no responde, `modo` vale `motor_local`.

Proveedores soportados: `openrouter`, `openai`, `xai`, `deepseek`, `mistral`,
`together`, `groq` y `ollama` (local, sin clave). Con `LLM_PROVIDER=auto` se
deduce del prefijo de la clave: `sk-or-` → OpenRouter, `gsk_` → Groq,
`xai-` → xAI, `sk-` → OpenAI.

El valor por defecto es OpenRouter con un modelo gratuito, que sólo necesita una
clave gratuita de <https://openrouter.ai/keys>.

Para un LLM local con Ollama, que no arranca por defecto porque son varios GB de
descarga:

```bash
docker compose --profile llm-local up -d
```

y en `.env`: `LLM_PROVIDER=ollama`, `LLM_API_KEY=` vacía y
`LLM_API_URL=http://ollama:11434/v1/chat/completions`.

---

## 1. Estado del servicio

**GET** `/api/ai/health`

Informa el estado real de MongoDB, del LLM y del motor local:

```json
{
  "status": "healthy",
  "llm": { "proveedor": "openrouter", "configurado": true, "contactado": true,
           "disponible": true, "modo": "llm+motor_local",
           "llamadas_ok": 3, "llamadas_fallidas": 0, "ultimo_error": null },
  "mongodb": { "conectado": true, "uri": "mongodb://localhost:27017/" },
  "motor_local": { "intenciones": 32, "ejercicios_en_catalogo": 42,
                   "preguntas_organizador": 30, "preguntas_entrenador": 30 }
}
```

En el bloque `llm`, `configurado` indica que hay proveedor, modelo y clave;
`contactado` indica que además respondió de verdad. `disponible` exige ambas
cosas, para que el diagnóstico no prometa un LLM inaccesible.

**GET** `/api/ai/diagnostico`

Comprueba si los demás microservicios responden y cuántos eventos hay
publicados. Útil cuando la recomendación de eventos vuelve vacía.

---

## 2. Chatbot

**POST** `/api/ai/chat/`

```json
{
  "mensaje": "¿Qué eventos hay disponibles?",
  "usuario_id": "e68b3227-a44d-472e-b5c5-2825fcfcc090",
  "disability_type": "visual"
}
```

`disability_type` es opcional (`visual`, `auditiva`, `motriz`, `cognitiva`,
`intelectual`, `multiple`). Si se omite, se toma del token o se asume perfil
general.

Respuesta:

```json
{
  "conversacion_id": "nueva",
  "respuesta": "Te reviso los eventos disponibles...\n\n- Encuentro de Natación Adaptada (Natación Adaptada) · 2026-08-14 · 5 cupos · con adaptaciones para tu perfil",
  "intencion": "eventos",
  "adaptada": false,
  "confianza": 0.824,
  "fuente": "motor_local",
  "sugerencias": ["Pregúntame cómo inscribirte en el que te interese"],
  "datos": { "eventos": [], "total": 9, "compatibles": 6 }
}
```

- `intencion`: intención detectada, o `no_entendido` si no se reconoce.
- `confianza`: de 0 a 1. Por debajo de 0.34 se considera no reconocida.
- `fuente`: `motor_local` o `llm`.
- `datos`: datos reales consultados para responder (eventos, deportes,
  adaptaciones, ejercicios), cuando la intención los necesita.

### Intenciones que reconoce

| Grupo | Intenciones |
|-------|-------------|
| Conversación | `saludo`, `despedida`, `agradecimiento`, `ayuda` |
| Entrenamiento | `rutinas`, `ejercicios`, `calentamiento`, `estiramiento`, `frecuencia`, `equipamiento` |
| Eventos | `eventos`, `inscripcion`, `progreso` |
| Catálogo | `deportes`, `discapacidades`, `adaptaciones`, `accesibilidad` |
| Verificación | `verificacion_entrenador`, `verificacion_organizador`, `quiz` |
| Salud y hábitos | `lesiones`, `nutricion`, `motivacion` |
| Plataforma | `plataforma`, `cuenta`, `soporte` |

Cada intención tiene varias redacciones que se van rotando, y adaptaciones
específicas para algunos tipos de discapacidad.

---

## 3. Rutinas

**POST** `/api/ai/rutinas/generar`

```json
{
  "usuario_id": "e68b3227-a44d-472e-b5c5-2825fcfcc090",
  "tipo": "en silla de ruedas",
  "objetivo": "ganar fuerza",
  "discapacidad": "motriz",
  "nivel": "principiante",
  "duracion_minutos": 35,
  "semilla": null
}
```

Solo `usuario_id` es obligatorio. Si no envías `discapacidad`, se toma del
perfil del usuario. `semilla` fija la selección para obtener una rutina
reproducible; sin ella, cada llamada devuelve una combinación distinta.

Respuesta (recortada):

```json
{
  "nombre": "Rutina de ganar fuerza y masa muscular · discapacidad física o motriz",
  "objetivo": "Ganar fuerza y masa muscular",
  "nivel": "principiante",
  "discapacidad": "motriz",
  "duracion_estimada_minutos": 32,
  "total_ejercicios": 8,
  "bloques": [
    { "bloque": "Calentamiento", "fase": "calentamiento", "ejercicios": [] },
    { "bloque": "Bloque principal", "fase": "principal", "ejercicios": [] },
    { "bloque": "Vuelta a la calma", "fase": "vuelta_a_la_calma", "ejercicios": [] }
  ],
  "ejercicios": [
    {
      "id": "fue-02",
      "nombre": "Remo con banda elástica",
      "categoria": "fuerza",
      "posicion": "sentado",
      "series": 3,
      "repeticiones": 12,
      "descanso": 60,
      "esfuerzo": 3,
      "material": ["banda elástica"],
      "instrucciones": "Con la banda anclada al frente, tira de los codos hacia atrás...",
      "adaptaciones": "Ejecuta en el rango de movimiento libre de dolor...",
      "seguridad": ""
    }
  ],
  "material_necesario": ["banda elástica"],
  "recomendaciones": "Prioriza control y postura sobre amplitud o carga...",
  "avisos_seguridad": [],
  "nota_personalizada": null,
  "usuario": { "id": "...", "fullName": "Samu Lara", "disability": "motriz" }
}
```

El catálogo tiene 42 ejercicios clasificados por fase, categoría, posición,
nivel y discapacidades compatibles. Los ejercicios de pie no se asignan a
perfiles con discapacidad motriz, y cada ejercicio incluye su adaptación.

---

## 4. Recomendación de eventos

**GET** `/api/ai/recomendacion/eventos/{usuario_id}?limite=3`

Puntúa los eventos reales de ink-ms-sports por compatibilidad con la
discapacidad del perfil, cercanía de la fecha, cupos y estado, y descarta
aquellos en los que el usuario ya está inscrito.

```json
{
  "recomendaciones": [
    {
      "evento_id": "a0000001-0000-4000-8000-000000000001",
      "evento": "Torneo Inclusivo de Fútbol Sala",
      "deporte": "Fútbol Sala",
      "fecha": "2026-08-17",
      "ubicacion": "Polideportivo Municipal El Salitre",
      "cupos_disponibles": 14,
      "compatible_discapacidad": true,
      "adaptaciones": [
        { "discapacidad": "Discapacidad Visual",
          "adaptacion": "Balón sonoro, guías táctiles, comunicación verbal constante" }
      ],
      "razon": "El deporte tiene adaptaciones registradas para discapacidad visual. Quedan 14 cupos disponibles.",
      "puntaje": 77.8,
      "ya_inscrito": false
    }
  ],
  "mensaje": "Samu Lara, encontré 3 evento(s) recomendables de 9 disponibles...",
  "total_eventos_disponibles": 9,
  "eventos_compatibles": 6
}
```

Si `recomendaciones` viene vacío, `mensaje` explica el motivo (no hay eventos
publicados, están cancelados o el usuario ya está inscrito en todos).

---

## 5. Análisis de competencia

**GET** `/api/ai/competencia/analizar/{usuario_id}`

Devuelve estadísticas del panorama competitivo del usuario (eventos
compatibles, cupos, inscripciones, asistencias) junto a ventajas, desventajas y
recomendaciones.

---

## 6. Quices de aptitud

Se generan automáticamente y son distintos en cada llamada: se muestrea el banco
equilibrando temas y dificultad, y se barajan preguntas y opciones.

| Rol | Generar | Evaluar | Umbral |
|-----|---------|---------|--------|
| Organizador | `POST /api/ai/quiz/organizer/generar` | `POST /api/ai/quiz/organizer/evaluar` | 70 |
| Entrenador | `POST /api/ai/quiz/trainer/generar` | `POST /api/ai/quiz/trainer/evaluar` | 75 |

También responden sin el segmento `/quiz`: `POST /api/ai/organizer/generar`.

Generar:

```json
{ "usuario_id": "e68b3227-...", "num_preguntas": 8, "dificultad": "media" }
```

`num_preguntas` va de 5 a 15 y `dificultad` puede ser `baja`, `media` o `alta`.
La respuesta **no incluye la opción correcta**:

```json
{
  "quiz_id": "334c9aea-81e8-4952-a561-d86141c05934",
  "rol": "ORGANIZADOR",
  "umbral_aprobacion": 70.0,
  "num_preguntas": 8,
  "preguntas": [
    {
      "id": "o13",
      "enunciado": "El control de asistencia de un participante inscrito se apoya en:",
      "tema": "asistencia",
      "opciones": [
        { "id": "a", "texto": "El código QR generado en la inscripción" },
        { "id": "b", "texto": "El nombre del deporte" }
      ]
    }
  ],
  "contexto": { "preguntas_en_banco": 30, "preguntas_generadas_por_llm": 0 }
}
```

Evaluar:

```json
{
  "usuario_id": "e68b3227-...",
  "quiz_id": "334c9aea-81e8-4952-a561-d86141c05934",
  "respuestas": [ { "pregunta_id": "o13", "opcion_id": "a" } ],
  "registrar_en_users": true
}
```

Respuesta:

```json
{
  "score": 100.0,
  "correctas": 8,
  "total": 8,
  "aprobado": true,
  "umbral_aprobacion": 70.0,
  "detalle": [
    { "pregunta_id": "o13", "correcta": true, "opcion_elegida": "a",
      "opcion_correcta": "a", "explicacion": "La inscripción confirmada genera un QR..." }
  ],
  "temas_a_reforzar": [],
  "score_registrado_en_users": true,
  "siguiente_paso": "Quiz aprobado con 100.0%. Completa el resto de requisitos..."
}
```

Con `registrar_en_users: true` el puntaje se envía a
`ink-ms-users` (`/api/users/verify/quiz/organizer|trainer/...`). Cada quiz se
evalúa una sola vez: para reintentar hay que generar uno nuevo.

---

## Colecciones en MongoDB

| Colección | Contenido |
|-----------|-----------|
| `catalogo_ejercicios` | Catálogo de ejercicios adaptados |
| `conocimiento_chatbot` | Intenciones con sus redacciones y adaptaciones |
| `banco_preguntas_quiz` | Preguntas de organizador y entrenador |
| `conversaciones_chatbot` | Historial de conversaciones |
| `quizzes_verificacion` | Quices generados, con respuestas y resultado |

Los catálogos se siembran al arrancar solo si faltan, así que puedes editarlos
en MongoDB sin que el reinicio sobrescriba los cambios.

## Errores comunes

| Código | Significado |
|--------|-------------|
| 400 | Quiz inexistente, ya evaluado, de otro rol o de otro usuario |
| 422 | Body inválido (por ejemplo `num_preguntas` fuera de 5-15) |
| 500 | Error inesperado; el detalle indica el agente que falló |

Si la recomendación de eventos vuelve vacía, consulta
`GET /api/ai/diagnostico`: normalmente significa que ink-ms-sports no está
arriba o que no hay eventos publicados.
