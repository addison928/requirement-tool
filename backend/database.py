import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL', '')


class _ConnWrapper:
    """Make psycopg2 behave like sqlite3: conn.execute() returns a cursor."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql.replace('?', '%s'), params if params else ())
        return cur

    def executemany(self, sql, params_list):
        cur = self._conn.cursor()
        cur.executemany(sql.replace('?', '%s'), params_list)
        return cur


@contextmanager
def get_conn():
    url = DATABASE_URL
    if url and 'sslmode' not in url:
        sep = '&' if '?' in url else '?'
        url = url + sep + 'sslmode=require'
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.DictCursor)
    try:
        yield _ConnWrapper(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS partners (
                token        TEXT PRIMARY KEY,
                country_id   TEXT NOT NULL,
                flag         TEXT,
                country_name TEXT,
                name         TEXT NOT NULL,
                lang         TEXT DEFAULT 'en',
                tier         TEXT DEFAULT 'normal'
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id           TEXT PRIMARY KEY,
                flag         TEXT,
                partner_name TEXT,
                country_id   TEXT,
                text         TEXT NOT NULL,
                merchant     TEXT,
                impact       TEXT DEFAULT 'mid',
                scenes       TEXT DEFAULT '[]',
                biz_type     TEXT,
                time         TEXT,
                status       TEXT DEFAULT 'pending',
                cluster_id   TEXT,
                attachments  TEXT DEFAULT '[]',
                manual       INTEGER DEFAULT 0,
                lang         TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS clusters (
                id          TEXT PRIMARY KEY,
                score       INTEGER DEFAULT 0,
                urgent      INTEGER DEFAULT 0,
                summary     TEXT,
                layer       TEXT DEFAULT 'saas',
                impact      TEXT DEFAULT 'mid',
                source_ids  TEXT DEFAULT '[]',
                partners    TEXT DEFAULT '[]',
                count       INTEGER DEFAULT 1,
                periods     INTEGER DEFAULT 1,
                status      TEXT DEFAULT 'pending',
                ai_summary  TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS cluster_tickets (
                cluster_id  TEXT NOT NULL,
                ticket_id   TEXT NOT NULL,
                PRIMARY KEY (cluster_id, ticket_id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scoring_config (
                id          INTEGER PRIMARY KEY,
                config_json TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS saas_vendors (
                token       TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                industry    TEXT NOT NULL,
                code        TEXT NOT NULL,
                contact     TEXT DEFAULT '',
                created_at  TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS saas_tickets (
                id               TEXT PRIMARY KEY,
                vendor_token     TEXT NOT NULL,
                vendor_name      TEXT NOT NULL,
                industry         TEXT,
                text             TEXT NOT NULL,
                merchant         TEXT DEFAULT '',
                impact           TEXT DEFAULT 'mid',
                scenes           TEXT DEFAULT '[]',
                biz_type         TEXT,
                time             TEXT,
                status           TEXT DEFAULT 'pending',
                saas_cluster_id  TEXT,
                attachments      TEXT DEFAULT '[]',
                manual           INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS saas_clusters (
                id           TEXT PRIMARY KEY,
                score        INTEGER DEFAULT 0,
                urgent       INTEGER DEFAULT 0,
                summary      TEXT,
                layer        TEXT DEFAULT 'saas',
                impact       TEXT DEFAULT 'mid',
                vendor_names TEXT DEFAULT '[]',
                count        INTEGER DEFAULT 1,
                periods      INTEGER DEFAULT 1,
                status       TEXT DEFAULT 'pending',
                ai_summary   TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS saas_cluster_tickets (
                cluster_id  TEXT NOT NULL,
                ticket_id   TEXT NOT NULL,
                PRIMARY KEY (cluster_id, ticket_id)
            )
        ''')
