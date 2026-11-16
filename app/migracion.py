"""Migración única: copia los contextos del Redis anterior (ctx:* y bienvenido:*) a SQLite.

Se ejecuta al arrancar solo si existe MIGRAR_DESDE_REDIS_URL y todavía no se hizo (marca en la tabla
meta). Ya se ejecutó en producción (2026-11-16) y el servicio Redis se eliminó; para usarla otra vez
hay que instalar `redis` (no está en requirements.txt).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .store import Store

log = logging.getLogger("migracion")

MARCA = "migracion_redis"
CTX_PREFIX = "ctx:"
BIENVENIDO_PREFIX = "bienvenido:"


def conectar_redis(url: str):
    import redis  # solo se necesita para la migración

    kwargs: dict[str, Any] = {"decode_responses": True}
    if url.startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = None
    cliente = redis.from_url(url, **kwargs)
    cliente.ping()
    return cliente


def migrar_desde_redis(store: Store, cliente) -> dict[str, int]:
    """Copia contactos, perfil e historial. No pisa contactos que ya existan en SQLite."""
    if store.meta(MARCA):
        log.info("La migración desde Redis ya se hizo el %s; no se repite.", store.meta(MARCA))
        return {"contactos": 0, "mensajes": 0, "saludados": 0}
    with store.en_lote():   # todo o nada: si falla a medias, se reintenta completa en el próximo arranque
        return _migrar(store, cliente)


def _migrar(store: Store, cliente) -> dict[str, int]:
    contactos = mensajes = saludados = 0
    vistos: set[str] = set()
    for clave in cliente.scan_iter(CTX_PREFIX + "*"):
        wa_id = clave[len(CTX_PREFIX):]
        try:
            ctx = json.loads(cliente.get(clave) or "{}")
        except (TypeError, ValueError):
            log.warning("Contexto ilegible en %s; se omite", clave)
            continue
        vistos.add(wa_id)
        if store.contacto(wa_id) is not None:
            continue
        ultimo = float(ctx.get("last_seen") or ctx.get("timestamp") or time.time())
        historial = ctx.get("history") or []
        # Redis no guardaba la hora de cada mensaje: se reparten hacia atrás, un segundo entre cada uno.
        primero = ultimo - len(historial)
        store.registrar_entrante(wa_id, None, ts=primero)
        store.marcar_bienvenido(wa_id)
        store.actualizar_perfil(wa_id, nombre=ctx.get("nombre", ""), disciplina=ctx.get("disciplina_raw", ""),
                                turno=ctx.get("turno_raw", ""), dia=ctx.get("dia_raw", ""))
        if ctx.get("tema"):
            store.poner_tema(wa_id, str(ctx["tema"]))
        ultimo_cliente = None
        for i, item in enumerate(historial):
            rol = item.get("role")
            if rol not in ("user", "assistant") or not item.get("content"):
                continue
            ts = primero + i
            store.agregar_mensaje(wa_id, rol, str(item["content"]), ts=ts)
            mensajes += 1
            if rol == "user":
                ultimo_cliente = ts
        # ultimo_mensaje = último mensaje del cliente (lo usa la ventana de 24 h)
        store.registrar_entrante(wa_id, None, ts=ultimo_cliente or ultimo)
        contactos += 1
    for clave in cliente.scan_iter(BIENVENIDO_PREFIX + "*"):
        wa_id = clave[len(BIENVENIDO_PREFIX):]
        if wa_id in vistos or store.contacto(wa_id) is not None:
            continue
        store.registrar_entrante(wa_id, None)
        store.marcar_bienvenido(wa_id)
        saludados += 1
    store.poner_meta(MARCA, time.strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Migración desde Redis: %d contactos, %d mensajes, %d solo saludados", contactos, mensajes, saludados)
    return {"contactos": contactos, "mensajes": mensajes, "saludados": saludados}
