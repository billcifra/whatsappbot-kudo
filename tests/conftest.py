"""Dobles de prueba y utilidades compartidas (sin red: ni WhatsApp, ni OpenAI, ni Google)."""

from __future__ import annotations

import hashlib
import inspect
import hmac
import time
from typing import Callable

import pytest

from app.agente import Respuesta
from app.config import cargar_settings
from app.main import Servicio
from app.store import Store

SECRETO = "secreto-de-prueba"
CLIENTE = "59171234567"
PERSONAL = "59170000001"


class WhatsAppFalso:
    def __init__(self):
        self.enviados: list[tuple[str, str]] = []
        self.menus: list[str] = []
        self.filas_menu: list[list[dict] | None] = []
        self.leidos: list[str] = []
        self.media: tuple[bytes | None, str] = (b"audio-falso", "audio/ogg")
        self.falla = False

    async def enviar_texto(self, para, texto):
        if self.falla:
            return False
        self.enviados.append((para, texto))
        return True

    async def enviar_menu(self, para, cuerpo="", filas=None):
        self.menus.append(para)
        self.filas_menu.append(filas)
        return True

    async def marcar_leido_y_escribiendo(self, msg_id):
        self.leidos.append(msg_id)

    async def descargar_media(self, media_id):
        return self.media

    async def cerrar(self):
        pass

    def textos_a(self, para: str) -> list[str]:
        return [t for p, t in self.enviados if p == para]


class AgenteFalso:
    """Devuelve respuestas guionadas. Cada respuesta puede ser texto o una función que actúa como
    las herramientas (recibe el servicio y el wa_id) y devuelve el texto."""

    def __init__(self, respuestas: list[str | Callable] | None = None):
        self.respuestas = list(respuestas or [])
        self.entradas: list[str] = []

    async def responder(self, servicio, wa_id, entrada):
        self.entradas.append(entrada)
        r = self.respuestas.pop(0) if self.respuestas else "Respuesta del agente"
        if callable(r):
            r = r(servicio, wa_id)
            if inspect.isawaitable(r):
                r = await r
        return Respuesta(r, entrada=1000, salida=200)


class SheetsFalso:
    def __init__(self):
        self.filas: list[tuple[str, list[str]]] = []
        self.activo = True

    def anotar(self, hoja, fila):
        self.filas.append((hoja, fila))

    async def esperar(self):
        pass


class TranscriptorFalso:
    def __init__(self, texto: str = "hola, quiero info de bjj"):
        self.texto = texto

    async def transcribir(self, audio, mime):
        return self.texto


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for k, v in {
        "DATA_DIR": str(tmp_path), "WHATSAPP_VERIFY_TOKEN": "verifica", "WHATSAPP_APP_SECRET": SECRETO,
        "NUMEROS_PERSONAL": PERSONAL, "OPENAI_API_KEY": "sk-test", "GOOGLE_SHEET_KEY": "",
        "GOOGLE_CREDENTIALS_JSON": "", "GOOGLE_CREDENTIALS_FILE": str(tmp_path / "no-existe.json"),
        "PANEL_COOKIE_SEGURA": "false", "MIGRAR_DESDE_REDIS_URL": "", "PAUSA_DERIVACION_HORAS": "0",
    }.items():
        monkeypatch.setenv(k, v)
    return cargar_settings(env_file=tmp_path / "no-existe.env")


def armar(settings, respuestas=None, texto_audio="hola, quiero info de bjj"):
    store = Store(settings.data_dir / "test.db")
    agente, wa, sheets = AgenteFalso(respuestas), WhatsAppFalso(), SheetsFalso()
    svc = Servicio(settings, store, agente, wa, sheets, TranscriptorFalso(texto_audio))
    return svc, agente, wa, sheets, store


def payload(texto: str = "", msg_id: str = "wamid.1", de: str = CLIENTE, tipo: str = "text",
            interactivo: str | None = None) -> dict:
    m: dict = {"from": de, "id": msg_id, "timestamp": str(int(time.time())), "type": tipo}
    if tipo == "text":
        m["text"] = {"body": texto}
    elif tipo == "interactive":
        m["interactive"] = {"type": "list_reply", "list_reply": {"id": interactivo, "title": "x"}}
    elif tipo == "audio":
        m["audio"] = {"id": "media-1", "mime_type": "audio/ogg"}
    elif tipo == "image":
        m["image"] = {"id": "media-2", "mime_type": "image/jpeg"}
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "123"},
        "contacts": [{"wa_id": de, "profile": {"name": "Ana WA"}}], "messages": [m]}}]}]}


def firmar(cuerpo: bytes) -> str:
    return "sha256=" + hmac.new(SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()
