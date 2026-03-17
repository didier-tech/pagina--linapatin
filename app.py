
import os
import psycopg2
from flask import Flask, render_template

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode='require'
    )

@app.route("/")
def index():
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT id, titulo, contenido, fecha FROM noticias ORDER BY fecha DESC")
        datos = cur.fetchall()

        cur.close()
        conn.close()

        noticias = []
        for n in datos:
            noticias.append({
                "id": n[0],
                "title": n[1],
                "content": n[2],
                "created_at": n[3],
                "image": None
            })

        return render_template("index.html", noticias=noticias, heroes=[])

    except Exception as e:
        import traceback
        return f"<pre>{traceback.format_exc()}</pre>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
