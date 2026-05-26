import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'data.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS partners (
                token        TEXT PRIMARY KEY,
                country_id   TEXT NOT NULL,
                flag         TEXT,
                country_name TEXT,
                name         TEXT NOT NULL,
                lang         TEXT DEFAULT 'en',
                tier         TEXT DEFAULT 'normal'
            );

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
            );

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
            );

            CREATE TABLE IF NOT EXISTS cluster_tickets (
                cluster_id  TEXT NOT NULL,
                ticket_id   TEXT NOT NULL,
                PRIMARY KEY (cluster_id, ticket_id)
            );

            CREATE TABLE IF NOT EXISTS scoring_config (
                id          INTEGER PRIMARY KEY,
                config_json TEXT NOT NULL
            );
        ''')
