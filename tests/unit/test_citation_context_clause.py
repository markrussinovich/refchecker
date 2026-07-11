"""Regression: bracket-style citation contexts isolate the clause containing the
marker (no table/caption bleed) and never drop or over-trim a context."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from backend.refchecker_wrapper import _extract_clause_containing_marker, _attach_citation_contexts  # noqa: E402


def test_clause_isolates_marker_drops_table_bleed():
    s = ('The Charlson Comorbidity Index was calculated and categorized [15]. '
         'Table 2 Baseline characteristics of patients undergoing surgery (N = 1733)')
    out = _extract_clause_containing_marker(s, '[15]')
    assert out == 'The Charlson Comorbidity Index was calculated and categorized [15].'


def test_clause_fallback_when_marker_absent_or_short():
    full = 'A normal sentence without the target marker present here.'
    assert _extract_clause_containing_marker(full, '[9]') == full


def test_contexts_still_attach_after_clause_change():
    body = 'Hip fractures are common [1]. Delay worsens outcomes [2]. The index was used [3]. ' * 3
    refs = [{'index': i + 1, 'title': f'R{i+1}', 'authors': ['X Y'], 'year': 2020} for i in range(10)]
    _attach_citation_contexts(refs, body)
    assert sum(1 for r in refs if r.get('citation_contexts')) == 3
    assert refs[0]['citation_contexts'][0]['sentence'] == 'Hip fractures are common [1].'
