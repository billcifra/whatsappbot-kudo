"""Agente de OpenAI (Agents SDK): instrucciones, herramientas y armado del mensaje de entrada.

Las herramientas reciben el número del cliente por el contexto de la ejecución (RunContextWrapper),
no como argumento del modelo: así el modelo no puede equivocarse de número.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agents import Agent, RunContextWrapper, Runner, function_tool

from .contenido import EVENTO_ID, EVENTO_INFO, EVENTO_INSTRUCCIONES, EVENTO_NOMBRE, FERIADOS, evento_vigente
from .prompts import SYSTEM_PROMPT

if TYPE_CHECKING:
    from .main import Servicio

log = logging.getLogger("agente")

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


@dataclass
class ContextoAgente:
    wa_id: str
    servicio: "Servicio"


@dataclass
class Respuesta:
    texto: str
    entrada: int = 0
    salida: int = 0


# ---------------------------------------------
# Herramientas
# ---------------------------------------------
@function_tool
async def solicitar_asistencia_humana(ctx: RunContextWrapper[ContextoAgente], user_message: str) -> str:
    """
    Notifica al equipo humano por WhatsApp y registra la solicitud en Google Sheets.
    El agente debe llamar esta herramienta cuando el usuario pida 'hablar con alguien',
    'atención humana', 'hablar con una persona', etc.

    Args:
        user_message: el mensaje del usuario que motivó la solicitud.
    """
    await ctx.context.servicio.solicitar_humano(ctx.context.wa_id, user_message)
    return "Notificación enviada al equipo humano y solicitud registrada."


@function_tool
async def guardar_datos_prospecto(ctx: RunContextWrapper[ContextoAgente], nombre: str = "", disciplina: str = "",
                                  turno: str = "", dia: str = "", edad: str = "",
                                  interes_evento: bool = False) -> str:
    """
    Guarda los datos del prospecto recolectados durante la conversación.
    Llama a esta herramienta CADA VEZ que el usuario te entregue uno de estos datos:
    su nombre, la disciplina de interés, el turno preferido, el día que podría asistir
    o la edad del alumno (por ejemplo la edad del hijo/a).
    Puedes llamarla varias veces a medida que obtienes más datos; envía siempre todos los
    que tengas hasta el momento (los que aún no conozcas déjalos vacíos).

    Args:
        edad: edad del alumno tal como la dijo el usuario (ej: '9 años'); vacío si no se sabe.
        interes_evento: true si el usuario mostró interés en el evento del bloque EVENTO_VIGENTE.
    """
    ctx.context.servicio.guardar_prospecto(ctx.context.wa_id, nombre=nombre, disciplina=disciplina,
                                           turno=turno, dia=dia, edad=edad, interes_evento=interes_evento)
    return "Datos del prospecto guardados."


def crear_agente(modelo: str) -> Agent[ContextoAgente]:
    return Agent[ContextoAgente](
        name="KUDO Bolivia Assistant",
        model=modelo,
        instructions=SYSTEM_PROMPT,
        tools=[solicitar_asistencia_humana, guardar_datos_prospecto],
    )


class AgenteKudo:
    """Envoltorio del agente real. Las pruebas usan un doble con el mismo método `responder`."""

    def __init__(self, modelo: str):
        self.agente = crear_agente(modelo)

    async def responder(self, servicio: "Servicio", wa_id: str, entrada: str) -> Respuesta:
        result = await Runner.run(self.agente, entrada, context=ContextoAgente(wa_id, servicio))
        texto = getattr(result, "final_output", None) or str(result)
        uso = result.context_wrapper.usage
        return Respuesta(str(texto), int(uso.input_tokens or 0), int(uso.output_tokens or 0))


# ---------------------------------------------
# Mensaje de entrada para el agente
# ---------------------------------------------
def construir_bloque_evento(hoy: str) -> str:
    """Bloque EVENTO_VIGENTE (info + instrucciones), solo mientras hoy <= EVENTO_PROMO_HASTA."""
    if not evento_vigente(hoy):
        return ""
    return "EVENTO_VIGENTE — " + EVENTO_INFO + EVENTO_INSTRUCCIONES


def construir_contexto_fechas(ahora: datetime) -> str:
    """Fecha de hoy (hora local del dojo), feriados futuros y evento vigente."""
    hoy = ahora.strftime("%Y-%m-%d")
    bloque = f"FECHA_HOY: {hoy} ({DIAS_SEMANA[ahora.weekday()]})\n"
    feriados = {f: motivo for f, motivo in FERIADOS.items() if f >= hoy}
    if feriados:
        lineas = [f"  • {f}: {motivo}" for f, motivo in sorted(feriados.items())]
        bloque += "FERIADOS (NO hay clases, no coordines clases de prueba estos días):\n" + "\n".join(lineas) + "\n"
    bloque += construir_bloque_evento(hoy)
    return bloque + "\n"


def build_agent_input(user_phone: str, user_msg: str, history: list[dict[str, str]],
                      perfil: dict[str, Any] | None, ahora: datetime) -> str:
    contexto_fechas = construir_contexto_fechas(ahora)
    transcript = [f"{'Usuario' if it['role'] == 'user' else 'Asistente'}: {it['content']}" for it in history]
    historial_texto = "\n".join(transcript).strip()

    perfil_texto = ""
    if perfil:
        partes = []
        if perfil.get("nombre"):
            partes.append(f"Nombre: {perfil['nombre']}")
        if perfil.get("disciplina"):
            partes.append(f"Disciplina de interés: {perfil['disciplina']}")
        if perfil.get("turno"):
            partes.append(f"Turno preferido: {perfil['turno']}")
        if perfil.get("dia"):
            partes.append(f"Día disponible: {perfil['dia']}")
        if perfil.get("edad"):
            partes.append(f"Edad del alumno: {perfil['edad']}")
        if perfil.get("evento") == EVENTO_ID:
            partes.append(f"Interesado en: {EVENTO_NOMBRE}")
        if partes:
            perfil_texto = "PERFIL_DEL_PROSPECTO:\n" + "\n".join(partes) + "\n\n"

    cabecera = f"TELÉFONO_USUARIO: {user_phone}\n{contexto_fechas}{perfil_texto}"
    if historial_texto:
        return f"{cabecera}HISTORIAL_CONVERSACION:\n{historial_texto}\n\nMENSAJE_ACTUAL_USUARIO: {user_msg}"
    return f"{cabecera}MENSAJE_ACTUAL_USUARIO: {user_msg}"
