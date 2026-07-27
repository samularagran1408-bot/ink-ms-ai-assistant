# Pruebas del modulo IA (sin Postman)

Las pruebas automaticas viven en `src/test/java/com/inklusport/ia/IaApiIntegrationTest.java`.

## Que necesitas

- Java 17
- Maven

Las pruebas usan **Mongo embebido** (no hace falta Docker para `mvn test`).

## Correr todas las pruebas

Desde la carpeta del microservicio:

```bash
cd ai-assistant-ms
mvn test
```

Si todo va bien veras `BUILD SUCCESS` y varios tests en verde.

## Que prueba cada test

| Test | Que valida |
|------|------------|
| `registrarAnalisis_calculaPuntajeYRecomendaciones` | POST analisis, puntaje 65, 3 recomendaciones, guarda en Mongo |
| `historialUsuario_devuelveLista` | GET historial con datos |
| `historialUsuario_sinDatos_devuelve404` | GET sin datos = 404 |
| `planEntrenamiento_creaYActualiza` | PUT plan crea y actualiza sin duplicar |
| `chatbot_devuelveRespuestaFijaPorIntencion` | POST chat con respuestaBot y estado ACTIVA |
| `chatbot_cierreMarcaConversacionCerrada` | mensaje de despedida = CERRADA |
| `validacion_fallaSinCamposObligatorios` | body vacio = 400 |

## Probar manual con Mongo en docker-compose

En la raiz del monorepo:

```bash
docker compose up -d mongo
cd ai-assistant-ms
mvn spring-boot:run
```

Luego puedes usar Postman si quieres, pero con `mvn test` ya queda cubierto el flujo principal.
