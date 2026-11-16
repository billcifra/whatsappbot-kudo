"""Importación única del histórico de Google Sheets (hojas Interesados y SolicitudesHumano) a SQLite.

Corre al arrancar si IMPORTAR_HISTORICO_SHEETS=true y no se hizo antes (marca en la tabla meta), DESPUÉS
de la migración de Redis: Redis trae el historial y los perfiles más recientes, que no se pisan.

- Las fechas de las hojas se escribieron con la hora del servidor (UTC).
- Se omiten las filas de prueba (TEST), las de los números del equipo y los encabezados mezclados.
- A los mensajes migrados de Redis (que no tenían hora) se les pone la hora real cuando el texto coincide.
Todo ocurre en una transacción: si algo falla, no queda nada a medias y se reintenta en el próximo arranque.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from .store import Store

log = logging.getLogger("importacion")

MARCA = "importacion_sheets"
NUEVO = "[NUEVO USUARIO]"
DATOS = "[DATOS PROSPECTO]"
# Valores que en realidad son encabezados de columna escritos como datos.
ENCABEZADOS = {"nombre", "disciplina", "disciplina_interesada", "turno", "turno_preferido", "dia", "día",
               "dia_disponible", "telefono", "teléfono", "phone", "mensaje", "message", "fecha"}


@dataclass
class Fila:
    wa_id: str
    mensaje: str
    ts: float
    nombre: str = ""
    disciplina: str = ""
    turno: str = ""
    dia: str = ""


def fecha_utc(texto: str) -> float | None:
    try:
        return datetime.strptime(texto.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _valor(fila: list[str], i: int) -> str:
    v = fila[i].strip() if len(fila) > i else ""
    return "" if v.lower() in ENCABEZADOS else v


def leer_filas(filas: list[list[str]], excluir: set[str]) -> tuple[list[Fila], Counter]:
    """Convierte las filas crudas de la hoja; devuelve (válidas, motivos de descarte)."""
    validas: list[Fila] = []
    descartes: Counter = Counter()
    for f in filas:
        wa_id = f[0].strip() if f else ""
        if not wa_id.isdigit():
            descartes["sin teléfono / TEST / encabezado"] += 1
            continue
        if wa_id in excluir:
            descartes["número del equipo"] += 1
            continue
        ts = fecha_utc(f[2]) if len(f) > 2 else None
        if ts is None:
            descartes["sin fecha válida"] += 1
            continue
        validas.append(Fila(wa_id, f[1].strip() if len(f) > 1 else "", ts,
                            _valor(f, 3), _valor(f, 4), _valor(f, 5), _valor(f, 6)))
    return validas, descartes


def _ajustar_horas(store: Store, wa_id: str, mensajes: list[dict], textos: list[Fila]) -> tuple[int, float | None]:
    """Pone la hora real de la hoja a los mensajes migrados de Redis. Devuelve (ajustados, hora más antigua)."""
    ajustados, puntero, hora_actual = 0, 0, None
    for m in mensajes:
        if m["rol"] == "user":
            hora_actual = None
            for j in range(puntero, len(textos)):
                if textos[j].mensaje == m["contenido"].strip():
                    hora_actual, puntero = textos[j].ts, j + 1
                    store.poner_ts_mensaje(m["id"], hora_actual)
                    ajustados += 1
                    break
        elif hora_actual is not None:   # respuestas del bot que siguen a un mensaje ya ubicado
            hora_actual += 1
            store.poner_ts_mensaje(m["id"], hora_actual)
    filas = store.mensajes_con_id(wa_id)
    return ajustados, min((m["ts"] for m in filas), default=None)


def importar(store: Store, interesados: list[list[str]], solicitudes: list[list[str]],
             excluir: set[str]) -> dict[str, int]:
    if store.meta(MARCA):
        log.info("El histórico de Sheets ya se importó el %s; no se repite.", store.meta(MARCA))
        return {}
    filas, descartes = leer_filas(interesados, excluir)
    filas_sol, descartes_sol = leer_filas(solicitudes, excluir)
    por_numero: dict[str, list[Fila]] = defaultdict(list)
    for f in sorted(filas, key=lambda f: f.ts):
        por_numero[f.wa_id].append(f)
    r: Counter = Counter()

    with store.en_lote():
        for wa_id, lista in por_numero.items():
            existente = store.contacto(wa_id)
            migrados = store.mensajes_con_id(wa_id) if existente else []
            if existente is None:
                store.registrar_entrante(wa_id, None, ts=lista[0].ts)
                store.marcar_bienvenido(wa_id)
                r["contactos_nuevos"] += 1
            else:
                r["contactos_existentes"] += 1
            store.ajustar_fechas_contacto(wa_id, lista[0].ts, lista[-1].ts)

            # Perfil: el dato más reciente de cada campo, sin pisar lo que ya hay (Redis es más nuevo).
            perfil: dict[str, str] = {}
            for f in reversed(lista):
                for campo in ("nombre", "disciplina", "turno", "dia"):
                    if getattr(f, campo) and campo not in perfil:
                        perfil[campo] = getattr(f, campo)
            store.completar_perfil(wa_id, **perfil)

            textos = [f for f in lista if not f.mensaje.startswith(("[", "TEST"))]
            desde_hoja = None
            if migrados:
                ajustados, mas_antiguo = _ajustar_horas(store, wa_id, migrados, textos)
                r["mensajes_redis_con_hora_real"] += ajustados
                usados = {m["contenido"].strip() for m in store.mensajes_con_id(wa_id) if m["rol"] == "user"}
                # Lo anterior al historial de Redis (que guardaba solo los últimos 40) se agrega desde la hoja.
                desde_hoja = [f for f in textos if f.ts < (mas_antiguo or 0) and f.mensaje not in usados]
            for f in lista:
                if f.mensaje.startswith(NUEVO):
                    texto = f.mensaje[len(NUEVO):].strip()
                    store.registrar_evento(wa_id, "nuevo_usuario", texto, ts=f.ts)
                    if not migrados and texto:
                        store.agregar_mensaje(wa_id, "user", texto, tipo="importado", para_agente=False, ts=f.ts)
                        r["mensajes"] += 1
                elif f.mensaje.startswith(DATOS):
                    store.registrar_evento(wa_id, "datos_prospecto", {"nombre": f.nombre, "disciplina": f.disciplina,
                                                                      "turno": f.turno, "dia": f.dia}, ts=f.ts)
                elif f.mensaje:
                    store.registrar_evento(wa_id, "agente", f.mensaje, ts=f.ts)
                    if not migrados or (desde_hoja is not None and f in desde_hoja):
                        store.agregar_mensaje(wa_id, "user", f.mensaje, tipo="importado", para_agente=False, ts=f.ts)
                        r["mensajes"] += 1
                r["eventos"] += 1

        for f in filas_sol:
            if store.contacto(f.wa_id) is None:
                store.registrar_entrante(f.wa_id, None, ts=f.ts)
                store.marcar_bienvenido(f.wa_id)
                r["contactos_nuevos"] += 1
            store.ajustar_fechas_contacto(f.wa_id, f.ts, f.ts)
            store.crear_solicitud(f.wa_id, f.mensaje, ts=f.ts, atendida=f.ts, atendida_por="histórico")
            store.registrar_evento(f.wa_id, "solicitud_humana", f.mensaje, ts=f.ts)
            r["solicitudes"] += 1

        store.poner_meta(MARCA, time.strftime("%Y-%m-%d %H:%M:%S"))

    resultado = dict(r)
    resultado.update({f"descartadas: {k}": v for k, v in (descartes + descartes_sol).items()})
    log.info("Importación de Sheets: %s", resultado)
    return resultado
