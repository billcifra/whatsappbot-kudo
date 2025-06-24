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

intenciones = {"1": ["horarios", "hora", "a qué hora", "qué días", "qué horario"],
               "2": ["precio", "cuánto cuesta", "cuánto cobran", "tarifa", "vale", "costo"],
               "3": ["qué enseñan", "disciplinas", "qué clases hay", "qué actividades"],
               "4": ["inscribir", "inscripción", "cómo me apunto", "cómo me inscribo", "registrarme"],
               "5": ["dónde están", "dirección", "ubicación", "dónde queda", "cómo llegar"]
               }

respuestas_directas = {"1": "👉 *Horarios de clases en KUDO Bolivia:*\n• *Kudo Niños (7 a 13 años):"
                            "*\n\t*Martes y Jueves* 8:45–10:00 y \n\t16:30–18:00 | \n\t*Sábados* 11:15–12:45\n• "
                            "*Kudo Jovenes y Adultos:*\n\t*Martes y Jueves* 8:45–10:00 y \n\t19:30–21:00 | "
                            "\n\t*Sábado 10:00–11:15*\n• *Brazilian Jiu Jitsu:*\n\t *Lunes, Miércoles y Viernes* "
                            "\n\t17:00–18:30 y 19:30–21:00",
                       "2": "👉 *Precios:*\nBs. 250 la mensualidad por persona y Bs. 150 por las 2 semanas de "
                            "vacaciones de invierno. Consulta por descuentos directamente con el equipo del dojo.",
                       "3": "👉 *Disciplinas que ofrecemos:*\n🥋 Kudo\n\tQue es KUDO: "
                            "https://www.youtube.com/watch?v=NqcE1J7z2eE\n\n🥋 Brazilian Jiu-Jitsu\n\t"
                            "Que es BJJ: https://www.youtube.com/watch?v=tztK3dJksk0",
                       "4": "👉 *¿Cómo inscribirte?*\nAcercate al dojo para poder inscribirte. "
                            "¡Estamos disponibles para recibirte!\n\n🥋¡Tienes una clase de prueba gratis en "
                            "todas nuestras disciplinas!",
                       "5": "📍 *Ubicación de KUDO Bolivia:*\nEdificio ex-Hotel Plaza, Av. 16 de Julio - Prado, "
                            "La Paz, Bolivia,\ningreso gradas del colegio Don bosco\n\n"
                            "📌Mapa: https://maps.app.goo.gl/CoJ7eoVns5tckgPv7"
                       }

# Menú adicional que se agrega al final de cada mensaje
menu = ("\n\n📋 ¿Sobre qué más te gustaría saber?\n"
        "1️⃣ Horarios\n2️⃣ Precios\n3️⃣ Disciplinas\n4️⃣ Inscripción\n5️⃣ Ubicación")

# Palabras clave para atención humana
hablar_con_humano = ["hablar con alguien",
                     "necesito ayuda",
                     "quiero hablar con una persona",
                     "me ayudan", "me pueden ayudar",
                     "humano",
                     "persona",
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
            prompt = ("Eres un asistente virtual del centro de artes marciales *KUDO Bolivia*, ubicado en el "
                      "edificio ex-Hotel Plaza, en la ciudad de La Paz, Bolivia. Tu objetivo es brindar "
                      "información clara, respetuosa y profesional a todas las personas que consultan por "
                      "WhatsApp.\n"
                      "\n"
                      "🏆 En *KUDO Bolivia* se imparten dos disciplinas principales: *Kudo* y *Jiu-Jitsu Brasileño "
                      "(BJJ)*.\n"
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
                      "• Kudo Niños (7 a 13 años): martes y jueves 8:45–10:00 y 16:30–18:00 | sábados 11:15–12:45\n"
                      "• Kudo Jóvenes y Adultos: martes y jueves 8:45–10:00 y 19:30–21:00 | sábados 10:00–11:15\n"
                      "• Brazilian Jiu-Jitsu: lunes, miércoles y viernes 17:00–18:30 y 19:30–21:00\n\n"
                      "💰 *Precios:* Bs. 250 mensual por persona. También ofrecemos una opción de Bs. 150 por dos "
                      "semanas de vacaciones de invierno. Consulta por descuentos directamente con el equipo "
                      "del dojo.\n\n"
                      "🆓 *Clase de prueba:*\n"
                      "Puedes asistir a una clase gratuita antes de tomar una decisión de inscripción.\n""\n"
                      "🧥 *Indumentaria:*\n"
                      "Para las primeras clases se recomienda ropa deportiva cómoda. Para entrenamientos regulares "
                      "se utilizan implementos básicos como *gi* (kimono), guantes, protector facial y otros, según "
                      "la disciplina.\n\n"
                      "📝 *Inscripción:* Puedes inscribirte acercándote al dojo. ¡Estamos disponibles para "
                      "recibirte!\n\n"
                      "📍 *Ubicación:* Edificio ex-Hotel Plaza, Av. 16 de Julio - Prado, La Paz, Bolivia. Ingreso "
                      "por las gradas del colegio Don Bosco. "
                      "📌 Mapa: https://maps.app.goo.gl/CoJ7eoVns5tckgPv7\n\n"
                      "📝 Si alguien pregunta por temas como horarios, precios, inscripción o ubicación, ofrece "
                      "primero este menú de opciones:\n"
                      "1️⃣ Horarios\n"
                      "2️⃣ Precios\n"
                      "3️⃣ Disciplinas\n"
                      "4️⃣ Inscripción\n"
                      "5️⃣ Ubicación\n"
                      "\n"
                      "📌 Siempre responde en español neutro, con cortesía y como si formaras parte del equipo de "
                      "*KUDO Bolivia*. Si no conoces la respuesta exacta, invita amablemente a visitar el dojo para "
                      "obtener más información. Si el usuario escribe una lista de números como “1, 3, 4”, responde "
                      "a cada opción en orden. Cada número corresponde al menú que se muestra. No inventes ni combines"
                      " si no está especificado.\n"
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
