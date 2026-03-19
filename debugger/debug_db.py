import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST'),
    port=os.getenv('POSTGRES_PORT'),
    user=os.getenv('POSTGRES_USER'),
    password=os.getenv('POSTGRES_PASSWORD'),
    dbname=os.getenv('POSTGRES_DB')
)
cur = conn.cursor()

print(f"Connected to: {os.getenv('POSTGRES_DB')} @ {os.getenv('POSTGRES_HOST')}")

cur.execute("""
    SELECT table_schema, table_name 
    FROM information_schema.tables 
    WHERE table_type='BASE TABLE' 
    AND table_schema NOT IN ('pg_catalog','information_schema')
""")
rows = cur.fetchall()
print(f"Found {len(rows)} tables:")
for r in rows:
    print(f"  {r[0]}.{r[1]}")

conn.close()
