
import os
import psycopg2
from flask import Flask

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
return psycopg2.connect(DATABASE_URL)

@app.route("/")
def index():
try:
conn = get_db()
cur = conn.cursor()

cur.execute("SELECT titulo, contenido FROM noticias ORDER BY fecha DESC")
noticias = cur.fetchall()

cur.close()
conn.close()

return str(noticias)

except Exception as e:
print("ERROR:", e)
return "Error conectando a la base de datos"

if __name__ == "__main__":
port = int(os.environ.get("PORT", 10000))
app.run(host="0.0.0.0", port=port)
