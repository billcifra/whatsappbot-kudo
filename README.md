# Bot de WhatsApp — KUDO Bolivia

Bot que atiende el WhatsApp del dojo con dos tipos de respuesta:
- respuestas fijas (menú de 7 opciones);
- un agente de IA que responde dudas y anota el embudo del prospecto: nombre, disciplina, turno y día de la clase de prueba.

El equipo usa un panel web en `/panel` para ver métricas, prospectos y conversaciones, y para pausar el bot o responder a mano.

Para el detalle técnico, ver [CLAUDE.md](CLAUDE.md). La especificación funcional está en [specs.md](specs.md).

## Correr en local

```powershell
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env        # completar los valores
uvicorn app.main:app --port 8000 --reload
```

**Panel:** http://localhost:8000/panel. En local:
- pon `PANEL_COOKIE_SEGURA=false`;
- crea un usuario con `python -m app.panel.usuarios crear <usuario>`, o define `PANEL_USUARIO_INICIAL` y `PANEL_CLAVE_INICIAL`.

**Pruebas:** `pytest`, sin red.

**Probar el agente real por terminal:** `python scripts/simular.py`. Usa `data/simulador.db` y gasta tokens.

## Deploy en Railway, paso a paso

1. **Volume.** En el servicio del bot ve a *Settings → Volumes* y agrega un volumen montado en **`/data`**. Ahí vive la
   base SQLite (`/data/kudo.db`): sin volumen, los datos se pierden en cada deploy. El `Dockerfile` ya define `DATA_DIR=/data`.
2. **Build.** `railway.json` le indica a Railway que use el `Dockerfile` y fija una réplica y el healthcheck en `/salud`.
   Si la versión nueva no responde, Railway mantiene la anterior. Ya no hay `Procfile`.
3. **Puerto.** Uvicorn escucha en `$PORT`, que Railway define, o en 8000 si no hay `$PORT`. Si el dominio público apuntaba
   fijo al puerto 8000, revisa en *Settings → Networking* que coincida con el puerto donde escucha la app.
4. **Variables** (*Variables*). Además de las que ya existían:
   - `WHATSAPP_VERIFY_TOKEN`: el mismo que está en Meta. Hasta ahora era `mibotverificacion`.
   - `WHATSAPP_APP_SECRET`: *App Secret* de la app en developers.facebook.com. Activa la validación de firma.
   - `NUMEROS_PERSONAL`: números del equipo separados por coma.
   - `PANEL_USUARIO_INICIAL` y `PANEL_CLAVE_INICIAL`: primer usuario del panel (clave de 10 o más caracteres).
   - `IMPORTAR_HISTORICO_SHEETS=true`: importa una vez el histórico de Google Sheets (ver el paso 6).
   - La migración desde Redis usa el `REDIS_URL` que ya existe. Para desactivarla, define `MIGRAR_DESDE_REDIS_URL` vacía.
5. **Una sola réplica.** No escales a más réplicas ni workers: SQLite y el orden de los mensajes viven en un único proceso.
6. **Datos anteriores.** Al primer arranque, y una sola vez (queda una marca en la base):
   - El bot copia de Redis los contactos, el perfil y el historial.
   - Después importa el histórico de Sheets:
     - contactos, eventos para los gráficos y solicitudes (estas quedan como atendidas);
     - pone la hora real a los mensajes que vinieron de Redis;
     - omite las filas `TEST` y las de los números del equipo.
   - Los logs muestran los conteos. Revisa en el panel (*Prospectos* y *Resumen* con 90 días) que estén los datos.
   - Después borra `IMPORTAR_HISTORICO_SHEETS` y `REDIS_URL`, elimina el servicio Redis y quita `redis` de `requirements.txt`.
   - Para probar la importación en local sin guardar nada: `python scripts/importar_sheets.py --simular`.
7. **Verificación.**
   - `https://<tu-dominio>/salud` responde `{"ok": true}`.
   - Escríbele al bot desde un número de prueba.
   - Entra a `https://<tu-dominio>/panel`.

## Estructura

```
app/            código del bot (ver CLAUDE.md)
  panel/        panel web: rutas, auth, métricas, gráficos SVG, plantillas
scripts/        simular.py (chat por terminal), inspeccionar_db.py, importar_sheets.py
tests/          pruebas con pytest (sin red)
Dockerfile      imagen para Railway
railway.json    build con Dockerfile, 1 réplica, healthcheck /salud
```
