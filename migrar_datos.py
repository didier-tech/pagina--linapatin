
import json, psycopg2, os

conn = psycopg2.connect(os.environ.get("DATABASE_URL"))
cur = conn.cursor()

with open("data/noticias.json", encoding="utf-8") as f:
    noticias = json.load(f)
    for n in noticias.values():
        cur.execute(
            "INSERT INTO noticias (titulo, contenido, imagen, fecha) VALUES (%s,%s,%s,%s)",
            (n.get("title"), n.get("content"), n.get("image"), n.get("created_at"))
        )

conn.commit()
cur.close()
conn.close()

print("Migración completada")
