import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager


def get_connection():
    """Open and return a new psycopg2 connection using DATABASE_URL."""
    return psycopg2.connect(os.environ["DATABASE_URL"])


@contextmanager
def get_cursor(conn=None, *, cursor_factory=RealDictCursor):
    """Context manager yielding a cursor; commits on exit, rolls back on error.

    If *conn* is None (the default), a new connection is opened for the
    duration of the block and closed on exit.  Pass an existing connection to
    participate in a caller-managed transaction.
    """
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        with conn.cursor(cursor_factory=cursor_factory) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()
