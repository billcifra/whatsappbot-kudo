# CLAUDE.md

Guía para Claude Code (claude.ai/code) al trabajar en este repositorio.

## Qué es

Bot de WhatsApp de **KUDO Bolivia** (dojo de artes marciales en La Paz). Recibe mensajes por el webhook de la
WhatsApp Cloud API (Meta) y responde con:
- respuestas fijas (menú 1–7, también como lista interactiva);
- un agente de OpenAI (Agents SDK, `gpt-4.1`) que lleva el embudo del prospecto: nombre → disciplina → turno → día.

Tiene un **panel web** en `/panel` con métricas, prospectos (exportables a CSV), conversaciones, pausa del bot y
respuesta manual.

La estructura sigue la del proyecto hermano `../wp-bot-FOTR` (FastAPI + SQLite en el volumen `/data` de Railway).
Código, comentarios e identificadores en español.

## Comandos

```powershell
pip install -r requirements-dev.txt
uvicorn app.main:app --port 8000 --reload   # servidor local (panel en http://localhost:8000/panel)
pytest                                      # pruebas, sin red
python scripts/simular.py                   # chat por terminal contra el agente REAL (gasta tokens)
python scripts/inspeccionar_db.py           # resumen de la base SQLite
python scripts/importar_sheets.py --simular # prueba la importación del histórico sin guardar
python -m app.panel.usuarios crear ana      # usuarios del panel
```

Producción: **Railway**, que construye con el `Dockerfile` (según `railway.json`, con healthcheck en `/salud`). Corre uvicorn en un solo proceso. La base está en un
Volume montado en `/data` (`DATA_DIR=/data`).

## Mapa del código (`app/`)

| Archivo | Contenido |
|---|---|
| `main.py` | `crear_app()` (FastAPI, lifespan, `/webhook`, `/salud`) y `Servicio`, con todo el flujo de mensajes y las acciones de las herramientas y del panel |
| `config.py` | `Settings` desde el entorno o `.env` (`cargar_settings`) |
| `store.py` | SQLite: esquema, `COLUMNAS_NUEVAS` para migraciones aditivas, todas las consultas |
| `contenido.py` | Menú 1–7 (`respuestas_directas`, `MENU_ROWS`), bienvenida, `FERIADOS`, evento temporal (`EVENTO_*`) |
| `prompts.py` | `SYSTEM_PROMPT` del agente; los horarios están aquí **y** en el menú de `contenido.py` |
| `agente.py` | Herramientas `solicitar_asistencia_humana` y `guardar_datos_prospecto`, `AgenteKudo`, `build_agent_input` |
| `whatsapp.py` | Cliente async (httpx), firma `X-Hub-Signature-256`, `extraer_mensajes` |
| `reintentos.py` | Backoff exponencial: 3 intentos, 1s/2s/4s, timeout de 20s |
| `sheets.py` | Copia secundaria en Google Sheets; escribe en un hilo y nunca bloquea |
| `transcripcion.py` | Notas de voz con Whisper |
| `migracion.py` | Migración única Redis → SQLite (`MIGRAR_DESDE_REDIS_URL`; en Railway, si no está, `REDIS_URL`) |
| `importacion_sheets.py` | Importación única del histórico de Sheets (`IMPORTAR_HISTORICO_SHEETS=true`). Corre después de la migración; fechas de la hoja en UTC; excluye `TEST` y `NUMEROS_PERSONAL` |
| `panel/` | `rutas.py` (rutas), `auth.py` (scrypt, sesiones, CSRF, bloqueo), `metricas.py` (series y normalización), `graficos.py` (SVG del servidor), `templates/`, `static/panel.css` |

### Flujo de un mensaje (`Servicio.procesar`)

1. Se ignoran los grupos (`-` en el número) y los reintentos de Meta (tabla `procesados`).
2. Se procesa un mensaje a la vez por número, con un `asyncio.Lock`.
3. Si el bot está en pausa para ese número, solo se guarda el mensaje: no hay respuesta ni "escribiendo…".
4. Se obtiene el texto según el tipo:
   - texto;
   - opción tocada (el `id` de la fila);
   - audio, que se transcribe;
   - cualquier otro tipo recibe una respuesta amable.
5. Si el usuario es nuevo (`bienvenido=0`), recibe la bienvenida.
6. Si escribe o toca `"1"`–`"7"`, se envían los mensajes fijos y el menú.
7. Lo demás va al agente.
   - Antes de correrlo se guarda el mensaje.
   - Si la respuesta termina en `[[MENU]]`, se envía también el menú interactivo.
   - Se registra el consumo de tokens.

Las herramientas reciben el número por `RunContextWrapper[ContextoAgente]`, no como argumento del modelo.

### Datos (SQLite, `${DATA_DIR}/kudo.db`)

| Tabla | Contenido |
|---|---|
| `contactos` | Perfil del embudo, `bienvenido`, `primer_contacto`, `ultimo_mensaje` (último mensaje **del cliente**, para la ventana de 24 h) |
| `mensajes` | Historial. `rol` user/assistant/staff; `tipo` text/audio/menu/otro/bienvenida; `para_agente` indica qué ve el agente (el menú y lo no soportado no) |
| `eventos` | Para las métricas: nuevo_usuario, menu, agente, datos_prospecto, solicitud_humana, no_soportado |
| `solicitudes_humano` | Solicitudes de atención humana; se marcan como atendidas desde el panel |
| `pausas`, `procesados`, `consumo`, `usuarios`, `sesiones`, `meta` | Pausas del bot, mensajes ya procesados, consumo de la IA, panel y marcas internas |

El agente ve los últimos 40 mensajes (`MAX_TURNOS=20`) de los últimos 90 días (`TTL_SEGUNDOS`).

Todas las fechas se guardan en epoch y se muestran en `America/La_Paz`.

## Reglas

- **Un solo proceso.** No subir `--workers` ni agregar réplicas en Railway: SQLite y los locks por cliente viven en memoria.
- **Cambios de esquema.** Solo aditivos. Una columna nueva va en `COLUMNAS_NUEVAS`; no se reescriben tablas que ya están desplegadas.
- **Horarios y precios.** Si cambian, actualizar `prompts.py` **y** `contenido.py`.
- **Pruebas.** No hacen llamadas de red; usan los dobles de `tests/conftest.py` (`WhatsAppFalso`, `AgenteFalso`, `SheetsFalso`). Cada cambio de flujo lleva su prueba.
- **Panel.** No lleva JavaScript ni recursos externos, por la CSP `default-src 'self'`. Los gráficos son SVG generados en `graficos.py` y estilizados con las clases `g-*`.
- **Secretos.** Nunca subir `.env` ni `credentials.json`. Las variables están en `.env.example`.

## Variables de entorno

Ver `.env.example`.

**Mínimas para producción:**
- `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`
- `OPENAI_API_KEY`
- `GOOGLE_SHEET_KEY`, `GOOGLE_CREDENTIALS_JSON`
- `NUMEROS_PERSONAL`
- `PANEL_USUARIO_INICIAL`, `PANEL_CLAVE_INICIAL`

**Valores por defecto que conviene conocer:**
- Sin `WHATSAPP_APP_SECRET` no se verifica la firma (solo aceptable en local).
- `WHATSAPP_VERIFY_TOKEN` y `NUMEROS_PERSONAL` toman por defecto los valores que antes estaban fijos en el código.

## Pendientes conocidos

- No hay plantillas aprobadas: fuera de la ventana de 24 h, el panel no puede escribirle al cliente.
- La normalización de disciplina, turno y día del panel se hace por palabras clave (`panel/metricas.py`).
