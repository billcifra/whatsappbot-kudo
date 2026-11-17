"""Servidor web del bot de KUDO Bolivia: webhook de WhatsApp, flujo de mensajes y panel.

Arranque:  uvicorn app.main:app --host 0.0.0.0 --port 8000

Flujo de un mensaje (Servicio.procesar):
  grupo → se ignora · ya procesado (reintento de Meta) → se ignora
  → texto / opción tocada / nota de voz (Whisper); otros tipos reciben una respuesta amable
  → bot en pausa para ese número → solo se guarda el mensaje
  → usuario nuevo → bienvenida
  → "1"-"7" (y "8" mientras haya evento vigente) → respuesta fija en mensajes cortos + menú interactivo
  → lo demás → agente de OpenAI con historial y perfil; [[MENU]] al final → menú interactivo
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .agente import AgenteKudo, Respuesta, build_agent_input
from .config import Settings, cargar_settings
from .importacion_sheets import MARCA as MARCA_IMPORTACION, importar
from .contenido import (AUDIO_NO_ENTENDIDO, EVENTO_ID, EVENTO_NOMBRE, FALLA_AGENTE, FILA_MENU_EVENTO,
                        TIPO_NO_SOPORTADO, TITULO_OPCION, construir_bienvenida, evento_vigente, menu_rows,
                        respuesta_directa)
from .migracion import MARCA as MARCA_MIGRACION, conectar_redis, migrar_desde_redis
from .panel import montar_panel
from .panel.auth import CLAVE_MIN, hash_clave
from .panel.metricas import grupo_edad
from .panel.usuarios import USUARIO_VALIDO
from .sheets import INTERESADOS, SOLICITUDES, Sheets
from .store import CAMPOS_PERFIL, Store
from .transcripcion import Transcriptor
from .whatsapp import MensajeEntrante, WhatsAppClient, extraer_mensajes, firma_valida

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("servidor")

# El bot recuerda a cada lead (historial + perfil) por este tiempo de inactividad.
TTL_SEGUNDOS = 60 * 60 * 24 * 90   # 90 días
MAX_TURNOS = 20                    # turnos (user+assistant) de historial que ve el agente
VENTANA_SEG = 23.5 * 3600          # margen bajo las 24 h de WhatsApp para texto libre


class Agente(Protocol):
    async def responder(self, servicio: "Servicio", wa_id: str, entrada: str) -> Respuesta: ...


class Servicio:
    """Agrupa todo lo que necesita el bot. Las pruebas lo arman con dobles (sin red)."""

    def __init__(self, settings: Settings, store: Store, agente: Agente, wa: WhatsAppClient, sheets: Sheets,
                 transcriptor: Transcriptor):
        self.s, self.store, self.agente, self.wa = settings, store, agente, wa
        self.sheets, self.transcriptor = sheets, transcriptor
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # --- Tiempo local del dojo -------------------------------------------------
    def ahora(self) -> datetime:
        return datetime.now(ZoneInfo(self.s.zona_horaria))

    def fecha_registro(self) -> str:
        return self.ahora().strftime("%Y-%m-%d %H:%M:%S")

    def hoy(self) -> str:
        return self.ahora().strftime("%Y-%m-%d")

    @staticmethod
    def inicio_dia(momento: datetime) -> float:
        return momento.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def dentro_de_ventana(self, wa_id: str) -> bool:
        """True si el cliente escribió hace menos de 24 h (WhatsApp permite texto libre)."""
        c = self.store.contacto(wa_id)
        return bool(c and c["ultimo_mensaje"] and time.time() - c["ultimo_mensaje"] < VENTANA_SEG)

    # --- Envíos (quedan en el historial) -----------------------------------------------
    async def _enviar(self, wa_id: str, texto: str, tipo: str = "text", para_agente: bool = True) -> bool:
        ok = await self.wa.enviar_texto(wa_id, texto)
        self.store.agregar_mensaje(wa_id, "assistant", texto, tipo=tipo, para_agente=para_agente)
        return ok

    async def _menu(self, wa_id: str) -> None:
        """Menú interactivo; incluye la opción del evento mientras esté vigente."""
        await self.wa.enviar_menu(wa_id, filas=menu_rows(self.hoy()))

    # --- Flujo principal -----------------------------------------------------------------
    async def procesar(self, msg: MensajeEntrante) -> None:
        if "-" in msg.wa_id:
            log.info("Mensaje ignorado: proviene de un grupo de WhatsApp.")
            return
        if msg.msg_id and not self.store.marcar_procesado(msg.msg_id):
            log.info("Mensaje %s repetido (reintento de Meta); se ignora", msg.msg_id)
            return
        try:
            async with self._locks[msg.wa_id]:   # un mensaje a la vez por cliente, en orden
                await self._procesar(msg)
        except Exception:
            log.exception("Error procesando el mensaje de %s", msg.wa_id)

    async def _procesar(self, msg: MensajeEntrante) -> None:
        wa_id = msg.wa_id
        pausado = self.store.esta_pausado(wa_id)
        if not pausado:
            # "escribiendo…" cuanto antes: también cubre lo que tarda transcribir un audio
            await self.wa.marcar_leido_y_escribiendo(msg.msg_id)

        texto = msg.texto
        if msg.tipo == "audio":
            audio, mime = await self.wa.descargar_media(msg.media_id)
            texto = await self.transcriptor.transcribir(audio, mime) if audio else ""
            if not texto:
                self.store.registrar_entrante(wa_id, msg.nombre_perfil)
                self.store.agregar_mensaje(wa_id, "user", "[nota de voz que no se pudo transcribir]", tipo="audio",
                                           para_agente=False)
                if not pausado:
                    await self._enviar(wa_id, AUDIO_NO_ENTENDIDO, tipo="otro", para_agente=False)
                return
            log.info("Nota de voz transcrita de %s: %s", wa_id, texto)
        elif msg.tipo not in ("text", "interactive"):
            # Imagen, documento, sticker, ubicación, etc.: aún no se procesan.
            self.store.registrar_entrante(wa_id, msg.nombre_perfil)
            self.store.agregar_mensaje(wa_id, "user", f"[{msg.tipo}]", tipo="otro", para_agente=False)
            self.store.registrar_evento(wa_id, "no_soportado", msg.tipo)
            if not pausado:
                await self._enviar(wa_id, TIPO_NO_SOPORTADO, tipo="otro", para_agente=False)
            return

        if not texto.strip():
            return
        tipo = "audio" if msg.tipo == "audio" else "text"
        log.info("Mensaje recibido de %s: %s", wa_id, texto)
        previo = self.store.contacto(wa_id)
        self.store.registrar_entrante(wa_id, msg.nombre_perfil)

        if pausado:
            # Lo atiende una persona: se guarda para el panel y para el contexto del agente al reactivar.
            self.store.agregar_mensaje(wa_id, "user", texto, tipo=tipo)
            return

        # --- Bienvenida para usuarios nuevos (determinística: gratis e instantánea) ---
        if previo is None or not previo["bienvenido"]:
            await self._bienvenida(wa_id, texto, tipo)
            return

        # --- Opciones directas del menú (1-7, y 8 si hay evento; escritas o tocadas) ---
        clave = texto.strip()
        chunks = respuesta_directa(clave, self.hoy())
        if chunks is not None:
            await self._opcion_menu(wa_id, clave, texto, previo, chunks)
            return

        # --- Todo lo demás va al agente IA, con historial y perfil del prospecto ---
        await self._agente(wa_id, texto, tipo)

    async def _bienvenida(self, wa_id: str, texto: str, tipo: str) -> None:
        self.store.marcar_bienvenido(wa_id)
        self.store.registrar_evento(wa_id, "nuevo_usuario", texto)
        self.sheets.anotar(INTERESADOS, [wa_id, f"[NUEVO USUARIO] {texto}", self.fecha_registro()])
        # El primer mensaje no entra al historial del agente (igual que antes); la bienvenida sí,
        # para que el agente sepa que ya saludó y pidió el nombre.
        self.store.agregar_mensaje(wa_id, "user", texto, tipo=tipo, para_agente=False)
        await self._enviar(wa_id, construir_bienvenida(self.hoy()), tipo="bienvenida")

    async def _opcion_menu(self, wa_id: str, clave: str, texto: str, contacto: dict[str, Any],
                           chunks: list[str]) -> None:
        self.store.poner_tema(wa_id, clave)
        self.store.registrar_evento(wa_id, "menu", clave)
        self.store.agregar_mensaje(wa_id, "user", f"{texto} · {TITULO_OPCION.get(clave, '')}", tipo="menu",
                                   para_agente=False)
        if clave == FILA_MENU_EVENTO["id"]:
            # Tocar la opción del evento ya es una señal de interés: queda marcado para el panel.
            self.store.actualizar_perfil(wa_id, evento=EVENTO_ID)
        nombre = contacto.get("nombre")
        # Respuestas partidas en mensajes cortos; el saludo va solo en el primero.
        for i, chunk in enumerate(chunks):
            if i == 0 and nombre:
                chunk = f"¡Hola, {nombre}! 😊\n\n{chunk}"
            await self._enviar(wa_id, chunk, tipo="menu", para_agente=False)
        await self._menu(wa_id)

    async def _agente(self, wa_id: str, texto: str, tipo: str) -> None:
        # El mensaje se guarda ANTES de correr el agente: el historial lo incluye, como antes.
        self.store.agregar_mensaje(wa_id, "user", texto, tipo=tipo)
        historial = self.store.historial(wa_id, MAX_TURNOS * 2, desde=time.time() - TTL_SEGUNDOS)
        entrada = build_agent_input(wa_id, texto, historial, self.store.contacto(wa_id), self.ahora())
        try:
            r = await self.agente.responder(self, wa_id, entrada)
        except Exception:
            log.exception("Falló el agente para %s; se envía la respuesta de respaldo", wa_id)
            # Respuesta de respaldo: no se deja al cliente sin contestar; el menú no depende de la IA.
            await self._enviar(wa_id, FALLA_AGENTE, tipo="otro", para_agente=False)
            await self._menu(wa_id)
            return
        costo = (r.entrada * self.s.precio_entrada_usd_m + r.salida * self.s.precio_salida_usd_m) / 1_000_000
        self.store.registrar_consumo(wa_id, r.entrada, r.salida, costo)

        # El agente pide mostrar el menú interactivo terminando con [[MENU]].
        mostrar_menu = "[[MENU]]" in r.texto
        respuesta = r.texto.replace("[[MENU]]", "").strip()

        self.store.poner_tema(wa_id, "libre")
        c = self.store.contacto(wa_id) or {}   # incluye lo que guardó guardar_datos_prospecto
        self.store.registrar_evento(wa_id, "agente", texto)
        self.sheets.anotar(INTERESADOS, [wa_id, texto, self.fecha_registro(), c.get("nombre") or "",
                                         c.get("disciplina") or "", c.get("turno") or ""])
        if respuesta:
            await self._enviar(wa_id, respuesta)
        if mostrar_menu:
            await self._menu(wa_id)

    # --- Acciones de las herramientas del agente ---------------------------------------------
    async def solicitar_humano(self, wa_id: str, mensaje: str) -> None:
        """Registra la solicitud y avisa al equipo con el contexto del prospecto."""
        self.store.crear_solicitud(wa_id, mensaje)
        self.store.registrar_evento(wa_id, "solicitud_humana", mensaje)
        self.sheets.anotar(SOLICITUDES, [wa_id, mensaje, self.fecha_registro()])

        c = self.store.contacto(wa_id) or {}
        ultimos = self.store.historial(wa_id, 6)
        historial_txt = "\n".join(
            f"  {'Cliente' if it['role'] == 'user' else 'Bot'}: {it['content'][:120]}" for it in ultimos
        ) or "  (sin historial)"
        extra = ""
        if c.get("edad") or c.get("evento"):
            grupo = grupo_edad(c.get("edad"))
            extra = (f"🧒 Edad: {c.get('edad') or '-'}{f' ({grupo})' if grupo and grupo != 'Otro' else ''}"
                     f"{' | ☀️ Interesado en el ' + EVENTO_NOMBRE.lower() if c.get('evento') == EVENTO_ID else ''}\n")
        aviso = (
            "📩 *Solicitud de atención humana*\n"
            f"👤 Nombre: {c.get('nombre') or c.get('nombre_perfil') or '(desconocido)'}\n"
            f"📱 Teléfono: {wa_id}\n"
            f"💬 Chatear: https://wa.me/{wa_id}\n"
            f"🥋 Interés: {c.get('disciplina') or '-'} | Turno: {c.get('turno') or '-'} | Día: {c.get('dia') or '-'}\n"
            f"{extra}\n"
            f"✉️ Último mensaje del cliente:\n{mensaje}\n\n"
            f"🧵 Conversación reciente:\n{historial_txt}"
        )
        for numero in self.s.numeros_personal:
            await self.wa.enviar_texto(numero, aviso)
        if self.s.pausa_derivacion_horas > 0:
            self.store.pausar(wa_id, self.s.pausa_derivacion_horas, "pidió atención humana")

    def guardar_prospecto(self, wa_id: str, interes_evento: bool = False, **datos: str) -> None:
        """Datos del embudo que entrega el agente. Con `interes_evento` marca el evento vigente (si lo hay)."""
        if interes_evento and evento_vigente(self.hoy()):
            datos["evento"] = EVENTO_ID
        c = self.store.actualizar_perfil(wa_id, **datos)
        perfil = {k: c.get(k) or "" for k in CAMPOS_PERFIL}
        self.store.registrar_evento(wa_id, "datos_prospecto", perfil)
        # edad y evento van al final para no mover las columnas que ya tiene la hoja.
        self.sheets.anotar(INTERESADOS, [wa_id, "[DATOS PROSPECTO]", self.fecha_registro(), perfil["nombre"],
                                         perfil["disciplina"], perfil["turno"], perfil["dia"], perfil["edad"],
                                         perfil["evento"]])

    # --- Acciones del panel ----------------------------------------------------------------
    async def responder_como_persona(self, wa_id: str, texto: str, usuario: str) -> bool:
        """Mensaje de una persona del equipo: se envía, queda en el historial y pausa el bot."""
        if not await self.wa.enviar_texto(wa_id, texto):
            return False
        self.store.agregar_mensaje(wa_id, "staff", texto)
        self.store.pausar(wa_id, self.s.pausa_respuesta_horas, f"respuesta desde el panel ({usuario})")
        return True


# ---------------------------------------------
# Arranque
# ---------------------------------------------
def crear_usuario_inicial(s: Settings, store: Store) -> None:
    """Crea PANEL_USUARIO_INICIAL si todavía no hay usuarios (Railway no tiene consola cómoda)."""
    if not (s.panel_activo and s.panel_usuario_inicial and s.panel_clave_inicial) or store.usuarios():
        return
    if not USUARIO_VALIDO.match(s.panel_usuario_inicial) or len(s.panel_clave_inicial) < CLAVE_MIN:
        log.warning("PANEL_USUARIO_INICIAL o PANEL_CLAVE_INICIAL inválidos (usuario de 3 a 40 caracteres en "
                    "minúscula; clave de al menos %d caracteres): no se creó el usuario.", CLAVE_MIN)
        return
    store.crear_usuario(s.panel_usuario_inicial, s.panel_usuario_inicial, hash_clave(s.panel_clave_inicial))
    log.info("Usuario inicial del panel '%s' creado.", s.panel_usuario_inicial)


async def _migrar_si_corresponde(s: Settings, store: Store) -> None:
    if not s.migrar_desde_redis_url:
        return
    try:
        cliente = await asyncio.to_thread(conectar_redis, s.migrar_desde_redis_url)
        await asyncio.to_thread(migrar_desde_redis, store, cliente)
    except Exception:
        log.exception("No se pudo migrar desde Redis (el bot sigue funcionando con SQLite)")


async def _importar_si_corresponde(svc: "Servicio") -> None:
    if not svc.s.importar_historico_sheets or svc.store.meta(MARCA_IMPORTACION):
        return
    if not svc.sheets.activo:
        log.warning("IMPORTAR_HISTORICO_SHEETS activo, pero Google Sheets no está configurado.")
        return
    if svc.s.migrar_desde_redis_url and not svc.store.meta(MARCA_MIGRACION):
        # Primero Redis: si la importación corriera antes, los contactos de Redis no recibirían su historial.
        log.warning("La migración desde Redis no terminó; la importación de Sheets se pospone al próximo arranque.")
        return
    try:
        interesados = await asyncio.to_thread(svc.sheets.leer, INTERESADOS)
        solicitudes = await asyncio.to_thread(svc.sheets.leer, SOLICITUDES)
        await asyncio.to_thread(importar, svc.store, interesados, solicitudes, set(svc.s.numeros_personal))
    except Exception:
        log.exception("No se pudo importar el histórico de Sheets (se reintentará en el próximo arranque)")


async def _bucle_limpieza(store: Store) -> None:
    """Borra las marcas de mensajes procesados de más de 7 días (solo sirven contra reintentos de Meta)."""
    while True:
        try:
            store.limpiar_procesados(time.time() - 7 * 86400)
        except Exception:
            log.exception("Falló la limpieza de procesados")
        await asyncio.sleep(6 * 3600)


def armar_servicio(s: Settings) -> Servicio:
    store = Store(s.ruta_db)
    log.info("Base de datos: %s", s.ruta_db)
    return Servicio(
        s, store, AgenteKudo(s.modelo), WhatsAppClient(s.whatsapp_token, s.phone_number_id, s.graph_api_version),
        Sheets(s.google_sheet_key, s.google_credentials_json), Transcriptor(s.openai_api_key),
    )


def crear_app(settings: Settings | None = None, servicio: Servicio | None = None) -> FastAPI:
    estado: dict[str, Servicio] = {}

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        svc = servicio or armar_servicio(settings or cargar_settings())
        estado["s"] = svc
        if not svc.s.app_secret:
            log.warning("WHATSAPP_APP_SECRET vacío: no se verifica la firma de los webhooks.")
        await _migrar_si_corresponde(svc.s, svc.store)
        await _importar_si_corresponde(svc)   # después de Redis: no pisa sus perfiles
        crear_usuario_inicial(svc.s, svc.store)
        tarea = asyncio.create_task(_bucle_limpieza(svc.store))
        yield
        tarea.cancel()
        with suppress(asyncio.CancelledError):
            await tarea
        await svc.sheets.esperar()
        if servicio is None:
            await svc.wa.cerrar()
            svc.store.cerrar()

    app = FastAPI(title="Bot KUDO Bolivia", lifespan=ciclo, docs_url=None, redoc_url=None, openapi_url=None)
    montar_panel(app, lambda: estado["s"])

    @app.get("/salud")
    async def salud():
        return {"ok": True}

    @app.get("/webhook")
    async def verificar(request: Request):
        """Verificación inicial del webhook con Meta."""
        q = request.query_params
        if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == estado["s"].s.verify_token:
            return PlainTextResponse(q.get("hub.challenge", ""))
        return PlainTextResponse("Error de verificación", status_code=403)

    @app.post("/webhook")
    async def recibir(request: Request, tareas: BackgroundTasks):
        svc = estado["s"]
        cuerpo = await request.body()
        if svc.s.app_secret and not firma_valida(cuerpo, request.headers.get("X-Hub-Signature-256"), svc.s.app_secret):
            raise HTTPException(status_code=401, detail="Firma inválida")
        try:
            payload = json.loads(cuerpo or b"{}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="JSON inválido") from None
        for msg in extraer_mensajes(payload):
            tareas.add_task(svc.procesar, msg)
        # Meta necesita un 200 rápido; el trabajo sigue en segundo plano.
        return {"ok": True}

    return app


app = crear_app()
