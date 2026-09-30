"""
Create PostgreSQL database for Fuel Route Optimizer.
Safely connects to the default 'postgres' maintenance database and executes
CREATE DATABASE if the target database does not already exist.
"""
import os
import sys
import psycopg
from psycopg import sql
from dotenv import load_dotenv

load_dotenv()

db_name = os.getenv("DB_NAME", "fuel_route")
user = os.getenv("DB_USER", "postgres")
password = os.getenv("DB_PASSWORD", "")
host = os.getenv("DB_HOST", "localhost")
port = os.getenv("DB_PORT", "5433")

print(f"Connecting to PostgreSQL (host={host}, port={port}, user={user}, maintenance_db=postgres)...")
try:
    conn = psycopg.connect(
        dbname="postgres",
        user=user,
        password=password,
        host=host,
        port=port,
        autocommit=True
    )
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (db_name,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
            print(f"Database '{db_name}' created successfully.")
        else:
            print(f"Database '{db_name}' already exists.")
    conn.close()
except Exception as e:
    print(f"Error connecting or creating database: {e}", file=sys.stderr)
    sys.exit(1)
