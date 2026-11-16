"""Cliente de la WhatsApp Cloud API (Meta) y utilidades del webhook (firma y parseo)."""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .contenido import MENU_BODY, MENU_ROWS
from .reintentos import HTTP_TIMEOUT, REINTENTOS, http_con_reintentos

log = logging.getLogger("whatsapp")


@dataclass
class MensajeEntrante:
    msg_id: str
    wa_id: str                  # número del remitente, p. ej. 59171234567
    nombre_perfil: str | None   # nombre de perfil de WhatsApp, si viene
    tipo: str                   # text, interactive, audio, image, sticker, ...
    texto: str                  # texto escrito o id de la opción tocada ("" si no aplica)
    media_id: str | None = None


def firma_valida(cuerpo: bytes, cabecera: str | None, app_secret: str) -> bool:
    """Verifica la cabecera X-Hub-Signature-256 que Meta envía con cada webhook."""
    if not cabecera or not cabecera.startswith("sha256="):
        return False
    esperado = hmac.new(app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecera.removeprefix("sha256="))


def extraer_mensajes(payload: dict[str, Any]) -> list[MensajeEntrante]:
    """Saca los mensajes entrantes de un webhook. Ignora avisos de estado (entregado, leído)."""
    resultado: list[MensajeEntrante] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            nombres = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", []) or []}
            for m in value.get("messages", []) or []:
                tipo = m.get("type", "text")
                texto, media_id = "", None
                if tipo == "text":
                    texto = (m.get("text") or {}).get("body", "")
                elif tipo == "interactive":
                    inter = m.get("interactive") or {}
                    if inter.get("type") == "list_reply":
                        texto = (inter.get("list_reply") or {}).get("id", "")
                    elif inter.get("type") == "button_reply":
                        texto = (inter.get("button_reply") or {}).get("id", "")
                elif tipo == "audio":
                    media_id = (m.get("audio") or {}).get("id")
                de = m.get("from", "")
                resultado.append(MensajeEntrante(
                    msg_id=m.get("id", ""), wa_id=de, nombre_perfil=nombres.get(de), tipo=tipo,
                    texto=texto or "", media_id=media_id,
                ))
    return resultado


class WhatsAppClient:
    """Envíos con reintentos. Ningún método lanza excepción: devuelven True/False o None."""

    def __init__(self, token: str, phone_number_id: str, version: str = "v18.0"):
        self._base = f"https://graph.facebook.com/{version}"
        self._url_mensajes = f"{self._base}/{phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self._http = httpx.AsyncClient(timeout=HTTP_TIMEOUT)

    async def _post(self, descripcion: str, payload: dict[str, Any]) -> bool:
        resp = await http_con_reintentos(self._http, descripcion, "POST", self._url_mensajes,
                                         headers=self._headers, json=payload)
        if resp is None:
            log.error("%s: sin respuesta tras %d intentos", descripcion, REINTENTOS)
            return False
        if resp.status_code >= 400:
            log.error("%s: WhatsApp respondió %d: %s", descripcion, resp.status_code, resp.text[:500])
            return False
        return True

    async def enviar_texto(self, para: str, texto: str) -> bool:
        log.info("Respuesta a %s: %s", para, texto[:200])
        return await self._post("Envío WhatsApp", {
            "messaging_product": "whatsapp", "to": para, "type": "text", "text": {"body": texto}})

    async def enviar_menu(self, para: str, cuerpo: str = MENU_BODY) -> bool:
        """Menú principal como lista interactiva: al tocar una fila, Meta reenvía su `id` (1-7)."""
        return await self._post("Menú WhatsApp", {
            "messaging_product": "whatsapp", "to": para, "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": "KUDO Bolivia 🥋"},
                "body": {"text": cuerpo},
                "footer": {"text": "Tu primera clase es GRATIS 🎁"},
                "action": {"button": "Ver opciones", "sections": [{"title": "Información", "rows": MENU_ROWS}]},
            },
        })

    async def marcar_leido_y_escribiendo(self, msg_id: str) -> None:
        """Marca como leído y muestra 'escribiendo…' (~25 s o hasta la respuesta). Un fallo se ignora."""
        if not msg_id:
            return
        try:
            await self._http.post(self._url_mensajes, headers=self._headers, json={
                "messaging_product": "whatsapp", "status": "read", "message_id": msg_id,
                "typing_indicator": {"type": "text"}})
        except httpx.HTTPError as e:
            log.warning("No se pudo enviar el indicador de escritura: %s", e)

    async def descargar_media(self, media_id: str | None) -> tuple[bytes | None, str]:
        """Media en 2 pasos: el id da una URL temporal que se baja con el mismo token. (None, '') si falla."""
        if not media_id:
            return None, ""
        headers = {"Authorization": self._headers["Authorization"]}
        meta = await http_con_reintentos(self._http, "Metadata de media", "GET", f"{self._base}/{media_id}",
                                         headers=headers)
        if meta is None or meta.status_code != 200:
            log.warning("Metadata de media falló: %s", getattr(meta, "status_code", "sin respuesta"))
            return None, ""
        datos = meta.json()
        if not datos.get("url"):
            return None, ""
        binario = await http_con_reintentos(self._http, "Descarga de media", "GET", datos["url"], headers=headers)
        if binario is None or binario.status_code != 200:
            log.warning("Descarga de media falló: %s", getattr(binario, "status_code", "sin respuesta"))
            return None, ""
        return binario.content, datos.get("mime_type", "")

    async def cerrar(self) -> None:
        await self._http.aclose()
