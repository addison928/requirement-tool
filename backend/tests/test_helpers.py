"""Unit tests for pure helper functions — no DB, no HTTP."""
import json
import re
import pytest
from unittest.mock import patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from main import parse_json_field, generate_token, _strip_markdown_json, _next_cluster_ids
from tests.conftest import make_fake_conn


# ── parse_json_field ─────────────────────────────────────────────────────────

class TestParseJsonField:
    def test_valid_list(self):
        assert parse_json_field('["a","b"]', []) == ["a", "b"]

    def test_valid_dict(self):
        assert parse_json_field('{"k":1}', {}) == {"k": 1}

    def test_empty_list_string(self):
        assert parse_json_field('[]', []) == []

    def test_invalid_string_returns_default(self):
        assert parse_json_field('not-json', []) == []

    def test_none_returns_default(self):
        assert parse_json_field(None, ["default"]) == ["default"]

    def test_empty_string_returns_default(self):
        assert parse_json_field('', []) == []

    def test_partial_json_returns_default(self):
        assert parse_json_field('[1,2,', []) == []


# ── generate_token ────────────────────────────────────────────────────────────

class TestGenerateToken:
    def test_format_two_char(self):
        token = generate_token("TH")
        assert re.match(r'^TH_[a-zA-Z0-9]{8}$', token), f"Bad format: {token}"

    def test_format_three_char(self):
        token = generate_token("KHM")
        assert re.match(r'^KHM_[a-zA-Z0-9]{8}$', token), f"Bad format: {token}"

    def test_uniqueness(self):
        tokens = {generate_token("IT") for _ in range(20)}
        assert len(tokens) > 1  # should not all be identical


# ── _strip_markdown_json ──────────────────────────────────────────────────────

class TestStripMarkdownJson:
    def test_multiline_fence(self):
        raw = "```json\n[{\"a\":1}]\n```"
        result = _strip_markdown_json(raw)
        assert result == '[{"a":1}]'

    def test_no_fence(self):
        raw = '[{"a":1}]'
        assert _strip_markdown_json(raw) == '[{"a":1}]'

    def test_inline_fence(self):
        raw = "```json[{\"x\":2}]```"
        result = _strip_markdown_json(raw)
        assert result == '[{"x":2}]'

    def test_plain_fence_no_lang(self):
        raw = "```\n[1,2,3]\n```"
        result = _strip_markdown_json(raw)
        assert result == '[1,2,3]'

    def test_extra_whitespace_stripped(self):
        raw = "  ```json\n  []\n  ```  "
        result = _strip_markdown_json(raw)
        assert result == '[]'

    def test_parseable_after_strip(self):
        raw = "```json\n[{\"ticket_ids\":[\"TH-001\"]}]\n```"
        result = json.loads(_strip_markdown_json(raw))
        assert result[0]["ticket_ids"] == ["TH-001"]


# ── _next_cluster_ids ─────────────────────────────────────────────────────────

class TestNextClusterIds:
    def _make_rows(self, ids):
        return [{"id": i} for i in ids]

    def test_empty_db_starts_at_001(self):
        ctx = make_fake_conn([[]])
        with ctx() as conn:
            result = _next_cluster_ids(conn, 1)
        assert result == ['#001']

    def test_existing_clusters_continue_sequence(self):
        rows = self._make_rows(['#001', '#002', '#005'])
        ctx = make_fake_conn([rows])
        with ctx() as conn:
            result = _next_cluster_ids(conn, 2)
        assert result == ['#006', '#007']

    def test_count_three(self):
        rows = self._make_rows(['#010'])
        ctx = make_fake_conn([rows])
        with ctx() as conn:
            result = _next_cluster_ids(conn, 3)
        assert result == ['#011', '#012', '#013']

    def test_non_numeric_ids_ignored(self):
        rows = self._make_rows(['#001', '#abc', 'NO_HASH'])
        ctx = make_fake_conn([rows])
        with ctx() as conn:
            result = _next_cluster_ids(conn, 1)
        assert result == ['#002']

    def test_zero_count_returns_empty(self):
        ctx = make_fake_conn([[]])
        with ctx() as conn:
            result = _next_cluster_ids(conn, 0)
        assert result == []
