"""Rutas del panel: resumen con gráficos, prospectos (+CSV), conversaciones, pausar y responder.

HTML generado en el servidor con Jinja2 (autoescape: lo que escribe un cliente se muestra como texto).
Sin JavaScript ni recursos externos. Cada formulario POST lleva el token CSRF de la sesión.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..contenido import EVENTO_ID, EVENTO_NOMBRE, TITULO_OPCION
from . import auth, graficos, metricas

if TYPE_CHECKING:
    from ..main import Servicio

CARPETA = Path(__file__).resolve().parent
MAX_FORMULARIO = 64 * 1024
MAX_RESPUESTA = 4000
PERIODOS = (7, 30, 90)
_WA_ID = re.compile(r"^\d{6,20}$")

# Mensajes que se muestran tras una acción. Se eligen por clave: nunca se muestra texto de la URL.
AVISOS = {
    "enviado": ("ok", "Mensaje enviado. El bot queda en pausa para este contacto."),
    "error_envio": ("alerta", "No se pudo enviar. Si el contacto no escribió en las últimas 24 h, WhatsApp solo "
                              "permite escribirle con una plantilla aprobada."),
    "pausado": ("ok", "El bot no responderá a este contacto durante la pausa."),
    "reactivado": ("ok", "El bot vuelve a atender a este contacto."),
    "no_estaba": ("ok", "Este contacto no estaba en pausa."),
    "vacio": ("alerta", "Escribe un mensaje antes de enviar."),
    "atendida": ("ok", "Solicitud marcada como atendida."),
    "ya_atendida": ("ok", "Esa solicitud ya estaba atendida."),
}


def _celda_csv(valor: Any) -> str:
    """Evita que Excel interprete un texto del cliente como fórmula."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


def router_panel(obtener: Callable[[], "Servicio"]) -> APIRouter:
    env = Environment(loader=FileSystemLoader(CARPETA / "templates"), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    bloqueos = auth.Bloqueos()

    def servicio_activo() -> "Servicio":
        svc = obtener()
        if not svc.s.panel_activo:
            raise HTTPException(status_code=404)
        return svc

    router = APIRouter(prefix="/panel", dependencies=[Depends(servicio_activo)])

    # --- Utilidades ---------------------------------------------------------
    def zona(svc: "Servicio") -> ZoneInfo:
        return ZoneInfo(svc.s.zona_horaria)

    def render(svc: "Servicio", plantilla: str, request: Request, sesion: dict | None, **datos: Any) -> HTMLResponse:
        z = zona(svc)
        env.filters["fecha"] = lambda ts: datetime.fromtimestamp(ts, z).strftime("%d/%m/%Y %H:%M") if ts else "—"
        env.filters["fecha_corta"] = lambda ts: datetime.fromtimestamp(ts, z).strftime("%d/%m %H:%M") if ts else "—"
        html = env.get_template(plantilla).render(
            negocio="KUDO Bolivia",
            sesion=sesion,
            csrf=sesion["csrf"] if sesion else "",
            aviso=AVISOS.get(request.query_params.get("aviso", "")),
            refrescar=svc.s.panel_refrescar_seg,
            **({"auto_refrescar": False} | datos),
        )
        return HTMLResponse(html)

    def ir(url: str, **params: str) -> RedirectResponse:
        return RedirectResponse(url + (("?" + urlencode(params)) if params else ""), status_code=303)

    async def formulario(request: Request) -> dict[str, str]:
        cuerpo = await request.body()
        if len(cuerpo) > MAX_FORMULARIO:
            raise HTTPException(status_code=413)
        datos = parse_qs(cuerpo.decode("utf-8", "replace"), keep_blank_values=True)
        return {k: v[0] for k, v in datos.items()}

    def sesion_de(request: Request, svc: "Servicio") -> dict | None:
        return auth.sesion(svc.store, request.cookies.get(auth.COOKIE_SESION))

    def exigir_sesion(request: Request, svc: "Servicio" = Depends(servicio_activo)) -> dict:
        s = sesion_de(request, svc)
        if s is None:
            # FastAPI no deja devolver respuestas desde dependencias: 303 hacia el login con una excepción
            raise HTTPException(status_code=303, headers={"Location": "/panel/entrar"})
        return s

    async def exigir_post(request: Request, svc: "Servicio" = Depends(servicio_activo),
                          sesion: dict = Depends(exigir_sesion)) -> tuple[dict, dict[str, str]]:
        datos = await formulario(request)
        if not auth.csrf_valido(sesion["csrf"], datos.get("csrf")):
            raise HTTPException(status_code=403, detail="Formulario vencido. Recarga la página.")
        return sesion, datos

    def validar_wa_id(wa_id: str) -> str:
        if not _WA_ID.match(wa_id):
            raise HTTPException(status_code=404)
        return wa_id

    def periodo(dias: str) -> int:
        return int(dias) if dias.isdigit() and int(dias) in PERIODOS else 30

    # --- Estático -------------------------------------------------------------
    @router.get("/estatico/panel.css", include_in_schema=False)
    async def css():
        return Response((CARPETA / "static" / "panel.css").read_text(encoding="utf-8"), media_type="text/css",
                        headers={"Cache-Control": "public, max-age=3600"})

    # --- Entrar y salir -------------------------------------------------------
    @router.get("/entrar", response_class=HTMLResponse)
    async def entrar_form(request: Request, svc: "Servicio" = Depends(servicio_activo)):
        if sesion_de(request, svc):
            return ir("/panel/")
        token = auth.nuevo_csrf()
        r = render(svc, "entrar.html", request, None, csrf_entrar=token, error="")
        r.set_cookie(auth.COOKIE_CSRF_ENTRAR, token, httponly=True, samesite="strict",
                     secure=svc.s.panel_cookie_segura, path="/panel", max_age=3600)
        return r

    @router.post("/entrar")
    async def entrar(request: Request, svc: "Servicio" = Depends(servicio_activo)):
        datos = await formulario(request)
        if not auth.csrf_valido(request.cookies.get(auth.COOKIE_CSRF_ENTRAR), datos.get("csrf")):
            return ir("/panel/entrar")
        u, error = auth.autenticar(svc.store, bloqueos, datos.get("usuario", ""), datos.get("clave", ""))
        if u is None:
            r = render(svc, "entrar.html", request, None, csrf_entrar=request.cookies.get(auth.COOKIE_CSRF_ENTRAR),
                       error=error, usuario=datos.get("usuario", ""))
            r.status_code = 401
            return r
        horas = svc.s.panel_sesion_horas
        token = auth.crear_sesion(svc.store, u["id"], horas)
        r = ir("/panel/")
        r.set_cookie(auth.COOKIE_SESION, token, httponly=True, samesite="strict", secure=svc.s.panel_cookie_segura,
                     path="/panel", max_age=int(horas * 3600))
        r.delete_cookie(auth.COOKIE_CSRF_ENTRAR, path="/panel")
        return r

    @router.post("/salir")
    async def salir(request: Request, svc: "Servicio" = Depends(servicio_activo), post=Depends(exigir_post)):
        auth.cerrar_sesion(svc.store, request.cookies.get(auth.COOKIE_SESION))
        r = ir("/panel/entrar")
        r.delete_cookie(auth.COOKIE_SESION, path="/panel")
        return r

    # --- Resumen --------------------------------------------------------------
    @router.get("/", response_class=HTMLResponse)
    async def resumen(request: Request, dias: str = "", svc: "Servicio" = Depends(servicio_activo),
                      sesion=Depends(exigir_sesion)):
        z = zona(svc)
        n = periodo(dias)
        ahora = svc.ahora()
        hoy = ahora.date()
        desde = metricas.inicio_de(hoy - timedelta(days=n - 1), z)
        st = svc.store

        serie_msgs = metricas.serie_diaria(st.ts_mensajes_cliente(desde), n, z, hoy)
        serie_nuevos = metricas.serie_diaria(st.ts_primer_contacto(desde), n, z, hoy)
        perfiles = st.perfiles_desde(desde)
        menu = metricas.conteo([e["detalle"] for e in st.eventos_desde("menu", desde)], list(TITULO_OPCION))
        menu = sorted(((TITULO_OPCION[k], v) for k, v in menu), key=lambda kv: -kv[1])
        pendientes = st.solicitudes_pendientes()

        return render(
            svc, "resumen.html", request, sesion, seccion="resumen", auto_refrescar=True,
            dias=n, periodos=PERIODOS,
            nuevos=sum(v for _, v in serie_nuevos), mensajes=sum(v for _, v in serie_msgs),
            solicitudes_periodo=len(st.ts_solicitudes(desde)),
            pendientes=pendientes, pausados=st.pausas_activas(),
            consumo_hoy=st.resumen_consumo(svc.inicio_dia(ahora)),
            consumo_mes=st.resumen_consumo(svc.inicio_dia(ahora.replace(day=1))),
            g_mensajes=graficos.columnas(serie_msgs, "mensajes", "Mensajes de clientes por día"),
            g_nuevos=graficos.columnas(serie_nuevos, "prospectos nuevos", "Prospectos nuevos por día"),
            g_disciplinas=graficos.barras(
                metricas.conteo([metricas.disciplina(p["disciplina"]) for p in perfiles], metricas.DISCIPLINAS),
                "prospectos", "Disciplina de interés"),
            g_turnos=graficos.barras(
                metricas.conteo([metricas.turno(p["turno"]) for p in perfiles], metricas.TURNOS),
                "prospectos", "Turno preferido"),
            g_dias=graficos.barras(
                metricas.conteo([metricas.dia(p["dia"]) for p in perfiles], metricas.DIAS),
                "prospectos", "Día para la clase de prueba"),
            g_menu=graficos.barras(menu, "veces", "Opciones del menú más usadas"),
            tabla_dias=[(graficos.fecha_corta(d), m, nv) for (d, m), (_, nv) in zip(serie_msgs, serie_nuevos)],
            con_nombre=sum(1 for p in perfiles if p["nombre"]),
            con_disciplina=sum(1 for p in perfiles if p["disciplina"]),
            con_turno=sum(1 for p in perfiles if p["turno"]),
            con_dia=sum(1 for p in perfiles if p["dia"]),
            activos=len(perfiles),
        )

    # --- Prospectos ---------------------------------------------------------------
    def nombre_evento(evento_id: str | None) -> str:
        """Nombre legible del evento vigente; los eventos pasados se muestran por su id."""
        if not evento_id:
            return ""
        return EVENTO_NOMBRE if evento_id == EVENTO_ID else evento_id

    def filtrar_prospectos(svc: "Servicio", dias: str, disciplina: str,
                           evento: str = "") -> tuple[list[dict], int, str, str, list[tuple[str, str]]]:
        """Prospectos filtrados. Devuelve también los eventos disponibles como (id, nombre) para el filtro."""
        n = int(dias) if dias.isdigit() and int(dias) in PERIODOS else 0
        disciplina = disciplina if disciplina in metricas.DISCIPLINAS else ""
        desde = metricas.inicio_de(svc.ahora().date() - timedelta(days=n - 1), zona(svc)) if n else 0
        filas, ids_eventos = [], {EVENTO_ID} if EVENTO_ID else set()
        for p in svc.store.prospectos(desde):
            if p["wa_id"] in svc.s.numeros_personal:
                continue
            if p["evento"]:
                ids_eventos.add(p["evento"])
            p["disciplina_cat"] = metricas.disciplina(p["disciplina"]) or ""
            p["grupo"] = metricas.grupo_edad(p["edad"]) or ""
            p["evento_nombre"] = nombre_evento(p["evento"])
            filas.append(p)
        evento = evento if evento in ids_eventos else ""
        filas = [p for p in filas if (not disciplina or p["disciplina_cat"] == disciplina)
                 and (not evento or p["evento"] == evento)]
        eventos = [(e, nombre_evento(e)) for e in sorted(ids_eventos)]
        return filas, n, disciplina, evento, eventos

    @router.get("/prospectos", response_class=HTMLResponse)
    async def prospectos(request: Request, dias: str = "", disciplina: str = "", evento: str = "",
                         svc: "Servicio" = Depends(servicio_activo), sesion=Depends(exigir_sesion)):
        filas, n, disciplina, evento, eventos = filtrar_prospectos(svc, dias, disciplina, evento)
        consulta = urlencode({k: v for k, v in (("dias", str(n) if n else ""), ("disciplina", disciplina),
                                                ("evento", evento)) if v})
        return render(svc, "prospectos.html", request, sesion, seccion="prospectos", prospectos=filas,
                      dias=n, disciplina=disciplina, periodos=PERIODOS, disciplinas=metricas.DISCIPLINAS,
                      evento=evento, eventos=eventos, consulta=consulta)

    @router.get("/prospectos.csv")
    async def prospectos_csv(dias: str = "", disciplina: str = "", evento: str = "",
                             svc: "Servicio" = Depends(servicio_activo), sesion=Depends(exigir_sesion)):
        filas, _, _, _, _ = filtrar_prospectos(svc, dias, disciplina, evento)
        z = zona(svc)
        fmt = lambda ts: datetime.fromtimestamp(ts, z).strftime("%Y-%m-%d %H:%M") if ts else ""  # noqa: E731
        salida = io.StringIO()
        w = csv.writer(salida)
        w.writerow(["telefono", "nombre", "nombre_whatsapp", "disciplina", "disciplina_categoria", "turno", "dia",
                    "primer_contacto", "ultimo_mensaje", "mensajes", "solicitudes_humano", "whatsapp",
                    "edad", "grupo", "evento"])
        for p in filas:
            w.writerow([_celda_csv(v) for v in (
                p["wa_id"], p["nombre"], p["nombre_perfil"], p["disciplina"], p["disciplina_cat"], p["turno"],
                p["dia"], fmt(p["primer_contacto"]), fmt(p["ultimo_mensaje"]), p["mensajes"], p["solicitudes"],
                f"https://wa.me/{p['wa_id']}", p["edad"], p["grupo"], p["evento"])])
        nombre = f"prospectos-{svc.ahora().strftime('%Y%m%d')}.csv"
        return Response("﻿" + salida.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nombre}"'})

    # --- Conversaciones -------------------------------------------------------------
    @router.get("/conversaciones", response_class=HTMLResponse)
    async def conversaciones(request: Request, svc: "Servicio" = Depends(servicio_activo),
                             sesion=Depends(exigir_sesion)):
        # Los números del equipo también aparecen (para ver sus pruebas), marcados como "Equipo".
        # En Prospectos y en el CSV siguen excluidos.
        personal = set(svc.s.numeros_personal)
        filas = svc.store.conversaciones(300)
        for c in filas:
            c["es_equipo"] = c["wa_id"] in personal
        return render(svc, "conversaciones.html", request, sesion, seccion="conversaciones", auto_refrescar=True,
                      conversaciones=filas)

    @router.get("/conversaciones/{wa_id}", response_class=HTMLResponse)
    async def conversacion(request: Request, wa_id: str, svc: "Servicio" = Depends(servicio_activo),
                           sesion=Depends(exigir_sesion)):
        validar_wa_id(wa_id)
        contacto = svc.store.contacto(wa_id)
        if contacto is None:
            raise HTTPException(status_code=404)
        return render(svc, "conversacion.html", request, sesion, seccion="conversaciones", wa_id=wa_id,
                      contacto=contacto, mensajes=svc.store.mensajes_de(wa_id, 300),
                      pausa=svc.store.pausa_de(wa_id), en_ventana=svc.dentro_de_ventana(wa_id),
                      solicitudes=svc.store.solicitudes_de(wa_id), horas_pausa=svc.s.pausa_respuesta_horas,
                      disciplina_cat=metricas.disciplina(contacto["disciplina"]),
                      grupo=metricas.grupo_edad(contacto["edad"]),
                      evento_nombre=nombre_evento(contacto["evento"]),
                      es_equipo=wa_id in svc.s.numeros_personal)

    @router.post("/conversaciones/{wa_id}/responder")
    async def responder(wa_id: str, svc: "Servicio" = Depends(servicio_activo), post=Depends(exigir_post)):
        validar_wa_id(wa_id)
        sesion, datos = post
        texto = datos.get("texto", "").strip()[:MAX_RESPUESTA]
        url = f"/panel/conversaciones/{wa_id}"
        if not texto:
            return ir(url, aviso="vacio")
        ok = await svc.responder_como_persona(wa_id, texto, sesion["usuario"])
        return ir(url, aviso="enviado" if ok else "error_envio")

    @router.post("/conversaciones/{wa_id}/pausar")
    async def pausar(wa_id: str, svc: "Servicio" = Depends(servicio_activo), post=Depends(exigir_post)):
        validar_wa_id(wa_id)
        sesion, datos = post
        try:
            horas = min(max(float(datos.get("horas", "").replace(",", ".") or svc.s.pausa_respuesta_horas), 0.25),
                        24 * 30)
        except ValueError:
            horas = svc.s.pausa_respuesta_horas
        svc.store.pausar(wa_id, horas, f"pausa manual ({sesion['usuario']})")
        return ir(f"/panel/conversaciones/{wa_id}", aviso="pausado")

    @router.post("/conversaciones/{wa_id}/reactivar")
    async def reactivar(wa_id: str, svc: "Servicio" = Depends(servicio_activo), post=Depends(exigir_post)):
        validar_wa_id(wa_id)
        ok = svc.store.reactivar(wa_id)
        return ir(f"/panel/conversaciones/{wa_id}", aviso="reactivado" if ok else "no_estaba")

    # --- Solicitudes de atención humana -------------------------------------------------
    @router.post("/solicitudes/{solicitud_id}/atendida")
    async def atendida(solicitud_id: int, svc: "Servicio" = Depends(servicio_activo), post=Depends(exigir_post)):
        sesion, datos = post
        ok = svc.store.marcar_atendida(solicitud_id, sesion["usuario"])
        volver = datos.get("volver", "")
        url = f"/panel/conversaciones/{volver}" if _WA_ID.match(volver) else "/panel/"
        return ir(url, aviso="atendida" if ok else "ya_atendida")

    return router
