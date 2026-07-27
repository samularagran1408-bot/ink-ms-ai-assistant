# Pruebas de ink-ms-ai-assistant

Hay dos niveles: pruebas del motor local (sin red ni base de datos) y una
verificación end-to-end contra el servicio levantado.

## 1. Motor local

No necesita MongoDB, ni los otros microservicios, ni LLM.

```bash
cd ink-ms-ai-assistant
python tests/test_motor_local.py
```

También funciona con pytest si lo tienes instalado:

```bash
pytest tests/ -v
```

| Prueba | Qué valida |
|--------|------------|
| `test_normalizacion_quita_acentos_y_signos` | "¿Qué rutinas hay?" se normaliza correctamente |
| `test_intenciones_reconocen_frases_naturales` | 18 preguntas reales se clasifican en la intención esperada |
| `test_mensaje_fuera_de_dominio_no_se_clasifica` | Una pregunta ajena al dominio no se fuerza a ninguna intención |
| `test_canonizacion_de_discapacidad` | "Discapacidad Física" y "fisica" se resuelven a `motriz` |
| `test_rutinas_distintas_en_llamadas_sucesivas` | Ocho rutinas seguidas no traen la misma combinación |
| `test_rutina_reproducible_con_semilla` | La misma semilla devuelve la misma rutina |
| `test_rutina_motriz_excluye_ejercicios_de_pie` | El filtro por discapacidad se aplica de verdad |
| `test_rutina_tiene_los_tres_bloques_y_adaptaciones` | Calentamiento, principal y vuelta a la calma, todos con adaptación |
| `test_objetivo_influye_en_la_seleccion` | Cambiar el objetivo cambia los ejercicios |
| `test_catalogo_de_ejercicios_es_consistente` | Sin ids duplicados y con datos completos |
| `test_banco_de_quiz_es_consistente` | Sin opciones repetidas y con índice de respuesta válido |
| `test_barajado_de_opciones_conserva_la_respuesta_correcta` | Al barajar, la respuesta correcta sigue siendo la misma |

## 2. Verificación end-to-end

Recorre todos los endpoints del servicio levantado y comprueba lo que el
usuario final debe notar: respuestas distintas por intención, rutinas que no se
repiten, eventos recomendados y quices generados y evaluados.

Requisitos:

- El servicio en marcha (`uvicorn app.main:app --port 3008`).
- Para la parte de eventos, **ink-ms-sports** arriba con eventos publicados.
- Para comprobar el registro del puntaje del quiz, **ink-ms-users** arriba.

```bash
# Solo lo necesario del monorepo
docker compose up -d mysql auth-service users-service sports-service

# El servicio de IA
cd ink-ms-ai-assistant
uvicorn app.main:app --port 3008

# En otra terminal
python scripts/prueba_e2e.py --usuario <id-de-usuario-real>
```

Si no pasas `--usuario`, se usa un identificador de ejemplo. Con un usuario real
la prueba también verifica que el perfil y su discapacidad se usan para filtrar
eventos y que el puntaje del quiz llega a ink-ms-users.

Para comprobar el flujo completo de aprobación del quiz, el script lee de
MongoDB el quiz recién generado y responde todas las preguntas bien. Necesita
apuntar a la **misma** instancia donde guarda el servicio, que no siempre es la
de `localhost`: si tienes un MongoDB instalado en la máquina y además el
contenedor `inklusport-mongodb`, ambos usan el puerto 27017 y `localhost` va al
local. En ese caso indica la instancia del contenedor:

```bash
python scripts/prueba_e2e.py --mongo-uri "mongodb://admin:admin123@<ip-del-host>:27017/"
```

Sin ese dato el script sigue funcionando: evalúa con respuestas fijas y avisa de
que no localizó el quiz.

## 3. Diagnóstico rápido

Si algo no responde como esperas:

```bash
curl http://localhost:3008/api/ai/health
curl http://localhost:3008/api/ai/diagnostico
```

`health` muestra si MongoDB está conectado y en qué modo trabaja el LLM.
`diagnostico` prueba auth, users y sports, e indica cuántos eventos hay
publicados.

Para comprobar solo la conectividad con el proveedor de LLM:

```bash
python scripts/diag_llm.py
```
