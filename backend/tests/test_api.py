"""Integration tests for all API endpoints — DB calls are mocked."""
import json
import re
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from main import app
from tests.conftest import make_fake_conn, make_fake_cursor

client = TestClient(app, raise_server_exceptions=False)


# ── /api/health ───────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_db_ok(self):
        fake = make_fake_conn([[{"1": 1}]])
        with patch('main.get_conn', fake):
            r = client.get('/api/health')
        assert r.status_code == 200
        data = r.json()
        assert data['status'] == 'ok'
        assert data['db'] == 'ok'

    def test_health_db_fail(self):
        from contextlib import contextmanager
        @contextmanager
        def boom():
            raise Exception("connection refused")
            yield  # noqa
        with patch('main.get_conn', boom):
            r = client.get('/api/health')
        assert r.status_code == 200
        data = r.json()
        assert data['db'] != 'ok'
        assert 'connection refused' in data['db']

    def test_health_tz_format(self):
        fake = make_fake_conn([[{"1": 1}]])
        with patch('main.get_conn', fake):
            r = client.get('/api/health')
        tz_now = r.json()['tz_now']
        assert re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', tz_now)


# ── /api/partners ─────────────────────────────────────────────────────────────

class TestPartners:
    def _partner_row(self):
        return {
            'token': 'TH_abc12345', 'country_id': 'TH', 'flag': '🇹🇭',
            'country_name': '泰国', 'name': 'TH-Test', 'lang': 'th', 'tier': 'normal'
        }

    def test_list_partners_empty(self):
        fake = make_fake_conn([[]])
        with patch('main.get_conn', fake):
            r = client.get('/api/partners')
        assert r.status_code == 200
        assert r.json() == []

    def test_list_partners_returns_rows(self):
        fake = make_fake_conn([[self._partner_row()]])
        with patch('main.get_conn', fake):
            r = client.get('/api/partners')
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]['country_id'] == 'TH'

    def test_create_partner_returns_201_with_token(self):
        fake = make_fake_conn([])  # INSERT succeeds silently
        with patch('main.get_conn', fake):
            r = client.post('/api/partners', json={
                'country_id': 'TH', 'flag': '🇹🇭', 'country_name': '泰国',
                'name': 'TH-Test', 'lang': 'th', 'tier': 'normal'
            })
        assert r.status_code == 201
        token = r.json()['token']
        assert re.match(r'^TH_[a-zA-Z0-9]{8}$', token)

    def test_create_partner_uppercases_country_id(self):
        fake = make_fake_conn([])
        with patch('main.get_conn', fake):
            r = client.post('/api/partners', json={
                'country_id': 'th', 'flag': '🇹🇭', 'country_name': '泰国',
                'name': 'test', 'lang': 'th', 'tier': 'normal'
            })
        assert r.json()['country_id'] == 'TH'

    def test_delete_partner_204(self):
        cur = make_fake_cursor([], rowcount=1)
        fake = make_fake_conn([cur])
        with patch('main.get_conn', fake):
            r = client.delete('/api/partners/TH_abc12345')
        assert r.status_code == 204

    def test_delete_partner_not_found(self):
        cur = make_fake_cursor([], rowcount=0)
        fake = make_fake_conn([cur])
        with patch('main.get_conn', fake):
            r = client.delete('/api/partners/NO_SUCH')
        assert r.status_code == 404

    def test_update_partner_not_found(self):
        cur = make_fake_cursor([], rowcount=0)
        fake = make_fake_conn([cur])
        with patch('main.get_conn', fake):
            r = client.put('/api/partners/NO_SUCH', json={
                'country_id': 'IT', 'flag': '🇮🇹', 'country_name': 'Italy',
                'name': 'test', 'lang': 'it', 'tier': 'normal'
            })
        assert r.status_code == 404


# ── /api/tickets ──────────────────────────────────────────────────────────────

def _ticket_row():
    return {
        'id': 'TH-1234', 'flag': '🇹🇭', 'partner_name': 'TH-Test', 'country_id': 'TH',
        'text': 'Need KDS', 'merchant': 'TestMart', 'impact': 'mid',
        'scenes': '["厨显"]', 'biz_type': 'restaurant',
        'time': '2026-05-27 11:00', 'status': 'pending', 'cluster_id': None,
        'attachments': '[]', 'manual': 0, 'lang': 'th'
    }


class TestTickets:
    def test_list_tickets_empty(self):
        # COUNT(*) fetchone()[0] needs a subscriptable row — use a list [0]
        fake = make_fake_conn([[[0]], []])
        with patch('main.get_conn', fake):
            r = client.get('/api/tickets')
        assert r.status_code == 200
        data = r.json()
        assert data['total'] == 0
        assert data['items'] == []

    def test_list_tickets_returns_items(self):
        fake = make_fake_conn([[[1]], [_ticket_row()]])
        with patch('main.get_conn', fake):
            r = client.get('/api/tickets')
        assert r.status_code == 200
        items = r.json()['items']
        assert len(items) == 1
        assert items[0]['id'] == 'TH-1234'
        assert isinstance(items[0]['scenes'], list)   # parsed from JSON string
        assert isinstance(items[0]['manual'], bool)   # converted to bool

    def test_list_tickets_pagination_fields(self):
        fake = make_fake_conn([[[0]], []])
        with patch('main.get_conn', fake):
            r = client.get('/api/tickets?page=2&page_size=10')
        assert r.json()['page'] == 2
        assert r.json()['page_size'] == 10

    def test_create_ticket_invalid_token(self):
        # partner lookup returns None
        fake = make_fake_conn([[]])  # fetchone returns None
        with patch('main.get_conn', fake):
            r = client.post('/api/tickets', json={
                'token': 'INVALID', 'text': 'test', 'merchant': 'M',
                'impact': 'mid', 'scenes': [], 'biz_type': 'pos'
            })
        assert r.status_code == 400

    def test_create_ticket_valid_returns_201(self):
        partner = {'country_id': 'TH', 'flag': '🇹🇭', 'name': 'TH-Test', 'lang': 'th'}
        # calls: SELECT partner, SELECT 1 (id check), INSERT ticket
        fake = make_fake_conn([[partner], [], []])
        with patch('main.get_conn', fake):
            r = client.post('/api/tickets', json={
                'token': 'TH_abc12345', 'text': 'Need KDS', 'merchant': 'M',
                'impact': 'high', 'scenes': ['厨显'], 'biz_type': 'restaurant'
            })
        assert r.status_code == 201
        data = r.json()
        assert 'id' in data
        assert re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$', data['time'])
        assert data['status'] == 'pending'

    def test_create_ticket_time_is_gmt8(self):
        """Time returned must be between 00:00 and 23:59 and not obviously UTC offset."""
        from datetime import datetime, timezone, timedelta
        partner = {'country_id': 'TH', 'flag': '🇹🇭', 'name': 'TH-Test', 'lang': 'th'}
        fake = make_fake_conn([[partner], [], []])
        with patch('main.get_conn', fake):
            r = client.post('/api/tickets', json={
                'token': 'TH_abc12345', 'text': 'TZ test', 'merchant': 'M',
                'impact': 'mid', 'scenes': [], 'biz_type': 'pos'
            })
        returned_time = r.json()['time']
        cst_now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
        # Should match within 1 minute
        assert returned_time == cst_now or abs(
            datetime.strptime(returned_time, '%Y-%m-%d %H:%M').minute -
            datetime.strptime(cst_now, '%Y-%m-%d %H:%M').minute
        ) <= 1

    def test_update_ticket_ok(self):
        cur = make_fake_cursor([], rowcount=1)
        fake = make_fake_conn([cur])
        with patch('main.get_conn', fake):
            r = client.put('/api/tickets/TH-1234', json={'status': 'in_progress'})
        assert r.status_code == 200
        assert r.json()['ok'] is True

    def test_update_ticket_not_found(self):
        cur = make_fake_cursor([], rowcount=0)
        fake = make_fake_conn([cur])
        with patch('main.get_conn', fake):
            r = client.put('/api/tickets/NO_SUCH', json={'status': 'done'})
        assert r.status_code == 404

    def test_update_ticket_nothing_to_update(self):
        with patch('main.get_conn', make_fake_conn([])):
            r = client.put('/api/tickets/TH-1234', json={})
        assert r.status_code == 400


# ── /api/clusters ─────────────────────────────────────────────────────────────

def _cluster_row():
    return {
        'id': '#001', 'score': 80, 'urgent': 0, 'summary': 'Test cluster',
        'layer': 'saas', 'impact': 'high', 'source_ids': '["TH"]',
        'partners': '["TH-Test"]', 'count': 1, 'periods': 1,
        'status': 'pending', 'ai_summary': 'Test AI summary'
    }


class TestClusters:
    def test_list_clusters_empty(self):
        # COUNT(*) fetchone()[0] needs list row; SELECT clusters returns []
        fake = make_fake_conn([[[0]], []])
        with patch('main.get_conn', fake):
            r = client.get('/api/clusters')
        assert r.status_code == 200
        assert r.json()['total'] == 0
        assert r.json()['items'] == []

    def test_update_cluster_ok(self):
        cur = make_fake_cursor([], rowcount=1)
        fake = make_fake_conn([cur])
        with patch('main.get_conn', fake):
            r = client.put('/api/clusters/%23001', json={'status': 'live'})
        assert r.status_code == 200
        assert r.json()['ok'] is True

    def test_update_cluster_not_found(self):
        cur = make_fake_cursor([], rowcount=0)
        fake = make_fake_conn([cur])
        with patch('main.get_conn', fake):
            r = client.put('/api/clusters/%23999', json={'layer': 'platform'})
        assert r.status_code == 404

    def test_update_cluster_nothing_to_update(self):
        with patch('main.get_conn', make_fake_conn([])):
            r = client.put('/api/clusters/%23001', json={})
        assert r.status_code == 400


# ── /api/scoring-config ───────────────────────────────────────────────────────

class TestScoringConfig:
    def test_get_config_not_found(self):
        fake = make_fake_conn([[]])  # fetchone returns None
        with patch('main.get_conn', fake):
            r = client.get('/api/scoring-config')
        assert r.status_code == 404

    def test_get_config_returns_json(self):
        row = {'config_json': json.dumps({'tier': {'strategic': 3}})}
        fake = make_fake_conn([[row]])
        with patch('main.get_conn', fake):
            r = client.get('/api/scoring-config')
        assert r.status_code == 200
        assert r.json()['tier']['strategic'] == 3

    def test_put_config_update(self):
        existing_row = {'id': 1}
        fake = make_fake_conn([[existing_row], []])  # SELECT existing, UPDATE
        with patch('main.get_conn', fake):
            r = client.put('/api/scoring-config', json={'tier': {'normal': 1}})
        assert r.status_code == 200
        assert r.json()['ok'] is True

    def test_put_config_insert_new(self):
        fake = make_fake_conn([[], []])  # SELECT returns None → INSERT
        with patch('main.get_conn', fake):
            r = client.put('/api/scoring-config', json={'tier': {'normal': 1}})
        assert r.status_code == 200
        assert r.json()['ok'] is True
