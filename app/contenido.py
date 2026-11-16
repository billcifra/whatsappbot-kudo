"""Contenido fijo del bot: menú 1-7, bienvenida, feriados y evento temporal vigente.

Editar aquí los textos, horarios del menú, feriados o el evento del momento. Los horarios del
agente viven en prompts.py: si cambian, actualizar AMBOS archivos.
"""

# ---------------------------------------------
# 📅 Feriados / días SIN clases de prueba
# ---------------------------------------------
# Días en los que el dojo NO dicta clases (feriados, cierres, etc.).
# El agente NO debe coordinar ni confirmar clases de prueba en estas fechas.
# Formato: "YYYY-MM-DD": "motivo". Edita esta lista para agregar o quitar feriados.
FERIADOS = {
    "2026-06-04": "Feriado (jueves) — sin clases",
    "2026-06-05": "Feriado (viernes) — sin clases",
    "2026-06-22": "Feriado (lunes) — sin clases",
}

# ---------------------------------------------
# Evento temporal vigente (camps de vacaciones, promociones, etc.).
# Se promociona automáticamente solo mientras hoy <= EVENTO_PROMO_HASTA;
# después desaparece de las respuestas del bot sin tocar más código.
# Para anunciar un evento nuevo, llena estas constantes; sin evento, déjalas en "".
# ---------------------------------------------
EVENTO_PROMO_HASTA = ""   # último día de promoción (YYYY-MM-DD); "" = sin evento
EVENTO_TEASER = ""        # línea corta para el mensaje de bienvenida; terminar en "\n\n"
EVENTO_INFO = ""          # descripción: nombre, fechas, horarios, precios
EVENTO_INSTRUCCIONES = "" # instrucciones al agente sobre cómo responder/promocionarlo
# --- Ejemplo (Winter Camp jul-2026), dejar comentado como plantilla: ---
# EVENTO_PROMO_HASTA = "2026-07-17"
# EVENTO_TEASER = (
#     "❄️ *¡Nuevo! Winter Camp de Kudo, del 6 al 17 de julio* "
#     "(Full Bs. 250 / Half Bs. 150) — cupos limitados.\n\n"
# )
# EVENTO_INFO = (
#     "WINTER CAMP (vacaciones de invierno) — disciplina *Kudo*:\n"
#     "  • Fechas: lunes 6 al viernes 17 de julio (lunes a viernes)\n"
#     "  • Horarios: 10:00–11:00 ó 15:00–16:00 (se elige uno)\n"
#     "  • Full Camp (Lunes a Viernes): Bs. 250\n"
#     "  • Half Camp (Lunes, Miércoles y Viernes): Bs. 150\n"
#     "  • Cupos limitados.\n"
# )
# EVENTO_INSTRUCCIONES = (
#     "INSTRUCCIONES sobre el Winter Camp:\n"
#     "  • Usa estos datos para responder cualquier pregunta sobre el winter camp / "
#     "campamento de invierno / vacaciones.\n"
#     "  • Menciónalo de forma proactiva (sin ser insistente) cuando saludes o cuando "
#     "ofrezcas el menú de opciones. Compara FECHA_HOY con el inicio (2026-07-06) "
#     "para frasear correctamente: si aún no empieza di que 'empieza el lunes 6 de julio'; "
#     "si ya está dentro de las fechas, di que 'está en curso'.\n"
#     "  • El Winter Camp es un programa PAGADO (Full Bs. 250 / Half Bs. 150); NO es la clase "
#     "de prueba gratuita. Para reservar un cupo (son limitados), pide el nombre y usa "
#     "`guardar_datos_prospecto` y/o `solicitar_asistencia_humana` para coordinar la inscripción.\n"
# )

# ---------------------------------------------
# Respuestas directas del menú numérico (1–7)
# ---------------------------------------------

# CTA estándar hacia la clase de prueba gratuita. Se envía como mensaje de cierre
# en las respuestas del menú para impulsar la conversión en CADA interacción.
CTA_PRUEBA = ("🎁 Tu *primera clase es GRATIS*, sin compromiso.\n"
              "¿Te coordino tu clase de prueba? 🥋 Dime qué día te viene bien.")

# Cada opción es una LISTA de mensajes cortos (chunks). El webhook los envía como
# mensajes separados para que sean fáciles de escanear en el celular, y cierra con
# el CTA a la clase de prueba. Los horarios se conservan EXACTOS (no inventar/alterar).
respuestas_directas = {
    "1": [
        "👉 *Horarios — Kudo* 🥋\n\n"
        "📍 *Niños (6 a 13 años)*\n"
        "• Mar y Jue: 8:30–10:00 y 16:30–18:00\n"
        "• Sáb: 10:30–12:00\n\n"
        "📍 *Jóvenes y Adultos*\n"
        "• Lun y Mié: 8:30–10:00\n"
        "• Mar y Jue: 19:30–21:00\n"
        "• Sáb: 9:00–10:30",

        "👉 *Horarios — BJJ y Kick Boxing* 🥋\n\n"
        "📍 *Brazilian Jiu-Jitsu (Jóvenes y Adultos)*\n"
        "• Lun, Mié y Vie: 17:00–18:30 y 19:30–21:00\n\n"
        "📍 *BJJ Kids*\n"
        "• Lun, Mié y Vie: 18:30–19:30\n\n"
        "🔄 *Kick Boxing — en reapertura*\n"
        "Estamos formando el nuevo grupo y abriremos horario en cuanto tengamos cupo suficiente. "
        "¿Te anoto para avisarte apenas se habilite? 📲\n"
        "Mientras tanto, ¡te invitamos a una *clase de prueba GRATIS* de Kudo o BJJ para que conozcas el dojo! 🥋\n\n"
        "⛔ BJJ no abre sábados ni domingos.",

        CTA_PRUEBA,
    ],
    "2": [
        "👉 *Precios* 💰\n\n"
        "Bs. *250/mes* por persona (3 clases por semana).\n\n"
        "¿Prefieres venir 1 día, 2 días o solo sábados? Podemos coordinar una opción a tu medida. 😊",
        CTA_PRUEBA,
    ],
    "3": [
        "👉 *Disciplinas que ofrecemos* 🥋\n\n"
        "🥋 *Kudo* — qué es: https://www.youtube.com/watch?v=NqcE1J7z2eE\n"
        "🥋 *Brazilian Jiu-Jitsu* — qué es: https://www.youtube.com/watch?v=tztK3dJksk0\n"
        "🥋 *Kick Boxing* *(en reapertura)* — qué es: https://www.youtube.com/watch?v=Sh9cVUidnr0",
        CTA_PRUEBA,
    ],
    "4": [
        "👉 *¿Cómo inscribirte?* 📝\n\n"
        "¡Súper fácil! Ven al dojo y te inscribimos en el momento.\n"
        "📍 Calle Cañada Strongest N.º 1847, a pasos de la plaza del estudiante, La Paz.",

        "🎁 Pero primero puedes venir a una *clase de prueba GRATIS*, sin compromiso. "
        "Es la mejor forma de conocernos.\n\n"
        "👉 ¿Qué día podrías venir? Dime el día y te confirmo el horario exacto. 🗓️",
    ],
    "5": [
        "📍 *Ubicación*\n"
        "Calle Cañada Strongest N.º 1847, a pasos de la plaza del estudiante, La Paz, Bolivia.\n\n"
        "🗺️ Mapa: https://maps.app.goo.gl/CeW1sAW77AgTzriA6?g_st=ipc",
        CTA_PRUEBA,
    ],
    "6": [
        "*¿Qué es Kudo?* 🥋\n\n"
        "Es un arte marcial japonés moderno y completo: combina golpes a contacto pleno, "
        "lanzamientos, controles y sumisiones en el suelo. Un *Budo* con valores de respeto y "
        "superación personal, creado por el maestro *Azuma Takashi* y practicado en más de 50 países.",

        "Su filosofía se basa en 3 conceptos:\n"
        "• *Transitoriedad* — nada es permanente\n"
        "• *Interdependencia* — todo está conectado\n"
        "• *Mente abierta* — humildad y aprendizaje\n\n"
        "📹 Videos:\n"
        "🎥 ¿Qué es Kudo?: https://www.youtube.com/watch?v=NqcE1J7z2eE\n"
        "🎥 Highlights: https://www.youtube.com/watch?v=JtTWeISoAFA\n"
        "🎥 Mundial 2023: https://www.youtube.com/watch?v=jfcne0M5qEU",

        CTA_PRUEBA,
    ],
    "7": [
        "🥊 *Guantillas para MMA*\n\n"
        "¡Nuevas y de alta calidad! Ideales para MMA, cualquier arte marcial y entrenamiento "
        "en sacos, pads y manoplas. Diseño ergonómico para todas las edades.\n\n"
        "💰 1 par: Bs. 90 · 2 o más: Bs. 80 c/u\n"
        "⏰ Ventas: Lun a Vie, 14:00–15:30\n"
        "📍 Entrega: Cañada Strongest 1847 (Ed. Sarawi), Dojo \"KUDO BOLIVIA\".",
        CTA_PRUEBA,
    ],
}

# Opciones del menú principal, presentadas como LISTA INTERACTIVA de WhatsApp.
# El `id` de cada fila coincide con la clave de `respuestas_directas`, de modo que
# tocar una opción produce exactamente el mismo efecto que escribir el número (1-7).
MENU_ROWS = [
    {"id": "1", "title": "Horarios", "description": "Días y horas por disciplina"},
    {"id": "2", "title": "Precios", "description": "Mensualidad y opciones"},
    {"id": "3", "title": "Disciplinas", "description": "Kudo, BJJ y Kick Boxing (próx.)"},
    {"id": "4", "title": "Inscripción", "description": "Cómo empezar + clase gratis"},
    {"id": "5", "title": "Ubicación", "description": "Dónde estamos"},
    {"id": "6", "title": "¿Qué es Kudo?", "description": "Conoce el arte marcial"},
    {"id": "7", "title": "Venta de Guantes", "description": "Guantillas de MMA en venta"},
]
MENU_BODY = "📋 ¿Sobre qué te gustaría saber? Toca una opción 👇"

# Respuestas fijas para mensajes que no son texto.
AUDIO_NO_ENTENDIDO = ("🎙️ Recibí tu audio pero no logré entenderlo bien. "
                      "¿Me lo puedes escribir en un mensajito? 😊")
TIPO_NO_SOPORTADO = ("Por ahora puedo leer *texto* y escuchar *notas de voz* 🎙️. "
                     "Cuéntame por aquí en qué te puedo ayudar 😊")

# Nombre corto de cada opción del menú (para el historial y el panel).
TITULO_OPCION = {fila["id"]: fila["title"] for fila in MENU_ROWS}


# Mensajes de conversión para leads de publicidad
def construir_bienvenida(hoy: str) -> str:
    """Mensaje de bienvenida para usuarios nuevos. `hoy` es la fecha local 'YYYY-MM-DD'.

    Si hay un evento temporal vigente (hoy <= EVENTO_PROMO_HASTA) añade su teaser
    corto; pasada la fecha (o sin evento configurado), el teaser desaparece solo.
    """
    teaser = ""
    if EVENTO_PROMO_HASTA and hoy <= EVENTO_PROMO_HASTA:
        teaser = EVENTO_TEASER
    return (
        "¡Hola! 👋 Bienvenido/a a *KUDO Bolivia*, tu centro de artes marciales en La Paz.\n\n"
        f"{teaser}"
        "🥋 Entrenamos *Kudo*, *Brazilian Jiu-Jitsu* y *Defensa Personal* (Kick Boxing próximamente).\n"
        "🎁 *¡Tu primera clase es completamente GRATIS!* Sin compromiso.\n\n"
        "Para ayudarte mejor, ¿cómo te llamas? 😊"
    )
