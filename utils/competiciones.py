import json
import os
from datetime import datetime

RUTA_COMPETICIONES = "data/competiciones.json"


# ---------- UTILIDADES INTERNAS ----------

def _leer_archivo():
    if not os.path.exists(RUTA_COMPETICIONES):
        return {}

    with open(RUTA_COMPETICIONES, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _guardar_archivo(data):
    with open(RUTA_COMPETICIONES, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def _generar_id(data):
    if not data:
        return "evt_001"

    ids = [int(k.split("_")[1]) for k in data.keys()]
    nuevo = max(ids) + 1
    return f"evt_{str(nuevo).zfill(3)}"


# ---------- CRUD PUBLICO ----------

def obtener_competiciones():
    """
    Retorna todas las competiciones
    """
    return _leer_archivo()


def obtener_competicion_por_id(evento_id):
    """
    Retorna una competencia por ID o None
    """
    data = _leer_archivo()
    return data.get(evento_id)


def crear_competicion(payload):
    """
    payload debe venir VALIDADO desde la vista
    """
    data = _leer_archivo()
    evento_id = _generar_id(data)

    data[evento_id] = {
        "nombre": payload["nombre"],
        "fecha_evento": payload["fecha_evento"],
        "ciudad": payload["ciudad"],
        "sede": payload["sede"],
        "descripcion": payload["descripcion"],

        "inscripcion": {
            "ordinaria": {
                "fecha_limite": payload["fecha_ordinaria"],
                "valor_deportista": payload["valor_ordinaria_deportista"],
                "valor_club": payload["valor_ordinaria_club"]
            },
            "extraordinaria": {
                "fecha_limite": payload["fecha_extraordinaria"],
                "valor_deportista": payload["valor_extra_deportista"],
                "valor_club": payload["valor_extra_club"]
            }
        },

        "estado": "abierta",
        "fecha_creacion": datetime.now().strftime("%Y-%m-%d")
    }

    _guardar_archivo(data)
    return evento_id


def actualizar_competicion(evento_id, payload):
    data = _leer_archivo()

    if evento_id not in data:
        return False

    data[evento_id].update({
        "nombre": payload["nombre"],
        "fecha_evento": payload["fecha_evento"],
        "ciudad": payload["ciudad"],
        "sede": payload["sede"],
        "descripcion": payload["descripcion"],
        "inscripcion": {
            "ordinaria": {
                "fecha_limite": payload["fecha_ordinaria"],
                "valor_deportista": payload["valor_ordinaria_deportista"],
                "valor_club": payload["valor_ordinaria_club"]
            },
            "extraordinaria": {
                "fecha_limite": payload["fecha_extraordinaria"],
                "valor_deportista": payload["valor_extra_deportista"],
                "valor_club": payload["valor_extra_club"]
            }
        }
    })

    _guardar_archivo(data)
    return True


def eliminar_competicion(evento_id):
    data = _leer_archivo()

    if evento_id not in data:
        return False

    del data[evento_id]
    _guardar_archivo(data)
    return True
