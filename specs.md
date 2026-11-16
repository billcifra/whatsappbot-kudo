# Bot de WhatsApp KUDO Bolivia — Especificación

## Descripción general

Bot de WhatsApp del centro de artes marciales **KUDO Bolivia**. Recibe los mensajes por el webhook de la WhatsApp
Business API (Meta) y responde de dos formas:
- de forma determinística: bienvenida y menú de 7 opciones;
- con un agente de IA (OpenAI Agents SDK, `gpt-4.1`), que responde dudas y conduce el embudo del prospecto hacia la
  clase de prueba gratuita.

Todo queda guardado en SQLite, con copia en Google Sheets. El equipo trabaja desde un panel web.

## Stack

| Capa | Tecnología |
|---|---|
| Servidor web | FastAPI + uvicorn (un proceso) |
| IA | OpenAI Agents SDK (`gpt-4.1`) y Whisper (`whisper-1`) para las notas de voz |
| Mensajería | WhatsApp Cloud API (Graph v18.0), cliente async `httpx` con reintentos |
| Persistencia | SQLite en el volumen de Railway (`/data/kudo.db`) |
| Copia secundaria | Google Sheets (`gspread`): hojas `Interesados` y `SolicitudesHumano` |
| Panel | Jinja2 + CSS, gráficos SVG generados en el servidor, sin JavaScript |
| Deploy | Railway (`Dockerfile`) |

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/webhook` | Verificación de Meta (`WHATSAPP_VERIFY_TOKEN`) |
| `POST` | `/webhook` | Mensajes entrantes. Valida `X-Hub-Signature-256` si hay `WHATSAPP_APP_SECRET`, responde 200 enseguida y procesa en segundo plano |
| `GET` | `/salud` | Health check |
| `GET` | `/panel/…` | Panel del equipo (login), descrito más abajo |

## Flujo de un mensaje

1. **Filtros.** Se ignoran los grupos (número con `-`) y los reintentos de Meta (id ya procesado).
2. **Orden.** Se procesa un mensaje a la vez por número.
3. **Pausa.** Si una persona del equipo tomó la conversación, el mensaje solo se guarda: el bot no responde.
4. **Tipo de mensaje.**
   - Texto: se usa tal cual.
   - Opción tocada en el menú: se usa el `id` de la opción (1–7).
   - Nota de voz: se transcribe; si no se entiende, se pide que la escriba.
   - Imagen, sticker, documento u otros: respuesta amable diciendo que solo lee texto y notas de voz.
5. **Usuario nuevo.** Recibe la bienvenida y se le pide su nombre. Si hay un evento vigente, la bienvenida lo anuncia.
6. **Opción "1"–"7".** Recibe la respuesta fija en mensajes cortos (con su nombre si ya lo dio), cierra con la invitación
   a la clase de prueba y se le envía el menú interactivo.
7. **Todo lo demás va al agente.** Recibe:
   - la fecha de hoy, los feriados y el evento vigente;
   - el perfil del prospecto;
   - los últimos 40 mensajes (90 días).

   Si la respuesta termina en `[[MENU]]`, se envía también el menú.

### Menú (1–7)

Horarios · Precios · Disciplinas · Inscripción · Ubicación · ¿Qué es Kudo? · Venta de Guantes. Los textos están en
`app/contenido.py`.

### Herramientas del agente

- **`guardar_datos_prospecto(nombre, disciplina, turno, dia)`**
  - Guarda en el contacto los campos que tengan valor.
  - Registra el evento `datos_prospecto` y anota una fila `[DATOS PROSPECTO]` en Sheets.
- **`solicitar_asistencia_humana(user_message)`**
  - Registra la solicitud en el panel y en Sheets.
  - Avisa por WhatsApp a `NUMEROS_PERSONAL` con el perfil, el link `wa.me` y la conversación reciente.
  - Si `PAUSA_DERIVACION_HORAS` > 0, pausa el bot para ese número.

Las herramientas reciben el número por el contexto de la ejecución, no como argumento del modelo.

## Datos

SQLite, archivo `${DATA_DIR}/kudo.db`. Detalle de las tablas en `CLAUDE.md`.

| Qué | Dónde |
|---|---|
| Perfil del prospecto y si ya fue saludado | `contactos` |
| Historial completo, incluidos el menú y las respuestas del equipo | `mensajes` |
| Eventos para las métricas | `eventos` |
| Solicitudes de atención humana | `solicitudes_humano` |
| Pausas, consumo de IA, usuarios y sesiones del panel | `pausas`, `consumo`, `usuarios`, `sesiones` |

**Google Sheets** recibe las mismas filas que antes, con la fecha en hora de La Paz:

| Hoja | Filas | Columnas |
|---|---|---|
| `Interesados` | `[NUEVO USUARIO] …`, `[DATOS PROSPECTO]` y cada mensaje que llega al agente | teléfono, mensaje, fecha, nombre, disciplina, turno, día |
| `SolicitudesHumano` | Una por solicitud | teléfono, mensaje, fecha |

## Panel (`/panel`)

- **Acceso.** Usuario y contraseña (scrypt). Sesión en cookie httponly con samesite strict. CSRF en cada formulario.
  Bloqueo por 15 minutos tras 5 intentos fallidos.
- **Resumen.** Se puede filtrar por 7, 30 o 90 días.
  - Tarjetas: prospectos nuevos, mensajes, pedidos de atención humana, solicitudes sin atender, chats en pausa.
  - Gráficos: mensajes por día, prospectos nuevos por día, disciplina, turno, día y opciones del menú más usadas.
  - Embudo: cuántos dieron cada dato.
  - Consumo de la IA.
- **Prospectos.** Tabla filtrable por período y disciplina, con exportación a CSV.
- **Conversaciones.** Historial por contacto y perfil. Desde ahí se puede:
  - pausar y reactivar el bot;
  - responder como persona (pausa el bot);
  - marcar las solicitudes como atendidas.

## Limitaciones

- Sin plantillas aprobadas: fuera de la ventana de 24 h no se puede escribir al cliente desde el panel.
- La disciplina, el turno y el día se agrupan por palabras clave para los gráficos.
- El histórico de Sheets se importó una vez y no tiene las elecciones del menú, porque antes no se registraban.
