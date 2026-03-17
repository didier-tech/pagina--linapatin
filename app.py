
import os
import psycopg2
from flask import Flask, render_template

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

@app.route("/")
def index():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT titulo, contenido FROM noticias ORDER BY fecha DESC")
    noticias = cur.fetchall()
    cur.close()
    conn.close()
    return str(noticias)

if __name__ == "__main__":
    app.run(debug=True)
