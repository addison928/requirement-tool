"""Tests for AI merge logic — mocks both DeepSeek and DB."""
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from main import app, _strip_markdown_json
from tests.conftest import make_fake_conn, make_fake_cursor

client = TestClient(app, raise_server_exceptions=False)

# ─── Helper data ─────────────────────────────────────────────────────────────

def _pending_ticket():
    return {
        'id': 'TH-0001', 'flag': '🇹🇭', 'partner_name': 'TH-Test', 'country_id': 'TH',
        'text': 'Need KDS', 'merchant': 'M', 'impact': 'mid',
        'scenes': '["厨显"]', 'biz_type': 'restaurant',
        'time': '2026-05-27 11:00', 'status': 'pending', 'cluster_id': None,
        'attachments': '[]', 'manual': 0, 'lang': 'th'
    }


def _existing_cluster():
    return {
        'id': '#001', 'summary': 'Kitchen Display System',
        'ai_summary': 'KDS requirement summary'
    }


# ─── /api/merge — pre-conditions ─────────────────────────────────────────────

class TestMergePreConditions:
    def test_no_api_key_returns_500(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': ''}, clear=False):
            with patch('main.get_conn', make_fake_conn([[]])):
                r = client.post('/api/merge')
        assert r.status_code == 500
        assert 'DEEPSEEK_API_KEY' in r.text

    def test_no_pending_tickets_returns_zero_counts(self):
        # pending_rows = [], existing_rows = []
        fake = make_fake_conn([[], []])
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('main.get_conn', fake):
                r = client.post('/api/merge')
        assert r.status_code == 200
        data = r.json()
        assert data['merged_into_existing'] == 0
        assert data['created_new'] == 0
        assert data['ticket_count'] == 0
        assert '没有' in data['message']


# ─── /api/merge — DeepSeek response parsing ──────────────────────────────────

class TestMergeDeepSeekParsing:
    def _patch_deepseek(self, content: str):
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = content
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        return patch('main.OpenAI', return_value=mock_client)

    def test_invalid_json_from_deepseek_returns_500(self):
        fake = make_fake_conn([[_pending_ticket()], []])
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('main.get_conn', fake):
                with self._patch_deepseek('not valid json at all'):
                    r = client.post('/api/merge')
        assert r.status_code == 500
        assert 'JSON' in r.text

    def test_non_array_json_from_deepseek_returns_500(self):
        fake = make_fake_conn([[_pending_ticket()], []])
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('main.get_conn', fake):
                with self._patch_deepseek('{"ticket_ids": ["TH-0001"]}'):
                    r = client.post('/api/merge')
        assert r.status_code == 500
        assert '数组' in r.text

    def test_markdown_wrapped_json_is_parsed(self):
        """DeepSeek returns JSON wrapped in ```json fences — should still parse."""
        payload = json.dumps([{
            'ticket_ids': ['TH-0001'],
            'summary': 'KDS系统', 'layer': 'saas', 'impact': 'mid', 'ai_summary': 'test'
        }])
        wrapped = f"```json\n{payload}\n```"
        # For merge: pending=[ticket], existing=[], cluster id generation, then inserts
        fake = make_fake_conn([
            [_pending_ticket()], [],     # pending + existing fetch
            [],                          # _next_cluster_ids SELECT
            [], [],                      # UPDATE ticket, INSERT cluster_ticket
        ])
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('main.get_conn', fake):
                with self._patch_deepseek(wrapped):
                    r = client.post('/api/merge')
        assert r.status_code == 200


# ─── /api/merge — create new cluster ─────────────────────────────────────────

class TestMergeCreateNew:
    def _patch_deepseek_new(self, ticket_ids, summary='New Feature', layer='saas',
                             impact='high', ai_summary='详细分析'):
        payload = json.dumps([{
            'ticket_ids': ticket_ids, 'summary': summary,
            'layer': layer, 'impact': impact, 'ai_summary': ai_summary
        }])
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = payload
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        return patch('main.OpenAI', return_value=mock_client)

    def test_create_new_cluster_returns_created_count(self):
        fake = make_fake_conn([
            [_pending_ticket()], [],     # pending + existing
            [],                          # _next_cluster_ids
            [], [],                      # UPDATE ticket, INSERT cluster_ticket
        ])
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('main.get_conn', fake):
                with self._patch_deepseek_new(['TH-0001']):
                    r = client.post('/api/merge')
        assert r.status_code == 200
        data = r.json()
        assert data['created_new'] == 1
        assert data['merged_into_existing'] == 0
        assert data['ticket_count'] == 1

    def test_create_new_cluster_with_no_matched_tickets_still_ok(self):
        """If DeepSeek references ticket IDs not in pending list, cluster is created with 0 tickets."""
        payload = json.dumps([{
            'ticket_ids': ['GHOST-9999'],
            'summary': 'Ghost cluster', 'layer': 'saas', 'impact': 'low', 'ai_summary': 'x'
        }])
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = payload
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        fake = make_fake_conn([
            [_pending_ticket()], [],     # pending + existing
            [],                          # _next_cluster_ids
        ])
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('main.get_conn', fake):
                with patch('main.OpenAI', return_value=mock_client):
                    r = client.post('/api/merge')
        assert r.status_code == 200
        assert r.json()['created_new'] == 1


# ─── /api/merge — merge into existing cluster ────────────────────────────────

class TestMergeIntoExisting:
    def _patch_deepseek_existing(self, ticket_ids, cluster_id):
        payload = json.dumps([{
            'ticket_ids': ticket_ids,
            'existing_cluster_id': cluster_id
        }])
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = payload
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        return patch('main.OpenAI', return_value=mock_client)

    def test_merge_into_existing_valid_cluster(self):
        existing_cluster = _existing_cluster()
        # pending tickets, existing clusters for DeepSeek context
        # then inside the merge loop: validate cluster exists, UPDATE ticket, INSERT cluster_ticket,
        # SELECT all tickets for metadata recalculation, UPDATE clusters
        ticket_row_for_metadata = {
            'country_id': 'TH', 'partner_name': 'TH-Test', 'impact': 'mid'
        }
        fake = make_fake_conn([
            [_pending_ticket()],           # pending
            [existing_cluster],            # existing clusters for DeepSeek
            [existing_cluster],            # validate existing_cluster_id exists
            [], [],                        # UPDATE ticket, INSERT cluster_ticket
            [ticket_row_for_metadata],     # SELECT for metadata recalc
            [],                            # UPDATE clusters metadata
        ])
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('main.get_conn', fake):
                with self._patch_deepseek_existing(['TH-0001'], '#001'):
                    r = client.post('/api/merge')
        assert r.status_code == 200
        data = r.json()
        assert data['merged_into_existing'] == 1
        assert data['created_new'] == 0

    def test_merge_into_nonexistent_cluster_is_skipped(self):
        """Bug fix: hallucinated cluster IDs from DeepSeek must be skipped silently."""
        existing_cluster = _existing_cluster()
        # validate returns empty (cluster #999 does not exist)
        fake = make_fake_conn([
            [_pending_ticket()],   # pending
            [existing_cluster],    # existing clusters for DeepSeek
            [],                    # SELECT 1 FROM clusters WHERE id='#999' → not found
        ])
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('main.get_conn', fake):
                with self._patch_deepseek_existing(['TH-0001'], '#999'):
                    r = client.post('/api/merge')
        assert r.status_code == 200
        data = r.json()
        # Should complete without error but NOT write data for the hallucinated cluster
        assert data['merged_into_existing'] == 1  # counted in response (based on LLM output length)
        # Crucially: ticket should NOT be updated (rowcount stays 0 since we skipped)

    def test_merge_skips_when_no_matching_tickets(self):
        """If existing_cluster_id given but ticket_ids don't match pending, skip."""
        existing_cluster = _existing_cluster()
        payload = json.dumps([{'ticket_ids': [], 'existing_cluster_id': '#001'}])
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = payload
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        fake = make_fake_conn([
            [_pending_ticket()],   # pending
            [existing_cluster],    # existing
        ])
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'sk-test'}):
            with patch('main.get_conn', fake):
                with patch('main.OpenAI', return_value=mock_client):
                    r = client.post('/api/merge')
        assert r.status_code == 200
