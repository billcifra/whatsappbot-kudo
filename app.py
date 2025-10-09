# ---------------------------------------------
# Configuración e importación de dependencias
# ---------------------------------------------
from flask import Flask, request
import requests
import os
import time
from dotenv import load_dotenv
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
import json
from google.auth.transport.requests import Request

# Cargar variables de entorno desde archivo .env
load_dotenv()

# Inicialización de la app Flask
app = Flask(__name__)

# Diccionario para almacenar contexto por usuario (tema y tiempo)
contexto_usuarios = {}

# Cargar credenciales desde variables de entorno
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY")
credentials_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))

# Cliente de OpenAI
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Cliente de Google Sheets
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)
gs_client = gspread.authorize(creds)
solicitudes_sheet = gs_client.open_by_key(GOOGLE_SHEET_KEY).worksheet("SolicitudesHumano")
interesados_sheet = gs_client.open_by_key(GOOGLE_SHEET_KEY).worksheet("Interesados")

# ---------------------------------------------
# Definición de intenciones y respuestas directas
# ---------------------------------------------

intenciones = {"1": ["horarios"],#, "hora", "a qué hora", "qué días", "qué horario"],
               "2": ["precio"],#, "cuánto cuesta", "cuánto cobran", "tarifa", "vale", "costo"],
               "3": ["disciplinas"],#, "qué enseñan", "qué clases hay", "qué actividades"],
               "4": ["inscripción"],#, "inscribir", "cómo me apunto", "cómo me inscribo", "registrarme"],
               "5": [ "ubicación"],#, "dónde están", "dirección", "dónde queda", "cómo llegar"]
               }

respuestas_directas = {"1": "👉 *Horarios de clases en KUDO Bolivia:*\n• "
                            "📍 *Kudo Niños (6 a 13 años)*\n"
                            "— *Iniciales:*\n"
                            "   🕗 *Turno mañana:*\n"
                            "     • Lunes: 8:30–9:30\n"
                            "     • Jueves: 8:30–10:00\n"
                            "     • Sábados: 10:30–12:00\n"
                            "   🌆 *Turno tarde:*\n"
                            "     • Lunes: 16:00–17:00\n"
                            "     • Jueves: 16:30–18:00\n"
                            "     • Sábados: 10:30–12:00\n"
                            "\n"
                            "— *Avanzados:*\n"
                            "   🕗 *Turno mañana:*\n"
                            "     • Martes y Jueves: 8:30–10:00\n"
                            "     • Sábados: 10:30–12:00\n"
                            "   🌆 *Turno tarde:*\n"
                            "     • Martes y Jueves: 16:30–18:00\n"
                            "     • Sábados: 10:30–12:00\n"
                            "\n"
                            "📍 *Kudo Jóvenes y Adultos*\n"
                            "— *Iniciales:*\n"
                            "   🕗 *Turno mañana:*\n"
                            "     • Lunes: 8:30–9:30\n"
                            "     • Jueves: 8:30–10:00\n"
                            "     • Sábados: 09:00–10:30\n"
                            "   🌙 *Turno noche:*\n"
                            "     • Martes: 20:30–21:30\n"
                            "     • Jueves: 19:30–21:00\n"
                            "     • Sábados: 9:00–10:30\n"
                            "\n"
                            "— *Avanzados:*\n"
                            "   🕗 *Turno mañana:*\n"
                            "     • Martes y Jueves: 8:30–10:00\n"
                            "     • Sábados: 9:00–10:30\n"
                            "   🌙 *Turno noche:*\n"
                            "     • Martes: 19:30–20:30\n"
                            "     • Jueves: 19:30–21:00\n"
                            "     • Sábados: 9:00–10:30\n"
                            "\n"
                            "📍 *Brazilian Jiu-Jitsu Jóvenes y Adultos*\n"
                            "— *Con Gi:*\n"
                            "   🕗 *Turno mañana:*\n"
                            "     • Lunes, Miércoles y Viernes: 9:30–11:00\n"
                            "   🌆 *Turno tarde:*\n"
                            "     • Lunes, Miércoles y Viernes: 17:00–18:30\n"
                            "   🌙 *Turno noche:*\n"
                            "     • Lunes, Miércoles y Viernes: 19:30–21:00\n"
                            "\n"
                            "— *No-Gi:*\n"
                            "   🕗 *Turno mañana:*\n"
                            "     • Martes y Jueves: 10:00–11:30\n"
                            "\n"
                            "📍 *Brazilian Jiu-Jitsu Kids*\n"
                            "   🌙 *Turno noche:*\n"
                            "     • Lunes, Miércoles y Viernes: 18:30–19:30\n"
                            "\n"
                            "📍 *Kick Boxing*\n"
                            "   🕗 *Turno mañana:*\n"
                            "     • Martes y Jueves: 7:00–8:30\n"
                            "   🌙 *Turno noche:*\n"
                            "     • Martes y Jueves: 18:00–19:30\n",
                       "2": "👉 *Precios:*\nBs. 250 la mensualidad por persona. "
                            "Consulta por descuentos directamente con el equipo del dojo.",
                       "3": "👉 *Disciplinas que ofrecemos:"
                            "*\n🥋 Kudo\n\t"
                            "Que es KUDO: https://www.youtube.com/watch?v=NqcE1J7z2eE\n\n"
                            "*\n🥋 Brazilian Jiu-Jitsu\n\t"
                            "Que es BJJ: https://www.youtube.com/watch?v=tztK3dJksk0\n\n"
                            "*\n🥋 Kick Boxing\n\t"
                            "Que es Kick Boxing: https://www.youtube.com/watch?v=Sh9cVUidnr0&pp=ygULa2ljayBib3hpbmc%3D",
                       "4": "👉 *¿Cómo inscribirte?*\nAcercate al dojo para poder inscribirte. "
                            "¡Estamos disponibles para recibirte!\n\n🥋¡Tienes una clase de prueba gratis en "
                            "todas nuestras disciplinas!",
                       "5": "📍 *Ubicación:* Calle Cañada Strongest N.º 1847 - a pasos de la plaza del estudiante, "
                            "La Paz, Bolivia.\n\n"
                            "📌Mapa: https://maps.app.goo.gl/CeW1sAW77AgTzriA6?g_st=ipc",
                       "6": "¿Qué es Kudo?\n\n"
                            "Kudo es un arte marcial japonés moderno y completo que combina golpes a contacto pleno, "
                            "lanzamientos, controles y técnicas de sumisión en el suelo. Se considera un *Budo* "
                            "contemporáneo con valores educativos, espirituales y de respeto, promoviendo la formación "
                            "del carácter, la superación personal y la cortesía (*Reigi*).\n"
                            "\n"
                            "Fue creado por el maestro *Azuma Takashi* y se practica en más de 50 países. Cada cuatro "
                            "años se celebra un Campeonato Mundial, que reúne a los mejores representantes del mundo.\n"
                            "\n"
                            "Su filosofía se basa en tres conceptos fundamentales:\n"
                            "• *Transitoriedad* (nada es permanente),\n"
                            "• *Interdependencia* (todo está conectado),\n"
                            "• *Mente abierta* (humildad, imparcialidad y aprendizaje continuo).\n\n"
                            "\n"
                            "📹 Videos recomendados:\n"
                            "🎥 Mira este video: https://www.youtube.com/watch?v=NqcE1J7z2eE&\n\n"
                            "🎥 Highlights: https://www.youtube.com/watch?v=JtTWeISoAFA&\n\n"
                            "🎥 Mundial 2023: https://www.youtube.com/watch?v=jfcne0M5qEU"
                       }

# Menú adicional que se agrega al final de cada mensaje
menu = ("\n\n📋 ¿Sobre qué más te gustaría saber?\n"
        "1️⃣ Horarios\n2️⃣ Precios\n3️⃣ Disciplinas\n4️⃣ Inscripción\n5️⃣ Ubicación\n6️⃣ ¿Qué es Kudo?")

# Palabras clave para atención humana
hablar_con_humano = ["hablar con alguien",
                     "necesito ayuda",
                     "quiero hablar con una persona",
                     "me ayudan", "me pueden ayudar",
                     "atención humana"
                     ]

# Lista de números a notificar en caso de solicitud de atención humana
notificar_humanos = ["59179598641", "59176785574"]


# ---------------------------------------------
# Funciones auxiliares
# ---------------------------------------------

def send_message(text, phone):
    """Envía un mensaje de texto por la API de WhatsApp"""
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}",
               "Content-Type": "application/json"
               }
    payload = {"messaging_product": "whatsapp",
               "to": phone,
               "type": "text",
               "text": {"body": text}
               }
    response = requests.post(url, headers=headers, json=payload)
    print("[INFO] WhatsApp API response:", response.status_code, response.text)


def registrar_interesado(phone, message):
    fecha = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    interesados_sheet.append_row([phone, message, fecha])


def registrar_solicitud_humana(phone, message):
    fecha = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    solicitudes_sheet.append_row([phone, message, fecha])


# ---------------------------------------------
# Webhooks
# ---------------------------------------------


@app.route("/webhook", methods=["GET"])
def verify():
    """Verificación inicial del webhook con Meta"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == "mibotverificacion":
        return challenge, 200
    return "Error de verificación", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    """Manejo de mensajes entrantes de WhatsApp"""
    data = request.get_json()
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})

        if "messages" in value:
            # Ignorar mensajes provenientes de grupos
            if "-" in value["messages"][0].get("from", ""):
                print("[INFO] Mensaje ignorado: proviene de un grupo de WhatsApp.")
                return "ok", 200
            # Se define más abajo si es necesario, para no interferir con la detección real de usuario nuevo
            message = value["messages"][0]
            user_msg = message["text"]["body"]
            user_phone = message["from"]
            ahora = time.time()

            msg_lower = user_msg.lower()  # Centralizado aquí una vez

            # Limpiar sesión si pasó más de 30 minutos
            if user_phone in contexto_usuarios:
                user_data = contexto_usuarios[user_phone]
                if "timestamp" in user_data and ahora - user_data["timestamp"] > 1800:
                    del contexto_usuarios[user_phone]

            print(f"[INFO] Mensaje recibido: {user_msg} de {user_phone}")

            # Detectar solicitud de atención humana
            if any(frase in msg_lower for frase in hablar_con_humano):
                registrar_solicitud_humana(user_phone, user_msg)
                send_message("¡Claro! Alguien del equipo de KUDO Bolivia se pondrá en contacto contigo."
                             , user_phone)
                for admin_phone in notificar_humanos:
                    send_message(f"📩 Solicitud de atención humana del número: {user_phone}\nMensaje: {user_msg}",
                                 admin_phone)
                return "ok", 200

            # Revisar si el mensaje es un número de opción directa
            if user_msg.strip() in respuestas_directas:
                key = user_msg.strip()
                contexto_usuarios[user_phone] = {"tema": key, "timestamp": ahora}
                send_message(respuestas_directas[key] + menu, user_phone)
                return "ok", 200

            # Revisar si el mensaje coincide con alguna intención textual
            for key, frases in intenciones.items():
                if any(frase in msg_lower for frase in frases):
                    contexto_usuarios[user_phone] = {"tema": key, "timestamp": ahora}
                    send_message(respuestas_directas[key] + menu, user_phone)
                    return "ok", 200

            # Fallback al modelo GPT si no se detectó ninguna intención conocida
            es_nuevo = user_phone not in contexto_usuarios

            # Si es nuevo, se registra ahora
            if es_nuevo:
                contexto_usuarios[user_phone] = {"tema": None, "timestamp": ahora}
            prompt = ("Eres un asistente virtual del centro de artes marciales *KUDO Bolivia*, ubicado "
                      "en la calle Cañada Strongest N.º 1847, a media cuadra de la plaza del estudiante, en La Paz, Bolivia."
                      "Tu objetivo es brindar información clara, respetuosa y profesional a todas las personas que "
                      "consultan por WhatsApp.\n"
                      "\n"
                      "🏆 En *KUDO Bolivia* se imparten las siguientes disciplinas: *Kudo*, *Jiu-Jitsu Brasileño "
                      "(BJJ)*, *Kick Boxing* y *Defensa Personal (clases privadas)*.\n"
                      "\n"
                      "🥋 *¿Qué es Kudo?*\n"
                      "Kudo es un arte marcial japonés moderno y completo que combina golpes a contacto pleno, "
                      "lanzamientos, controles y técnicas de sumisión en el suelo. Se considera un *Budo* "
                      "contemporáneo con valores educativos, espirituales y de respeto, promoviendo la formación "
                      "del carácter, la superación personal y la cortesía (*Reigi*).\n"
                      "\n"
                      "Fue creado por el maestro *Azuma Takashi* y se practica en más de 50 países. Cada cuatro "
                      "años se celebra un Campeonato Mundial, que reúne a los mejores representantes del mundo.\n"
                      "\n"
                      "Su filosofía se basa en tres conceptos fundamentales:\n"
                      "• *Transitoriedad* (nada es permanente),\n"
                      "• *Interdependencia* (todo está conectado),\n"
                      "• *Mente abierta* (humildad, imparcialidad y aprendizaje continuo).\n"
                      "\n"
                      "📌 *Sobre KUDO Bolivia:*\n"
                      "KUDO Bolivia fue oficialmente constituida en abril de 2021. Su director (*Branch Chief*) es "
                      "el Sensei *José Manuel Rioja Claure*, 2º DAN en Kudo. Desde su creación, el equipo boliviano "
                      "ha participado en eventos internacionales, incluyendo el Panamericano en Brasil y el "
                      "Campeonato Mundial en Japón en 2023.\n"
                      "\n"
                      "📹 Videos recomendados:\n"
                      "• ¿Qué es Kudo?: https://www.youtube.com/watch?v=NqcE1J7z2eE&\n"
                      "• Highlights: https://www.youtube.com/watch?v=JtTWeISoAFA&\n"
                      "• Mundial 2023: https://www.youtube.com/watch?v=jfcne0M5qEU\n"
                      "\n"
                      "🌐 Sitio oficial de la Federación Internacional de Kudo (KIF): https://ku-do.org/\n"
                      "📘 Facebook oficial KUDO Bolivia: https://www.facebook.com/profile.php?id=100032041972221\n"
                      "🗓️ Calendario de eventos KIF: https://ku-do.org/news/\n"
                      "\n"
                      "🥋 *¿Qué es el Jiu-Jitsu Brasileño (BJJ)?*\n"
                      "El BJJ es un arte marcial especializado en el combate cuerpo a cuerpo en el suelo, "
                      "utilizando técnicas como llaves articulares, estrangulamientos y controles. Se basa en la "
                      "técnica y la estrategia más que en la fuerza, permitiendo neutralizar o someter al oponente "
                      "con eficiencia.\n"
                      "\n"
                      "🎥 Video explicativo: https://www.youtube.com/watch?v=tztK3dJksk0\n"
                      "\n"
                      "🧍‍♂️ *Edades y niveles:*\n"
                      "Ofrecemos clases para todas las edades, desde niños hasta adultos. Se aceptan niños desde los"
                      " 6 años o próximos a cumplirlos. No se necesita experiencia previa.\n\n"
                      "🕒 *Horarios generales de referencia:*\n"
                      "📍 *Kudo Niños (6 a 13 años)*\n"
                      "— *Iniciales:*\n"
                      "   🕗 *Turno mañana:*\n"
                      "     • Lunes: 8:30–9:30\n"
                      "     • Jueves: 8:30–10:00\n"
                      "     • Sábados: 10:30–12:00\n"
                      "   🌆 *Turno tarde:*\n"
                      "     • Lunes: 16:00–17:00\n"
                      "     • Jueves: 16:30–18:00\n"
                      "     • Sábados: 10:30–12:00\n"
                      "\n"
                      "— *Avanzados:*\n"
                      "   🕗 *Turno mañana:*\n"
                      "     • Martes y Jueves: 8:30–10:00\n"
                      "     • Sábados: 10:30–12:00\n"
                      "   🌆 *Turno tarde:*\n"
                      "     • Martes y Jueves: 16:30–18:00\n"
                      "     • Sábados: 10:30–12:00\n"
                      "\n"
                      "📍 *Kudo Jóvenes y Adultos*\n"
                      "— *Iniciales:*\n"
                      "   🕗 *Turno mañana:*\n"
                      "     • Lunes: 8:30–9:30\n"
                      "     • Jueves: 8:30–10:00\n"
                      "     • Sábados: 09:00–10:30\n"
                      "   🌙 *Turno noche:*\n"
                      "     • Martes: 20:30–21:30\n"
                      "     • Jueves: 19:30–21:00\n"
                      "     • Sábados: 9:00–10:30\n"
                      "\n"
                      "— *Avanzados:*\n"
                      "   🕗 *Turno mañana:*\n"
                      "     • Martes y Jueves: 8:30–10:00\n"
                      "     • Sábados: 9:00–10:30\n"
                      "   🌙 *Turno noche:*\n"
                      "     • Martes: 19:30–20:30\n"
                      "     • Jueves: 19:30–21:00\n"
                      "     • Sábados: 9:00–10:30\n"
                      "📍 *Brazilian Jiu-Jitsu Jóvenes y Adultos*\n"
                      "— *Con Gi:*\n"
                      "   🕗 *Turno mañana:*\n"
                      "     • Lunes, Miércoles y Viernes: 9:30–11:00\n"
                      "   🌆 *Turno tarde:*\n"
                      "     • Lunes, Miércoles y Viernes: 17:00–18:30\n"
                      "   🌙 *Turno noche:*\n"
                      "     • Lunes, Miércoles y Viernes: 19:30–21:00\n"
                      "\n"
                      "— *No-Gi:*\n"
                      "   🕗 *Turno mañana:*\n"
                      "     • Martes y Jueves: 10:00–11:00\n"
                      "\n"
                      "📍 *Brazilian Jiu-Jitsu Kids*\n"
                      "   🌙 *Turno noche:*\n"
                      "     • Lunes, Miércoles y Viernes: 18:30–19:30\n"
                      "\n"
                      "📍 *Kick Boxing*\n"
                      "   🕗 *Turno mañana:*\n"
                      "     • Martes y Jueves: 7:00–8:30\n"
                      "   🌙 *Turno noche:*\n"
                      "     • Martes y Jueves: 18:00–19:30\n"
                      "💰 *Precios:* Bs. 250 mensual por persona. Consulta por descuentos directamente con el equipo "
                      "del dojo.\n\n"
                      "🆓 *Clase de prueba:*\n"
                      "Puedes asistir a una clase gratuita antes de tomar una decisión de inscripción.\n""\n"
                      "🧥 *Indumentaria:*\n"
                      "Para las primeras clases se recomienda ropa deportiva cómoda. Para entrenamientos regulares "
                      "se utilizan implementos básicos como *gi* (kimono), guantes, protector facial y otros, según "
                      "la disciplina.\n\n"
                      "📝 *Inscripción:* Puedes inscribirte acercándote al dojo. ¡Estamos disponibles para "
                      "recibirte!\n\n"
                      "📍📍 *Ubicación:* Calle Cañada Strongest N.º 1847 - a pasos de la plaza del estudiante, La Paz, "
                      "Bolivia.\n\n"
                      "📌 Puedes ver el mapa en Google Maps:  \n"
                      "https://maps.app.goo.gl/CeW1sAW77AgTzriA6?g_st=ipc\n\n"
                      "👨‍🏫 *Profesores de Jiu-Jitsu en KUDO Bolivia:*"
                      "• *Prof. Joaquín Carvajal* – 11 años de experiencia en Brazilian Jiu Jitsu Cinturón marrón, "
                      "1er grado Campeón y vice campeón nacional en BJJ (gi y nogi). Artes marciales complementarias: "
                      "Lucha Olímpica, Judo y MMA. "
                      " 🔹 Dicta clases *con Gi* en los siguientes horarios:"
                      "       - Lunes, Miércoles y Viernes: 17:00–18:30"
                      "• *Prof. Igor Ribeiro* – 14 años entrenando jiu-jitsu, cinturón negro 1er grado. Con "
                      "títulos dentro y fuera de Brasil, como el Campeonato Brasileño de Jiu-Jitsu, Campeonato "
                      "Sudamericano, Campeonato Panamericano, entre otros. "
                      " 🔹 Dicta clases *con Gi* en los siguientes horarios:"
                      "       - Lunes, Miércoles y Viernes: 19:30–21:00"
                      "• *Prof. Andre Costa* – 11 años de experiencia en Brazilian Jiu Jitsu Cinturón marrón, "
                      "1er grado Campeón y vice campeón nacional en BJJ (gi y nogi). Artes marciales complementarias: "
                      "Lucha Olímpica, Judo y MMA. "
                      " 🔹 Dicta clases *con Gi y No Gi* en los siguientes horarios:"
                      "       - Lunes, Miércoles y Viernes: 19:30–21:00 (Gi)"
                      "       - Lunes, Miércoles y Viernes: 9:30–11:00 (Gi)"
                      "       - Martes y Jueves: 10:00–11:00 (No Gi)"
                      "       - Lunes, Miércoles y Viernes: 18:30–19:30 (BJJ Kids)"
                      "📌 Si el usuario pregunta por el profesor de alguna clase de Jiu-Jitsu, responde con el nombre"
                      " del instructor y una breve descripción basada en la lista proporcionada. Si no hay información "
                      "suficiente, invita cordialmente a conocer al equipo en el dojo."                      
                      "📝 Si alguien pregunta por temas como horarios, precios, inscripción o ubicación, ofrece "
                      "primero este menú de opciones:\n"
                      "1️⃣ Horarios\n"
                      "2️⃣ Precios\n"
                      "3️⃣ Disciplinas\n"
                      "4️⃣ Inscripción\n"
                      "5️⃣ Ubicación\n"
                      "6️⃣ ¿Qué es Kudo"
                      "\n"
                      "📌 Siempre responde en español neutro, con cortesía y como si formaras parte del equipo de "
                      "*KUDO Bolivia*. Si no conoces la respuesta exacta, invita amablemente a visitar el dojo para "
                      "obtener más información. Si el usuario escribe una lista de números como “1, 3, 4”, responde "
                      "a cada opción en orden. Cada número corresponde al menú que se muestra. No inventes ni combines"
                      " si no está especificado.\n"
                      "🔁 Cuando el usuario solicite la opción 3 (*Disciplinas*), sola o combinada con otras, debes "
                      "incluir también los enlaces de video explicativo de *Kudo* y *BJJ* en tu respuesta."
                      )
            if not es_nuevo:
                prompt += " No inicies con saludos."

            response = client.responses.create(model="gpt-4.1",
                                               instructions=prompt,
                                               input=user_msg,
                                               )
            texto = response.output_text
            contexto_usuarios[user_phone] = {"tema": "libre", "timestamp": ahora}
            registrar_interesado(user_phone, user_msg)
            send_message(texto, user_phone)

    except Exception as e:
        print("Error:", e)

    return "ok", 200


@app.route("/testsheet")
def test_sheet():
    try:
        interesados_sheet.append_row(["TEST", "Prueba manual", time.strftime("%Y-%m-%d %H:%M:%S")])
        return "Escritura exitosa", 200
    except Exception as e:
        print("[ERROR]", e)
        return str(e), 500


# ---------------------------------------------
# Inicio del servidor Flask
# ---------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
