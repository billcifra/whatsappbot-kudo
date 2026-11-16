"""Panel web: acceso, CSRF, resumen, prospectos (+CSV), conversaciones, pausar y responder."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import crear_app, crear_usuario_inicial
from app.panel.auth import MAX_FALLOS, hash_clave, verificar_clave
from conftest import CLIENTE, armar

CLAVE = "clave-segura-123"


def preparar(settings):
    svc, agente, wa, sheets, store = armar(settings)
    store.crear_usuario("ana", "Ana", hash_clave(CLAVE))
    store.registrar_entrante(CLIENTE, "Ana WA")
    store.marcar_bienvenido(CLIENTE)
    store.actualizar_perfil(CLIENTE, nombre="Juan", disciplina="jiu jitsu", turno="noche", dia="lunes")
    store.agregar_mensaje(CLIENTE, "user", "quiero info <b>bjj</b>")
    store.registrar_evento(CLIENTE, "menu", "1")
    return svc, wa, store


def csrf_de(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "la página no tiene token CSRF"
    return m.group(1)


def entrar(c: TestClient, usuario: str = "ana", clave: str = CLAVE):
    token = csrf_de(c.get("/panel/entrar").text)
    return c.post("/panel/entrar", data={"usuario": usuario, "clave": clave, "csrf": token}, follow_redirects=False)


def publicar(c: TestClient, url: str, pagina: str, **datos):
    token = csrf_de(c.get(pagina).text)
    return c.post(url, data={"csrf": token, **datos}, follow_redirects=False)


def test_hash_de_claves():
    h = hash_clave(CLAVE)
    assert h.startswith("scrypt$") and CLAVE not in h
    assert verificar_clave(CLAVE, h) and not verificar_clave("otra-clave-123", h)


def test_sin_sesion_redirige_al_login(settings):
    svc, *_ = preparar(settings)
    with TestClient(crear_app(servicio=svc)) as c:
        for url in ("/panel/", "/panel/prospectos", "/panel/prospectos.csv", f"/panel/conversaciones/{CLIENTE}"):
            r = c.get(url, follow_redirects=False)
            assert r.status_code == 303 and r.headers["location"] == "/panel/entrar"


def test_panel_desactivado_responde_404(settings):
    settings.panel_activo = False
    svc, *_ = preparar(settings)
    with TestClient(crear_app(servicio=svc)) as c:
        assert c.get("/panel/entrar").status_code == 404


def test_login_y_bloqueo(settings):
    svc, *_ = preparar(settings)
    with TestClient(crear_app(servicio=svc)) as c:
        assert entrar(c, clave="incorrecta-123").status_code == 401
        r = entrar(c)
        assert r.status_code == 303 and "panel_sesion" in r.headers["set-cookie"]
        assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]
    with TestClient(crear_app(servicio=svc)) as c:
        for _ in range(MAX_FALLOS):
            entrar(c, "pepe", "incorrecta-123")
        assert "Demasiados intentos" in entrar(c, "pepe", "incorrecta-123").text


def test_resumen_muestra_graficos_y_cabeceras(settings):
    svc, *_ = preparar(settings)
    with TestClient(crear_app(servicio=svc)) as c:
        entrar(c)
        r = c.get("/panel/?dias=7")
        assert r.status_code == 200
        assert "<svg" in r.text and "BJJ" in r.text and "Noche" in r.text and "Horarios" in r.text
        assert "default-src 'self'" in r.headers["content-security-policy"]
        assert r.headers["cache-control"] == "no-store"


def test_prospectos_y_csv(settings):
    svc, *_ = preparar(settings)
    with TestClient(crear_app(servicio=svc)) as c:
        entrar(c)
        assert "Juan" in c.get("/panel/prospectos?disciplina=BJJ").text
        assert "Juan" not in c.get("/panel/prospectos?disciplina=Kudo").text
        r = c.get("/panel/prospectos.csv")
        assert r.headers["content-type"].startswith("text/csv")
        lineas = r.text.lstrip("﻿").splitlines()
        assert lineas[0].startswith("telefono,nombre") and CLIENTE in lineas[1] and "BJJ" in lineas[1]


def test_conversacion_escapa_html(settings):
    svc, *_ = preparar(settings)
    with TestClient(crear_app(servicio=svc)) as c:
        entrar(c)
        html = c.get(f"/panel/conversaciones/{CLIENTE}").text
        assert "&lt;b&gt;bjj&lt;/b&gt;" in html and "<b>bjj</b>" not in html
        assert c.get("/panel/conversaciones/123abc").status_code == 404


def test_pausar_responder_y_reactivar(settings):
    svc, wa, store = preparar(settings)
    pagina = f"/panel/conversaciones/{CLIENTE}"
    with TestClient(crear_app(servicio=svc)) as c:
        entrar(c)
        r = c.post(f"{pagina}/pausar", data={"csrf": "malo", "horas": "2"}, follow_redirects=False)
        assert r.status_code == 403 and not store.esta_pausado(CLIENTE)
        assert publicar(c, f"{pagina}/pausar", pagina, horas="2").status_code == 303
        assert store.esta_pausado(CLIENTE)
        assert publicar(c, f"{pagina}/reactivar", pagina).status_code == 303
        assert not store.esta_pausado(CLIENTE)
        r = publicar(c, f"{pagina}/responder", pagina, texto="Hola Juan, soy Ana del dojo")
        assert "aviso=enviado" in r.headers["location"]
        assert wa.textos_a(CLIENTE) == ["Hola Juan, soy Ana del dojo"]
        assert store.esta_pausado(CLIENTE)
        assert store.mensajes_de(CLIENTE)[-1]["rol"] == "staff"


def test_marcar_solicitud_atendida(settings):
    svc, _, store = preparar(settings)
    sid = store.crear_solicitud(CLIENTE, "quiero hablar con alguien")
    with TestClient(crear_app(servicio=svc)) as c:
        entrar(c)
        assert "quiero hablar con alguien" in c.get("/panel/").text
        r = publicar(c, f"/panel/solicitudes/{sid}/atendida", "/panel/", volver=CLIENTE)
        assert r.headers["location"] == f"/panel/conversaciones/{CLIENTE}?aviso=atendida"
    assert store.solicitudes_pendientes() == []


def test_usuario_inicial(settings):
    svc, *_rest, store = armar(settings)
    settings.panel_usuario_inicial, settings.panel_clave_inicial = "dojo", "corta"
    crear_usuario_inicial(settings, store)
    assert store.usuarios() == []
    settings.panel_clave_inicial = "una-clave-larga"
    crear_usuario_inicial(settings, store)
    assert [u["usuario"] for u in store.usuarios()] == ["dojo"]
