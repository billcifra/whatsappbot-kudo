"""Evento temporal (curso vacacional dic-2026/ene-2027): vigencia, opción 8 del menú, edad y panel."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.agente import build_agent_input, construir_contexto_fechas
from app.contenido import (EVENTO_ID, EVENTO_TEASER, FILA_MENU_EVENTO, MENU_ROWS, RESPUESTA_EVENTO,
                           construir_bienvenida, evento_vigente, menu_rows, respuesta_directa)
from app.main import crear_app
from app.panel.auth import hash_clave
from app.panel.metricas import grupo_edad
from app.sheets import INTERESADOS
from app.store import Store
from conftest import CLIENTE, PERSONAL, armar, payload
from test_panel import CLAVE, entrar
from test_webhook import enviar, saludado

LA_PAZ = ZoneInfo("America/La_Paz")
DURANTE = datetime(2026, 12, 2, 10, 0, tzinfo=LA_PAZ)
DESPUES = datetime(2027, 1, 30, 10, 0, tzinfo=LA_PAZ)


def con_fecha(svc, momento: datetime):
    svc.ahora = lambda: momento
    return svc


# --- Contenido ------------------------------------------------------------------------
def test_vigencia_del_evento_en_los_bordes():
    for hoy in ("2026-11-16", "2026-11-30", "2026-12-01", "2027-01-29"):
        assert evento_vigente(hoy), hoy
    assert not evento_vigente("2027-01-30")


def test_menu_y_respuestas_segun_la_fecha():
    assert menu_rows("2026-12-02") == [*MENU_ROWS, FILA_MENU_EVENTO]
    assert menu_rows("2027-01-30") == MENU_ROWS
    assert respuesta_directa("8", "2026-12-02") == RESPUESTA_EVENTO
    assert respuesta_directa("8", "2027-01-30") is None
    assert respuesta_directa("2", "2027-01-30") is not None
    assert len(FILA_MENU_EVENTO["title"]) <= 24 and len(FILA_MENU_EVENTO["description"]) <= 72


def test_bienvenida_con_teaser_solo_durante_el_evento():
    assert EVENTO_TEASER in construir_bienvenida("2026-12-02")
    assert EVENTO_TEASER not in construir_bienvenida("2027-01-30")


def test_contexto_del_agente_incluye_evento_y_receso():
    bloque = construir_contexto_fechas(DURANTE)
    assert "EVENTO_VIGENTE" in bloque and "Bs. 400" in bloque and "INFANTIL (7 a 12 años)" in bloque
    assert "2026-12-25" in bloque and "2027-01-01" in bloque
    despues = construir_contexto_fechas(DESPUES)
    assert "EVENTO_VIGENTE" not in despues and "2026-12-25" not in despues


def test_perfil_del_agente_muestra_edad_y_evento():
    perfil = {"nombre": "Ana", "edad": "9 años", "evento": EVENTO_ID}
    entrada = build_agent_input(CLIENTE, "hola", [], perfil, DURANTE)
    assert "Edad del alumno: 9 años" in entrada and "Interesado en: Curso vacacional" in entrada


def test_grupo_edad():
    assert grupo_edad("9 años") == "Infantil"
    assert grupo_edad("tiene 14") == "Juvenil"
    assert grupo_edad("7") == "Infantil" and grupo_edad("17") == "Juvenil"
    assert grupo_edad("adulto") == "Otro" and grupo_edad("30") == "Otro"
    assert grupo_edad("") is None and grupo_edad(None) is None


# --- Flujo -------------------------------------------------------------------------------
def test_opcion_8_durante_el_evento(settings):
    svc, agente, wa, _, store = armar(settings)
    con_fecha(svc, DURANTE)
    saludado(svc, wa)
    enviar(svc, payload(tipo="interactive", interactivo="8", msg_id="wamid.8"))
    assert wa.textos_a(CLIENTE) == RESPUESTA_EVENTO
    assert agente.entradas == []
    assert wa.filas_menu[-1] == [*MENU_ROWS, FILA_MENU_EVENTO]
    assert store.contacto(CLIENTE)["evento"] == EVENTO_ID


def test_opcion_8_despues_del_evento_va_al_agente(settings):
    svc, agente, wa, _, store = armar(settings, ["Respuesta del agente [[MENU]]"])
    con_fecha(svc, DESPUES)
    saludado(svc, wa)
    enviar(svc, payload("8", "wamid.8"))
    assert len(agente.entradas) == 1
    assert wa.filas_menu[-1] == MENU_ROWS
    assert store.contacto(CLIENTE)["evento"] is None


def test_guardar_prospecto_con_edad_e_interes_en_el_evento(settings):
    svc, _, wa, sheets, store = armar(settings)
    con_fecha(svc, DURANTE)
    svc.guardar_prospecto(CLIENTE, nombre="Ana", edad="9 años", interes_evento=True)
    c = store.contacto(CLIENTE)
    assert c["edad"] == "9 años" and c["evento"] == EVENTO_ID
    hoja, fila = sheets.filas[-1]
    assert hoja == INTERESADOS and fila[-2:] == ["9 años", EVENTO_ID]

    svc2, _, _, _, store2 = armar(settings)
    con_fecha(svc2, DESPUES)
    svc2.guardar_prospecto("59170000099", edad="10", interes_evento=True)
    assert store2.contacto("59170000099")["evento"] is None


def test_aviso_al_equipo_incluye_edad_y_grupo(settings):
    svc, _, wa, _, store = armar(settings)
    con_fecha(svc, DURANTE)
    store.registrar_entrante(CLIENTE, "Ana WA")
    store.actualizar_perfil(CLIENTE, edad="14 años", evento=EVENTO_ID)
    asyncio.run(svc.solicitar_humano(CLIENTE, "quiero inscribir a mi hijo"))
    aviso = wa.textos_a(PERSONAL)[0]
    assert "Edad: 14 años (Juvenil)" in aviso and "curso vacacional" in aviso


# --- Store: migración aditiva --------------------------------------------------------------
def test_base_vieja_recibe_columnas_edad_y_evento(tmp_path):
    ruta = tmp_path / "vieja.db"
    db = sqlite3.connect(ruta)
    db.execute("CREATE TABLE contactos (wa_id TEXT PRIMARY KEY, nombre TEXT, nombre_perfil TEXT, disciplina TEXT, "
               "turno TEXT, dia TEXT, tema TEXT, bienvenido INTEGER NOT NULL DEFAULT 0, "
               "primer_contacto REAL NOT NULL, ultimo_mensaje REAL)")
    db.execute("INSERT INTO contactos (wa_id, nombre, primer_contacto) VALUES ('591700', 'Viejo', 1)")
    db.commit()
    db.close()
    st = Store(ruta)
    assert st.contacto("591700")["edad"] is None
    st.actualizar_perfil("591700", edad="8", evento=EVENTO_ID)
    assert st.contacto("591700")["edad"] == "8" and st.contacto("591700")["nombre"] == "Viejo"


# --- Panel -----------------------------------------------------------------------------------
def test_panel_filtra_por_evento_y_exporta_edad(settings):
    svc, _, _, _, store = armar(settings)
    store.crear_usuario("ana", "Ana", hash_clave(CLAVE))
    store.registrar_entrante(CLIENTE, "Ana WA")
    store.actualizar_perfil(CLIENTE, nombre="Mamá de Leo", edad="9 años", evento=EVENTO_ID)
    store.registrar_entrante("59170000077", "Otro")
    store.actualizar_perfil("59170000077", nombre="Adulto BJJ", disciplina="bjj")
    with TestClient(crear_app(servicio=svc)) as c:
        entrar(c)
        todos = c.get("/panel/prospectos").text
        assert "Mamá de Leo" in todos and "Adulto BJJ" in todos and "Curso vacacional" in todos
        filtrado = c.get("/panel/prospectos", params={"evento": EVENTO_ID}).text
        assert "Mamá de Leo" in filtrado and "Adulto BJJ" not in filtrado and "Infantil" in filtrado
        csv = c.get("/panel/prospectos.csv", params={"evento": EVENTO_ID}).text
        cabecera, *filas = csv.strip().splitlines()
        assert cabecera.endswith("edad,grupo,evento")
        assert len(filas) == 1 and filas[0].endswith(f"9 años,Infantil,{EVENTO_ID}")
        ficha = c.get(f"/panel/conversaciones/{CLIENTE}").text
        assert "9 años" in ficha and "Infantil" in ficha and "Curso vacacional" in ficha
