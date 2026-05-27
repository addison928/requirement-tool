import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from contextlib import contextmanager
from unittest.mock import MagicMock


def make_fake_cursor(rows=None, rowcount=1):
    cur = MagicMock()
    cur.fetchone.return_value = rows[0] if rows else None
    cur.fetchall.return_value = rows or []
    cur.rowcount = rowcount
    cur.__iter__ = lambda self: iter(self.fetchall())
    return cur


def make_fake_conn(side_effects=None):
    """
    Returns a context-manager factory that yields a fake conn.
    side_effects: list of cursor return values, popped in order per execute() call.
    If exhausted, returns an empty cursor.
    """
    effects = list(side_effects or [])

    class FakeConn:
        def execute(self, sql, params=()):
            if effects:
                val = effects.pop(0)
                if isinstance(val, list):
                    return make_fake_cursor(val)
                return val  # allow passing a pre-built cursor
            return make_fake_cursor([])

        def executemany(self, sql, params_list):
            return make_fake_cursor([])

    @contextmanager
    def _ctx():
        yield FakeConn()

    return _ctx
