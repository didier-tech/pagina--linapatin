
import os
import psycopg2
from flask import Flask

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL) # ← ESTA LÍNEA VA INDENTADA

@app.route("/")
def index():
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT titulo, contenido FROM noticias ORDER BY fecha DESC")
        noticias_db = cur.fetchall()

        cur.close()
        conn.close()
        # convertir a formato tipo JSON (como antes)
        noticias = []
        for n in noticias_db:
            noticias.append({
                "id": n[0],
                "title": n[1],
                "content": n[2],
                "created_at": n[3]
            })
                


        return render_template("index.html", noticias=noticias, heroes[])

    except Exception as e:
        print("ERROR:", e)
        return "Error en la base de datos"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
