"""CrossRef must return the same metadata shape from every lookup path.

CrossRef's API wraps several fields in lists even when there is only one value:
`"title": ["Attention Is All You Need"]`. The title-search and bibliographic-search
paths unwrapped this before matching, but the DOI lookup returned the raw
`message`, so a DOI-verified reference carried a list in `title`.

That value is copied into the "corrected reference" shown to the user, where it
rendered literally as `['Attention Is All You Need']`, and any consumer calling
a string method on it raises `AttributeError`.
"""

from unittest.mock import patch

import pytest

from refchecker.checkers.crossref import CrossRefReferenceChecker, _normalize_crossref_work

# A realistic CrossRef `message` payload, with the list-valued fields intact.
RAW_MESSAGE = {
    'DOI': '10.1109/5.771073',
    'title': ['Toward unique identifiers'],
    'container-title': ['Proceedings of the IEEE'],
    'short-container-title': ['Proc. IEEE'],
    'subtitle': [],
    'author': [{'given': 'N.', 'family': 'Paskin'}],
    'issued': {'date-parts': [[1999, 7]]},
    'URL': 'http://dx.doi.org/10.1109/5.771073',
}


class TestNormalizer:
    def test_single_element_lists_become_strings(self):
        out = _normalize_crossref_work(RAW_MESSAGE)
        assert out['title'] == 'Toward unique identifiers'
        assert out['container-title'] == 'Proceedings of the IEEE'
        assert out['short-container-title'] == 'Proc. IEEE'

    def test_empty_lists_become_empty_strings(self):
        assert _normalize_crossref_work(RAW_MESSAGE)['subtitle'] == ''

    def test_non_list_values_are_untouched(self):
        out = _normalize_crossref_work({'title': 'Already A String', 'DOI': '10.1/x'})
        assert out['title'] == 'Already A String'
        assert out['DOI'] == '10.1/x'

    def test_unrelated_fields_survive(self):
        out = _normalize_crossref_work(RAW_MESSAGE)
        assert out['author'] == RAW_MESSAGE['author']
        assert out['URL'] == RAW_MESSAGE['URL']

    def test_input_is_not_mutated(self):
        payload = {'title': ['A Title']}
        _normalize_crossref_work(payload)
        assert payload['title'] == ['A Title']

    @pytest.mark.parametrize('falsy', [None, {}])
    def test_missing_work_passes_through(self, falsy):
        assert _normalize_crossref_work(falsy) == falsy


class TestDoiLookupShape:
    def _checker(self):
        c = CrossRefReferenceChecker()
        c.cache_dir = None
        return c

    def test_doi_path_returns_a_string_title(self):
        checker = self._checker()
        with patch.object(checker, '_get_work_by_doi_uncached', return_value=dict(RAW_MESSAGE)):
            work = checker.get_work_by_doi('10.1109/5.771073')
        assert isinstance(work['title'], str)
        assert work['title'].strip() == 'Toward unique identifiers'

    def test_a_cached_raw_response_is_normalized_too(self):
        """Entries written to the API cache before this fix still hold lists."""
        checker = self._checker()
        with patch('refchecker.utils.cache_utils.cached_api_response',
                   return_value=dict(RAW_MESSAGE)):
            work = checker.get_work_by_doi('10.1109/5.771073')
        assert isinstance(work['title'], str)

    def test_verified_title_can_be_used_as_a_correction(self):
        """The exact downstream use: copying the canonical title into the
        corrected reference shown to the user."""
        checker = self._checker()
        with patch.object(checker, '_get_work_by_doi_uncached', return_value=dict(RAW_MESSAGE)):
            verified, _errors, _url = checker.verify_reference({
                'title': 'Toward unique identifiers',
                'authors': [],
                'year': 1999,
                'doi': '10.1109/5.771073',
            })
        corrected = {'title': verified['title']}
        assert corrected['title'] == 'Toward unique identifiers'
        assert '[' not in str(corrected['title'])
