"""Tests for bulk pipeline checkpoint/resume support."""

import json
import os
import tempfile

import pytest

from refchecker.core.bulk_pipeline import (
    BulkPaperResult,
    _get_checkpoint_path,
    _load_checkpoint,
    _save_checkpoint,
)


def _make_result(index: int, input_spec: str, **overrides) -> BulkPaperResult:
    defaults = dict(
        index=index,
        input_spec=input_spec,
        paper_id=f'paper-{index}',
        title=f'Paper {index}',
        source_url=input_spec,
        elapsed_seconds=10.0,
        references_processed=5,
        total_errors_found=1,
        total_warnings_found=0,
        total_info_found=0,
        total_unverified_refs=0,
        total_arxiv_refs=2,
        total_non_arxiv_refs=3,
        total_other_refs=0,
        papers_with_errors=1,
        papers_with_warnings=0,
        papers_with_info=0,
        errors=[{'error_type': 'year', 'error_details': 'off by one'}],
        fatal_error=False,
        fatal_error_message=None,
        used_regex_extraction=False,
        used_unreliable_extraction=False,
    )
    defaults.update(overrides)
    return BulkPaperResult(**defaults)


# --- _get_checkpoint_path ---

class TestGetCheckpointPath:
    def test_returns_none_when_no_report_file(self):
        assert _get_checkpoint_path(None) is None

    def test_returns_none_for_empty_string(self):
        assert _get_checkpoint_path('') is None

    def test_replaces_json_extension(self):
        assert _get_checkpoint_path('/some/dir/report.json') == '/some/dir/report.checkpoint.jsonl'

    def test_replaces_csv_extension(self):
        assert _get_checkpoint_path('results.csv') == 'results.checkpoint.jsonl'

    def test_appends_to_extensionless_file(self):
        assert _get_checkpoint_path('results') == 'results.checkpoint.jsonl'


# --- _save_checkpoint / _load_checkpoint round-trip ---

class TestCheckpointRoundTrip:
    def test_save_and_load_single_result(self, tmp_path):
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        specs = ['https://example.com/paper-0']
        result = _make_result(0, specs[0])

        _save_checkpoint(cp, result)
        loaded = _load_checkpoint(cp, specs)

        assert len(loaded) == 1
        assert loaded[0].index == 0
        assert loaded[0].input_spec == specs[0]
        assert loaded[0].paper_id == 'paper-0'
        assert loaded[0].references_processed == 5

    def test_save_and_load_multiple_results(self, tmp_path):
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        specs = ['spec-0', 'spec-1', 'spec-2']

        _save_checkpoint(cp, _make_result(0, 'spec-0'))
        _save_checkpoint(cp, _make_result(2, 'spec-2'))

        loaded = _load_checkpoint(cp, specs)

        assert set(loaded.keys()) == {0, 2}
        assert loaded[0].input_spec == 'spec-0'
        assert loaded[2].input_spec == 'spec-2'

    def test_preserves_errors_list(self, tmp_path):
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        specs = ['spec-0']
        errors = [
            {'error_type': 'year', 'error_details': 'off by one'},
            {'error_type': 'title', 'error_details': 'mismatch'},
        ]
        result = _make_result(0, 'spec-0', errors=errors)
        _save_checkpoint(cp, result)

        loaded = _load_checkpoint(cp, specs)
        assert loaded[0].errors == errors

    def test_preserves_fatal_error_fields(self, tmp_path):
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        specs = ['spec-0']
        result = _make_result(0, 'spec-0', fatal_error=True, fatal_error_message='boom')
        _save_checkpoint(cp, result)

        loaded = _load_checkpoint(cp, specs)
        assert loaded[0].fatal_error is True
        assert loaded[0].fatal_error_message == 'boom'


# --- _load_checkpoint validation ---

class TestLoadCheckpointValidation:
    def test_returns_empty_when_file_missing(self, tmp_path):
        cp = str(tmp_path / 'nonexistent.checkpoint.jsonl')
        loaded = _load_checkpoint(cp, ['spec-0'])
        assert loaded == {}

    def test_returns_empty_for_none_path(self):
        loaded = _load_checkpoint(None, ['spec-0'])
        assert loaded == {}

    def test_ignores_mismatched_spec(self, tmp_path):
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        _save_checkpoint(cp, _make_result(0, 'old-spec'))

        loaded = _load_checkpoint(cp, ['new-spec'])
        assert loaded == {}

    def test_ignores_out_of_range_index(self, tmp_path):
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        _save_checkpoint(cp, _make_result(5, 'spec-5'))

        # Only 2 specs in the list, index 5 is out of range
        loaded = _load_checkpoint(cp, ['spec-0', 'spec-1'])
        assert loaded == {}

    def test_ignores_index_with_wrong_spec(self, tmp_path):
        """Index exists but spec at that index doesn't match."""
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        _save_checkpoint(cp, _make_result(0, 'spec-A'))

        # Same index but different spec
        loaded = _load_checkpoint(cp, ['spec-B'])
        assert loaded == {}

    def test_handles_corrupt_json(self, tmp_path):
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        with open(cp, 'w') as f:
            f.write('{"index": 0, "input_spec": "s"\n')  # valid JSON but missing fields
            f.write('not valid json\n')
        loaded = _load_checkpoint(cp, ['s'])
        assert loaded == {}

    def test_skips_blank_lines(self, tmp_path):
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        specs = ['spec-0']
        _save_checkpoint(cp, _make_result(0, 'spec-0'))
        # Append blank lines
        with open(cp, 'a') as f:
            f.write('\n\n\n')

        loaded = _load_checkpoint(cp, specs)
        assert len(loaded) == 1
        assert loaded[0].input_spec == 'spec-0'

    def test_partial_checkpoint_loads_valid_entries(self, tmp_path):
        """A checkpoint with some valid and some stale entries loads only valid ones."""
        cp = str(tmp_path / 'test.checkpoint.jsonl')
        specs = ['spec-0', 'spec-1', 'spec-2']

        _save_checkpoint(cp, _make_result(0, 'spec-0'))
        _save_checkpoint(cp, _make_result(1, 'WRONG-spec'))  # stale
        _save_checkpoint(cp, _make_result(2, 'spec-2'))

        loaded = _load_checkpoint(cp, specs)
        assert set(loaded.keys()) == {0, 2}
