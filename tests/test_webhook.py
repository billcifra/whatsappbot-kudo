"""Flujo de mensajes: webhook, bienvenida, menú, agente, pausa, audio, deduplicación y firma."""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from app.contenido import AUDIO_NO_ENTENDIDO, TIPO_NO_SOPORTADO, respuestas_directas
from app.main import crear_app
from app.sheets import INTERESADOS, SOLICITUDES
from app.whatsapp import extraer_mensajes
from conftest import CLIENTE, PERSONAL, armar, firmar, payload


def enviar(svc, *payloads):
    for p in payloads:
        for msg in extraer_mensajes(p):
            asyncio.run(svc.procesar(msg))


def saludado(svc, wa):
    """Deja al cliente ya saludado y limpia lo enviado."""
    enviar(svc, payload("Hola", "wamid.0"))
    wa.enviados.clear()
    wa.menus.clear()


# --- Webhook HTTP ---------------------------------------------------------------
def test_verificacion_de_meta(settings):
    svc, *_ = armar(settings)
    with TestClient(crear_app(servicio=svc)) as c:
        ok = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verifica", "hub.challenge": "42"})
        assert ok.status_code == 200 and ok.text == "42"
        assert c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "otro"}).status_code == 403


def test_firma_invalida_se_rechaza(settings):
    svc, _, wa, *_ = armar(settings)
    cuerpo = json.dumps(payload("Hola")).encode()
    with TestClient(crear_app(servicio=svc)) as c:
        r = c.post("/webhook", content=cuerpo, headers={"X-Hub-Signature-256": "sha256=malo",
                                                        "Content-Type": "application/json"})
        assert r.status_code == 401
    assert wa.enviados == []


def test_webhook_firmado_responde_y_procesa(settings):
    svc, _, wa, *_ = armar(settings)
    cuerpo = json.dumps(payload("Hola")).encode()
    with TestClient(crear_app(servicio=svc)) as c:
        r = c.post("/webhook", content=cuerpo, headers={"X-Hub-Signature-256": firmar(cuerpo),
                                                        "Content-Type": "application/json"})
        assert r.status_code == 200
    assert "Bienvenido/a a *KUDO Bolivia*" in wa.textos_a(CLIENTE)[0]


def test_salud(settings):
    svc, *_ = armar(settings)
    with TestClient(crear_app(servicio=svc)) as c:
        assert c.get("/salud").json() == {"ok": True}


# --- Flujo -------------------------------------------------------------------------
def test_usuario_nuevo_recibe_bienvenida_y_queda_registrado(settings):
    svc, agente, wa, sheets, store = armar(settings)
    enviar(svc, payload("Hola, vi su anuncio"))
    assert len(wa.textos_a(CLIENTE)) == 1 and "¿cómo te llamas?" in wa.textos_a(CLIENTE)[0]
    assert agente.entradas == []
    c = store.contacto(CLIENTE)
    assert c["bienvenido"] == 1 and c["nombre_perfil"] == "Ana WA"
    assert store.eventos_desde("nuevo_usuario", 0)[0]["detalle"] == "Hola, vi su anuncio"
    assert sheets.filas[0][0] == INTERESADOS and sheets.filas[0][1][1] == "[NUEVO USUARIO] Hola, vi su anuncio"
    # el agente ve la bienvenida, pero no el primer mensaje (igual que antes)
    assert [h["role"] for h in store.historial(CLIENTE, 40)] == ["assistant"]


def test_opcion_del_menu_escrita_o_tocada(settings):
    svc, agente, wa, _, store = armar(settings)
    saludado(svc, wa)
    store.actualizar_perfil(CLIENTE, nombre="Juan")
    enviar(svc, payload("2", "wamid.2"), payload(tipo="interactive", interactivo="5", msg_id="wamid.3"))
    textos = wa.textos_a(CLIENTE)
    assert len(textos) == len(respuestas_directas["2"]) + len(respuestas_directas["5"])
    assert textos[0].startswith("¡Hola, Juan! 😊") and "Bs. *250/mes*" in textos[0]
    assert wa.menus == [CLIENTE, CLIENTE]
    assert agente.entradas == []
    assert [e["detalle"] for e in store.eventos_desde("menu", 0)] == ["2", "5"]
    assert store.contacto(CLIENTE)["tema"] == "5"


def test_texto_libre_va_al_agente_con_historial_y_perfil(settings):
    svc, agente, wa, sheets, store = armar(settings, ["¡Claro! Te cuento [[MENU]]"])
    saludado(svc, wa)
    store.actualizar_perfil(CLIENTE, nombre="Juan", disciplina="BJJ")
    enviar(svc, payload("¿cuánto cuesta?", "wamid.2"))
    entrada = agente.entradas[0]
    assert f"TELÉFONO_USUARIO: {CLIENTE}" in entrada and "FECHA_HOY:" in entrada
    assert "Nombre: Juan" in entrada and "Disciplina de interés: BJJ" in entrada
    assert "HISTORIAL_CONVERSACION:" in entrada and entrada.endswith("MENSAJE_ACTUAL_USUARIO: ¿cuánto cuesta?")
    assert wa.textos_a(CLIENTE) == ["¡Claro! Te cuento"]
    assert wa.menus == [CLIENTE]
    assert store.contacto(CLIENTE)["tema"] == "libre"
    assert store.resumen_consumo(0)["llamadas"] == 1
    assert sheets.filas[-1] == (INTERESADOS, [CLIENTE, "¿cuánto cuesta?", sheets.filas[-1][1][2], "Juan", "BJJ", ""])


def test_herramientas_guardan_perfil_y_avisan_al_equipo(settings):
    def con_herramientas(svc, wa_id):
        svc.guardar_prospecto(wa_id, nombre="Juan", turno="noche")
        return svc.solicitar_humano(wa_id, "quiero hablar con alguien")

    async def agente(svc, wa_id):
        await con_herramientas(svc, wa_id)
        return "Listo, ya avisé al equipo."

    svc, _, wa, sheets, store = armar(settings, [agente])
    saludado(svc, wa)
    enviar(svc, payload("quiero hablar con alguien", "wamid.2"))
    c = store.contacto(CLIENTE)
    assert c["nombre"] == "Juan" and c["turno"] == "noche"
    aviso = wa.textos_a(PERSONAL)[0]
    assert "Solicitud de atención humana" in aviso and f"https://wa.me/{CLIENTE}" in aviso and "Juan" in aviso
    assert store.solicitudes_pendientes()[0]["mensaje"] == "quiero hablar con alguien"
    assert any(h == SOLICITUDES for h, _ in sheets.filas)
    assert any(f[1] == "[DATOS PROSPECTO]" and f[3] == "Juan" for _, f in sheets.filas)
    assert not store.esta_pausado(CLIENTE)   # PAUSA_DERIVACION_HORAS=0


def test_derivacion_puede_pausar_el_bot(settings):
    settings.pausa_derivacion_horas = 2
    svc, *_rest, store = armar(settings)
    asyncio.run(svc.solicitar_humano(CLIENTE, "ayuda"))
    assert store.esta_pausado(CLIENTE)


def test_bot_pausado_no_responde_pero_guarda(settings):
    svc, agente, wa, _, store = armar(settings)
    saludado(svc, wa)
    store.pausar(CLIENTE, 1, "prueba")
    enviar(svc, payload("¿hay alguien?", "wamid.2"), payload("1", "wamid.3"))
    assert wa.enviados == [] and wa.menus == [] and agente.entradas == []
    assert [m["contenido"] for m in store.mensajes_de(CLIENTE)][-2:] == ["¿hay alguien?", "1"]
    assert wa.leidos == ["wamid.0"]   # tampoco muestra "escribiendo…"


def test_nota_de_voz_se_transcribe(settings):
    svc, agente, wa, _, store = armar(settings, ["Sí, tenemos BJJ"])
    saludado(svc, wa)
    enviar(svc, payload(tipo="audio", msg_id="wamid.2"))
    assert agente.entradas[0].endswith("MENSAJE_ACTUAL_USUARIO: hola, quiero info de bjj")
    assert wa.textos_a(CLIENTE) == ["Sí, tenemos BJJ"]


def test_nota_de_voz_que_no_se_entiende(settings):
    svc, agente, wa, *_ = armar(settings, texto_audio="")
    saludado(svc, wa)
    enviar(svc, payload(tipo="audio", msg_id="wamid.2"))
    assert wa.textos_a(CLIENTE) == [AUDIO_NO_ENTENDIDO] and agente.entradas == []


def test_imagen_recibe_respuesta_amable(settings):
    svc, agente, wa, _, store = armar(settings)
    enviar(svc, payload(tipo="image", msg_id="wamid.9"))
    assert wa.textos_a(CLIENTE) == [TIPO_NO_SOPORTADO]
    assert store.eventos_desde("no_soportado", 0)[0]["detalle"] == "image"
    # sigue sin saludar: el primer texto recibe la bienvenida
    enviar(svc, payload("Hola", "wamid.10"))
    assert "Bienvenido/a" in wa.textos_a(CLIENTE)[-1]


def test_mensaje_repetido_y_de_grupo_se_ignoran(settings):
    svc, _, wa, *_ = armar(settings)
    enviar(svc, payload("Hola", "wamid.1"), payload("Hola", "wamid.1"))
    assert len(wa.enviados) == 1
    enviar(svc, payload("Hola", "wamid.2", de="120363-123"))
    assert len(wa.enviados) == 1


def test_error_del_agente_no_rompe_el_servicio(settings):
    def falla(svc, wa_id):
        raise RuntimeError("OpenAI caído")

    svc, _, wa, *_ = armar(settings, [falla, "Ahora sí"])
    saludado(svc, wa)
    enviar(svc, payload("hola", "wamid.2"), payload("hola otra vez", "wamid.3"))
    assert wa.textos_a(CLIENTE) == ["Ahora sí"]
