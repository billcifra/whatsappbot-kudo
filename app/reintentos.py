"""Reintentos con backoff exponencial para llamadas a servicios externos (WhatsApp, Google Sheets).

La red y las APIs externas fallan de forma transitoria. En vez de perder el mensaje, se reintenta.
Ninguna función lanza excepción: quien llama decide qué hacer con un None.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import httpx

log = logging.getLogger("reintentos")

HTTP_TIMEOUT = 20                                   # segundos máx. por llamada HTTP
REINTENTOS = 3                                      # nº total de intentos
ESPERA_BASE = 1.0                                   # backoff: 1s, 2s, 4s…
STATUS_REINTENTABLES = {429, 500, 502, 503, 504}    # respuestas que vale la pena reintentar


async def http_con_reintentos(cliente: httpx.AsyncClient, descripcion: str, metodo: str, url: str,
                              **kwargs: Any) -> httpx.Response | None:
    """HTTP con reintentos ante fallos de red o respuestas 5xx/429.

    Devuelve la respuesta (incluso un error no reintentable, p. ej. 4xx) o None si no hubo respuesta.
    """
    for intento in range(1, REINTENTOS + 1):
        try:
            resp = await cliente.request(metodo, url, **kwargs)
        except httpx.HTTPError as e:
            if intento == REINTENTOS:
                log.error("%s: agotados %d intentos (red): %s", descripcion, REINTENTOS, e)
                return None
            espera = ESPERA_BASE * (2 ** (intento - 1))
            log.warning("%s: intento %d falló (red: %s); reintento en %.1fs", descripcion, intento, e, espera)
            await asyncio.sleep(espera)
            continue
        if resp.status_code in STATUS_REINTENTABLES and intento < REINTENTOS:
            espera = ESPERA_BASE * (2 ** (intento - 1))
            log.warning("%s: intento %d devolvió %d; reintento en %.1fs", descripcion, intento, resp.status_code, espera)
            await asyncio.sleep(espera)
            continue
        return resp
    return None


def con_reintentos(descripcion: str, fn: Callable[[], Any]) -> Any:
    """Ejecuta fn() (código bloqueante) reintentando ante cualquier excepción. Devuelve el resultado o None."""
    for intento in range(1, REINTENTOS + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — cualquier fallo de la librería externa
            if intento == REINTENTOS:
                log.error("%s: agotados %d intentos: %s", descripcion, REINTENTOS, e)
                return None
            espera = ESPERA_BASE * (2 ** (intento - 1))
            log.warning("%s: intento %d falló (%s); reintento en %.1fs", descripcion, intento, e, espera)
            time.sleep(espera)
    return None
