import os
import json
import time
import tempfile
import re
import io
import pandas as pd
import csv
from datetime import datetime, date, timedelta

# Librerías de Flask y Seguridad 
from flask import Flask, Response, render_template, request, redirect, session, url_for, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image

# 1. CONFIGURACIÓN DE LA APP
app = Flask(__name__)
app.secret_key = "LINAPATIN_PROD_2026_SECURE_KEY_99X"
app.permanent_session_lifetime = timedelta(hours=1)

# 2. DEFINICIÓN DE RUTAS DE CARPETAS
UPLOAD_CALENDAR = "static/uploads/calendario"
UPLOAD_NEWS = "static/uploads/noticias"
UPLOAD_HERO = "static/uploads/hero"
UPLOAD_CLUBES = "static/uploads/clubes"
UPLOAD_INFO = "static/uploads/info"
UPLOAD_FLYERS = "static/uploads/flyers"
UPLOAD_REGLAMENTOS = "static/uploads/reglamentos"
UPLOAD_RESULTADOS = "static/uploads/resultados"
os.makedirs(UPLOAD_RESULTADOS, exist_ok=True)
DATA_DIR = "data"

# 3. CREACIÓN AUTOMÁTICA DE TODAS LAS CARPETAS
CARPETAS = [
    UPLOAD_CALENDAR, UPLOAD_NEWS, UPLOAD_HERO, 
    UPLOAD_CLUBES, UPLOAD_INFO, UPLOAD_FLYERS, 
    UPLOAD_REGLAMENTOS, DATA_DIR
]

for carpeta in CARPETAS:
    os.makedirs(carpeta, exist_ok=True)

# 4. FUNCIONES ÚTILES (Helpers)
# funciones que ayudan a que las rutas no se rompan
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# PARA GESTION DE USUARIOS
# Para ver noticias, calendario, etc. (Acceso General Staff)
def es_staff():
    rol = session.get("user", {}).get("rol")
    return rol in ["admin", "editor", "colaborador"]

# Para ver usuarios y borrar cosas (Acceso Súper Admin)
def es_super_admin():
    """Solo para el Administrador principal"""
    if "user" not in session: return False
    rol = session["user"].get("rol") or session["user"].get("role")
    return rol == "admin"

def user_role():
    """Retorna el rol para usar en templates"""
    if "user" not in session: return None
    return session["user"].get("rol") or session["user"].get("role")

def validar_caracteres_seguros(texto):
    """
    Verifica que el texto solo contenga letras básicas (A-Z), 
    números y no tenga espacios, tildes ni eñes.
    Ideal para usuarios y contraseñas.
    """
    if not texto:
        return False
    # Expresión regular: Solo permite a-z, A-Z y 0-9
    # No permite espacios ni caracteres especiales
    patron = r'^[a-zA-Z0-9]+$'
    return bool(re.match(patron, texto))

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# Atajos para cargar datos comunes
def load_users(): return load_json("data/users.json", {})
def save_users(users): save_json("data/users.json", users)
def load_competiciones(): return load_json("data/competiciones.json", {})
def save_competiciones(data): save_json("data/competiciones.json", data)

# ---------- UTILIDADES ----------
def parse_fecha_latam(fecha_str):
    """
    Normaliza fechas de DD/MM/YYYY o YYYY-MM-DD a DD/MM/YYYY.
    """
    if not fecha_str:
        return ""

    # Caso 1: ya está en formato latam
    if "/" in fecha_str:
        try:
            datetime.strptime(fecha_str, "%d/%m/%Y")
            return fecha_str
        except ValueError:
            pass

    # Caso 2: viene de input date (ISO)
    if "-" in fecha_str:
        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
            return fecha.strftime("%d/%m/%Y")
        except ValueError:
            pass

    return fecha_str


def es_hash(password):
    return password.startswith("pbkdf2:sha256")


def fecha_corte(evento_fecha):
    """
    Calcula la fecha de referencia (1 de julio) para determinar categorías.
    """
    try:
        # Intentamos ambos formatos posibles
        if "-" in evento_fecha:
            evento = datetime.strptime(evento_fecha, "%Y-%m-%d").date()
        else:
            evento = datetime.strptime(evento_fecha, "%d/%m/%Y").date()
    except:
        evento = date.today()

    corte_actual = date(evento.year, 7, 1)
    if evento < corte_actual:
        return date(evento.year - 1, 7, 1)
    return corte_actual


def calcular_edad(fecha_nacimiento, fecha_corte):
    # Convertir string a objeto date si es necesario
    if isinstance(fecha_nacimiento, str):
        try:
            fecha_nacimiento = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
        except:
            return 0
    edad = fecha_corte.year - fecha_nacimiento.year
    if (fecha_corte.month, fecha_corte.day) < (fecha_nacimiento.month, fecha_nacimiento.day):
        edad -= 1
    return edad


def obtener_categoria(edad, modalidad):
    # Evita errores si modalidad es None o vacía
    mod = (modalidad or "").lower()

    # CATEGORÍA PARA ESCUELA / RECREATIVO
    if mod in ["escuela", "recreativo"]:
        return f"{edad} AÑOS"

    # CATEGORÍA PARA NOVATOS / LIGADOS
    if mod in ["novatos", "ligados"]:
        # Agrupa categorías similares
        if 7 <= edad <= 9:
            return f"Mini Infantil {edad}"
        if 10 <= edad <= 11:
            return f"Pre Infantil {edad}"
       
        if edad == 12: return "Infantil 12"
        if edad == 13: return "Junior 13"
        if edad == 14: return "Prejuvenil 14"
        
        if 15 <= edad <= 17:
            return "Juvenil"
        if edad >= 18:
            return "Mayores"

    return "No válida"


def validar_edad(edad, modalidad):
    modalidad = (modalidad or "").lower()
    
    # Si es muy pequeño (menor de 3), no entra en ninguna modalidad
    if edad < 3:
        return False

    # Regla específica para Novatos/Ligados
    if modalidad in ["novatos", "ligados"]:
        return edad >= 6

    # Para Escuela/Recreativo ya sabemos que tiene 3 o más
    return True


def obtener_valor_inscripcion(competencia, fecha_inscripcion, tipo_usuario):
    try:
        # 1. Normalizamos la fecha límite (soporta - y /)
        f_limite = competencia["fecha_limite_ordinaria"]
        formato = "%Y-%m-%d" if "-" in f_limite else "%d/%m/%Y"
        limite = datetime.strptime(f_limite, formato).date()
        
        hoy = fecha_inscripcion.date()
        
        # 2. Determinamos si es ordinaria o extraordinaria
        fase = "ordinaria" if hoy <= limite else "extraordinaria"
        
        # 3. Determinamos si es club o deportista para armar la llave del JSON
        perfil = "club" if tipo_usuario == "club" else "deportista"
        
        llave_precio = f"valor_{fase}_{perfil}"
        
        # 4. Retornamos el tipo y el valor convertido a número
        return fase, int(competencia.get(llave_precio, 0))
        
    except Exception as e:
        print(f"Error en cobro: {e}")
        return "error", 0

# ---------- GESTIÓN DE ARCHIVOS Y DATOS (JSON) ----------

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return default

def save_json(path, data):
    """
    Guarda JSON con soporte para Ñ y tildes en los valores.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# Atajos de carga/guardado específicos
def load_users(): return load_json("data/users.json", {})
def save_users(users): save_json("data/users.json", users)
def load_news(): return load_json("data/noticias.json", {}) 
def save_news(news): save_json("data/noticias.json", news)
def load_heroes(): return load_json("data/heroes.json", []) 
def load_competiciones(): return load_json("data/competiciones.json", {})
def save_competiciones(data): save_json("data/competiciones.json", data)

# --- HELPER UNIFICADO PARA STAFF ---
def is_admin():
    """Cubre a todo el equipo administrativo (Admin, Editor, Colaborador)"""
    if "user" not in session: return False
    rol = session["user"].get("rol") or session["user"].get("role")
    return rol in ["admin", "editor", "colaborador"]


def require_role(roles):
    if "user" not in session: return False
    rol = session["user"].get("rol") or session["user"].get("role")
    return rol in roles


def require_club():
    if "user" not in session: return False
    u = session["user"]
    rol = u.get("rol") or u.get("role")
    return rol == "club" and u.get("club_id") is not None


def user_role():
    if "user" not in session: return None
    return session["user"].get("rol") or session["user"].get("role")

@app.route("/")
def index():
    heroes = load_heroes() 
    noticias_dict = load_news() 
    
    # Ordenamos por ID de forma descendente
    noticias_ordenadas = sorted(
        noticias_dict.items(), 
        key=lambda x: x[0], 
        reverse=True
    )
    
    # Tomamos solo las primeras 9 para la página principal (3 filas de 3)
    noticias_limitadas = dict(noticias_ordenadas[:9])
    
    return render_template("index.html", 
                           heroes=heroes, 
                           noticias=noticias_limitadas)

@app.route("/noticias")
def noticias_completo():
    noticias_dict = load_news()
    # Ordenamos todas para el archivo
    noticias_ordenadas = sorted(
        noticias_dict.items(), 
        key=lambda x: x[0], 
        reverse=True
    )
    # Enviamos el diccionario completo convertido de la lista ordenada
    return render_template("public/noticias_archivo.html", noticias=dict(noticias_ordenadas))

@app.route('/noticias')
def lista_noticias():
    # Enviamos todas las noticias a la página de archivo
    return render_template('noticias_archivo.html', noticias=db['noticias'])

#---------------Menu principal para Usuarios-----------------------
@app.route("/admin/inicio")
def admin_inicio():
    if "user" not in session:
        return redirect("/login")
    
    # Obtenemos el rol de la sesión
    rol_actual = session["user"].get("rol") or session["user"].get("role")
    
    if rol_actual not in ["admin", "editor", "colaborador"]:
        return redirect("/login")
    
    return render_template("admin/inicio_staff.html", rol=rol_actual)
#--------------------------------------------------------------

# --- LISTA DE COMPETICIONES (Admin y Editor) ---
@app.route("/admin/competiciones")
def admin_competiciones():
    rol = user_role()
    if rol not in ["admin", "editor"]: 
        return redirect("/login")

    competiciones = load_competiciones()
    return render_template(
        "admin/competiciones.html",
        competiciones=competiciones,
        role=rol # Pasamos el rol al HTML
    )

#------Marcar estado de pago desde ADMIN ----------------
@app.route("/admin/inscripciones/<insc_id>/estado", methods=["POST"])
def cambiar_estado_pago(insc_id):
    if not is_admin():
        return redirect("/login")

    nuevo_estado = request.form.get("estado_pago")
    if nuevo_estado not in ["pendiente", "pagado", "rechazado"]:
        return "Estado inválido", 400

    inscripciones = load_inscripciones()

    if insc_id not in inscripciones:
        return "Inscripción no encontrada", 404

    inscripciones[insc_id]["estado_pago"] = nuevo_estado
    save_inscripciones(inscripciones)

    return redirect(request.referrer or "/admin/inscripciones")
#----------------------------------------------------------


#------------CREAR NUEVA COMPETENCIA ----------------------------
@app.route("/admin/competiciones/nueva", methods=["GET", "POST"])
def nueva_competicion():
    rol = user_role()
    if rol not in ["admin", "editor"]:
        return redirect("/login")

    competiciones = load_competiciones()
    if request.method == "POST":
        ids = [int(k) for k in competiciones.keys() if k.isdigit()]
        new_id = str(max(ids) + 1) if ids else "1"

        # ... (Tu lógica de procesamiento de archivos se mantiene igual) ...
        flyer_name = ""
        f_file = request.files.get("flyer")
        if f_file and f_file.filename:
            flyer_name = secure_filename(f_file.filename)
            f_file.save(os.path.join(UPLOAD_FLYERS, flyer_name))

        reg_name = ""
        r_file = request.files.get("reglamento")
        if r_file and r_file.filename and r_file.filename.lower().endswith(".pdf"):
            reg_name = secure_filename(r_file.filename)
            r_file.save(os.path.join(UPLOAD_REGLAMENTOS, reg_name))

        competiciones[new_id] = {
            "id": new_id,
            "nombre": request.form["nombre"],
            "fecha_evento": request.form["fecha_evento"],
            "lugar": request.form["lugar"],
            "descripcion": request.form["descripcion"],
            "fecha_limite_ordinaria": request.form["fecha_limite_ordinaria"],
            "fecha_limite_extraordinaria": request.form["fecha_limite_extraordinaria"],
            "valor_ordinaria_deportista": int(request.form.get("valor_ordinaria_deportista", 0)),
            "valor_ordinaria_club": int(request.form.get("valor_ordinaria_club", 0)),
            "valor_extraordinaria_deportista": int(request.form.get("valor_extraordinaria_deportista", 0)),
            "valor_extraordinaria_club": int(request.form.get("valor_extraordinaria_club", 0)),
            "flyer": flyer_name,
            "reglamento": reg_name,
            "created_at": datetime.now().strftime("%d/%m/%Y %H:%M") 
        }

        save_competiciones(competiciones)
        return redirect("/admin/competiciones")

    return render_template("admin/competicion_form.html", competicion=None)
#------------------------------------------------------------------

#---------EDITAR COMPETENCIA ----------------------------
@app.route("/admin/competiciones/editar/<comp_id>", methods=["GET", "POST"])
def editar_competicion(comp_id):
    rol = user_role()
    if rol not in ["admin", "editor"]:
        return redirect("/login")

    competiciones = load_competiciones()
    if comp_id not in competiciones:
        return redirect("/admin/competiciones")

    comp = competiciones[comp_id]
    if request.method == "POST":
        # ... (Tu lógica de update se mantiene igual) ...
        comp.update({
            "nombre": request.form["nombre"],
            "fecha_evento": request.form["fecha_evento"],
            "lugar": request.form["lugar"],
            "descripcion": request.form["descripcion"],
            "fecha_limite_ordinaria": request.form["fecha_limite_ordinaria"],
            "fecha_limite_extraordinaria": request.form["fecha_limite_extraordinaria"],
            "valor_ordinaria_deportista": int(request.form.get("valor_ordinaria_deportista", 0)),
            "valor_ordinaria_club": int(request.form.get("valor_ordinaria_club", 0)),
            "valor_extraordinaria_deportista": int(request.form.get("valor_extraordinaria_deportista", 0)),
            "valor_extraordinaria_club": int(request.form.get("valor_extraordinaria_club", 0))
        })
        # Archivos
        f_file = request.files.get("flyer")
        if f_file and f_file.filename:
            fname = secure_filename(f_file.filename)
            f_file.save(os.path.join(UPLOAD_FLYERS, fname))
            comp["flyer"] = fname
        
        save_competiciones(competiciones)
        return redirect("/admin/competiciones")

    return render_template("admin/competicion_form.html", competicion=comp)
#----------------------------------------------------------------------------------

#------------------ELIMINAR COMPETENCIA -------------------------------------------
@app.route("/admin/competiciones/eliminar/<comp_id>")
def eliminar_competicion(comp_id):
    if not is_admin():
        return redirect("/login")

    competiciones = load_competiciones()
    if comp_id in competiciones:
        del competiciones[comp_id]
        save_competiciones(competiciones)

    return redirect("/admin/competiciones")


# --- VER INSCRITOS (SOLO ADMIN) ---
@app.route("/admin/competiciones/inscritos/<comp_id>")
def ver_inscritos_competencia(comp_id):
    rol = user_role()
    if rol != "admin": # BLOQUEO TOTAL AL EDITOR
        flash("Acceso denegado: Solo el administrador puede ver inscritos.", "error")
        return redirect("/admin/competiciones")
    
    # Lógica para filtrar inscripciones por comp_id
    todas = load_inscripciones()
    inscritos_evento = {k: v for k, v in todas.items() if v.get('competicion_id') == comp_id}
    
    return render_template("admin/ver_inscritos.html", inscritos=inscritos_evento, comp_id=comp_id)




def load_deportistas():
    return load_json("data/deportistas.json", {})


def save_deportistas(data):
    save_json("data/deportistas.json", data)



def load_inscripciones():
    return load_json("data/inscripciones.json", {})

def save_inscripciones(data):
    save_json("data/inscripciones.json", data)




#----------REDIMENSIONAR IMAGEN DEL HERO-------------
def resize_hero_image(path):
    img = Image.open(path).convert("RGB")
    target_w, target_h = 1200, 380
    
    # Cálculo inteligente de proporciones para recorte central (CROP)
    img_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if img_ratio > target_ratio:
        new_h = target_h
        new_w = int(new_h * img_ratio)
    else:
        new_w = target_w
        new_h = int(new_w / img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    
    # Recorte central
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))
    img.save(path, quality=90)





# ---------- RUTAS PUBLICAS ----------

def load_heroes(): return load_json("data/heroes.json", [])
def save_heroes(data): save_json("data/heroes.json", data)

@app.route("/")
def inicio():
    # Carga segura de elementos visuales
    return render_template(
        "index.html",
        noticias=load_news(),
        heroes=load_heroes()
    )


@app.route("/logout")
def logout():
    # 1. Limpiamos toda la información de la sesión
    session.clear()
    
    # 2. Añadimos un mensaje flash opcional (ayuda al usuario a saber qué pasó)
    flash("Has cerrado sesión correctamente.", "info")
    
    # 3. Redirigimos al inicio
    return redirect("/")


@app.route("/perfil")
def perfil_usuario():
    # 1. Verificación de Seguridad
    if "user" not in session:
        return redirect("/login")

    rol = user_role() # Usamos nuestra utilidad centralizada
    usuario = session["user"].get("usuario")

    # 2. Redirecciones por Rol
    if rol in ["admin", "editor", "colaborador"]:
        return redirect("/admin")
    if rol == "club":
        return redirect("/club")
    if rol != "deportista":
        return redirect("/")

    # 3. Carga de Datos del Deportista
    deportistas = load_deportistas() # Usamos la función de carga optimizada
    deportista = deportistas.get(usuario)
    
    if not deportista:
        flash("Perfil de deportista no encontrado. Contacte al administrador.", "error")
        return redirect("/")

    # 4. Obtener datos del Club
    clubes = load_json("data/clubes_registro.json", {})
    club_id = str(deportista.get("club_id", ""))
    club_data = clubes.get(club_id, {})
    deportista["club_nombre"] = club_data.get("nombre", "INDEPENDIENTE / SIN CLUB")

    # 5. Cálculo de Edad y Categoría (Protegido contra errores)
    try:
        f_nac_str = parse_fecha_latam(deportista["fecha_nacimiento"])
        fecha_nac_dt = datetime.strptime(f_nac_str, "%d/%m/%Y").date()
        
        # Usamos la fecha de hoy para la edad informativa del perfil
        hoy = date.today()
        edad = calcular_edad(fecha_nac_dt, hoy)
        
        # Para la categoría deportiva, usamos la lógica de fecha_corte
        # (Aunque aquí mostramos la categoría general basada en su edad hoy)
        deportista["categoria"] = obtener_categoria(edad, deportista.get("modalidad", ""))

        meses = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
                 "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
        deportista["fecha_bonita"] = f"{fecha_nac_dt.day} DE {meses[fecha_nac_dt.month - 1]} DE {fecha_nac_dt.year}"
        edad_mostrar = edad
    except Exception as e:
        print(f"Error en fechas: {e}")
        edad_mostrar = "N/A"
        deportista["fecha_bonita"] = "Fecha no válida"
        deportista["categoria"] = "Sin categoría"

    # 6. Eventos Abiertos (Solo los que no han pasado)
    competencias = load_competiciones()
    hoy_dt = date.today()
    eventos_abiertos = []
    
    for c in competencias.values():
        try:
            # Soporte para ambos formatos de fecha en competencias
            f_comp = c["fecha_evento"]
            f_dt = datetime.strptime(f_comp, "%Y-%m-%d").date() if "-" in f_comp else datetime.strptime(f_comp, "%d/%m/%Y").date()
            if f_dt >= hoy_dt:
                eventos_abiertos.append(c)
        except:
            continue

    # 7. Inscripciones del Deportista
    inscripciones_db = load_inscripciones()
    mis_inscripciones = []

    for insc in inscripciones_db.values():
        if str(insc.get("documento")) == str(usuario):
            comp_id = str(insc.get("competencia_id"))
            info_c = competencias.get(comp_id)
            # Evitamos que se rompa si la competencia fue borrada
            insc["nombre_evento"] = info_c["nombre"] if info_c else "Evento no disponible"
            mis_inscripciones.append(insc)

    return render_template(
        "perfil/deportista.html",
        deportista=deportista,
        edad=edad_mostrar,
        eventos=eventos_abiertos,
        inscripciones=mis_inscripciones
    )



@app.route("/perfil/editar", methods=["POST"])
def editar_perfil_deportista():
    # 1. Validación de Sesión y Rol
    if "user" not in session or user_role() != "deportista":
        return redirect("/")

    usuario = session["user"].get("usuario")
    deportistas = load_deportistas() # Carga optimizada

    if usuario not in deportistas:
        flash("Error: El perfil no existe.", "error")
        return redirect("/")

    deportista = deportistas[usuario]

    # 2. Lista de campos a actualizar automáticamente
    campos = [
        "nombre", "telefono", "correo", "sexo", 
        "acudiente_nombre", "acudiente_telefono"
    ]

    for campo in campos:
        valor = request.form.get(campo, "").strip()
        if valor: # Solo actualiza si el usuario escribió algo
            deportista[campo] = valor

    # 3. Tratamiento especial para la Fecha de Nacimiento
    f_nac = request.form.get("fecha_nacimiento", "").strip()
    if f_nac:
        # Usamos nuestra utilidad para asegurar el formato DD/MM/YYYY
        deportista["fecha_nacimiento"] = parse_fecha_latam(f_nac)

    # 4. Guardado seguro (soporta tildes y eñes en los nombres)
    save_deportistas(deportistas)

    flash("Datos actualizados correctamente", "success")
    return redirect("/perfil")



#---------------- ADMIN RESTABLECER CONTRASEÑA DEPORTISTA----------------
@app.route("/admin/deportistas/<documento>/reset-password", methods=["POST"])
def admin_reset_password(documento):
    # 1. Validación de seguridad
    if not is_admin():
        flash("No tienes permisos para realizar esta acción.", "error")
        return redirect("/login")

    # 2. CARGAMOS AMBAS BASES DE DATOS
    users = load_users()            # Carga data/users.json
    deportistas = load_deportistas() # Carga data/deportistas.json

    encontrado = False
    nueva_clave_plana = str(documento)
    hash_nuevo = generate_password_hash(nueva_clave_plana)

    # 3. BUSCAMOS Y ACTUALIZAMOS
    # Caso A: Está en users.json (Admins/Clubes)
    if documento in users:
        users[documento]["password"] = hash_nuevo
        save_users(users)
        encontrado = True

    # Caso B: Está en deportistas.json (Tus deportistas actuales)
    if documento in deportistas:
        # Aquí se soluciona tu problema: se crea el campo 'password' si no existe
        deportistas[documento]["password"] = hash_nuevo
        
        # Guardado manual para asegurar que se escriba en deportistas.json
        try:
            with open("data/deportistas.json", "w", encoding="utf-8") as f:
                json.dump(deportistas, f, indent=4)
            encontrado = True
        except Exception as e:
            flash(f"Error al escribir en el archivo de deportistas: {e}", "error")
            return redirect(f"/admin/deportistas/{documento}")

    # 4. FEEDBACK FINAL
    if encontrado:
        flash(f"Contraseña de {documento} restablecida. Ahora es su número de documento.", "success")
    else:
        flash("El usuario no existe en ninguna base de datos.", "error")
    
    return redirect(f"/admin/deportistas/{documento}")

#--------FIN ADMIN RESTABLECE CONTRASEÑA ---------------------------

#------------ADMIN RESTABLECE CONTRASEÑA DE CLUB---------------------
@app.route("/admin/usuarios/reset-password/<username>", methods=["POST"])
def admin_reset_user_password(username):
    if not is_admin():
        return redirect("/login")

    users = load_users()
    
    # 1. Intentamos buscar tal cual viene (Patin Galeras)
    # 2. Intentamos buscar todo en minúsculas y sin espacios (patingaleras)
    username_limpio = username.lower().replace(" ", "")

    target = None
    if username in users:
        target = username
    elif username_limpio in users:
        target = username_limpio

    if target:
        users[target]["password"] = generate_password_hash("123456")
        save_users(users)
        flash(f"Contraseña de '{target}' restablecida a 123456", "success")
    else:
        # Si fallan ambos, mostramos el error pero te doy una pista
        flash(f"Error: No existe el usuario '{username}' ni '{username_limpio}' en users.json", "danger")

    return redirect("/admin/clubes-registro")
#---------------------------------------------------------------------




#---------------- CREAR CALENDARIO ----------------
@app.route("/calendario")
def calendario():
    # 1. Definimos el nombre y la ruta física
    nombre_archivo = "calendario.pdf"
    file_path = os.path.join(UPLOAD_CALENDAR, nombre_archivo)

    # 2. Verificamos si el archivo existe físicamente
    if not os.path.exists(file_path):
        return render_template("calendario.html", archivo=None)

    # 3. TRUCO DE CACHÉ: Obtenemos la fecha de última modificación
    # Esto genera un número único (timestamp) que cambia solo cuando subes un archivo nuevo
    version = int(os.path.getmtime(file_path))

    # 4. Generamos la URL con el parámetro 'v' para forzar la actualización
    # Resultado: /static/uploads/calendario/calendario.pdf?v=1707312345
    archivo_url = url_for("static", filename=f"uploads/calendario/{nombre_archivo}", v=version)

    return render_template(
        "calendario.html",
        archivo=archivo_url
    )
#-----------------------------------------------------------



#-------- DEPORTISTA SE INSCRIBA A EVENTO-------------------
@app.route("/competencias/<comp_id>/inscripcion")
def form_inscripcion(comp_id):

    # 1. Verificación de Login obligatorio
    # Guardamos 'next' para que después de loguearse vuelva directo aquí
    if "user" not in session:
        return redirect(url_for("login", next=request.path))

    # 2. Validación de Rol usando nuestra utilidad
    rol = user_role()
    if rol != "deportista":
        flash("Esta sección es exclusiva para deportistas registrados.", "warning")
        return redirect("/competencias")

    # 3. Carga de datos de la competencia
    competencias = load_competiciones()
    comp_id_str = str(comp_id) # Aseguramos que sea string para buscar en el JSON

    if comp_id_str not in competencias:
        flash("La competencia seleccionada no existe o fue finalizada.", "error")
        return redirect("/competencias")

    # 4. Mostrar formulario con los datos cargados
    return render_template(
        "public/inscripcion_competencia.html",
        competencia=competencias[comp_id_str],
        role=rol
    )
#----------------------------------------------------

#-------------VITRINA DE LOS EVENTOS ---------------------
@app.route("/competencias")
def competencias_publicas():
    # 1. Carga de datos usando la utilidad específica
    competiciones_dict = load_competiciones()
    
    # 2. Convertimos a lista para poder ordenar
    lista_competencias = list(competiciones_dict.values())

    # 3. Ordenamos: Las fechas más cercanas/futuras primero
    # Intentamos ordenar por 'fecha_evento', si falla (por formato), sigue igual
    try:
        lista_competencias.sort(key=lambda x: x.get('fecha_evento', ''), reverse=False)
    except Exception as e:
        print(f"Aviso: No se pudo ordenar por fecha: {e}")

    # 4. Renderizamos pasando el rol para lógica de botones en el HTML
    return render_template(
        "public/competiciones.html",
        competencias=lista_competencias,
        role=user_role()
    )

@app.route("/eventos")
def eventos_publicos():
    """
    Alias para la ruta de competencias. 
    Redirige permanentemente para mantener una única fuente de verdad.
    """
    return redirect(url_for('competencias_publicas'))
#--------------------------------------------------------------

#----------USUARIO VE EL EVENTO, FLYER, REGLAMENTO--------------
@app.route("/competencias/<comp_id>")
def ver_competencia(comp_id):
    # 1. Carga segura de datos
    competencias = load_competiciones()
    comp_id_str = str(comp_id)

    # 2. Validación de existencia
    if comp_id_str not in competencias:
        flash("La competencia solicitada no está disponible.", "error")
        return redirect("/competencias")

    # 3. Renderizado con contexto
    return render_template(
        "public/detalle_competencia.html",
        competencia=competencias[comp_id_str],
        role=user_role() # Enviamos el rol para lógica de botones en el HTML
    )
#-------------------------------------------------------

#------- DEPORTISTA SE INSCRIBE EN EL EVENTO---------------
@app.route("/competencias/<comp_id>/inscribirse", methods=["POST"])
def inscribirse_competencia(comp_id):
    # 1. Validación de sesión y rol
    if "user" not in session:
        return redirect(url_for("login", next=request.path))

    if user_role() != "deportista":
        flash("Solo los deportistas pueden realizar inscripciones personales.", "warning")
        return redirect("/competencias")

    # 2. Carga centralizada de bases de datos
    competencias = load_competiciones()
    deportistas = load_deportistas()
    inscripciones = load_inscripciones()
    comp_id_str = str(comp_id)

    # 3. Validaciones de existencia
    if comp_id_str not in competencias:
        flash("Evento no encontrado.", "error")
        return redirect("/competencias")

    documento = request.form.get("documento")
    if documento not in deportistas:
        flash("Sus datos de deportista no coinciden. Contacte a la Liga.", "error")
        return redirect("/perfil")

    deportista = deportistas[documento]
    competencia = competencias[comp_id_str]

    # 4. Verificación de duplicados (¿Ya está inscrito?)
    for insc in inscripciones.values():
        if str(insc.get("competencia_id")) == comp_id_str and str(insc.get("documento")) == str(documento):
            flash(f"Ya te encuentras inscrito en el evento: {competencia['nombre']}", "info")
            return redirect("/perfil")

    # 5. Lógica de Edad y Categoría
    try:
        f_nac_str = parse_fecha_latam(deportista["fecha_nacimiento"])
        fecha_nac = datetime.strptime(f_nac_str, "%d/%m/%Y").date()
        
        # Usamos la fecha de corte oficial del evento
        corte = fecha_corte(competencia["fecha_evento"])
        edad_competencia = calcular_edad(fecha_nac, corte)

        if not validar_edad(edad_competencia, deportista.get("modalidad", "")):
            flash("Tu edad no está permitida para las categorías de este evento.", "error")
            return redirect(f"/competencias/{comp_id_str}")
            
    except Exception as e:
        flash("Error al validar tu fecha de nacimiento.", "error")
        return redirect("/perfil")

    # 6. Cálculo de Valor (según fecha actual y tipo de usuario)
    tipo_insc, valor = obtener_valor_inscripcion(
        competencia,
        datetime.now(),
        "deportista"
    )

    # 7. GENERACIÓN DE ID SEGURO
    # Buscamos el ID más alto existente para no repetir nunca
    ids_existentes = [int(k) for k in inscripciones.keys() if k.isdigit()]
    proximo_id = str(max(ids_existentes) + 1) if ids_existentes else "1"

    # 8. Obtener datos del Club
    clubes = load_json("data/clubes_registro.json", {})
    club_info = clubes.get(str(deportista.get("club_id", "")), {})

    # 9. GUARDAR INSCRIPCIÓN
    inscripciones[proximo_id] = {
        "id": proximo_id,
        "competencia_id": comp_id_str,
        "documento": documento,
        "nombre": deportista["nombre"],
        "club": club_info.get("nombre", "INDEPENDIENTE / SIN CLUB"),
        "club_id": deportista.get("club_id", ""),
        "sexo": deportista.get("sexo", ""),
        "modalidad": deportista.get("modalidad", ""),
        "edad": edad_competencia,
        "categoria": obtener_categoria(edad_competencia, deportista.get("modalidad", "")),
        "tipo_inscripcion": tipo_insc,
        "valor": valor,
        "fecha_registro": now(), # Usamos nuestra utilidad de tiempo
        "estado_pago": "pendiente",
        "forma_pago": "",
        "fecha_pago": ""
    }

    save_inscripciones(inscripciones)

    flash(f"✅ ¡FELICITACIONES! Te has inscrito correctamente a: {competencia['nombre']}", "success")
    return redirect("/perfil")
#-------------------------------------------------------------------


#--------------REGISTRASE EL DEPORTISTA------------------------
@app.route("/registro/deportista", methods=["GET", "POST"])
def registro_deportista():
    clubes_dict = load_json("data/clubes_registro.json", {})
    
    # Preparamos la lista para el HTML
    clubes = sorted(
        clubes_dict.values(),
        key=lambda c: (not c.get("afiliado", False), c.get("nombre", "").lower())
    )

    if request.method == "POST":
        users = load_users()
        deportistas = load_deportistas()

        documento = request.form.get("documento", "").strip()
        nombre = request.form.get("nombre", "").strip().title()

        # --- SECCIÓN CRÍTICA: BÚSQUEDA DEL CLUB ---
        id_club_sel = request.form.get("club_id") # Lo que viene del <select>
        
        # 1. Intentar buscarlo directamente
        info_club = clubes_dict.get(str(id_club_sel)) 
        
        # 2. Si no lo encuentra, buscar dentro de los valores (por si el ID está adentro)
        if not info_club:
            for c in clubes_dict.values():
                if str(c.get("id")) == str(id_club_sel):
                    info_club = c
                    break
        
        # 3. Asignar el nombre encontrado o un valor por defecto
        nombre_real_club = info_club.get("nombre") if info_club else "Independiente"
        
        # DEBUG: Mira tu terminal cuando des clic en registrar
        print(f"DEBUG: ID recibido: {id_club_sel} | Club encontrado: {nombre_real_club}")

        # ... (tus validaciones de documento)

        # 3. GUARDAR PERFIL
        deportistas[documento] = {
            "documento": documento,
            "nombre": nombre,
            "fecha_nacimiento": request.form.get("fecha_nacimiento"),
            "sexo": request.form.get("sexo"),
            "club_id": id_club_sel,
            "club": nombre_real_club, # <--- Aquí se guarda el texto "Club X"
            "modalidad": request.form.get("modalidad"),
            "telefono": request.form.get("telefono", ""),
            "correo": request.form.get("correo", "").lower(),
            "acudiente_nombre": request.form.get("acudiente_nombre", "").strip().title()
        }

        save_deportistas(deportistas)
        # ... resto de tu código de guardado de usuario y redirect

        flash(f"¡Bienvenido {nombre}! Tu contraseña es tu número de documento.", "success")
        return redirect("/login")

    return render_template("public/registro_deportista.html", clubes=clubes)


#---------------FIN REGISTRARSE EL DEPORTISTA----------------



#---------ADMIN ELIMINA DEPORTISTA---------------------------
@app.route("/admin/deportistas/<documento>/eliminar", methods=["POST"])
def eliminar_deportista(documento):
    # 1. Protección de seguridad
    if not is_admin():
        flash("No tienes permisos para eliminar registros.", "error")
        return redirect("/")

    documento_str = str(documento)
    users = load_users()
    deportistas = load_deportistas()
    inscripciones = load_inscripciones()

    # 2. Eliminar del perfil de deportistas
    if documento_str in deportistas:
        nombre_borrado = deportistas[documento_str].get("nombre", documento_str)
        del deportistas[documento_str]
        save_deportistas(deportistas)
    else:
        nombre_borrado = documento_str

    # 3. Eliminar de las credenciales de acceso (users.json)
    if documento_str in users:
        del users[documento_str]
        save_users(users)

    # 4. LIMPIEZA ADICIONAL: Eliminar inscripciones de este deportista
    # Evita que queden registros huérfanos en las competencias
    insc_a_eliminar = [id_i for id_i, i in inscripciones.items() 
                       if str(i.get("documento")) == documento_str]
    
    for id_i in insc_a_eliminar:
        del inscripciones[id_i]
    
    if insc_a_eliminar:
        save_inscripciones(inscripciones)

    flash(f"El deportista {nombre_borrado} y sus registros han sido eliminados.", "success")
    return redirect("/admin/deportistas")
#----------FIN ADMIN ELIMINA DEPORTISTA-----------------------




#=================TODAS LAS OPCIONES DE ADMIN=================

# ---------- PANEL ADMIN ----------
@app.route("/admin")
def admin():
    # 1. Verificación de seguridad centralizada
    if not is_admin():
        flash("Acceso restringido a administradores.", "error")
        return redirect("/login")

    # 2. Carga de datos para el resumen del Dashboard
    users = load_users()
    deportistas = load_deportistas()
    clubes = load_json("data/clubes_registro.json", {})
    competencias = load_competiciones()
    
    # 3. Preparamos estadísticas rápidas
    stats = {
        "total_usuarios": len(users),
        "total_deportistas": len(deportistas),
        "total_clubes": len(clubes),
        "total_competencias": len(competencias)
    }

    # 4. Obtenemos el rol exacto para la bienvenida
    rol_actual = user_role()

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        role=rol_actual
    )


# ==========================================
#          GESTIÓN DE NOTICIAS
# ==========================================

@app.route("/admin/noticias")
def admin_noticias():
    rol = user_role()
    if rol not in ["admin", "editor", "colaborador"]:
        flash("Acceso restringido.", "error")
        return redirect("/login")

    noticias_dict = load_json("data/noticias.json", {})
    # Convertimos a lista para que el template la recorra fácil
    noticias_lista = list(noticias_dict.values())

    try:
        # Ordenar: las más nuevas primero
        noticias_lista.sort(key=lambda x: str(x.get('id', '0')), reverse=True)
    except Exception as e:
        print(f"Error ordenando: {e}")

    return render_template("admin/noticias.html", noticias=noticias_lista, role=rol)

@app.route("/admin/noticias/crear", methods=["POST"])
def admin_noticias_crear_proceso():
    rol = user_role()
    if rol not in ["admin", "editor", "colaborador"]:
        return "No autorizado", 403

    title = request.form.get("title")
    content = request.form.get("content")
    image = request.files.get("image")
    
    filename = ""
    if image and image.filename != "":
        from werkzeug.utils import secure_filename
        filename = secure_filename(f"{int(time.time())}_{image.filename}")
        image.save(os.path.join(UPLOAD_NEWS, filename))

    noticias = load_json("data/noticias.json", {})
    nuevo_id = str(int(time.time()))
    
    noticias[nuevo_id] = {
        "id": nuevo_id,
        "title": title,
        "content": content,
        "image": filename,
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "updated_by": session.get("user", {}).get("username", "Admin")
    }
    
    save_json("data/noticias.json", noticias)
    flash("¡Noticia publicada con éxito!", "success")
    return redirect("/admin/noticias")

@app.route("/admin/noticias/editar/<news_id>", methods=["GET", "POST"])
def edit_news_form(news_id):
    rol = user_role()
    if rol not in ["admin", "editor", "colaborador"]:
        return redirect("/login")

    noticias = load_json("data/noticias.json", {})
    news_id_str = str(news_id)
    noticia = noticias.get(news_id_str)

    if not noticia:
        flash("La noticia no existe.", "error")
        return redirect("/admin/noticias")

    if request.method == "POST":
        try:
            noticia['title'] = request.form.get("title")
            noticia['content'] = request.form.get("content")
            noticia['updated_at'] = datetime.now().strftime("%d/%m/%Y %H:%M")
            noticia['updated_by'] = session.get("user", {}).get("username", "Admin")
            
            file = request.files.get("image")
            if file and file.filename != '':
                from werkzeug.utils import secure_filename
                filename = secure_filename(f"{int(time.time())}_{file.filename}")
                file.save(os.path.join(UPLOAD_NEWS, filename))
                noticia['image'] = filename

            noticias[news_id_str] = noticia
            save_json("data/noticias.json", noticias)
            flash("✅ Noticia actualizada correctamente.", "success")
            return redirect("/admin/noticias")
        except Exception as e:
            flash(f"Error al guardar: {e}", "error")
            return redirect("/admin/noticias")

    return render_template("admin/edit_news.html", noticia=noticia, news_id=news_id)

@app.route("/admin/noticias/eliminar/<news_id>")
def eliminar_noticia(news_id):
    rol = user_role()
    if rol not in ["admin", "editor"]:
        flash("No tienes permisos.", "error")
        return redirect("/login")

    noticias = load_json("data/noticias.json", {})
    news_id_str = str(news_id)

    if news_id_str in noticias:
        del noticias[news_id_str]
        save_json("data/noticias.json", noticias)
        flash("🗑️ Noticia eliminada.", "success")
    else:
        flash("Error: Noticia no encontrada.", "error")
        
    return redirect("/admin/noticias")


@app.route("/admin/hero")
def admin_hero():
    # 1. Validación estricta: Solo administradores pueden cambiar la portada
    if user_role() != "admin":
        flash("Acceso denegado. Solo administradores pueden modificar la portada del sitio.", "error")
        return redirect("/admin") # Te devuelve al dashboard

    # 2. Carga de banners/heroes
    # load_heroes() debería devolver la lista de imágenes y textos de la portada
    heroes_data = load_heroes()
    
    # Aseguramos que sea una lista para el bucle en el HTML
    lista_heroes = heroes_data if isinstance(heroes_data, list) else []

    # 3. Renderizado
    return render_template(
        "admin/hero.html",
        heroes=lista_heroes,
        role="admin"
    )


#----------PERMITIR ADMIN CREAR EL HERO------------------
@app.route("/admin/hero/create", methods=["POST"])
def create_hero():
    if "user" not in session or session["user"].get("rol") != "admin":
        return redirect("/login")

    heroes = load_heroes()
    new_id = str(int(datetime.now().timestamp()))

    image_name = ""
    file = request.files.get("image")
    if file and file.filename != "":
        filename = secure_filename(file.filename)
        filename = f"{new_id}_{filename}"
        path = os.path.join(UPLOAD_HERO, filename)
        file.save(path)
        image_name = filename

    heroes.append({
        "id": new_id,
        "title": request.form.get("title", ""),
        "subtitle": request.form.get("subtitle", ""),
        "text_color": request.form.get("text_color", "#ffffff"),
        "font_size": request.form.get("font_size", "45"),
        "text_align": request.form.get("text_align", "center"),
        "content_valign": request.form.get("content_valign", "center"),
        "image": image_name,
        "created_by": session["user"]["usuario"],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_by": session["user"]["usuario"],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    save_heroes(heroes)
    flash("✅ Banner creado", "success")
    return redirect("/admin/hero")
#------------------------------------------------------

#-------------EDITAR HERO--------------------------------
@app.route("/admin/hero/edit/<hero_id>", methods=["GET", "POST"])
def edit_hero(hero_id):
    # CORRECCIÓN: Usamos 'user' en session para validar acceso
    if "user" not in session or session["user"].get("rol") != "admin":
        flash("Acceso denegado. Solo administradores.", "error")
        return redirect("/login")

    heroes = load_heroes()
    # Buscamos el banner por ID
    hero = next((h for h in heroes if str(h["id"]) == str(hero_id)), None)

    if not hero:
        flash("Banner no encontrado", "error")
        return redirect("/admin/hero")

    if request.method == "POST":
        hero["title"] = request.form.get("title", "")
        hero["subtitle"] = request.form.get("subtitle", "")
        hero["text_color"] = request.form.get("text_color", "#ffffff")
        hero["font_size"] = request.form.get("font_size", "45")
        hero["text_align"] = request.form.get("text_align", "center")
        hero["content_valign"] = request.form.get("content_valign", "center")

        file = request.files.get("image")
        if file and file.filename != "":
            filename = secure_filename(file.filename)
            filename = f"edit_{hero_id}_{filename}"
            path = os.path.join(UPLOAD_HERO, filename)
            file.save(path)
            hero["image"] = filename

        hero["updated_by"] = session["user"]["usuario"]
        hero["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        save_heroes(heroes)
        flash("✅ Banner actualizado correctamente", "success")
        return redirect("/admin/hero")

    return render_template("admin/edit_hero.html", hero=hero)
#-------------------------------------------------------

#-----------------ADMIN BORRA EL HERO------------------
@app.route("/admin/hero/delete/<hero_id>")
def delete_hero(hero_id):
    if "user" not in session or session["user"].get("rol") != "admin":
        return redirect("/login")

    heroes = load_heroes()
    heroes = [h for h in heroes if str(h["id"]) != str(hero_id)]
    save_heroes(heroes)
    flash("🗑️ Banner eliminado", "info")
    return redirect("/admin/hero")
#--------------------------------------------------------

#----------------MOVER HERO ----------------------------
@app.route("/admin/hero/move/<hero_id>/<direction>")
def move_hero(hero_id, direction):
    if "user" not in session or session["user"].get("rol") != "admin":
        return redirect("/login")

    heroes = load_heroes()
    index = next((i for i, h in enumerate(heroes) if str(h["id"]) == str(hero_id)), None)

    if index is not None:
        if direction == "up" and index > 0:
            heroes[index], heroes[index - 1] = heroes[index - 1], heroes[index]
        elif direction == "down" and index < len(heroes) - 1:
            heroes[index], heroes[index + 1] = heroes[index + 1], heroes[index]
        
        save_heroes(heroes)
    
    return redirect("/admin/hero")
#---------------------------------------------------------

#------------PANEL CALENDARIO CARGADO POR EL ADMIN------------
@app.route("/admin/calendario", methods=["GET", "POST"])
def admin_calendario():
    if not is_admin(): # Usando tu helper is_admin
        return redirect("/login")

    file_path = os.path.join(UPLOAD_CALENDAR, "calendario.pdf")

    if request.method == "POST":
        # Acción: Eliminar
        if request.form.get("action") == "delete":
            if os.path.exists(file_path):
                os.remove(file_path)
                flash("Calendario eliminado correctamente", "info")
            return redirect("/admin/calendario")

        # Acción: Subir
        file = request.files.get("calendar")
        if file and file.filename.endswith('.pdf'):
            file.save(file_path)
            flash("Calendario PDF actualizado con éxito", "success")
        else:
            flash("Por favor sube un archivo PDF válido", "danger")
        return redirect("/admin/calendario")

    existe = os.path.exists(file_path)
    return render_template("admin/calendario.html", existe=existe, role=user_role())


#---------------CREAR USUARIOS Y ADMINISTRARLOS -----------------
@app.route("/admin/usuarios")
def admin_usuarios():
    if not es_super_admin():
        flash("No tienes permisos para esta sección", "danger")
        return redirect("/admin") # Mejor redirigir al panel admin que al login si ya está logueado

    users = load_users()
    usuarios_admin = {
        k: v for k, v in users.items() 
        if (v.get("rol") or v.get("role")) in ["admin", "editor", "colaborador"]
    }

    return render_template("admin/usuarios.html", users=usuarios_admin, role=user_role())

@app.route("/admin/usuarios/nuevo", methods=["GET", "POST"]) # Ruta clara para nuevos
@app.route("/admin/usuarios/editar/<username>", methods=["GET", "POST"])
def gestionar_usuario_admin(username=None):
    if not es_super_admin():
        flash("Acceso denegado", "danger")
        return redirect("/admin")

    users = load_users()
    user_data = users.get(username) if username else None

    if request.method == "POST":
        nuevo_username = request.form.get("username").strip().lower()
        nuevo_nombre = request.form.get("nombre").strip()
        nuevo_rol = request.form.get("rol")
        password = request.form.get("password")

        # Si es usuario nuevo y ya existe el nombre
        if not username and nuevo_username in users:
            flash("El nombre de usuario ya existe", "warning")
            return redirect("/admin/usuarios/nuevo")

        if not username: # CREAR
            users[nuevo_username] = {
                "usuario": nuevo_username,
                "nombre": nuevo_nombre,
                "rol": nuevo_rol,
                "password": generate_password_hash(password)
            }
        else: # EDITAR
            users[username]["nombre"] = nuevo_nombre
            users[username]["rol"] = nuevo_rol
            if password:
                users[username]["password"] = generate_password_hash(password)

        save_users(users)
        flash("Usuario guardado correctamente", "success")
        return redirect("/admin/usuarios")

    return render_template("admin/usuario_form.html", user_data=user_data, editando=bool(username))
#----------------------------------------------------------------------

#---------------CARGAR RESULTADOS DE EVENTOS-------------------------
@app.route("/admin/resultados", methods=["GET", "POST"])
def admin_resultados():
    if not is_admin(): 
        return redirect("/login")
    
    competiciones = load_competiciones()
    
    if request.method == "POST":
        id_evento = request.form.get("evento_id")
        archivos = request.files.getlist("archivo_resultado")
        
        # Validación: ¿Existe el evento en nuestro JSON?
        if id_evento and id_evento in competiciones:
            nombres_guardados = []
            for file in archivos:
                if file and file.filename != '':
                    # Limpiamos el nombre del archivo
                    filename = secure_filename(f"res_{id_evento}_{file.filename}")
                    # Asegúrate de que UPLOAD_RESULTADOS esté definida como ruta
                    file.save(os.path.join(UPLOAD_RESULTADOS, filename))
                    nombres_guardados.append(filename)
            
            if nombres_guardados:
                # Si no existe la lista en el JSON, la creamos
                if "resultados_lista" not in competiciones[id_evento]:
                    competiciones[id_evento]["resultados_lista"] = []
                
                competiciones[id_evento]["resultados_lista"].extend(nombres_guardados)
                
                # Mantenemos el campo antiguo para que la web pública no se rompa
                competiciones[id_evento]["resultado_pdf"] = competiciones[id_evento]["resultados_lista"][0]
                
                save_competiciones(competiciones)
                flash(f"✅ Se han publicado {len(nombres_guardados)} archivos.", "success")
        else:
            flash("❌ Error: El evento seleccionado no es válido.", "danger")
            
        return redirect("/admin/resultados")

    return render_template("admin/resultados.html", competiciones=competiciones)

@app.route("/admin/resultados/eliminar/<evento_id>/<filename>")
def eliminar_resultado(evento_id, filename):
    if not is_admin(): # O tu función de validación de rol
        return redirect("/login")
    
    competiciones = load_competiciones()
    
    if evento_id in competiciones and "resultados_lista" in competiciones[evento_id]:
        # 1. Intentar borrar el archivo físico de la carpeta
        try:
            file_path = os.path.join(UPLOAD_RESULTADOS, filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Error al borrar archivo físico: {e}")

        # 2. Quitar el nombre de la lista en el JSON
        if filename in competiciones[evento_id]["resultados_lista"]:
            competiciones[evento_id]["resultados_lista"].remove(filename)
            
            # Si borramos el que estaba como 'resultado_pdf', actualizamos ese campo también
            if competiciones[evento_id].get("resultado_pdf") == filename:
                competiciones[evento_id]["resultado_pdf"] = competiciones[evento_id]["resultados_lista"][0] if competiciones[evento_id]["resultados_lista"] else ""
            
            save_competiciones(competiciones)
            flash(f"✅ Archivo '{filename}' eliminado correctamente.", "success")
        
    return redirect("/admin/resultados")


# UNIFICADO: Listado de resultados con filtro de años
@app.route("/resultados")
@app.route("/resultados/<int:year>")
def lista_resultados_anual(year=None):
    competiciones = load_competiciones()
    
    # 1. Obtener todos los años disponibles que tienen resultados
    años_disponibles = sorted(list(set(
        v['fecha_evento'][:4] for v in competiciones.values() 
        if (v.get("resultado_pdf") or v.get("resultados_lista")) and v.get('fecha_evento')
    )), reverse=True)

    # 2. Si el usuario NO ha seleccionado un año, mostramos el menú de carpetas
    if year is None:
        return render_template("public/resultados_años.html", años=años_disponibles)

    # 3. Si seleccionó un año, filtramos y mostramos los eventos de ese año
    eventos_filtrados = {
        k: v for k, v in competiciones.items() 
        if (v.get("resultado_pdf") or v.get("resultados_lista")) 
        and v.get("fecha_evento", "").startswith(str(year))
    }

    eventos_ordenados = dict(sorted(
        eventos_filtrados.items(), 
        key=lambda x: x[1]['fecha_evento'], 
        reverse=True
    ))

    return render_template("public/resultados_lista.html", 
                           eventos=eventos_ordenados, 
                           año_actual=year)
#------------------------------------------------------------------------

# 2. Detalle de un evento específico
@app.route("/resultados/evento/<evento_id>")
def detalle_resultado(evento_id):
    competiciones = load_competiciones()
    evento = competiciones.get(evento_id)
    
    if not evento:
        flash("Evento no encontrado", "danger")
        return redirect("/resultados")
        
    return render_template("public/resultado_detalle.html", evento=evento)
#-------------------------------------------------------------------



UPLOAD_INFO_GENERAL = "static/uploads/info_general"
os.makedirs(UPLOAD_INFO_GENERAL, exist_ok=True)


# --- INFO GENERAL (Permitir Admin y Editor) ---
@app.route("/admin/info-general")
def admin_info_general():
    # Cambiamos require_role(["admin"]) por una lista que incluya al editor
    if not require_role(["admin", "editor"]): 
        return redirect("/login")

    info = load_json("data/info_general.json", {})
    return render_template("admin/info_general.html", info=info)

@app.route("/admin/info-general/nuevo", methods=["GET", "POST"])
def nuevo_info_general():
    # Esta versión permite a ambos, corrigiendo el problema del editor
    if not require_role(["admin", "editor"]):
        return redirect("/login")

    info = load_json("data/info_general.json", {})

    if request.method == "POST":
        item_id = str(len(info) + 1)
        archivo = request.files.get("archivo")
        filename = ""

        if archivo and archivo.filename.endswith(".pdf"):
            filename = secure_filename(archivo.filename)
            # Usamos la variable global de ruta que definiste arriba
            archivo.save(os.path.join(UPLOAD_INFO_GENERAL, filename))

        info[item_id] = {
            "id": item_id,
            "titulo": request.form["titulo"],
            "archivo": filename,
            "created_at": now()
        }

        save_json("data/info_general.json", info)
        flash("✅ Información general actualizada correctamente", "success")
        return redirect("/admin/info-general")

    return render_template("admin/info_general_form.html")



#--------------BASE DE DATOS DEPORTISTAS---------------------
@app.route("/admin/deportistas")
def admin_deportistas():
    # RESTRICCIÓN: Solo Admin y Editor pueden ver esta base de datos
    if "user" not in session or session["user"]["rol"] not in ["admin", "editor"]:
        flash("No tienes permiso para acceder a la base de datos de deportistas.", "danger")
        return redirect("/admin/inicio")

    # Limpiar filtros si se solicita
    if request.args.get("limpiar"):
        return redirect(url_for("admin_deportistas"))

    deportistas = load_json("data/deportistas.json", {})
    clubes = load_json("data/clubes_registro.json", {})
    
    hoy_str = date.today().strftime("%Y-%m-%d")
    corte = fecha_corte(hoy_str)

    # Captura de filtros
    q = request.args.get("q", "").lower().strip()
    club_f = request.args.get("club", "")
    mod_f = request.args.get("modalidad", "")
    cat_f = request.args.get("categoria", "")

    lista_deportistas = []

    for d_id, d in deportistas.items():
        # Calcular categoría en tiempo real
        edad = calcular_edad(d.get("fecha_nacimiento", ""), corte)
        cat = obtener_categoria(edad, d.get("modalidad", ""))
        d["categoria"] = cat
        d["club_nombre"] = clubes.get(str(d.get("club_id")), {}).get("nombre", "Sin Club")
        d["id"] = d_id 

        # Filtros
        if q and (q not in d.get("documento", "").lower() and q not in d.get("nombre", "").lower()):
            continue
        if club_f and str(d.get("club_id")) != club_f:
            continue
        if mod_f and d.get("modalidad") != mod_f:
            continue
        if cat_f and d.get("categoria") != cat_f:
            continue

        lista_deportistas.append(d)

    # Opciones dinámicas para los filtros basadas en deportistas cargados
    opciones = {
        "modalidades": sorted(list(set(d.get("modalidad") for d in deportistas.values() if d.get("modalidad")))),
        "categorias": sorted(list(set(d.get("categoria") for d in lista_deportistas if d.get("categoria"))))
    }

    return render_template(
        "admin/deportistas.html",
        deportistas=lista_deportistas,
        clubes=clubes,
        opciones=opciones,
        filtros=request.args
    )

@app.route("/admin/deportistas/exportar")
def exportar_deportistas():
    if "user" not in session or session["user"]["rol"] not in ["admin", "editor"]:
        return redirect("/login")

    deportistas = load_json("data/deportistas.json", {})
    clubes = load_json("data/clubes_registro.json", {})
    corte = fecha_corte(date.today().strftime("%Y-%m-%d"))

    q = request.args.get("q", "").lower().strip()
    club_f = request.args.get("club", "")
    categoria_f = request.args.get("categoria", "")

    data_exportar = []
    for d in deportistas.values():
        # Calcular categoría para el reporte
        edad = calcular_edad(d.get("fecha_nacimiento", ""), corte)
        cat = obtener_categoria(edad, d.get("modalidad", ""))
        
        club_nombre = clubes.get(str(d.get("club_id")), {}).get("nombre", "Sin Club")
        
        # Filtros
        if q and (q not in d.get("documento", "").lower() and q not in d.get("nombre", "").lower()): continue
        if club_f and str(d.get("club_id")) != club_f: continue
        if categoria_f and cat != categoria_f: continue

        data_exportar.append({
            "Documento": d.get("documento"),
            "Nombre": d.get("nombre"),
            "Fecha Nacimiento": d.get("fecha_nacimiento"),
            "Edad (a corte)": edad,
            "Sexo": d.get("sexo"),
            "Modalidad": d.get("modalidad"),
            "Categoría": cat,
            "Club": club_nombre,
            "Teléfono": d.get("telefono"),
            "Correo": d.get("correo"),
            "Acudiente": d.get("acudiente_nombre"),
            "Tel. Acudiente": d.get("acudiente_telefono")
        })

    df = pd.DataFrame(data_exportar)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Deportistas')
    output.seek(0)

    return send_file(output, 
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, 
                     download_name=f"reporte_deportistas_{datetime.now().strftime('%Y%m%d')}.xlsx")

@app.route("/admin/deportistas/<documento>")
def admin_ficha_deportista(documento):
    if "user" not in session or session["user"]["rol"] not in ["admin", "editor"]:
        return redirect("/login")

    deportistas = load_json("data/deportistas.json", {})
    clubes = load_json("data/clubes_registro.json", {})

    if documento not in deportistas:
        flash("Deportista no encontrado", "danger")
        return redirect("/admin/deportistas")

    d = deportistas[documento]
    
    # Calcular categoría para la ficha
    corte = fecha_corte(date.today().strftime("%Y-%m-%d"))
    edad = calcular_edad(d.get("fecha_nacimiento", ""), corte)
    d["categoria"] = obtener_categoria(edad, d.get("modalidad", ""))
    
    club = clubes.get(str(d.get("club_id")), {})
    d["club_nombre"] = club.get("nombre", "—")

    return render_template("admin/deportista_ficha.html", deportista=d, clubes=clubes)

@app.route("/admin/deportistas/<documento>/editar", methods=["POST"])
def admin_editar_deportista(documento):
    if "user" not in session or session["user"]["rol"] not in ["admin", "editor"]:
        return redirect("/login")

    deportistas = load_json("data/deportistas.json", {})

    if documento not in deportistas:
        flash("Deportista no encontrado", "danger")
        return redirect("/admin/deportistas")

    d = deportistas[documento]

    # Usamos d.get('campo') como valor por defecto si el formulario envía algo vacío
    d["nombre"] = request.form.get("nombre") or d.get("nombre")
    d["fecha_nacimiento"] = request.form.get("fecha_nacimiento") or d.get("fecha_nacimiento")
    d["sexo"] = request.form.get("sexo") or d.get("sexo")
    d["modalidad"] = request.form.get("modalidad") or d.get("modalidad")
    
    # Manejo especial para números (club_id)
    new_club_id = request.form.get("club_id")
    if new_club_id:
        d["club_id"] = int(new_club_id)

    d["telefono"] = request.form.get("telefono") or d.get("telefono", "")
    d["correo"] = request.form.get("correo") or d.get("correo", "")
    d["acudiente_nombre"] = request.form.get("acudiente_nombre") or d.get("acudiente_nombre", "")
    d["acudiente_telefono"] = request.form.get("acudiente_telefono") or d.get("acudiente_telefono", "")

    save_json("data/deportistas.json", deportistas)
    flash("Datos actualizados correctamente sin borrar campos anteriores", "success")
    
    return redirect(f"/admin/deportistas/{documento}")
#---------------------------------------------------------------




#---------CREAR BASE DE DATOS CLUBES y USER CLUB-------------
@app.route("/admin/clubes-registro", methods=["GET", "POST"])
def admin_clubes_registro():
    if "user" not in session or session["user"]["rol"] != "admin":
        return redirect("/login")

    clubes = load_json("data/clubes_registro.json", {})
    users = load_users()
    error = None

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        afiliado = request.form.get("afiliado") == "1"

        if not nombre:
            error = "El nombre del club es obligatorio"
        else:
            for c in clubes.values():
                if c["nombre"].lower() == nombre.lower():
                    error = "Ya existe un club con ese nombre"
                    break

        if not error:
            club_id = str(int(time.time()))
            username = nombre.lower().replace(" ", "")

            clubes[club_id] = {
                "id": club_id,
                "nombre": nombre,
                "afiliado": afiliado,
                "usuario": username,
                "activo": True
            }
            save_json("data/clubes_registro.json", clubes)

            # Crear usuario para el club si no existe
            if username not in users:
                users[username] = {
                    "password": generate_password_hash(username), # Password inicial es el mismo username
                    "rol": "club", # Aseguramos consistencia con 'rol'
                    "club_id": club_id
                }
                save_users(users)
            return redirect("/admin/clubes-registro")

    clubes_ordenados = sorted(
        clubes.values(),
        key=lambda c: (not c.get("afiliado", False), c["nombre"].lower())
    )
    return render_template("admin/clubes_registro.html", clubes=clubes_ordenados, error=error)


#--------------------------------------------------------

#--------- CLUB VER DEPORTISTAS -------------------
@app.route("/club/deportistas")
def club_deportistas():
    if "user" not in session or session["user"]["rol"] != "club":
        return redirect("/login")

    club_id = session["user"]["club_id"]
    deportistas = load_json("data/deportistas.json", {})
    
    # Fecha de corte temporada actual
    corte = fecha_corte(date.today().strftime("%Y-%m-%d"))
    
    lista = []
    for d in deportistas.values():
        if str(d.get("club_id")) != str(club_id):
            continue

        # Cálculo de edad y categoría al vuelo
        edad = calcular_edad(d.get("fecha_nacimiento", ""), corte)
        categoria = obtener_categoria(edad, d.get("modalidad", ""))
        
        d["edad"] = edad
        d["categoria"] = categoria

        # Filtros de búsqueda
        q = request.args.get("q", "").lower()
        if q and q not in d["nombre"].lower() and q not in d["documento"]:
            continue

        lista.append(d)

    return render_template("club/deportistas.html", deportistas=lista)

#---------ISNCRIPCION MASIVA A COMPETENCIAS --------
@app.route("/club/competencias/<comp_id>/inscribir", methods=["GET", "POST"])
def club_inscribir_competencia(comp_id):
    if not require_club(): return redirect("/login")

    club_id = session["user"]["club_id"]
    competencias = load_json("data/competiciones.json", {})
    deportistas = load_json("data/deportistas.json", {})
    inscripciones = load_json("data/inscripciones.json", {})
    clubes = load_json("data/clubes_registro.json", {})

    competencia = competencias.get(comp_id)
    club = clubes.get(str(club_id), {})
    
    # Fecha corte del evento para categoría exacta
    corte_evento = fecha_corte(competencia.get("fecha_evento"))

    if request.method == "POST":
        documentos = request.form.getlist("documentos")
        
        for doc in documentos:
            if doc not in deportistas: continue
            
            # Evitar duplicados en el mismo evento
            ya_inscrito = any(i for i in inscripciones.values() 
                             if i["competencia_id"] == comp_id and i["documento"] == doc)
            if ya_inscrito: continue

            d = deportistas[doc]
            edad_evento = calcular_edad(d["fecha_nacimiento"], corte_evento)
            cat_evento = obtener_categoria(edad_evento, d["modalidad"])
            
            insc_id = str(int(time.time()) + len(inscripciones))

            inscripciones[insc_id] = {
                "id": insc_id,
                "competencia_id": comp_id,
                "nombre_evento": competencia.get("nombre"),
                "documento": doc,
                "nombre": d["nombre"],
                "sexo": d["sexo"],
                "modalidad": d["modalidad"],
                "categoria": cat_evento, # Se guarda la categoría calculada
                "club_id": club_id,
                "club": club.get("nombre"), # Nombre para el Admin
                "estado_pago": "pendiente",
                "valor": competencia.get("valor", 0)
            }

        save_json("data/inscripciones.json", inscripciones)
        return redirect("/club/inscripciones")

    deportistas_club = [d for d in deportistas.values() if str(d.get("club_id")) == str(club_id)]
    return render_template("club/inscripcion_masiva.html", competencia=competencia, deportistas=deportistas_club)

#--------------------------------------------------

#---------CLUB EDITA DATOS BASICOS DEL DEPORTISTA----------
@app.route("/club/deportistas/editar/<documento>", methods=["GET", "POST"])
def editar_deportista_club(documento):
    if not require_club(): return redirect("/login")

    deportistas = load_json("data/deportistas.json", {})
    d = deportistas.get(documento)

    if not d or str(d.get("club_id")) != str(session["user"]["club_id"]):
        return "No autorizado", 403

    if request.method == "POST":
        # Mantiene el dato anterior si el input llega vacío
        d["nombre"] = request.form.get("nombre") or d.get("nombre")
        d["fecha_nacimiento"] = request.form.get("fecha_nacimiento") or d.get("fecha_nacimiento")
        d["telefono"] = request.form.get("telefono") or d.get("telefono")
        d["correo"] = request.form.get("correo") or d.get("correo")
        d["sexo"] = request.form.get("sexo") or d.get("sexo")

        save_json("data/deportistas.json", deportistas)
        flash("Datos actualizados", "success")
        return redirect("/club/deportistas")

    return render_template("club/editar_deportista.html", d=d)
#-------------------------------------------------------------

#---------------EDITAR CLUBES DE BASE DE DATOS-------------
@app.route("/admin/clubes-registro/editar/<club_id>", methods=["GET", "POST"])
def editar_club_registro(club_id):
    # Verificación de seguridad (solo Admin)
    if "user" not in session or session["user"]["rol"] != "admin":
        return redirect("/login")

    clubes = load_json("data/clubes_registro.json", {})
    club = clubes.get(club_id)

    if not club:
        flash("Club no encontrado", "danger")
        return redirect("/admin/clubes-registro")

    error = None

    if request.method == "POST":
        # Capturamos datos del formulario
        nuevo_nombre = request.form.get("nombre", "").strip()
        # El estado 'afiliado' es un checkbox o select, si no viene marcamos lo que estaba o False
        afiliado = request.form.get("afiliado") == "1"

        # 1. VALIDAR DUPLICADO (Solo si el nombre cambió)
        if nuevo_nombre and nuevo_nombre.lower() != club["nombre"].lower():
            for cid, c in clubes.items():
                if cid != club_id and c["nombre"].lower() == nuevo_nombre.lower():
                    error = "Ya existe otro club con ese nombre"
                    break

        # 2. GUARDAR CAMBIOS (Protección contra vacíos)
        if not error:
            # Si nuevo_nombre está vacío (y no es requerido en HTML), mantenemos el anterior
            club["nombre"] = nuevo_nombre or club["nombre"]
            club["afiliado"] = afiliado
            
            # Nota: El 'usuario' y el 'id' normalmente no se editan para no romper 
            # el login del club ni las referencias de los deportistas.
            
            save_json("data/clubes_registro.json", clubes)
            flash(f"Club '{club['nombre']}' actualizado correctamente", "success")
            return redirect("/admin/clubes-registro")

    return render_template(
        "admin/editar_club_registro.html",
        club=club,
        error=error
    )
#-------------------------------------------------------

#-------------ELIMINAR CLUB DE BASE DE DATOS-------------
@app.route("/admin/clubes-registro/eliminar/<club_id>")
def eliminar_club_registro(club_id):
    # Seguridad: Solo el administrador principal puede borrar clubes
    if "user" not in session or session["user"]["rol"] != "admin":
        return redirect("/login")

    clubes = load_json("data/clubes_registro.json", {})
    
    if club_id in clubes:
        # 1. Obtener el nombre de usuario antes de borrar el club
        # Esto es para poder borrar sus credenciales de login también
        username_a_borrar = clubes[club_id].get("usuario")
        nombre_club = clubes[club_id].get("nombre")

        # 2. Eliminar el club de la lista de clubes
        del clubes[club_id]
        save_json("data/clubes_registro.json", clubes)

        # 3. Eliminar el usuario del archivo de logins (users.json)
        # Así el club ya no podrá entrar al sistema
        users = load_users()
        if username_a_borrar in users:
            del users[username_a_borrar]
            save_users(users)

        flash(f"El club '{nombre_club}' y su acceso han sido eliminados.", "success")
    else:
        flash("El club no existe o ya fue eliminado.", "warning")

    return redirect("/admin/clubes-registro")
#-----------------------------------------------------------------------

#---------- CLUB VE SUS EVENTOS INSCRITOS ---------------------
@app.route("/club/inscripciones")
def club_inscripciones_eventos():
    if "user" not in session or session["user"].get("rol") != "club":
        return redirect("/login")

    club_id_session = str(session["user"].get("club_id", "")).strip()
    
    # Cargamos archivos asegurando el nombre correcto
    inscripciones = load_json("data/inscripciones.json", {})
    competencias = load_json("data/competiciones.json", {}) # Unificado a competiciones.json

    eventos = {}

    for i in inscripciones.values():
        # Validamos que la inscripción pertenezca al club de la sesión
        if str(i.get("club_id", "")).strip() == club_id_session:
            cid = str(i.get("competencia_id", "")).strip()
            
            # Si el evento no está en nuestro diccionario, lo preparamos
            if cid not in eventos:
                comp_data = competencias.get(cid)
                
                # Si la competencia no existe en el JSON, creamos un placeholder para evitar Error 500
                nombre_ev = comp_data.get("nombre", "Evento Desconocido") if comp_data else f"ID: {cid} (No hallado)"
                
                eventos[cid] = {
                    "evento": {"nombre": nombre_ev},
                    "total": 0,
                    "valor": 0
                }

            # Sumatoria ágil
            eventos[cid]["total"] += 1
            try:
                eventos[cid]["valor"] += float(i.get("valor", 0))
            except (ValueError, TypeError):
                pass 

    return render_template("club/inscripciones_eventos.html", eventos=eventos)

#------------ VER DETALLE EVENTO -----------------------
@app.route("/club/inscripciones/detalle/<cid>")
def club_inscripciones_por_evento(cid):
    if "user" not in session or session["user"].get("rol") != "club":
        return redirect("/login")

    club_id = str(session["user"].get("club_id", "")).strip()
    cid_str = str(cid).strip()
    
    # Captura de filtros
    f_cat = request.args.get("categoria", "")
    f_mod = request.args.get("modalidad", "")
    f_sex = request.args.get("sexo", "")
    f_est = request.args.get("estado", "") # Aquí entrarán: pendiente, pagado, rechazado
    q_search = request.args.get("q", "").lower().strip()
    
    inscripciones = load_json("data/inscripciones.json", {})
    competencias = load_json("data/competiciones.json", {})
    db_deportistas = load_json("data/deportistas.json", {})

    competencia = competencias.get(cid_str, {"nombre": "Evento Desconocido", "id": cid_str})
    listado_final = []
    
    cats, mods, sexs = set(), set(), set()
    total_dinero_filtrado = 0

    for i in inscripciones.values():
        if str(i.get("club_id", "")).strip() == club_id and str(i.get("competencia_id", "")).strip() == cid_str:
            
            dep_id = str(i.get("deportista_id", ""))
            info_dep = db_deportistas.get(dep_id, {})

            # Normalización de datos para visualización
            sexo_valor = i.get("rama") or i.get("sexo") or info_dep.get("sexo") or info_dep.get("rama") or "N/A"
            nombre = (i.get("nombre") or info_dep.get("nombre", "N/A")).strip()
            documento = str(i.get("documento") or info_dep.get("documento", "N/A")).strip()
            categoria = i.get("categoria") or info_dep.get("categoria", "N/A")
            modalidad = i.get("modalidad") or info_dep.get("modalidad") or "N/A"
            estado = i.get("estado_pago", "pendiente").lower() # Definido por Admin

            # Alimentar selectores
            cats.add(categoria); mods.add(modalidad); sexs.add(sexo_valor)

            # Aplicación de filtros Excel-Style
            if f_cat and categoria != f_cat: continue
            if f_mod and modalidad != f_mod: continue
            if f_sex and sexo_valor != f_sex: continue
            if f_est and estado != f_est: continue
            if q_search and (q_search not in nombre.lower() and q_search not in documento.lower()):
                continue

            valor_ins = 0
            try: valor_ins = float(i.get("valor", 0))
            except: pass
            
            total_dinero_filtrado += valor_ins

            listado_final.append({
                "id": i.get("id"), "nombre": nombre, "documento": documento,
                "categoria": categoria, "modalidad": modalidad, 
                "sexo": sexo_valor, "estado_pago": estado, "valor": valor_ins
            })

    return render_template(
        "club/inscripciones.html", 
        inscripciones=listado_final, 
        competencia=competencia,
        total_dinero=total_dinero_filtrado,
        filtros_data={
            "cats": sorted(list(cats)), "mods": sorted(list(mods)), "sexs": sorted(list(sexs)),
            "activos": {"cat": f_cat, "mod": f_mod, "sex": f_sex, "est": f_est, "q": q_search}
        }
    )
#------------ RESUMEN ECONÓMICO PARA CLUB -----------
@app.route("/club/resumen")
def club_resumen():
    try:
        if "user" not in session or session["user"].get("rol") != "club":
            return redirect("/login")

        club_id = str(session["user"].get("club_id", "")).strip()
        inscripciones = load_json("data/inscripciones.json", {})

        total_pagado = 0.0
        total_pendiente = 0.0
        conteo_inscritos = 0

        for i in inscripciones.values():
            if str(i.get("club_id", "")).strip() == club_id:
                conteo_inscritos += 1
                try:
                    valor = float(i.get("valor", 0))
                except (ValueError, TypeError):
                    valor = 0.0
                
                if i.get("estado_pago") == "pagado":
                    total_pagado += valor
                else:
                    total_pendiente += valor

        return render_template(
            "club/resumen.html",
            total=conteo_inscritos,
            total_pagado=total_pagado,
            total_pendiente=total_pendiente,
            total_general=total_pagado + total_pendiente
        )
    except Exception as e:
        print(f"Error crítico en resumen: {e}")
        flash("No se pudo cargar el resumen económico.", "danger")
        return redirect("/club")
#---------------------------------------------------------

#---------CLUB ELIMINA DEPORTISTA DE UN EVENTO----------------
@app.route("/club/inscripciones/eliminar/<insc_id>")
def eliminar_inscripcion_club(insc_id):
    # 1. Verificación de identidad y rol
    if "user" not in session or session["user"].get("rol") != "club":
        flash("Sesión no válida o expirada.", "danger")
        return redirect("/login")

    try:
        # 2. Normalización de IDs
        club_id_sesion = str(session["user"].get("club_id", "")).strip()
        id_a_borrar = str(insc_id).strip()
        
        inscripciones = load_json("data/inscripciones.json", {})
        insc = inscripciones.get(id_a_borrar)

        # 3. Validación de existencia
        if not insc:
            flash("La inscripción no existe o ya fue eliminada.", "warning")
            return redirect("/club/inscripciones")
            
        # 4. VALIDACIÓN DE PROPIEDAD (Seguridad crítica)
        # Solo permitimos borrar si el club_id coincide con el de la sesión
        if str(insc.get("club_id", "")).strip() != club_id_sesion:
            flash("⚠️ No tienes permiso para eliminar esta inscripción.", "danger")
            return redirect("/club/inscripciones")

        # 5. PROCESO DE ELIMINACIÓN (Sin restricción de pago)
        nombre_deportista = insc.get("nombre", "Deportista")
        id_evento = insc.get("competencia_id")
        
        # Eliminamos del diccionario
        if id_a_borrar in inscripciones:
            del inscripciones[id_a_borrar]
            # Guardamos los cambios en el archivo
            save_json("data/inscripciones.json", inscripciones)
            flash(f"✅ Se ha eliminado la inscripción de {nombre_deportista} correctamente.", "success")
        
        # 6. Redirección inteligente al detalle del evento
        if id_evento:
            return redirect(f"/club/inscripciones/detalle/{id_evento}")
        
        return redirect("/club/inscripciones")

    except Exception as e:
        print(f"Error al eliminar inscripción: {e}")
        flash("Hubo un error técnico al procesar la eliminación.", "danger")
        return redirect("/club/inscripciones")
#-------------------------------------------------------------


#--------- LOGIN DE USUARIOS ---------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u_input = request.form.get("username", "").strip().lower() # Normalizamos entrada
        p_input = request.form.get("password", "")
        
        users = load_users()
        deportistas = load_deportistas()
        clubes_reg = load_json("data/clubes_registro.json", {})
        
        target_user = None

        # 1. Identificar usuario y asignar rol
        if u_input in users:
            target_user = users[u_input]
            if "rol" not in target_user: target_user["rol"] = "club"
        elif u_input in deportistas:
            target_user = deportistas[u_input]
            if "rol" not in target_user: target_user["rol"] = "deportista"

        if target_user:
            if check_password_hash(target_user.get("password"), p_input):
                session.permanent = True
                cid = None
                rol = target_user.get("rol")

                if rol == "club":
                    print(f"\n--- BUSCANDO CLUB PARA: '{u_input}' ---")
                    for id_c, datos_c in clubes_reg.items():
                        # Extraemos el usuario del JSON limpiándolo de espacios
                        u_json = str(datos_c.get("usuario", "")).strip().lower()
                        print(f"Comparando con: '{u_json}' (ID: {id_c})")
                        
                        if u_json == u_input:
                            cid = id_c
                            print(f"✅ ¡ENCONTRADO! ID asignado: {cid}")
                            break
                    
                    if not cid:
                        print(f"❌ ERROR: El usuario '{u_input}' no coincide con ningún 'usuario' en clubes_registro.json")
                        flash("Tu cuenta no tiene un ID de club vinculado. Contacta al admin.", "danger")
                        return render_template("login.html")
                
                session["user"] = {
                    "usuario": u_input,
                    "rol": rol,
                    "club_id": str(cid) if cid else None 
                }
                
                flash(f"¡Bienvenido/a {u_input}!", "success")
                if rol == "admin": return redirect("/admin")
                elif rol == "club": return redirect("/club")
                else: return redirect("/perfil")
            else:
                flash("Contraseña incorrecta.", "danger")
        else:
            flash("El usuario no existe.", "danger")
            
    return render_template("login.html")
#----------------------------------------------------------

#-----------RUTA CLUB DASHBOARD -----------------
@app.route("/club")
def club_home():
    # 1. Verificación de seguridad
    if "user" not in session or session["user"].get("rol") != "club":
        flash("Acceso denegado.", "danger")
        return redirect("/login")

    # 2. Obtener club_id de forma segura
    # Usamos .get() para evitar que el programa se cierre si no existe la llave
    club_id = session["user"].get("club_id")

    if not club_id:
        flash("Error: No se encontró el ID de tu club en la sesión. Reintenta el ingreso.", "warning")
        return redirect("/login")

    # 3. Carga de datos
    clubes = load_json("data/clubes_registro.json", {})
    deportistas = load_json("data/deportistas.json", {})
    inscripciones = load_json("data/inscripciones.json", {})

    # Obtener datos del club actual
    club = clubes.get(str(club_id), {})
    nombre_club = club.get("nombre", "Club")
    es_afiliado = club.get("afiliado", False)

    # Filtrar datos usando el ID asegurado como string
    str_cid = str(club_id)
    
    deportistas_club = [
        d for d in deportistas.values()
        if str(d.get("club_id")) == str_cid
    ]

    inscripciones_club = [
        i for i in inscripciones.values()
        if str(i.get("club_id")) == str_cid
    ]
    
    pagadas = len([i for i in inscripciones_club if i.get("estado_pago") == "pagado"])
    pendientes = len(inscripciones_club) - pagadas

    return render_template(
        "club/dashboard.html",
        nombre_club=nombre_club,
        afiliado=es_afiliado,
        total_deportistas=len(deportistas_club),
        total_inscripciones=len(inscripciones_club),
        inscripciones_pagadas=pagadas,
        inscripciones_pendientes=pendientes
    )
#---------------------------------------------------




#--------- SELECCION DE EVENTO PARA INSCRIPCIÓN --------------
@app.route("/club/deportistas/inscribir", methods=["POST"])
def seleccionar_evento_inscripcion():
    # Verificación de rol 'club'
    if "user" not in session or session["user"]["rol"] != "club":
        return redirect("/login")

    # Capturamos los documentos seleccionados en el checklist anterior
    documentos = request.form.getlist("documentos")
    
    # Si el club no seleccionó a nadie, lo devolvemos con un aviso
    if not documentos:
        flash("Debes seleccionar al menos un deportista", "warning")
        return redirect("/club/deportistas")

    competencias = load_json("data/competiciones.json", {})
    hoy = date.today()
    eventos_abiertos = []

    # Filtrar eventos que aún no han ocurrido
    for c in competencias.values():
        fecha_str = c.get("fecha_evento")
        if not fecha_str:
            continue
            
        try:
            # Intentamos procesar ambos formatos de fecha posibles
            if "-" in fecha_str:
                fecha_dt = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            else:
                fecha_dt = datetime.strptime(fecha_str, "%d/%m/%Y").date()
            
            # Solo agregamos si el evento es hoy o en el futuro
            if fecha_dt >= hoy:
                eventos_abiertos.append(c)
        except Exception as e:
            print(f"Error procesando fecha del evento {c.get('id')}: {e}")
            continue

    # Ordenar los eventos por fecha para que el más cercano aparezca primero
    eventos_abiertos.sort(key=lambda x: x.get("fecha_evento", ""))

    return render_template(
        "club/seleccionar_evento.html",
        documentos=documentos,
        eventos=eventos_abiertos
    )
#-------------------------------------------------------------





#---------------FICHA DEPORTISTA DESDE CLUB------------------
@app.route("/club/deportistas/<documento>")
def ficha_deportista(documento):

    if not require_club():
        return redirect("/login")

    deportistas = load_json("data/deportistas.json", {})
    d = deportistas.get(documento)

    if not d:
        return "No encontrado", 404

    return render_template(
        "club/ficha_deportista.html",
        d=d
    )
#---------------------------------------------------------------
#--------------DETALLE EVENTO--------------------------------
@app.route("/club/inscripciones/<comp_id>")
def detalle_evento_club(comp_id):

    if not require_club():
        return redirect("/login")

    club_id = session["user"]["club_id"]

    inscripciones = load_json("data/inscripciones.json", {})
    competencias = load_json("data/competiciones.json", {})

    lista = [
        i for i in inscripciones.values()
        if i["competencia_id"] == comp_id
        and str(i.get("club_id")) == str(club_id)
    ]

    return render_template(
        "club/detalle_evento.html",
        evento=competencias.get(comp_id),
        inscripciones=lista
    )
#------------------------------------------------------------------
#---------------INSCRIPCION MASIVA (PASO FINAL) -------------------
@app.route("/club/inscripcion-masiva/confirmar", methods=["POST"])
def confirmar_inscripcion_masiva():
    if "user" not in session or session["user"]["rol"] != "club":
        return redirect("/login")

    club_id = str(session["user"]["club_id"])

    # Capturamos datos del formulario anterior
    documentos = request.form.getlist("documentos")
    comp_id = request.form.get("competencia_id")

    if not documentos or not comp_id:
        flash("Datos incompletos para la inscripción", "danger")
        return redirect("/club/deportistas")

    # Cargar bases de datos
    deportistas = load_json("data/deportistas.json", {})
    inscripciones = load_json("data/inscripciones.json", {})
    competencias = load_json("data/competiciones.json", {})
    clubes = load_json("data/clubes_registro.json", {})

    competencia = competencias.get(comp_id)
    club_info = clubes.get(club_id, {})
    
    if not competencia:
        flash("La competencia seleccionada ya no existe", "danger")
        return redirect("/club/inscripciones")

    # Definir la fecha de corte basada en la fecha del evento
    # Esto asegura que la categoría sea la legal para ese torneo
    fecha_evento_str = competencia.get("fecha_evento", date.today().strftime("%Y-%m-%d"))
    corte = fecha_corte(fecha_evento_str)

    conteo_exitoso = 0

    for doc in documentos:
        if doc not in deportistas:
            continue

        # 1. EVITAR DUPLICADOS (Si ya está inscrito en este evento, saltar)
        ya_inscrito = any(
            i for i in inscripciones.values() 
            if str(i.get("competencia_id")) == str(comp_id) and str(i.get("documento")) == str(doc)
        )
        if ya_inscrito:
            continue

        d = deportistas[doc]
        
        # 2. CALCULAR EDAD Y CATEGORÍA PARA EL EVENTO
        edad_evento = calcular_edad(d.get("fecha_nacimiento", ""), corte)
        categoria_evento = obtener_categoria(edad_evento, d.get("modalidad", ""))

        # 3. GENERAR ID ÚNICO PARA LA INSCRIPCIÓN
        # Usamos timestamp para evitar que choquen si hay muchos clubes inscribiendo
        insc_id = f"insc_{int(time.time())}_{doc}"

        # 4. CREAR OBJETO DE INSCRIPCIÓN COMPLETO
        inscripciones[insc_id] = {
            "id": insc_id,
            "competencia_id": comp_id,
            "nombre_evento": competencia.get("nombre", "Sin nombre"),
            
            # Datos del deportista (importante para que el admin los vea sin buscar)
            "documento": doc,
            "nombre": d.get("nombre"),
            "sexo": d.get("sexo"),
            "modalidad": d.get("modalidad"),
            "categoria": categoria_evento,  # <--- AQUÍ SE GUARDA LA CATEGORÍA
            "edad_en_evento": edad_evento,
            
            # Datos del club
            "club_id": club_id,
            "club": club_info.get("nombre", "Club desconocido"), # <--- PARA QUE EL ADMIN VEA EL NOMBRE
            
            # Datos financieros
            "estado_pago": "pendiente",
            "valor": float(competencia.get("valor", 0)), # <--- SE TOMA EL PRECIO DEL EVENTO
            "fecha_registro": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        conteo_exitoso += 1

    if conteo_exitoso > 0:
        save_json("data/inscripciones.json", inscripciones)
        flash(f"Se han inscrito {conteo_exitoso} deportistas exitosamente.", "success")
    else:
        flash("No se realizaron nuevas inscripciones (posibles duplicados).", "info")

    return redirect("/club/inscripciones")
#------------------------------------------------------------------

#------------------ VER LOS INSCRITOS A EVENTOS ------------------
@app.route("/admin/inscripciones-eventos")
def admin_inscripciones_eventos():
    if "user" not in session or session["user"]["rol"] not in ["admin", "editor", "colaborador"]:
        return redirect("/login")

    competencias = load_json("data/competiciones.json", {})
    inscripciones = load_json("data/inscripciones.json", {})

    eventos = []
    for comp_id, comp in competencias.items():
        # Optimizamos el conteo forzando string en el ID
        total = sum(1 for i in inscripciones.values() 
                   if str(i.get("competencia_id")) == str(comp_id))

        eventos.append({
            "id": comp_id,
            "nombre": comp.get("nombre", "Sin nombre"),
            "fecha": comp.get("fecha_evento", "Sin fecha"),
            "total": total
        })

    # Ordenar por fecha (más recientes primero)
    eventos.sort(key=lambda x: x['fecha'], reverse=True)

    return render_template("admin/inscripciones_eventos.html", eventos=eventos)


@app.route("/admin/inscripciones-eventos/<comp_id>")
def admin_inscripciones_evento(comp_id):
    if "user" not in session or session["user"]["rol"] not in ["admin", "editor", "colaborador"]:
        return redirect("/login")

    competencias = load_json("data/competiciones.json", {})
    inscripciones = load_json("data/inscripciones.json", {})

    competencia = competencias.get(str(comp_id))
    if not competencia:
        flash("Evento no encontrado", "danger")
        return redirect("/admin/inscripciones-eventos")

    # Filtrar solo inscripciones de este evento de forma segura
    insc_comp = [i for i in inscripciones.values() 
                 if str(i.get("competencia_id")) == str(comp_id)]

    # Obtener parámetros de búsqueda/filtro
    f = {
        "club": request.args.get("club", "").strip(),
        "cat": request.args.get("categoria", "").strip(),
        "sexo": request.args.get("sexo", "").strip(),
        "mod": request.args.get("modalidad", "").strip(),
        "q": request.args.get("q", "").strip().lower()
    }

    lista_filtrada = []
    for i in insc_comp:
        # Texto libre: Busca en documento, nombre, club y categoría
        if f["q"]:
            search_box = f"{i.get('documento','')} {i.get('nombre','')} {i.get('club','')} {i.get('categoria','')}".lower()
            if f["q"] not in search_box: continue

        # Filtros directos (si el campo tiene valor y no coincide, saltamos)
        if f["club"] and i.get("club") != f["club"]: continue
        if f["cat"] and i.get("categoria") != f["cat"]: continue
        if f["sexo"] and i.get("sexo") != f["sexo"]: continue
        if f["mod"] and i.get("modalidad") != f["mod"]: continue

        lista_filtrada.append(i)

    # Generar listas únicas para los dropdowns del filtro (basado solo en los inscritos reales)
    opciones = {
        "clubes": sorted({i["club"] for i in insc_comp if i.get("club")}),
        "categorias": sorted({i["categoria"] for i in insc_comp if i.get("categoria")}),
        "sexos": sorted({i["sexo"] for i in insc_comp if i.get("sexo")}),
        "modalidades": sorted({i["modalidad"] for i in insc_comp if i.get("modalidad")})
    }

    return render_template(
        "admin/inscripciones_evento.html",
        competencia=competencia,
        inscripciones=lista_filtrada,
        opciones=opciones,
        total_inscritos=len(insc_comp),
        mostrados=len(lista_filtrada),
        filtros=f
    )
#--------------------------------------------------------------

#-------EXPORTAR INSCRITOS A EVENTOS--------------
@app.route("/admin/inscripciones-eventos/<comp_id>/excel")
def exportar_inscripciones_excel(comp_id):
    # Seguridad
    if "user" not in session or session["user"]["rol"] not in ["admin", "editor", "colaborador"]:
        return redirect("/login")

    inscripciones = load_json("data/inscripciones.json", {})
    competencias = load_json("data/competiciones.json", {})

    if comp_id not in competencias:
        return "Competencia no encontrada", 404

    # 1. CAPTURAR FILTROS (Para exportar solo lo que el admin está viendo)
    # Usamos .lower() para comparaciones, pero mantenemos los originales para visualización
    f = {
        "club": request.args.get("club", "").lower(),
        "cat": request.args.get("categoria", "").lower(),
        "sexo": request.args.get("sexo", "").lower(),
        "mod": request.args.get("modalidad", "").lower(),
        "q": request.args.get("q", "").lower()
    }

    filas_ligados = []
    filas_escuela = []

    # 2. PROCESAR DATOS
    for i in inscripciones.values():
        if str(i.get("competencia_id")) != str(comp_id):
            continue

        # Aplicar los mismos filtros que en la vista web
        if f["club"] and f["club"] != i.get("club", "").lower(): continue
        if f["cat"] and f["cat"] != i.get("categoria", "").lower(): continue
        if f["sexo"] and f["sexo"] != i.get("sexo", "").lower(): continue
        if f["mod"] and f["mod"] != i.get("modalidad", "").lower(): continue
        
        if f["q"]:
            search_text = f"{i.get('documento','')} {i.get('nombre','')} {i.get('club','')} {i.get('categoria','')}".lower()
            if f["q"] not in search_text: continue

        # Crear la fila con nombres de columna limpios
        fila = {
            "Documento": i.get("documento"),
            "Nombre": i.get("nombre"),
            "Club": i.get("club"),
            "Categoría": i.get("categoria"),  # Antes: i.get("edad")
            "Modalidad": i.get("modalidad"),  # Antes: i.get("categoria")
            "Rama": i.get("sexo"),
            "Estado Pago": i.get("estado_pago", "pendiente").upper()
        }

        # Separar por pestañas según modalidad (Escuela vs Ligados/Federados)
        if "escuela" in i.get("modalidad", "").lower():
            filas_escuela.append(fila)
        else:
            filas_ligados.append(fila)

    if not filas_ligados and not filas_escuela:
        return "No hay datos filtrados para exportar", 400

    # 3. GENERAR EL ARCHIVO EXCEL
    nombre_evento = competencias[comp_id]["nombre"].replace(" ", "_")
    archivo_nombre = f"Inscritos_{nombre_evento}.xlsx"
    ruta_archivo = os.path.join(tempfile.gettempdir(), archivo_nombre)

    with pd.ExcelWriter(ruta_archivo, engine="openpyxl") as writer:
        if filas_ligados:
            df_ligados = pd.DataFrame(filas_ligados)
            df_ligados.sort_values(by=["Club", "Categoría"], inplace=True)
            df_ligados.to_excel(writer, sheet_name="Federados_Ligados", index=False)
            
        if filas_escuela:
            df_escuela = pd.DataFrame(filas_escuela)
            df_escuela.sort_values(by=["Club", "Categoría"], inplace=True)
            df_escuela.to_excel(writer, sheet_name="Escuela", index=False)

        # Auto-ajustar ancho de columnas (Opcional pero recomendado)
        for sheet in writer.sheets.values():
            for col in sheet.columns:
                max_length = max(len(str(cell.value)) for cell in col) + 2
                sheet.column_dimensions[col[0].column_letter].width = max_length

    return send_file(ruta_archivo, as_attachment=True, download_name=archivo_nombre)
#--------------------------------------------------------------------------------

# ---------- GESTION DE USUARIOS ----------
@app.route("/admin/users", methods=["POST"])
def create_user():
    # Verificación de seguridad centralizada
    if not require_role(["admin"]):
        return redirect("/login")

    # Captura de datos con limpieza
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role", "colaborador")

    users = load_users()

    # 1. VALIDACIÓN DE CAMPOS VACÍOS
    if not username or not password:
        return render_template(
            "admin/usuarios.html",
            users=users,
            error="El nombre de usuario y la contraseña son obligatorios",
            role=user_role()
        )

    # 2. VALIDAR DUPLICADO
    if username in users:
        return render_template(
            "admin/usuarios.html",
            users=users,
            error=f"El usuario '{username}' ya se encuentra registrado",
            role=user_role()
        )

    # 3. GUARDAR NUEVO USUARIO
    # Guardamos 'rol' y 'role' para mantener compatibilidad con todas tus funciones
    users[username] = {
        "password": generate_password_hash(password),
        "rol": role,
        "role": role,
        "club_id": None  # Los usuarios creados aquí suelen ser Staff (Admin/Editor)
    }

    save_users(users)
    flash(f"Usuario {username} creado exitosamente como {role}", "success")
    
    return redirect("/admin/usuarios")

#------------------------------------------------------

#--------------ELIMINAR USUARIOS-----------------------
@app.route("/admin/users/delete/<username>")
def delete_user(username):
    # Seguridad: Solo admin
    if not require_role(["admin"]):
        return redirect("/login")

    # Impedir suicidio administrativo (no borrarse a sí mismo)
    if username == session["user"]["usuario"]:
        flash("No puedes eliminar tu propia cuenta de administrador", "danger")
        return redirect("/admin/usuarios")

    users = load_users()

    if username in users:
        # Si el usuario es un club, opcionalmente podrías avisar 
        # que el club en 'clubes_registro.json' quedará sin acceso
        del users[username]
        save_users(users)
        flash(f"Usuario {username} eliminado correctamente", "success")

    return redirect("/admin/usuarios")
#--------------------------------------------------------

#----------------EDITAR USUARIOS (ADMIN) ------------------------
@app.route("/admin/usuarios/editar/<username>", methods=["GET", "POST"])
def editar_usuario(username):
    if not require_role(["admin"]):
        return redirect("/login")

    users = load_users()

    if username not in users:
        flash("Usuario no encontrado", "warning")
        return redirect("/admin/usuarios")

    # Bloqueo de seguridad: No editar deportistas desde aquí si tienen rol user
    if users[username].get("role") == "deportista":
        return redirect("/admin/deportistas")

    if request.method == "POST":
        nuevo_rol = request.form.get("role")
        nueva_password = request.form.get("password")

        # Actualizar Rol (Estandarizado)
        if nuevo_rol:
            users[username]["role"] = nuevo_rol
            users[username]["rol"] = nuevo_rol # Sincronizamos ambos campos

        # Restablecer contraseña si se escribió algo
        if nueva_password and nueva_password.strip() != "":
            users[username]["password"] = generate_password_hash(nueva_password)
            flash(f"Contraseña de {username} actualizada", "success")

        save_users(users)
        flash(f"Cambios guardados para {username}", "success")
        return redirect("/admin/usuarios")

    return render_template(
        "admin/editar_usuario.html",
        username=username,
        user=users[username]
    )
#--------------------------------------------------

#----------------CAMBIAR MI CONTRASEÑA (UNIVERSAL) ----------------
@app.route("/perfil/cambiar-password", methods=["GET", "POST"])
def cambiar_mi_password():
    # 1. Verificar que haya alguien logueado
    if "user" not in session:
        return redirect("/login")

    # Si es GET, mostramos el formulario
    if request.method == "GET":
        return render_template("perfil/cambio_password.html")

    # Si es POST, procesamos el cambio
    if request.method == "POST":
        p_actual = request.form.get("password_actual")
        p_nueva = request.form.get("password_nueva")
        p_confirma = request.form.get("password_confirmacion")
        
        username = session["user"]["usuario"]
        rol = session["user"].get("rol")
        
        # 2. CARGA DE USUARIOS (Usando la función nativa load_users)
        users = load_users() 
        
        # 3. Validaciones
        if username not in users:
            flash("Error: Usuario no encontrado.", "danger")
            return redirect("/login")

        # Verificar contraseña actual
        if not check_password_hash(users[username]["password"], p_actual):
            return render_template("perfil/cambio_password.html", error="La contraseña actual es incorrecta")

        # Verificar coincidencias
        if p_nueva != p_confirma:
            return render_template("perfil/cambio_password.html", error="Las nuevas contraseñas no coinciden")

        if len(p_nueva) < 4:
            return render_template("perfil/cambio_password.html", error="La contraseña es muy corta")

        # 4. GUARDADO
        try:
            users[username]["password"] = generate_password_hash(p_nueva)
            save_users(users) # Usamos tu función save_users que ya funciona bien
            
            flash("Contraseña actualizada con éxito. Inicia sesión de nuevo.", "success")
            session.clear()
            return redirect("/login")
            
        except Exception as e:
            print(f"ERROR: {e}")
            return render_template("perfil/cambio_password.html", error="Error interno al guardar")

    return render_template("perfil/cambio_password.html")


#----------- NOTICIAS ----------------------------------------------------
@app.route("/news/<news_id>")
def view_news(news_id):
    try:
        noticias = load_news()
        
        # 1. Verificación de existencia (asegurando que news_id sea tratado correctamente)
        if not noticias or news_id not in noticias:
            flash("La noticia solicitada no existe o ha sido eliminada.", "warning")
            return redirect(url_for('index')) # Asumiendo que tu ruta principal se llama index

        # 2. Obtener la noticia
        noticia = noticias[news_id]

        return render_template("news_detail.html", noticia=noticia)

    except Exception as e:
        # 3. Log del error para el desarrollador
        print(f"Error al cargar noticia {news_id}: {e}")
        return redirect(url_for('index'))

@app.route("/admin/edit/<news_id>", methods=["GET", "POST"])
def edit_news(news_id):
    # 1. Verificación de seguridad
    if not require_login():
        return redirect("/login")

    noticias = load_news()

    # 2. Verificar que la noticia existe
    if news_id not in noticias:
        flash("La noticia no existe.", "danger")
        return redirect("/admin")

    if request.method == "POST":
        # Usamos .get() para evitar errores si falta un campo en el HTML
        title = request.form.get("title")
        content = request.form.get("content")

        if not title or not content:
            flash("El título y el contenido son obligatorios.", "warning")
            return render_template("admin/edit_news.html", noticia=noticias[news_id], role=user_role())

        # 3. Actualizar datos básicos
        noticias[news_id]["title"] = title
        noticias[news_id]["content"] = content

        # 4. Manejo de archivos (Imagen)
        if "image" in request.files:
            image = request.files["image"]
            if image and image.filename != "":
                filename = secure_filename(image.filename)
                # Aseguramos que la carpeta existe antes de guardar
                if not os.path.exists(UPLOAD_NEWS):
                    os.makedirs(UPLOAD_NEWS)
                
                image.save(os.path.join(UPLOAD_NEWS, filename))
                noticias[news_id]["image"] = filename

        # 5. Metadatos de auditoría
        # Usamos session["user"]["usuario"] si tu sesión guarda un objeto
        noticias[news_id]["updated_by"] = session.get("user", {}).get("usuario", "desconocido")
        noticias[news_id]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        save_news(noticias)
        flash("Noticia actualizada correctamente.", "success")
        return redirect("/admin")

    return render_template(
        "admin/edit_news.html", 
        noticia=noticias[news_id],
        role=user_role()
    )

@app.route("/deportista/editar", methods=["GET", "POST"])
def deportista_editar():
    documento = session.get("user_id")
    if not documento:
        return redirect("/login")

    deportistas = load_json("data/deportistas.json", {})
    deportista = deportistas.get(documento)

    if not deportista:
        return redirect("/login")

    if request.method == "POST":
        deportista["telefono"] = request.form.get("telefono", "").strip()
        deportista["correo"] = request.form.get("correo", "").strip()
        deportista["acudiente_nombre"] = request.form.get("acudiente_nombre", "").strip()
        deportista["acudiente_telefono"] = request.form.get("acudiente_telefono", "").strip()

        save_json("data/deportistas.json", deportistas)
        return redirect("/deportista/perfil")

    return render_template(
        "deportista/editar_perfil.html",
        deportista=deportista
    )
#-----------------------------------------------------------------------------


# ---------- PANEL AFILIATE-CLUBES ----------

@app.route("/admin/clubes")
def admin_clubes():
    # Verificamos que sea admin para gestionar la vitrina
    if not require_role(["admin"]):
        return redirect("/login")

    clubes = load_json("data/clubes.json", {})
    return render_template("admin/clubes.html", clubes=clubes)

@app.route("/admin/clubes/nuevo", methods=["GET", "POST"])
def nuevo_club():
    if not require_role(["admin"]):
        return redirect("/login")

    # Cargamos el diccionario actual de clubes
    clubes = load_json("data/clubes.json", {})

    if request.method == "POST":
        # 1. ID ÚNICO: Usamos tiempo actual (timestamp) para que nunca se repita el ID
        club_id = str(int(time.time()))

        # 2. MANEJO DE LOGO SEGURO
        logo_name = ""
        file = request.files.get("logo")
        if file and file.filename != "":
            # Limpiamos el nombre y le pegamos el ID para evitar que un club borre el logo de otro
            filename = secure_filename(file.filename)
            filename = f"{club_id}_{filename}"
            
            # Aseguramos que la carpeta exista antes de guardar
            if not os.path.exists(UPLOAD_CLUBES):
                os.makedirs(UPLOAD_CLUBES)
            
            path = os.path.join(UPLOAD_CLUBES, filename)
            file.save(path)
            logo_name = filename

        # 3. CREACIÓN DEL REGISTRO (Corregido 'now()' por formato datetime)
        clubes[club_id] = {
            "id": club_id,
            "nombre": request.form.get("nombre", "Sin nombre"),
            "contacto": request.form.get("contacto", ""),
            "correo": request.form.get("correo", ""),
            "logo": logo_name,
            "destacado": "destacado" in request.form,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        save_json("data/clubes.json", clubes)
        flash("Club registrado exitosamente en la vitrina.", "success")
        return redirect("/admin/clubes")

    # Si es GET, mostramos el formulario
    return render_template("admin/club_form.html", club=None)

@app.route("/admin/clubes/editar/<club_id>", methods=["GET", "POST"])
def editar_club(club_id):
    if not require_role(["admin"]):
        return redirect("/login")

    clubes = load_json("data/clubes.json", {})

    if club_id not in clubes:
        flash("El club no existe", "danger")
        return redirect("/admin/clubes")

    if request.method == "POST":
        # Actualizamos los campos de texto de forma segura
        clubes[club_id]["nombre"] = request.form.get("nombre", clubes[club_id]["nombre"])
        clubes[club_id]["contacto"] = request.form.get("contacto", "")
        clubes[club_id]["correo"] = request.form.get("correo", "")
        clubes[club_id]["destacado"] = "destacado" in request.form

        # Manejo del nuevo logo
        file = request.files.get("logo")
        if file and file.filename != "":
            filename = secure_filename(file.filename)
            # Usamos el ID para que el archivo sea único
            filename = f"{club_id}_{filename}"
            
            if not os.path.exists(UPLOAD_CLUBES):
                os.makedirs(UPLOAD_CLUBES)
                
            file.save(os.path.join(UPLOAD_CLUBES, filename))
            clubes[club_id]["logo"] = filename

        clubes[club_id]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        save_json("data/clubes.json", clubes)
        flash("Información del club actualizada con éxito.", "success")
        return redirect("/admin/clubes")

    return render_template("admin/club_form.html", club=clubes[club_id])

@app.route("/admin/clubes/eliminar/<club_id>")
def eliminar_club(club_id):
    if not require_role(["admin"]):
        return redirect("/login")

    clubes = load_json("data/clubes.json", {})

    if club_id in clubes:
        # --- MEJORA: Borrar la imagen física del servidor ---
        logo_filename = clubes[club_id].get("logo")
        if logo_filename:
            path_logo = os.path.join(UPLOAD_CLUBES, logo_filename)
            if os.path.exists(path_logo):
                try:
                    os.remove(path_logo)
                except Exception as e:
                    print(f"Error borrando logo: {e}")

        # Borrar el registro del JSON
        del clubes[club_id]
        save_json("data/clubes.json", clubes)
        flash("Club eliminado permanentemente.", "info")
    else:
        flash("No se pudo encontrar el club para eliminar.", "warning")

    return redirect("/admin/clubes")

@app.route("/afiliate")
def afiliate():
    # El {} asegura que si el archivo no existe, no se rompa la app
    clubes = load_json("data/clubes.json", {})

    destacados = []
    normales = []

    for club in clubes.values():
        if club.get("destacado"):
            destacados.append(club)
        else:
            normales.append(club)

    # Ordenar alfabéticamente los clubes normales
    normales.sort(key=lambda x: x.get("nombre", "").lower())

    # Los destacados van primero en la vitrina
    clubes_ordenados = destacados + normales

    return render_template("public/afiliate.html", clubes=clubes_ordenados)
#-----------------------------------------------------------

# ---------- MENU INFO (REGLAMENTOS Y DOCUMENTOS) ----------

@app.route("/admin/info")
def admin_info():
    if not require_role(["admin"]):
        return redirect("/login")

    info = load_json("data/info.json", {})
    return render_template("admin/info.html", info=info)


@app.route("/admin/info/nuevo", methods=["GET", "POST"])
def nuevo_info():
    if not require_role(["admin"]):
        return redirect("/login")

    info = load_json("data/info.json", {})

    if request.method == "POST":
        # 1. ID Seguro basado en tiempo (evita choques al borrar)
        item_id = str(int(time.time()))

        archivo = request.files.get("archivo")
        filename = ""

        if archivo and archivo.filename != "":
            # 2. Validación estricta de PDF
            if archivo.filename.lower().endswith(".pdf"):
                original_name = secure_filename(archivo.filename)
                # Renombramos para evitar duplicados en la carpeta uploads
                filename = f"doc_{item_id}_{original_name}"
                
                if not os.path.exists(UPLOAD_INFO):
                    os.makedirs(UPLOAD_INFO)
                    
                archivo.save(os.path.join(UPLOAD_INFO, filename))
            else:
                flash("Solo se permiten archivos PDF", "danger")
                return render_template("admin/info_form.html")

        # 3. Guardado con validación de campos y fecha corregida
        titulo = request.form.get("titulo", "Sin título")
        
        info[item_id] = {
            "id": item_id,
            "titulo": titulo,
            "archivo": filename,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") # Reemplazo de now()
        }

        save_json("data/info.json", info)
        flash(f"Documento '{titulo}' cargado correctamente.", "success")
        return redirect("/admin/info")

    return render_template("admin/info_form.html")


@app.route("/info")
def info_publica():
    # El público ve los documentos para descargar
    info_data = load_json("data/info.json", {})
    # Ordenamos por fecha de creación (más nuevos primero)
    documentos = sorted(info_data.values(), key=lambda x: x.get('created_at', ''), reverse=True)
    return render_template("public/info.html", info=documentos)


@app.route("/admin/info/delete/<info_id>")
def admin_info_delete(info_id):
    if not require_role(["admin"]):
        return redirect("/login")

    path_json = "data/info.json"
    info_dict = load_json(path_json, {})

    if info_id in info_dict:
        # Borramos el archivo físico del servidor
        archivo = info_dict[info_id].get("archivo")
        if archivo:
            file_path = os.path.join(UPLOAD_INFO, archivo)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"No se pudo eliminar el PDF: {e}")

        # Borramos del JSON
        del info_dict[info_id]
        save_json(path_json, info_dict)
        flash("Documento eliminado correctamente.", "info")
    
    return redirect(url_for("admin_info"))


# ------------ INFORMACION GENERAL ---------------------
# ---------- INFO GENERAL (INSTITUCIONAL) ----------

@app.route("/liga/informacion-general")
def info_general_public():
    # Cargamos la información para el público
    info = load_json("data/info_general.json", {})
    # Convertimos a lista y ordenamos por título para que se vea organizado
    documentos = sorted(info.values(), key=lambda x: x.get('titulo', '').lower())
    return render_template(
        "public/info_general.html",
        info=documentos
    )


@app.route("/admin/info-general/delete/<info_id>")
def delete_info_general(info_id):
    # 1. SEGURIDAD: Solo el admin debe poder borrar
    if not require_role(["admin"]):
        flash("No tienes permiso para eliminar documentos institucionales", "danger")
        return redirect("/login")

    info = load_json("data/info_general.json", {})

    if info_id not in info:
        flash("El documento no existe", "warning")
        return redirect("/admin/info-general")

    # 2. BORRADO FÍSICO DEL ARCHIVO
    archivo = info[info_id].get("archivo")
    if archivo:
        # Es mejor usar la variable global UPLOAD_INFO_GENERAL si la tienes definida
        # o asegurar la ruta completa
        path = os.path.join("static/uploads/info_general", archivo)
        
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                print(f"Error al eliminar archivo físico: {e}")

    # 3. BORRADO DEL REGISTRO
    del info[info_id]
    save_json("data/info_general.json", info)
    
    flash("Documento institucional eliminado correctamente", "info")
    return redirect("/admin/info-general")
#-----------------------------------------------------------------




# ---------- INSCRIPCIÓN A COMPETENCIAS ----------
@app.route("/admin/inscripciones")
def admin_inscripciones():
    if not require_role(["admin", "editor"]):
        return redirect("/login")

    competencias = load_json("data/competiciones.json", {})
    inscripciones_dict = load_json("data/inscripciones.json", {})

    inscripciones = []
    for insc in inscripciones_dict.values():
        comp = competencias.get(insc.get("competencia_id"))
        # Agregamos el nombre del evento para que se vea en la tabla
        insc["nombre_evento"] = comp["nombre"] if comp else "Evento eliminado"
        inscripciones.append(insc)

    return render_template("admin/inscripciones.html", inscripciones=inscripciones)



@app.route("/admin/inscripciones/pagar/<insc_id>")
def marcar_pagado(insc_id):
    if not require_role(["admin"]):
        return redirect("/login")

    inscripciones = load_json("data/inscripciones.json", {})

    if insc_id in inscripciones:
        if inscripciones[insc_id].get("estado_pago") != "pagado":
            inscripciones[insc_id]["estado_pago"] = "pagado"
            # Corregido: usando datetime en lugar de now()
            inscripciones[insc_id]["fecha_pago"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            inscripciones[insc_id]["forma_pago"] = "manual"
            save_json("data/inscripciones.json", inscripciones)
            flash("Pago registrado correctamente", "success")

    return redirect("/admin/inscripciones")






@app.route("/admin/inscripciones/exportar")
def exportar_inscripciones_admin():
    if not require_role(["admin"]):
        return redirect("/login")

    inscripciones = load_json("data/inscripciones.json", {})
    
    # Usamos StringIO para generar el archivo en memoria de forma segura
    output = io.StringIO()
    writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

    # Encabezados
    writer.writerow(["Competencia", "Documento", "Nombre", "Club", "Sexo", "Modalidad", "Edad", "Categoría", "Pago", "Valor", "Fecha"])

    for i in inscripciones.values():
        writer.writerow([
            i.get("competencia_id", ""),
            i.get("documento", ""),
            i.get("nombre", ""),
            i.get("club", ""),
            i.get("sexo", ""),
            i.get("modalidad", ""),
            i.get("edad", ""),
            i.get("categoria", ""),
            i.get("estado_pago", "pendiente"),
            i.get("valor", 0),
            i.get("fecha", "")
        ])

    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=reporte_general_inscripciones.csv"
    return response







@app.route("/admin/competencias/<comp_id>/reporte")
def reporte_competencia(comp_id):
    if not require_role(["admin", "editor"]):
        return redirect("/login")

    competencias = load_json("data/competiciones.json", {})
    inscripciones = load_json("data/inscripciones.json", {})

    if comp_id not in competencias:
        flash("Competencia no encontrada", "danger")
        return redirect("/admin/competencias")

    competencia = competencias[comp_id]

    # Filtramos solo los inscritos en esta competencia
    reporte = [
        i for i in inscripciones.values() 
        if str(i.get("competencia_id")) == str(comp_id)
    ]

    # Ordenamos por Categoría y luego por Nombre
    reporte.sort(key=lambda x: (x.get("categoria", ""), x.get("nombre", "")))

    return render_template(
        "admin/reporte_competencia.html",
        competencia=competencia,
        reporte=reporte
    )

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)


