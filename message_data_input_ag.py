import time

value = {"messages": [{"from": "59171234567",
                       "text": {"body": "Hola, ¿cómo estás?"
                                }
                       }
                      ]
         }

if "messages" in value:
    message = value["messages"][0]
    user_msg = message["text"]["body"]
    user_phone = message["from"]
    ahora = time.time()

    print("Mensaje:", user_msg)
    print("Teléfono:", user_phone)
    print("Hora:", ahora)


#%%
import time

data = {"entry": [{"changes": [{"value": {"messages": [{"from": "59171234567",
                                                        "text": {"body": "Hola, ¿cómo estás?"
                                                                 }
                                                        }
                                                       ]
                                          }
                                }
                               ]
                   }, "aasdasdasd"
                  ]
        }

try:
    entry = data.get("entry", [])[0]
    print(entry)
    changes = entry.get("changes", [])[0]
    value = changes.get("value", {})

    if "messages" in value:
        message = value["messages"][0]
        user_msg = message["text"]["body"]
        user_phone = message["from"]
        ahora = time.time()

        print("Mensaje:", user_msg)
        print("Teléfono:", user_phone)
        print("Hora:", ahora)

except Exception as e:
    print("Error al procesar:", e)
