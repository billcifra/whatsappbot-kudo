"""Panel web del equipo de KUDO Bolivia (PANEL_ACTIVO, activo por defecto).

Vive en el mismo proceso que el bot, en /panel. Usuarios: python -m app.panel.usuarios crear <usuario>
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import FastAPI, Request

from .rutas import router_panel

if TYPE_CHECKING:
    from ..main import Servicio

CABECERAS_SEGURIDAD = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def montar_panel(app: FastAPI, obtener: Callable[[], "Servicio"]) -> None:
    app.include_router(router_panel(obtener))

    @app.middleware("http")
    async def cabeceras_panel(request: Request, siguiente):
        respuesta = await siguiente(request)
        if request.url.path.startswith("/panel"):
            for clave, valor in CABECERAS_SEGURIDAD.items():
                respuesta.headers.setdefault(clave, valor)
            # Las páginas tienen datos personales: que el navegador no las guarde (salvo el CSS).
            respuesta.headers.setdefault("Cache-Control", "no-store")
        return respuesta
