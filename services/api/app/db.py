"""Helper di connessione a PostgreSQL per l'API gateway."""
import os
from contextlib import contextmanager

import psycopg2

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://absa_app:absa_local_pw@postgres:5432/absa"
)


@contextmanager
def get_conn():
    """Context manager: apre una connessione, fa commit/rollback e chiude."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
