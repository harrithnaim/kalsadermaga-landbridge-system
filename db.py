import os
import json
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS containers (
                    container_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS plans (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT NOW(),
                    data JSONB NOT NULL
                )
            """)
        conn.commit()


def save_containers(containers):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for c in containers:
                cur.execute(
                    "INSERT INTO containers (container_id, data) VALUES (%s, %s) "
                    "ON CONFLICT (container_id) DO UPDATE SET data = EXCLUDED.data",
                    (c["container_id"], json.dumps(c)),
                )
        conn.commit()


def get_containers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM containers")
            return [row[0] for row in cur.fetchall()]


def clear_containers():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM containers")
        conn.commit()


def save_plan(plan):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO plans (data) VALUES (%s)", (json.dumps(plan),))
        conn.commit()


def get_last_plan():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM plans ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            return row[0] if row else None
