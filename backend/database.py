"""
database.py - Supabase REST API database wrapper.

Provides get_conn() and init_db() with the same interface as the original
sqlite3/psycopg2 database.py, but uses the Supabase REST API (PostgREST).
"""

import os
import json
import re
from contextlib import contextmanager
import urllib.request
import urllib.parse
import ssl

# ── Load .env ──────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv()  # backend dir fallback

# ── Configuration ────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get(
    'SUPABASE_URL', 'https://tfdowgfykxoekjkxsonm.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
_http_ctx = ssl.create_default_context()

# ── Low-level REST helper ────────────────────────────────────────────────────

def _rest(method, path, data=None, prefer=None, count_header=False):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = prefer or "return=representation"
    if prefer:
        headers["Prefer"] = prefer
    if count_header and not prefer:
        headers["Prefer"] = "count=exact"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    resp = urllib.request.urlopen(req, context=_http_ctx, timeout=30)
    status = resp.status
    content_range = resp.headers.get('content-range', '')
    raw = resp.read().decode()
    total_count = None
    if count_header and content_range:
        # content-range: */total
        parts = content_range.split('/')
        if len(parts) == 2:
            total_count = int(parts[1])
    if status in (204, 201, 200) and raw:
        return json.loads(raw), total_count
    return [], total_count


# ── Row & Cursor wrappers ────────────────────────────────────────────────────

class Row(dict):
    """Dict supporting index access and attribute access like sqlite3.Row."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def keys(self):
        return super().keys()


class Cursor:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


# ── Connection wrapper ──────────────────────────────────────────────────────

class _SupaConn:
    """Mimics sqlite3/psycopg2 connection using Supabase REST API."""

    def execute(self, sql, params=()):
        sql_norm = ' '.join(sql.split())
        sql_up = sql_norm.upper()
        params = list(params) if params else []

        # Skip SQLite / DDL commands
        if (sql_up.startswith('PRAGMA') or sql_up.startswith('ALTER TABLE')
                or sql_up.startswith('CREATE TABLE') or sql_up.startswith('CREATE INDEX')):
            return Cursor([Row({'result': 1})], rowcount=0)

        if sql_up.startswith('SELECT'):
            return self._select(sql_norm, params)
        elif sql_up.startswith('INSERT'):
            return self._insert(sql_norm, params)
        elif sql_up.startswith('UPDATE'):
            return self._update(sql_norm, params)
        elif sql_up.startswith('DELETE'):
            return self._delete(sql_norm, params)
        else:
            return Cursor([], rowcount=0)

    def executemany(self, sql, params_list):
        for params in params_list:
            self.execute(sql, params)
        return Cursor([], rowcount=0)

    # ── SELECT ───────────────────────────────────────────────────────────
    def _select(self, sql, params):
        table = self._table(sql, 'FROM')
        if not table:
            return Cursor([], rowcount=0)

        # Check for SELECT COUNT(*)
        if re.match(r'\s*SELECT\s+COUNT\(\*\)', sql, re.IGNORECASE):
            return self._count(sql, params, table)

        # Check for GROUP BY (stats queries) → fetch all + group in Python
        if 'GROUP BY' in sql.upper():
            return self._group_by(sql, params, table)

        # Check for JOIN → handle specially
        if ' JOIN ' in sql.upper():
            return self._join(sql, params)

        # Get selected columns
        cols = self._select_cols(sql)

        # Build PostgREST path: table?select=cols&filters&order&limit&offset
        path_parts = [table]
        query_parts = []

        if cols:
            query_parts.append(f"select={','.join(cols)}")

        # WHERE clauses
        where_str = self._extract_where(sql)
        filters, remaining_params = self._parse_where(where_str, params, table)
        if filters:
            query_parts.append(filters)

        # ORDER BY
        order, limit, offset = self._parse_order_limit_offset(sql, remaining_params)
        if order:
            query_parts.append(f"order={order}")
        if limit is not None:
            query_parts.append(f"limit={limit}")
        if offset is not None:
            query_parts.append(f"offset={offset}")

        path = path_parts[0]
        if query_parts:
            path += '?' + '&'.join(query_parts)

        try:
            rows, total_count = _rest('GET', path)
            result_rows = [Row(r) for r in rows]
            return Cursor(result_rows, rowcount=len(result_rows))
        except Exception as e:
            print(f"REST SELECT error: {e}", flush=True)
            return Cursor([], rowcount=0)

    def _count(self, sql, params, table):
        where_str = self._extract_where(sql)
        path = f"{table}?select=*"
        if where_str:
            filters, _ = self._parse_where(where_str, params, table)
            if filters:
                path += f"&{filters}"
        try:
            rows, total = _rest('GET', path, prefer="count=exact")
            count = total if total is not None else len(rows)
            return Cursor([Row({'count': count})], rowcount=0)
        except Exception as e:
            print(f"REST COUNT error: {e}", flush=True)
            return Cursor([Row({'count': 0})], rowcount=0)

    def _group_by(self, sql, params, table):
        # For GROUP BY, fetch all rows and group in Python
        cols = self._select_cols(sql)
        try:
            if cols:
                rows, _ = _rest('GET', f"{table}?select={','.join(cols)}")
            else:
                rows, _ = _rest('GET', f"{table}?select=*")
            # Parse GROUP BY column and aggregation
            group_match = re.search(
                r'GROUP\s+BY\s+(\w+)', sql, re.IGNORECASE)
            if group_match:
                group_col = group_match.group(1)
                groups = {}
                for r in rows:
                    key = r.get(group_col)
                    if key not in groups:
                        groups[key] = {'cnt': 0}
                        for k, v in r.items():
                            if k != 'cnt':
                                groups[key][k] = v
                    groups[key]['cnt'] += 1
                order_match = re.search(
                    r'ORDER\s+BY\s+(\w+)', sql, re.IGNORECASE)
                result = list(groups.values())
                if order_match:
                    order_col = order_match.group(1)
                    result.sort(key=lambda x: x.get(order_col, 0), reverse=True)
                return Cursor([Row(r) for r in result], rowcount=len(result))
            return Cursor([Row(r) for r in rows], rowcount=len(rows))
        except Exception as e:
            print(f"REST GROUP BY error: {e}", flush=True)
            return Cursor([], rowcount=0)

    def _join(self, sql, params):
        # Handle JOIN by fetching from both tables in Python
        # Pattern: SELECT cols FROM t1 alias1 JOIN t2 alias2 ON alias2.col = alias1.col WHERE ...
        m = re.search(
            r'FROM\s+(\w+)\s+(\w+)\s+JOIN\s+(\w+)\s+(\w+)\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)',
            sql, re.IGNORECASE)
        if not m:
            return Cursor([], rowcount=0)

        table1, alias1, table2, alias2 = m.group(1), m.group(2), m.group(3), m.group(4)
        j_alias, j_col = m.group(5), m.group(6)
        j_alias2, j_col2 = m.group(7), m.group(8)

        # Determine which is the main table and which is the join table
        if alias1 == j_alias:
            main_table, join_table = table1, table2
            main_col, join_col = j_col2, j_col
        else:
            main_table, join_table = table2, table1
            main_col, join_col = j_col, j_col2

        # Get WHERE conditions
        where_str = self._extract_where(sql)
        where_params = list(params)

        # Find the WHERE condition for the join table
        join_where_val = None
        if where_str:
            # Look for conditions like ct.cluster_id=?
            pattern = re.search(
                rf'{alias2}\.(\w+)\s*=\s*\?', where_str, re.IGNORECASE)
            if pattern:
                join_where_col = pattern.group(1)
                if where_params:
                    join_where_val = where_params.pop(0)

        # Fetch from join table
        try:
            join_path = join_table
            if join_where_val is not None:
                join_path += f"?{join_where_col}=eq.{urllib.parse.quote(str(join_where_val), safe='')}"
            join_rows, _ = _rest('GET', join_path)
        except Exception:
            join_rows = []

        # Get main table IDs from join results
        main_ids = []
        for jr in join_rows:
            mid = jr.get(main_col)
            if mid:
                main_ids.append(mid)

        if not main_ids:
            return Cursor([], rowcount=0)

        # Fetch from main table
        select_cols = self._select_cols(sql)
        id_filter = ','.join(
            urllib.parse.quote(str(mid), safe='') for mid in main_ids)
        main_path = f"{main_table}?{main_col}=in.({id_filter})"
        if select_cols:
            main_path += f"&select={','.join(select_cols)}"

        try:
            main_rows, _ = _rest('GET', main_path)
            # Build a map
            main_map = {r.get(main_col): r for r in main_rows}
            # Combine
            result = []
            for jr in join_rows:
                mid = jr.get(main_col)
                mr = main_map.get(mid)
                if mr:
                    combined = {}
                    for k, v in mr.items():
                        combined[k] = v
                    result.append(Row(combined))
            return Cursor(result, rowcount=len(result))
        except Exception as e:
            print(f"REST JOIN error: {e}", flush=True)
            return Cursor([], rowcount=0)

    # ── INSERT ───────────────────────────────────────────────────────────
    def _insert(self, sql, params):
        table = self._table(sql, 'INTO')
        if not table:
            return Cursor([], rowcount=0)

        # Extract column names if present (INSERT INTO table (col1, col2) VALUES ...)
        col_match = re.search(
            r'INSERT\s+INTO\s+\w+\s*\(([^)]+)\)\s*VALUES', sql, re.IGNORECASE)
        if col_match:
            col_names = [c.strip() for c in col_match.group(1).split(',')]
        else:
            # Need to get column names from the table
            col_names = self._get_table_columns(table)

        row_dict = {}
        for i, val in enumerate(params):
            if i < len(col_names):
                row_dict[col_names[i]] = val

        on_conflict = 'ON CONFLICT DO NOTHING' in sql.upper()

        try:
            prefer = "resolution=merge-duplicates,return=representation" if on_conflict else "return=representation"
            result, _ = _rest('POST', table, data=[row_dict], prefer=prefer)
            rowcount = len(result) if result else 0
            return Cursor([Row(r) for r in result], rowcount=rowcount)
        except Exception as e:
            print(f"REST INSERT error: {e}", flush=True)
            return Cursor([], rowcount=0)

    # ── UPDATE ───────────────────────────────────────────────────────────
    def _update(self, sql, params):
        table = self._table(sql, 'UPDATE')
        if not table:
            return Cursor([], rowcount=0)

        # Extract SET clause
        set_match = re.search(
            r'SET\s+(.+?)\s+WHERE', sql, re.IGNORECASE | re.DOTALL)
        where_str = self._extract_where(sql)

        if not set_match:
            return Cursor([], rowcount=0)

        set_str = set_match.group(1).strip()
        set_parts = [s.strip() for s in set_str.split(',')]

        # Extract column names and placeholders from SET clause
        update_data = {}
        for part in set_parts:
            if '=?' in part:
                col, _ = part.split('=?', 1)
                update_data[col.strip()] = None
            elif '=NULL' in part.upper():
                col, _ = part.split('=', 1)
                update_data[col.strip()] = None

        # Match params: first SET params, then WHERE params
        set_placeholder_count = set_str.count('?')
        set_params = params[:set_placeholder_count]
        where_params = params[set_placeholder_count:]

        for i, col in enumerate(update_data):
            if i < len(set_params):
                update_data[col] = set_params[i]

        # Build WHERE filter
        where_filter = ''
        if where_str:
            filters, _ = self._parse_where(where_str, where_params, table)
            where_filter = filters

        # Build path
        if where_filter:
            path = f"{table}?{where_filter}"
        else:
            path = table

        try:
            result, _ = _rest('PATCH', path, data=update_data)
            rowcount = len(result) if isinstance(result, list) else 0
            return Cursor([Row(r) for r in (result or [])], rowcount=rowcount)
        except Exception as e:
            print(f"REST UPDATE error: {e}", flush=True)
            return Cursor([], rowcount=0)

    # ── DELETE ───────────────────────────────────────────────────────────
    def _delete(self, sql, params):
        table = self._table(sql, 'FROM')
        if not table:
            return Cursor([], rowcount=0)

        where_str = self._extract_where(sql)
        if not where_str:
            try:
                result, _ = _rest('DELETE', table)
                return Cursor([], rowcount=0)
            except Exception:
                return Cursor([], rowcount=0)

        filters, _ = self._parse_where(where_str, params, table)
        path = f"{table}?{filters}"

        try:
            result, _ = _rest('DELETE', path)
            rowcount = len(result) if isinstance(result, list) else 0
            return Cursor([], rowcount=rowcount)
        except Exception as e:
            print(f"REST DELETE error: {e}", flush=True)
            return Cursor([], rowcount=0)

    # ── SQL parsing helpers ──────────────────────────────────────────────
    @staticmethod
    def _table(sql, keyword):
        m = re.search(
            rf'{keyword}\s+(\w+)', sql, re.IGNORECASE)
        return m.group(1) if m else None

    @staticmethod
    def _select_cols(sql):
        m = re.match(r'\s*SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        cols = m.group(1).strip()
        if cols == '*':
            return None
        # Clean up aliases and functions
        result = []
        for c in cols.split(','):
            c = c.strip()
            # Handle COUNT(*) → just 'count' for now
            if 'COUNT(*)' in c.upper():
                result.append('count')
            elif 'COUNT(' in c.upper():
                result.append(c.split(' as ')[-1].strip() if ' as ' in c.lower() else 'count')
            else:
                # Strip alias after AS
                if ' as ' in c.lower():
                    c = c.split(' as ')[-1].strip()
                result.append(c)
        return result

    @staticmethod
    def _extract_where(sql):
        # Remove WHERE keyword and everything after ORDER BY / LIMIT / GROUP BY
        m = re.search(r'\bWHERE\b\s+(.+)', sql, re.IGNORECASE | re.DOTALL)
        if not m:
            return ''
        where = m.group(1)
        # Truncate at ORDER BY, LIMIT, GROUP BY
        for term in ['ORDER BY', 'LIMIT', 'GROUP BY', 'OFFSET']:
            idx = re.search(rf'\b{term}\b', where, re.IGNORECASE)
            if idx:
                where = where[:idx.start()]
        # Remove surrounding parentheses
        where = where.strip()
        if where.startswith('(') and where.endswith(')'):
            where = where[1:-1]
        return where.strip()

    def _parse_where(self, where_str, params, table):
        """Parse WHERE clause into PostgREST filter string."""
        if not where_str:
            return '', params

        parts = [p.strip() for p in where_str.split('AND')]
        if not parts:
            return '', params

        filters = []
        params = list(params)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # IS NULL
            m = re.match(r'(\w+)\s+IS\s+NULL', part, re.IGNORECASE)
            if m:
                filters.append(f"{m.group(1)}=is.null")
                continue

            # IS NOT NULL
            m = re.match(r'(\w+)\s+IS\s+NOT\s+NULL', part, re.IGNORECASE)
            if m:
                filters.append(f"{m.group(1)}=not.is.null")
                continue

            # != (not equal)
            m = re.match(r"(\w+)\s*!=\s*'?(\w+)'?", part)
            if m:
                filters.append(f"{m.group(1)}=neq.{m.group(2)}")
                continue

            # IN (?, ?, ?)
            m = re.match(r'(\w+)\s+IN\s*\((.+)\)', part, re.IGNORECASE)
            if m:
                col = m.group(1)
                in_part = m.group(2).strip()
                placeholders = in_part.split(',')
                vals = []
                for p in placeholders:
                    p = p.strip()
                    if p == '?':
                        if params:
                            vals.append(str(params.pop(0)))
                    else:
                        vals.append(p.strip("'"))
                if vals:
                    filters.append(f"{col}=in.({','.join(vals)})")
                continue

            # LIKE ?
            m = re.match(r"(\w+)\s+LIKE\s+\?", part, re.IGNORECASE)
            if m:
                col = m.group(1)
                if params:
                    val = str(params.pop(0))
                    # Convert SQL LIKE %pattern% to PostgREST *pattern*
                    pg_val = urllib.parse.quote(val, safe='')
                    filters.append(f"{col}=like.{pg_val}")
                continue

            # col = ? (parameterized)
            m = re.match(r"(\w+(?:\.\w+)?)\s*=\s*\?", part)
            if m:
                col = m.group(1).split('.')[-1]  # Remove alias
                if params:
                    val = params.pop(0)
                    encoded = urllib.parse.quote(str(val), safe='')
                    filters.append(f"{col}=eq.{encoded}")
                continue

            # col = 'literal'
            m = re.match(r"(\w+(?:\.\w+)?)\s*=\s*'([^']*)'", part)
            if m:
                col = m.group(1).split('.')[-1]
                encoded = urllib.parse.quote(m.group(2), safe='')
                filters.append(f"{col}=eq.{encoded}")
                continue

            # col = literal (unquoted)
            m = re.match(r"(\w+(?:\.\w+)?)\s*=\s*(\S+)", part)
            if m:
                col = m.group(1).split('.')[-1]
                encoded = urllib.parse.quote(m.group(2), safe='')
                filters.append(f"{col}=eq.{encoded}")
                continue

        # Handle OR conditions (for search queries)
        # Check if the original where_str contains OR
        if ' OR ' in where_str.upper():
            # Re-parse with OR
            or_parts = re.split(r'\s+OR\s+', where_str, flags=re.IGNORECASE)
            or_filters = []
            params = list(params)  # Reset params since AND parsing consumed them
            for op in or_parts:
                op = op.strip()
                # col LIKE ?
                m = re.match(r"(\w+)\s+LIKE\s+\?", op, re.IGNORECASE)
                if m and params:
                    col = m.group(1)
                    val = str(params.pop(0))
                    pg_val = urllib.parse.quote(val, safe='')
                    or_filters.append(f"{col}.like.{pg_val}")
                    continue
                # col = ?
                m = re.match(r"(\w+(?:\.\w+)?)\s*=\s*\?", op)
                if m and params:
                    col = m.group(1).split('.')[-1]
                    val = str(params.pop(0))
                    encoded = urllib.parse.quote(val, safe='')
                    or_filters.append(f"{col}.eq.{encoded}")
                    continue
            if or_filters:
                return f"or=({','.join(or_filters)})", params

        return '&'.join(filters), params

    @staticmethod
    def _parse_order_limit_offset(sql, params):
        order = None
        limit = None
        offset = None

        # ORDER BY
        m = re.search(r'ORDER\s+BY\s+(\w+)\s*(ASC|DESC)?', sql, re.IGNORECASE)
        if m:
            col = m.group(1)
            direction = m.group(2)
            order = f"{col}.desc" if (direction and direction.upper() == 'DESC') else f"{col}.asc"

        # LIMIT ? and OFFSET ?
        # They may appear in reverse order in the SQL
        params = list(params)
        limit_idx = sql.upper().find('LIMIT')
        offset_idx = sql.upper().find('OFFSET')

        if limit_idx > -1 and '?' in sql[limit_idx:limit_idx+8]:
            if params:
                limit = int(params.pop(0))
        if offset_idx > -1 and '?' in sql[offset_idx:offset_idx+8]:
            if params:
                offset = int(params.pop(0))

        return order, limit, offset

    def _get_table_columns(self, table):
        """Fetch column names from the table via REST API."""
        try:
            # Fetch one row to get column names
            rows, _ = _rest('GET', f"{table}?select=*&limit=1")
            if rows:
                return list(rows[0].keys())
        except Exception:
            pass
        return []

    @staticmethod
    def sql_up(sql):
        return sql.upper()


# ── Public interface ─────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    """Provide a database connection that mimics sqlite3/psycopg2."""
    conn = _SupaConn()
    try:
        yield conn
    except Exception:
        raise


def init_db():
    """No-op for Supabase: tables are created via SQL Editor."""
    pass
