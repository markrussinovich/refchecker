import sys

from refchecker.checkers.openreview_checker import OpenReviewReferenceChecker
from refchecker.core import refchecker as refchecker_module
from refchecker.core.refchecker import prepare_openreview_paper_specs


def test_parse_openreview_venue_spec_accepts_shorthand():
    venue_info = OpenReviewReferenceChecker.parse_venue_spec('iclr-2024')

    assert venue_info['series'] == 'ICLR'
    assert venue_info['year'] == 2024
    assert venue_info['accepted_venue'] == 'ICLR 2024 Conference'
    assert venue_info['submission_invitation'] == 'ICLR.cc/2024/Conference/-/Submission'


def test_parse_openreview_venue_spec_supports_aistats():
    venue_info = OpenReviewReferenceChecker.parse_venue_spec('aistats2025')

    assert venue_info['series'] == 'AISTATS'
    assert venue_info['year'] == 2025
    assert venue_info['group_id'] == 'aistats.org/AISTATS/2025/Conference'
    assert venue_info['submission_invitation'] == 'aistats.org/AISTATS/2025/Conference/-/Submission'


def test_parse_openreview_venue_spec_supports_uai():
    venue_info = OpenReviewReferenceChecker.parse_venue_spec('uai2025')

    assert venue_info['series'] == 'UAI'
    assert venue_info['year'] == 2025
    assert venue_info['group_id'] == 'auai.org/UAI/2025/Conference'
    assert venue_info['submission_invitation'] == 'auai.org/UAI/2025/Conference/-/Submission'


def test_parse_openreview_venue_spec_supports_corl():
    venue_info = OpenReviewReferenceChecker.parse_venue_spec('corl2025')

    assert venue_info['series'] == 'CoRL'
    assert venue_info['year'] == 2025
    assert venue_info['group_id'] == 'robot-learning.org/CoRL/2025/Conference'
    assert venue_info['submission_invitation'] == 'robot-learning.org/CoRL/2025/Conference/-/Submission'


def test_parse_openreview_venue_spec_rejects_unsupported_prefix():
    try:
        OpenReviewReferenceChecker.parse_venue_spec('neurips2025')
    except ValueError as exc:
        assert 'Supported prefixes: aistats, corl, iclr, icml, uai.' in str(exc)
    else:
        raise AssertionError('Expected unsupported OpenReview venue to raise ValueError')


def test_list_conference_papers_filters_accepted_from_conference_metadata(monkeypatch):
    checker = OpenReviewReferenceChecker(request_delay=0.0)

    def fake_get_conference_metadata(venue_spec):
        assert venue_spec == 'iclr2024'
        return {
            'display_name': 'ICLR 2024',
            'submission_id': 'ICLR.cc/2024/Conference/-/Submission',
            'submission_venue_id': 'ICLR.cc/2024/Conference/Submission',
            'withdrawn_venue_id': 'ICLR.cc/2024/Conference/Withdrawn_Submission',
            'desk_rejected_venue_id': 'ICLR.cc/2024/Conference/Desk_Rejected_Submission',
            'rejected_venue_id': 'ICLR.cc/2024/Conference/Rejected_Submission',
            'decision_heading_map': {
                'ICLR 2024 Oral': 'Accept (Oral)',
                'ICLR 2024 Poster': 'Accept (Poster)',
                'Submitted to ICLR 2024': 'Reject',
            },
            'accepted_venue': 'ICLR 2024 Conference',
        }

    def fake_fetch_all_notes(params, page_size=1000):
        assert params == {'invitation': 'ICLR.cc/2024/Conference/-/Submission'}
        return [
            {'id': 'accepted-1'},
            {'id': 'submitted-1'},
            {'id': 'accepted-1'},
        ]

    def fake_parse(note):
        if note['id'] == 'accepted-1':
            return {
                'id': 'accepted-1',
                'title': 'Accepted Paper',
                'venue': 'ICLR 2024 Oral',
                'venueid': 'ICLR.cc/2024/Conference',
                'forum_url': 'https://openreview.net/forum?id=accepted-1',
            }
        return {
            'id': 'submitted-1',
            'title': 'Rejected Paper',
            'venue': 'Submitted to ICLR 2024',
            'venueid': 'ICLR.cc/2024/Conference/Rejected_Submission',
            'forum_url': 'https://openreview.net/forum?id=submitted-1',
        }

    monkeypatch.setattr(checker, 'get_conference_metadata', fake_get_conference_metadata)
    monkeypatch.setattr(checker, '_fetch_all_notes', fake_fetch_all_notes)
    monkeypatch.setattr(checker, '_parse_api_response', fake_parse)

    papers = checker.list_conference_papers('iclr2024', status='accepted')

    assert [paper['id'] for paper in papers] == ['accepted-1']


def test_list_conference_papers_returns_all_public_submissions(monkeypatch):
    checker = OpenReviewReferenceChecker(request_delay=0.0)

    monkeypatch.setattr(
        checker,
        'get_conference_metadata',
        lambda venue_spec: {
            'display_name': 'ICLR 2024',
            'submission_id': 'ICLR.cc/2024/Conference/-/Submission',
            'submission_venue_id': 'ICLR.cc/2024/Conference/Submission',
            'withdrawn_venue_id': 'ICLR.cc/2024/Conference/Withdrawn_Submission',
            'desk_rejected_venue_id': 'ICLR.cc/2024/Conference/Desk_Rejected_Submission',
            'rejected_venue_id': 'ICLR.cc/2024/Conference/Rejected_Submission',
            'decision_heading_map': {},
            'accepted_venue': 'ICLR 2024 Conference',
        },
    )
    monkeypatch.setattr(
        checker,
        '_fetch_all_notes',
        lambda params, page_size=1000: [{'id': 'paper-1'}, {'id': 'paper-2'}],
    )
    monkeypatch.setattr(
        checker,
        '_parse_api_response',
        lambda note: {
            'id': note['id'],
            'title': f"Paper {note['id']}",
            'venue': 'Submitted to ICLR 2024',
            'venueid': 'ICLR.cc/2024/Conference/Rejected_Submission',
            'forum_url': f"https://openreview.net/forum?id={note['id']}",
        },
    )

    papers = checker.list_conference_papers('iclr2024', status='submitted')

    assert [paper['id'] for paper in papers] == ['paper-1', 'paper-2']


def test_prepare_openreview_paper_specs_writes_generated_list(tmp_path, monkeypatch):
    class FakeOpenReviewReferenceChecker:
        def get_conference_metadata(self, venue_spec):
            assert venue_spec == 'iclr2024'
            return {
                'display_name': 'ICLR 2024',
                'slug': 'iclr2024',
            }

        def list_conference_papers(self, venue_spec, status='accepted'):
            assert venue_spec == 'iclr2024'
            assert status == 'submitted'
            return [
                {'forum_url': 'https://openreview.net/forum?id=paper-1'},
                {'forum_url': 'https://openreview.net/forum?id=paper-2'},
            ]

    monkeypatch.setattr(
        'refchecker.checkers.openreview_checker.OpenReviewReferenceChecker',
        FakeOpenReviewReferenceChecker,
    )

    input_specs, list_path, venue_info = prepare_openreview_paper_specs(
        'iclr2024',
        output_dir=str(tmp_path),
        status='submitted',
    )

    assert input_specs == [
        'https://openreview.net/forum?id=paper-1',
        'https://openreview.net/forum?id=paper-2',
    ]
    assert venue_info['display_name'] == 'ICLR 2024'
    assert tmp_path.joinpath('openreview_iclr2024_submitted.txt').read_text(encoding='utf-8').splitlines() == input_specs
    assert list_path == str(tmp_path / 'openreview_iclr2024_submitted.txt')


def test_prepare_openreview_paper_specs_writes_custom_output_path(tmp_path, monkeypatch):
    class FakeOpenReviewReferenceChecker:
        def get_conference_metadata(self, venue_spec):
            assert venue_spec == 'iclr2024'
            return {
                'display_name': 'ICLR 2024',
                'slug': 'iclr2024',
            }

        def list_conference_papers(self, venue_spec, status='accepted'):
            assert venue_spec == 'iclr2024'
            assert status == 'accepted'
            return [
                {'forum_url': 'https://openreview.net/forum?id=paper-1'},
                {'forum_url': 'https://openreview.net/forum?id=paper-2'},
            ]

    output_path = tmp_path / 'lists' / 'custom-openreview.txt'

    monkeypatch.setattr(
        'refchecker.checkers.openreview_checker.OpenReviewReferenceChecker',
        FakeOpenReviewReferenceChecker,
    )

    input_specs, list_path, venue_info = prepare_openreview_paper_specs(
        'iclr2024',
        output_path=str(output_path),
        status='accepted',
    )

    assert input_specs == [
        'https://openreview.net/forum?id=paper-1',
        'https://openreview.net/forum?id=paper-2',
    ]
    assert venue_info['display_name'] == 'ICLR 2024'
    assert output_path.read_text(encoding='utf-8').splitlines() == input_specs
    assert list_path == str(output_path)


def test_main_openreview_list_only_exits_after_fetch(monkeypatch, tmp_path, capsys):
    expected_output_path = tmp_path / 'openreview.txt'

    def fake_prepare(venue_spec, output_dir='output', status='accepted', output_path=None):
        assert venue_spec == 'iclr2024'
        assert status == 'accepted'
        assert output_path == str(expected_output_path)
        return [
            'https://openreview.net/forum?id=paper-1',
            'https://openreview.net/forum?id=paper-2',
        ], str(expected_output_path), {'display_name': 'ICLR 2024'}

    def fail_checker(*args, **kwargs):
        raise AssertionError('ArxivReferenceChecker should not be constructed in list-only mode')

    monkeypatch.setattr(refchecker_module, 'prepare_openreview_paper_specs', fake_prepare)
    monkeypatch.setattr(refchecker_module, 'ArxivReferenceChecker', fail_checker)
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'academic-refchecker',
            '--openreview', 'iclr2024',
            '--openreview-list-only',
            '--openreview-output-file', str(expected_output_path),
        ],
    )

    exit_code = refchecker_module.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert 'Fetched 2 accepted OpenReview papers for ICLR 2024 into' in captured.out