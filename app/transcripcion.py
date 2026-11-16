"""Transcripción de notas de voz con Whisper (OpenAI)."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

log = logging.getLogger("transcripcion")


def extension(mime: str) -> str:
    """WhatsApp envía las notas de voz como audio/ogg (opus); otros formatos por si acaso."""
    if "mp4" in mime or "m4a" in mime:
        return "m4a"
    if "mpeg" in mime or "mp3" in mime:
        return "mp3"
    return "ogg"


class Transcriptor:
    def __init__(self, api_key: str):
        self._cliente = AsyncOpenAI(api_key=api_key) if api_key else None

    async def transcribir(self, audio: bytes, mime: str) -> str:
        """Devuelve el texto o "" si no se pudo."""
        if self._cliente is None:
            log.error("Sin OPENAI_API_KEY: no se puede transcribir audio")
            return ""
        try:
            resultado = await self._cliente.audio.transcriptions.create(
                model="whisper-1", file=(f"audio.{extension(mime)}", audio))
            return (getattr(resultado, "text", "") or "").strip()
        except Exception as e:  # noqa: BLE001
            log.error("Falló la transcripción de audio: %s", e)
            return ""
