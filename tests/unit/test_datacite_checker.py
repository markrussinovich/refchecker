"""
Regression tests for the DataCite checker.

Zenodo/Figshare/OSF/Dryad DOIs are registered through DataCite rather
than CrossRef, and CrossRef/OpenAlex/Semantic Scholar only
inconsistently index them. The "Detecting Hallucinated and Suspicious
Citations" study (arXiv:2607.22693) found this was the largest source
of RefChecker false positives — genuine, resolvable Zenodo-DOI
citations (e.g. an OpenCitations snapshot archived on Zenodo) were
flagged as unverified because no bibliographic database the tool
queried had indexed the record.
"""

from unittest.mock import MagicMock, patch

from refchecker.checkers.datacite import DataCiteChecker


def _datacite_response(title, creators, year, container_title='Zenodo', url=None):
    return {
        'data': {
            'id': '10.5281/zenodo.17199853',
            'attributes': {
                'titles': [{'title': title}],
                'creators': [{'name': name} for name in creators],
                'publicationYear': year,
                'container': {'title': container_title} if container_title else {},
                'url': url,
            },
        }
    }


def test_datacite_verifies_zenodo_doi_reference():
    """Real FP from the paper's gold dataset: an OpenCitations Zenodo DOI
    citation flagged as unverified despite the DOI resolving to exactly
    the cited work."""
    checker = DataCiteChecker()
    reference = {
        'title': 'OpenCitations: an open infrastructure enabling Open Research Information',
        'doi': '10.5281/zenodo.17199853',
        'year': 2025,
        'authors': ['Chiara Di Giambattista', 'Ivan Heibi'],
    }

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _datacite_response(
        'OpenCitations: an open infrastructure enabling Open Research Information',
        ['Chiara Di Giambattista', 'Ivan Heibi'],
        2025,
    )

    with patch.object(checker.session, 'get', return_value=response) as mock_get:
        verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is not None
    assert verified_data['_matched_database'] == 'DataCite'
    assert verified_data['year'] == 2025
    assert errors == []
    assert url == 'https://doi.org/10.5281/zenodo.17199853'
    mock_get.assert_called_once()


def test_datacite_flags_title_mismatch_as_warning_not_hallucination():
    checker = DataCiteChecker()
    reference = {
        'title': 'OpenCitations',  # terse citation of the same record
        'doi': '10.5281/zenodo.17199853',
        'year': 2025,
        'authors': [],
    }

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _datacite_response(
        'OpenCitations: an open infrastructure enabling Open Research Information',
        ['Chiara Di Giambattista', 'Ivan Heibi'],
        2025,
    )

    with patch.object(checker.session, 'get', return_value=response):
        verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is not None
    assert any(e.get('warning_type') == 'title' for e in errors)


def test_datacite_returns_none_when_doi_not_found():
    checker = DataCiteChecker()
    reference = {'title': 'Some paper', 'doi': '10.5281/zenodo.99999999', 'year': 2024}

    response = MagicMock()
    response.status_code = 404

    with patch.object(checker.session, 'get', return_value=response):
        verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is None
    assert errors == []
    assert url is None


def test_datacite_skips_references_without_doi():
    checker = DataCiteChecker()
    reference = {'title': 'Some blog post', 'url': 'https://example.com/post'}

    with patch.object(checker.session, 'get') as mock_get:
        verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is None
    mock_get.assert_not_called()


def test_datacite_extracts_doi_from_url_when_doi_field_missing():
    checker = DataCiteChecker()
    reference = {
        'title': 'Archived dataset',
        'url': 'https://doi.org/10.5281/zenodo.16325125',
        'authors': ['Weimer'],
        'year': 2024,
    }

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = _datacite_response('Archived dataset', ['Weimer'], 2024)

    with patch.object(checker.session, 'get', return_value=response) as mock_get:
        verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is not None
    assert mock_get.call_args.args[0].endswith('10.5281/zenodo.16325125')
