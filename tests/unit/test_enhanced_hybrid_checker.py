from copy import deepcopy
from unittest.mock import Mock, patch

import pytest
import requests

from refchecker.checkers.arxiv_citation import ArXivCitationChecker
from refchecker.checkers.crossref import CrossRefReferenceChecker
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker


class NoMatchChecker:
    def verify_reference(self, reference):
        return None, [], None


class TimeoutChecker:
    def verify_reference(self, reference):
        raise requests.exceptions.Timeout('simulated timeout')


class LocalMatchChecker:
    database_label = "Semantic Scholar"
    database_key = "local_s2"

    def verify_reference(self, reference):
        return (
            {
                "title": reference.get("title", ""),
                "paperId": "s2-match-id",
            },
            [],
            "https://www.semanticscholar.org/paper/s2-match-id",
        )


class LocalArxivMismatchChecker:
    database_label = "Semantic Scholar"
    database_key = "local_s2"

    def verify_reference(self, reference):
        return (
            {
                "title": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                "authors": [
                    {"name": "Fengjun Pan"},
                    {"name": "Xiaobao Wu"},
                    {"name": "Tho Quan"},
                    {"name": "Anh Tuan Luu"},
                ],
                "year": 2025,
                "externalIds": {"ArXiv": "2506.08477"},
            },
            [
                {
                    "error_type": "title",
                    "error_details": "Title mismatch",
                    "ref_title_correct": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                },
                {
                    "error_type": "author",
                    "error_details": "Author count mismatch: 3 cited vs 4 correct",
                    "ref_authors_correct": "Fengjun Pan, Xiaobao Wu, Tho Quan, Anh Tuan Luu",
                },
            ],
            "https://api.semanticscholar.org/CorpusID:test",
        )


class ArxivVersionWarningChecker:
    def is_arxiv_reference(self, reference):
        return False

    def verify_reference(self, reference):
        assert reference["url"] == "https://arxiv.org/abs/2506.08477"
        return (
            {
                "title": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                "authors": [
                    {"name": "Fengjun Pan"},
                    {"name": "Xiaobao Wu"},
                    {"name": "Tho Quan"},
                    {"name": "Anh Tuan Luu"},
                ],
                "year": 2025,
                "externalIds": {"ArXiv": "2506.08477"},
            },
            [
                {
                    "warning_type": "title (v1 vs v2 update)",
                    "warning_details": "Title mismatch (v1 vs v2 update)",
                    "ref_title_correct": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                },
                {
                    "warning_type": "author (v1 vs v2 update)",
                    "warning_details": "Author count mismatch: 3 cited vs 4 correct (v1 vs v2 update)",
                    "ref_authors_correct": "Fengjun Pan, Xiaobao Wu, Tho Quan, Anh Tuan Luu",
                },
            ],
            "https://arxiv.org/abs/2506.08477v1",
        )


class ArxivTitleSearchChecker:
    def is_arxiv_reference(self, reference):
        return False

    def extract_arxiv_id(self, reference):
        return None, None

    def find_arxiv_id_by_title(self, title, authors=None, year=None):
        assert title == 'Retrospective for the dynamics sensorium competition for predicting large-scale mouse primary visual cortex activity from videos'
        return '2407.09100'

    def verify_reference(self, reference):
        assert reference['url'] == 'https://arxiv.org/abs/2407.09100'
        return (
            {
                'title': 'Retrospective for the Dynamic Sensorium Competition for predicting large-scale mouse primary visual cortex activity from videos',
                'authors': [
                    {'name': 'Polina Turishcheva'},
                    {'name': 'Paul G. Fahey'},
                    {'name': 'Michaela Vystrčilová'},
                ],
                'year': 2024,
                'externalIds': {'ArXiv': '2407.09100'},
            },
            [],
            'https://arxiv.org/abs/2407.09100',
        )


class WrongOpenReviewChecker:
    def __init__(self):
        self.called = False

    def verify_reference_by_search(self, reference):
        self.called = True
        return (
            {
                'title': 'The sensorium competition on predicting large-scale mouse primary visual cortex activity',
                'authors': ['Konstantin F. Willeke', 'Paul G. Fahey'],
                'year': 2022,
                '_matched_database': 'OpenReview',
            },
            [{'warning_type': 'author', 'warning_details': 'wrong paper'}],
            'https://openreview.net/forum?id=2aphixM7rbf',
        )


def _build_checker():
    with patch.object(EnhancedHybridReferenceChecker, '_initialize_checker', return_value=None):
        checker = EnhancedHybridReferenceChecker(
            enable_openalex=False,
            enable_crossref=False,
            enable_arxiv_citation=False,
        )

    checker.local_db = None
    checker.semantic_scholar = NoMatchChecker()
    checker.crossref = TimeoutChecker()
    checker.openalex = None
    checker.dblp = None
    checker.openreview = None
    return checker


RESNET_REFERENCE = {
    'title': 'Deep Residual Learning for Image Recognition',
    'authors': ['Kaiming He', 'Xiangyu Zhang', 'Shaoqing Ren', 'Jian Sun'],
    'year': 2016,
    'venue': '2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)',
    'doi': '10.1109/CVPR.2016.90',
}
RESNET_CROSSREF = {
    'DOI': '10.1109/CVPR.2016.90',
    'title': [RESNET_REFERENCE['title']],
    'author': [
        {'given': name.rsplit(' ', 1)[0], 'family': name.rsplit(' ', 1)[1]}
        for name in RESNET_REFERENCE['authors']
    ],
    'container-title': [RESNET_REFERENCE['venue']],
    'published-print': {'date-parts': [[2016, 6]]},
    'created': {'date-parts': [[2017, 1]]},
    'URL': 'https://doi.org/10.1109/CVPR.2016.90',
    'type': 'proceedings-article',
}


@pytest.fixture
def resnet_checker(monkeypatch):
    checker = _build_checker()
    checker.crossref = CrossRefReferenceChecker()
    monkeypatch.setattr(
        checker.crossref, '_get_work_by_doi_uncached',
        Mock(side_effect=lambda doi: deepcopy(RESNET_CROSSREF)),
    )
    checker.semantic_scholar = Mock()
    checker.semantic_scholar.get_venue_from_paper_data.return_value = RESNET_REFERENCE['venue']

    def merged_record(reference):
        return (
            {
                'title': RESNET_REFERENCE['title'],
                'authors': [{'name': name} for name in RESNET_REFERENCE['authors']],
                'year': 2015,
                'venue': RESNET_REFERENCE['venue'],
                'externalIds': {'DOI': RESNET_REFERENCE['doi'], 'ArXiv': '1512.03385'},
            },
            [{
                'warning_type': 'year', 'warning_details': 'Year mismatch: 2016 vs 2015',
                'ref_year_correct': 2015,
            }] if int(reference['year']) != 2015 else [],
            'https://www.semanticscholar.org/paper/resnet',
        )

    checker.semantic_scholar.verify_reference.side_effect = merged_record
    monkeypatch.setattr(checker, '_cross_verify_secondary', Mock())
    return checker


@pytest.mark.parametrize('source', ['local', 'remote'])
@pytest.mark.parametrize('doi_field', ['doi', 'url', 'cited_url'])
def test_resnet_publication_doi_precedes_merged_preprint_record(resnet_checker, source, doi_field):
    checker = resnet_checker
    if source == 'local':
        checker.local_db = checker.semantic_scholar
    reference = deepcopy(RESNET_REFERENCE)
    reference.pop('doi')
    reference[doi_field] = (
        RESNET_REFERENCE['doi'] if doi_field == 'doi'
        else RESNET_CROSSREF['URL']
    )

    data, errors, url = checker.verify_reference(reference)

    assert data['_matched_checker'] == 'crossref'
    assert data['year'] == 2016
    assert data['venue'] == RESNET_REFERENCE['venue']
    assert data['doi'].lower() == RESNET_REFERENCE['doi'].lower()
    assert errors == []
    assert url == RESNET_CROSSREF['URL']
    checker.semantic_scholar.verify_reference.assert_not_called()


@pytest.mark.parametrize('doi', [None, '10.48550/arXiv.1512.03385'])
def test_explicit_resnet_preprint_keeps_preprint_year_and_doi(
    resnet_checker, monkeypatch, doi,
):
    checker = resnet_checker
    checker.arxiv_citation = ArXivCitationChecker()
    monkeypatch.setattr(checker.arxiv_citation, 'fetch_bibtex', Mock(return_value=r"""
        @misc{he2015deep,
          title={Deep Residual Learning for Image Recognition},
          author={Kaiming He and Xiangyu Zhang and Shaoqing Ren and Jian Sun},
          year={2015}, eprint={1512.03385}
        }
    """))
    reference = dict(RESNET_REFERENCE, year=2015, venue='arXiv',
                     url='https://arxiv.org/abs/1512.03385')
    reference.pop('doi')
    if doi:
        reference['doi'] = doi

    data, errors, url = checker.verify_reference(reference)

    assert data['year'] == 2015
    assert data['venue'] == 'arXiv'
    assert url == reference['url']
    assert not any(error.get('warning_type') == 'year' for error in errors)
    assert data['externalIds'].get('DOI') != RESNET_REFERENCE['doi']
    checker.crossref._get_work_by_doi_uncached.assert_not_called()


@pytest.fixture(params=[
    pytest.param({
        'title': 'Focal Loss for Dense Object Detection',
        'authors': [
            'Tsung-Yi Lin', 'Priya Goyal', 'Ross Girshick', 'Kaiming He',
            'Piotr Dollar',
        ],
        'year': 2020,
        'venue': (
            'IEEE Transactions on Pattern Analysis and Machine Intelligence'
        ),
        'doi': '10.1109/TPAMI.2018.2858826',
        'arxiv_id': '1708.02002',
        'preprint_year': 2017,
    }, id='focal-loss'),
    pytest.param({
        'title': 'Densely Connected Convolutional Networks',
        'authors': [
            'Gao Huang', 'Zhuang Liu', 'Laurens van der Maaten',
            'Kilian Q. Weinberger',
        ],
        'year': 2017,
        'venue': (
            '2017 IEEE Conference on Computer Vision and '
            'Pattern Recognition (CVPR)'
        ),
        'doi': '10.1109/CVPR.2017.243',
        'arxiv_id': '1608.06993',
        'preprint_year': 2016,
    }, id='densenet'),
])
def publication_checker(request, resnet_checker, monkeypatch):
    reference = dict(request.param)
    arxiv_id = reference.pop('arxiv_id')
    preprint_year = reference.pop('preprint_year')
    reference['url'] = f'https://arxiv.org/abs/{arxiv_id}'
    checker = resnet_checker
    work = {
        'DOI': reference['doi'],
        'title': [reference['title']],
        'author': [
            {'given': name.rsplit(' ', 1)[0], 'family': name.rsplit(' ', 1)[1]}
            for name in reference['authors']
        ],
        'container-title': [reference['venue']],
        'published-print': {'date-parts': [[reference['year'], 2]]},
        'URL': 'https://doi.org/' + reference['doi'],
        'type': (
            'journal-article' if reference['year'] == 2020
            else 'proceedings-article'
        ),
    }
    monkeypatch.setattr(checker.crossref, '_get_work_by_doi_uncached',
                        Mock(side_effect=lambda doi: deepcopy(work)))
    checker.semantic_scholar = None
    checker.arxiv_citation = ArXivCitationChecker()
    bibtex = (
        '@misc{preprint, title={' + reference['title'] + '}, author={'
        + ' and '.join(reference['authors']) + '}, year={'
        + str(preprint_year) + '}, eprint={' + arxiv_id + '}}'
    )
    monkeypatch.setattr(
        checker.arxiv_citation, 'fetch_bibtex', Mock(return_value=bibtex),
    )
    return checker, reference


@pytest.mark.parametrize(('copy_field', 'copy_path'), [
    ('url', 'abs'), ('url', 'pdf'), ('cited_url', 'abs'),
])
def test_publication_doi_metadata_is_independent_of_accessible_copy(
    publication_checker, copy_field, copy_path,
):
    checker, reference = publication_checker
    doi_result = checker.verify_reference(dict(
        reference, url='https://doi.org/' + reference['doi'],
    ))
    copy_url = reference.pop('url').replace('/abs/', f'/{copy_path}/')
    reference[copy_field] = copy_url

    data, errors, url = checker.verify_reference(reference)

    assert (data, errors, url) == doi_result
    assert data['_matched_checker'] == 'crossref'
    assert data['year'] == reference['year']
    assert data['venue'] == reference['venue']
    assert errors == []
    checker.arxiv_citation.fetch_bibtex.assert_not_called()


@pytest.mark.parametrize('failure', [
    'not_found', 'timeout', 'incomplete', 'other_doi', 'disabled',
])
def test_publication_doi_failure_allows_arxiv_copy_fallback(
    publication_checker, failure, monkeypatch,
):
    checker, reference = publication_checker
    if failure == 'disabled':
        checker.crossref = None
    elif failure == 'timeout':
        monkeypatch.setattr(
            checker.crossref, 'verify_reference',
            Mock(side_effect=requests.Timeout('offline')),
        )
    else:
        work = checker.crossref._get_work_by_doi_uncached(reference['doi'])
        if failure == 'not_found':
            work = None
        elif failure == 'incomplete':
            work['author'] = []
        else:
            work['DOI'] = '10.1000/another-version'
        monkeypatch.setattr(checker.crossref, 'verify_reference', Mock(
            return_value=(work, [], 'https://doi.org/10.1000/another-version'),
        ))

    data, _, url = checker.verify_reference(reference)

    assert data['_matched_checker'] == 'arxiv_citation'
    assert data['venue'] == 'arXiv'
    assert data['year'] < reference['year']
    assert url == reference['url']
    checker.arxiv_citation.fetch_bibtex.assert_called()


@pytest.mark.parametrize(('field', 'value', 'issue_type'), [
    ('title', 'A Completely Different Paper', 'title'),
    ('authors', ['Invented Author'], 'author'),
    ('year', 2015, 'year'),
    ('venue', 'Nature', 'venue'),
])
def test_arxiv_postprocessing_cannot_replace_publication_doi_match(
    publication_checker, monkeypatch, field, value, issue_type,
):
    checker, reference = publication_checker
    preprint = {
        'title': reference['title'],
        'authors': [{'name': name} for name in reference['authors']],
        'year': 2016,
        'venue': 'arXiv',
    }
    version_result = (
        preprint,
        [{
            'warning_type': 'author (v1 vs v2 update)',
            'warning_details': 'Preprint version update',
        }],
        reference['url'],
    )
    monkeypatch.setattr(
        checker.arxiv_citation, 'verify_reference',
        Mock(return_value=version_result),
    )

    data, errors, url = checker.verify_reference(dict(
        reference, **{field: value},
    ))

    assert data['_matched_checker'] == 'crossref'
    assert data['doi'].lower() == reference['doi'].lower()
    assert data['year'] == reference['year']
    assert data['venue'] == reference['venue']
    assert url == 'https://doi.org/' + reference['doi']
    assert any(
        (issue.get('error_type') or issue.get('warning_type')) == issue_type
        for issue in errors
    )
    assert not any(
        'update' in issue.get('warning_type', '') for issue in errors
    )


@pytest.mark.parametrize(
    ('field', 'value', 'issue_type'),
    [
        ('title', 'A Completely Different Paper', 'title'),
        ('authors', ['Invented Author'], 'author'),
        ('year', 2015, 'year'),
        ('venue', 'Nature', 'venue'),
    ],
)
def test_doi_priority_preserves_real_metadata_mismatches(resnet_checker, field, value, issue_type):
    data, errors, _ = resnet_checker.verify_reference(dict(RESNET_REFERENCE, **{field: value}))

    assert data['_matched_checker'] == 'crossref'
    assert any((error.get('error_type') or error.get('warning_type')) == issue_type
               for error in errors)
    assert data['year'] == 2016


def test_unavailable_doi_metadata_still_allows_other_checkers(resnet_checker, monkeypatch):
    checker = resnet_checker
    monkeypatch.setattr(checker.crossref, 'verify_reference', Mock(side_effect=requests.Timeout('offline')))
    data, _, _ = checker.verify_reference(deepcopy(RESNET_REFERENCE))

    assert data['_matched_checker'] == 'semantic_scholar'
    checker.semantic_scholar.verify_reference.assert_called_once()


@pytest.mark.parametrize('online_year', [2015, 2012])
def test_doi_accepts_recorded_online_year_without_using_preprint_metadata(
    resnet_checker, monkeypatch, online_year,
):
    work = dict(deepcopy(RESNET_CROSSREF), **{'published-online': {'date-parts': [[online_year, 12]]}})
    monkeypatch.setattr(resnet_checker.crossref, '_get_work_by_doi_uncached', Mock(return_value=work))

    data, errors, _ = resnet_checker.verify_reference(dict(RESNET_REFERENCE, year=online_year))

    assert errors == []
    assert data['_matched_checker'] == 'crossref'
    assert data['year'] == 2016
    assert data['venue'] == RESNET_REFERENCE['venue']


def test_doi_registration_year_is_not_a_publication_year(resnet_checker):
    data, errors, _ = resnet_checker.verify_reference(dict(RESNET_REFERENCE, year=2017))

    assert data['year'] == 2016
    assert any(error.get('ref_year_correct') == 2016 for error in errors)


def test_title_search_for_another_doi_cannot_override_the_cited_version(resnet_checker, monkeypatch):
    checker = resnet_checker
    other_version = dict(deepcopy(RESNET_CROSSREF), DOI='10.1000/another-version')
    monkeypatch.setattr(checker.crossref, 'verify_reference', Mock(
        return_value=(other_version, [], 'https://doi.org/10.1000/another-version'),
    ))

    data, _, _ = checker.verify_reference(deepcopy(RESNET_REFERENCE))

    assert data['_matched_checker'] == 'semantic_scholar'
    checker.semantic_scholar.verify_reference.assert_called_once()


def test_incomplete_doi_metadata_does_not_preempt_complete_matches(resnet_checker, monkeypatch):
    checker = resnet_checker
    incomplete = dict(deepcopy(RESNET_CROSSREF), author=[])
    monkeypatch.setattr(checker.crossref, '_get_work_by_doi_uncached', Mock(return_value=incomplete))

    data, _, _ = checker.verify_reference(deepcopy(RESNET_REFERENCE))

    assert data['_matched_checker'] == 'semantic_scholar'
    checker.semantic_scholar.verify_reference.assert_called_once()
    checker.crossref._get_work_by_doi_uncached.assert_called_once()


def test_cached_doi_response_keeps_publication_metadata(resnet_checker, tmp_path):
    checker = resnet_checker
    checker.crossref.cache_dir = str(tmp_path)
    first = checker.verify_reference(deepcopy(RESNET_REFERENCE))
    checker.crossref._get_work_by_doi_uncached.side_effect = AssertionError('Expected cached DOI metadata')

    second = checker.verify_reference(deepcopy(RESNET_REFERENCE))

    assert second == first
    assert second[0]['year'] == 2016
    assert second[1] == []
    checker.crossref._get_work_by_doi_uncached.assert_called_once()


@pytest.mark.parametrize('with_arxiv_copy', [False, True])
def test_doi_version_selection_matches_cli_bulk_and_webui(
    publication_checker, with_arxiv_copy,
):
    from backend.refchecker_wrapper import ProgressRefChecker
    from refchecker.core.refchecker import ArxivReferenceChecker

    checker, reference = publication_checker
    if not with_arxiv_copy:
        reference.pop('url')
    cli = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    cli.non_arxiv_checker = checker
    cli.verify_github_reference = lambda ref: None
    cli.verify_webpage_reference = lambda ref: None
    web = ProgressRefChecker.__new__(ProgressRefChecker)
    web.checker = checker
    web.check_id = None
    cli_errors, cli_url, cli_data = cli.verify_reference_standard(
        None, deepcopy(reference),
    )
    bulk_errors, bulk_url, bulk_data = cli.verify_reference(
        None, deepcopy(reference),
    )
    web_result = web._verify_reference(deepcopy(reference))

    assert (cli_data, cli_errors or [], cli_url) == (bulk_data, bulk_errors or [], bulk_url) == web_result
    assert cli_data['_matched_checker'] == 'crossref'
    assert cli_data['year'] == reference['year']
    assert not cli_errors


def test_paperclip_key_can_be_supplied_per_request(monkeypatch):
    paperclip_calls = []

    class FakePaperclip:
        enabled = True

    def fake_initialize(self, module_name, class_name, log_name, *args, **kwargs):
        if module_name == 'paperclip':
            paperclip_calls.append(kwargs)
            return FakePaperclip()
        return None

    monkeypatch.delenv('PAPERCLIP_API_KEY', raising=False)
    with patch.object(EnhancedHybridReferenceChecker, '_initialize_checker', fake_initialize):
        checker = EnhancedHybridReferenceChecker(
            paperclip_api_key='pc-request-key',
            enable_openalex=False,
            enable_crossref=False,
            enable_arxiv_citation=False,
            enable_acl_anthology=False,
        )

    assert checker.paperclip is not None
    assert paperclip_calls == [{'api_key': 'pc-request-key'}]


@patch('refchecker.checkers.enhanced_hybrid_checker.time.sleep', return_value=None)
def test_unverified_reason_includes_negative_and_failed_checkers(_mock_sleep):
    checker = _build_checker()
    reference = {
        'title': 'Few-shot learning for personalized facial expression recognition',
        'authors': ['Anan Yao', 'Sheng Zhang', 'Ruisha Qian'],
        'venue': 'Proceedings of the 29th ACM International Conference on Multimedia',
        'year': 2021,
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is None
    assert url is None
    assert len(errors) == 1
    assert errors[0]['error_type'] == 'unverified'
    assert errors[0]['error_details'] == (
        'Paper not found by any checker; no match in Semantic Scholar; '
        'checker failures: CrossRef: simulated timeout'
    )
    assert errors[0]['sources_checked'] == 2
    assert errors[0]['sources_negative'] == 1


def test_verify_reference_records_matched_database_from_local_checker():
    checker = _build_checker()
    checker.local_db = LocalMatchChecker()
    checker.semantic_scholar = None
    checker.crossref = None

    verified_data, errors, url = checker.verify_reference({"title": "Test title", "authors": []})

    assert errors == []
    assert url == "https://www.semanticscholar.org/paper/s2-match-id"
    assert verified_data["_matched_database"] == "Semantic Scholar"
    assert verified_data["_matched_checker"] == "local_s2"


@patch('refchecker.checkers.enhanced_hybrid_checker.time.sleep', return_value=None)
def test_institutional_report_fallback_resolves_technical_report(_mock_sleep):
    checker = _build_checker()
    checker.crossref = NoMatchChecker()

    class FakeInstitutionalReports:
        def verify_reference(self, reference):
            return (
                {
                    'title': reference['title'],
                    'authors': reference['authors'],
                    'year': 1992,
                    'venue': 'University of Chicago Department of Statistics',
                    'volume': '348',
                    'url': 'https://example.edu/tr348.pdf',
                    '_matched_database': 'Official Institutional Report Index',
                },
                [],
                'https://example.edu/tr348.pdf',
            )

    checker.institutional_reports = FakeInstitutionalReports()
    checker.official_proceedings = None
    checker.datacite = None
    reference = {
        'title': 'A note on importance sampling using standardized weights',
        'authors': ['Kong, Augustine'],
        'year': 1992,
        'journal': 'University of Chicago, Dept. of Statistics, Tech. Rep',
        'volume': '348',
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data['_matched_database'] == 'Official Institutional Report Index'
    assert errors == []
    assert url.endswith('tr348.pdf')


@patch('refchecker.checkers.enhanced_hybrid_checker.time.sleep', return_value=None)
def test_official_proceedings_fallback_resolves_workshop_abstract(_mock_sleep):
    checker = _build_checker()
    checker.crossref = NoMatchChecker()

    class FakeOfficialProceedings:
        def verify_reference(self, reference):
            return (
                {
                    'title': reference['title'],
                    'authors': reference['authors'],
                    'year': 2020,
                    'venue': 'SciNLP 2020',
                    'url': 'https://scinlp.org/history/2020/pdfs/softcite.pdf',
                    '_matched_database': 'Official Workshop Program',
                },
                [],
                'https://scinlp.org/history/2020/pdfs/softcite.pdf',
            )

    checker.official_proceedings = FakeOfficialProceedings()
    checker.datacite = None
    reference = {
        'title': 'Softcite: Automatic Extraction of Software Mentions in Research Literature',
        'authors': ['Caifan Du', 'James Howison', 'Patrice Lopez'],
        'year': 2020,
        'venue': 'SciNLP',
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data['_matched_database'] == 'Official Workshop Program'
    assert errors == []
    assert url.endswith('softcite.pdf')


@patch('refchecker.checkers.enhanced_hybrid_checker.time.sleep', return_value=None)
def test_datacite_fallback_resolves_zenodo_doi_when_other_apis_miss(_mock_sleep):
    """DataCite is tried as a last-resort fallback for DOIs that CrossRef/
    OpenAlex/Semantic Scholar don't resolve (e.g. Zenodo-registered DOIs) —
    this is the fix for the Zenodo false-positive pattern identified in
    arXiv:2607.22693."""
    checker = _build_checker()
    checker.dblp = None
    checker.openreview = None

    class FakeDataCite:
        def verify_reference(self, reference):
            return (
                {
                    'title': reference.get('title', ''),
                    'authors': ['Chiara Di Giambattista'],
                    'year': 2025,
                    'venue': 'Zenodo',
                    'doi': '10.5281/zenodo.17199853',
                    'url': 'https://doi.org/10.5281/zenodo.17199853',
                    '_matched_database': 'DataCite',
                },
                [],
                'https://doi.org/10.5281/zenodo.17199853',
            )

    checker.datacite = FakeDataCite()

    reference = {
        'title': 'OpenCitations snapshot',
        'doi': '10.5281/zenodo.17199853',
        'year': 2025,
        'authors': ['Chiara Di Giambattista'],
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is not None
    assert verified_data['_matched_database'] == 'DataCite'
    assert errors == []
    assert url == 'https://doi.org/10.5281/zenodo.17199853'


def test_major_author_discrepancy_recognizes_no_matching_authors_error():
    checker = _build_checker()

    assert checker._has_major_author_discrepancy([
        {
            'error_type': 'author',
            'error_details': (
                'no matching authors:\n'
                '       cited:  Alice Example, Bob Example\n'
                '       actual: Carol Verified, Dave Verified'
            ),
            'ref_authors_correct': 'Carol Verified, Dave Verified',
        }
    ]) is True


def test_shared_postprocess_converts_arxiv_version_mismatch_to_warnings():
    checker = _build_checker()
    checker.local_db = LocalArxivMismatchChecker()
    checker.semantic_scholar = None
    checker.crossref = None
    checker.arxiv_citation = ArxivVersionWarningChecker()

    reference = {
        "title": "Detecting harmful memes with decoupled understanding and guided cot reasoning",
        "authors": ["Fengjun Pan", "Anh Tuan Luu", "Xiaobao Wu"],
        "year": 2025,
        "venue": "arXiv:2506.08477",
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert url == "https://arxiv.org/abs/2506.08477v1"
    assert verified_data["_matched_database"] == "ArXiv"
    assert all("warning_type" in error for error in errors)
    assert not any("error_type" in error for error in errors)
    assert any(error["warning_type"] == "title (v1 vs v2 update)" for error in errors)
    assert any(error["warning_type"] == "author (v1 vs v2 update)" for error in errors)


def test_arxiv_title_search_precedes_loose_openreview_match():
    checker = _build_checker()
    checker.arxiv_citation = ArxivTitleSearchChecker()
    checker.local_db = NoMatchChecker()
    checker.semantic_scholar = NoMatchChecker()
    checker.crossref = None
    checker.openreview = WrongOpenReviewChecker()

    reference = {
        'title': 'Retrospective for the dynamics sensorium competition for predicting large-scale mouse primary visual cortex activity from videos',
        'authors': ['Polina Turishcheva', 'Paul Fahey', 'Michaela Vystrčilová'],
        'year': 2024,
        'venue': 'Advances in Neural Information Processing Systems',
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert errors == []
    assert url == 'https://arxiv.org/abs/2407.09100'
    assert verified_data['_matched_database'] == 'ArXiv'
    assert verified_data['_matched_checker'] == 'arxiv_citation'
    assert checker.openreview.called is False


class LocalMissChecker:
    """Local S2 DB that finds nothing, with configurable ingest completeness."""

    database_label = "Semantic Scholar"
    database_key = "local_s2"

    def __init__(self, complete):
        self._complete = complete

    def has_complete_coverage(self):
        return self._complete

    def verify_reference(self, reference):
        return None, [], None


class RecordingSemanticScholar:
    def __init__(self):
        self.calls = 0

    def verify_reference(self, reference):
        self.calls += 1
        return None, [], None


def test_incomplete_local_db_miss_still_queries_semantic_scholar():
    """A DB mid-bootstrap answers 'not found' for papers it hasn't ingested;
    trusting that would turn coverage gaps into wrong verdicts."""
    checker = _build_checker()
    checker.local_db = LocalMissChecker(complete=False)
    checker.crossref = None
    recorder = RecordingSemanticScholar()
    checker.semantic_scholar = recorder

    checker.verify_reference({"title": "Some uningested paper", "authors": []})

    assert recorder.calls == 1


def test_complete_local_db_miss_skips_semantic_scholar():
    """The skip-SS optimization must survive for a fully ingested snapshot."""
    checker = _build_checker()
    checker.local_db = LocalMissChecker(complete=True)
    checker.crossref = None
    recorder = RecordingSemanticScholar()
    checker.semantic_scholar = recorder

    checker.verify_reference({"title": "Some uningested paper", "authors": []})

    assert recorder.calls == 0
